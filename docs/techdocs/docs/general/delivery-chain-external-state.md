# Delivery chain: state that git does not hold

> Inventory taken 2026-10-18 against `origin/main` of this repo, `origin/development` of
> `ploeg-hq/ploeg` (8ffd3b7) and of `webgrip/unfold`, read-only `gh api` calls, and anonymous
> Forgejo API reads. No secret value was read. Plan for
> [ADR-0069](../adr/adr-0069-one-delivery-contract.md) and the
> [delivery contract RFC](../rfc/rfc-unfold-release-train.md).

## The question

The delivery chain is:

```text
Ploeg (GitHub ploeg-hq/ploeg)
  → release + contract bundle on GHCR
  → Unfold (Forgejo webgrip/unfold) opens/merges its Ploeg bump
  → Unfold image + chart on Harbor
  → homelab-cluster bump by Renovate, merged on e2e, applied by Flux
```

Every hop depends on state that lives in a forge, a registry or the vault rather than in a
manifest: bot users, tokens, branch rules, webhooks, CI variables. If that state is lost, or the
estate is rebuilt elsewhere, git alone does not bring the chain back. This page lists that state
(part A) and names the mechanism that should own each item (part B).

**Terms used below.** *Reconciled* means a controller or scheduled job rewrites the state from git
on its own (Flux, a CronJob, tofu-controller). *Script* means a person runs a script from this
repo with the right environment; the result is right once and then drifts. *Hand* means a
person clicked it or typed it. *Provided* means a value that came from outside the estate (an
account's API key) and was typed into OpenBao once; it cannot be regenerated, only re-issued by
the provider. The secrets levels L0–L5 are those of
[ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md).

## What is already declarative

Large parts of the chain already rebuild from git. They are listed so the gaps stand out.

| State | Owner in git | How |
| --- | --- | --- |
| Harbor projects (`webgrip`, the proxy-cache projects), proxy registries, robots `webgrip+ci` and the Renovate robot, retention, immutability, scanning, GC, webhook policy `unfold-release-renovate` | `kubernetes/apps/harbor/harbor/app/harbor-proxy-config.*` | hourly CronJob against the Harbor API; robot secrets from `password-generator-32`, pushed to OpenBao |
| Harbor → Renovate trigger | `kubernetes/apps/harbor/release-relay` | Deployment; inbound token from a generator |
| Forgejo bots `renovate`, `webgrip-ci`, `unfold-reports`, `agent-builder`, `agent-reviewer`, their team memberships and tokens | provisioner Jobs/CronJobs in `kubernetes/apps/renovate/renovate-operator/forgejo-provisioner` and `kubernetes/apps/forgejo/forgejo-actions-secrets/app` | idempotent API calls with the Forgejo admin credential; passwords from generators; tokens written to Secrets and PushSecret to OpenBao |
| Forgejo producer bot `ploeg-release` (restricted user, Write collaborator on `webgrip/unfold` only, token `ploeg-release-hook` with `write:repository`, `write:issue`, `read:user`) | `kubernetes/apps/forgejo/forgejo-actions-secrets/app/ploeg-release-provisioner.*` | hourly CronJob; password from `password-generator`; token kept while it authenticates with those scopes, else re-minted; PushSecret to OpenBao `forgejo/ploeg-release` property `token`; the run fails, and `DeliveryReleaseBotProvisionerFailing` fires, when the bot can reach any repository but `webgrip/unfold` or holds admin on it |
| Forgejo org and repo Actions secrets (`WEBGRIP_CI_TOKEN`, `HARBOR_ROBOT_*`, `GHCR_*`, `CLOUDFLARE_*`, `OVSX_PAT`, `TECHDOCS_S3_*`) | `forgejo-actions-secrets.cronjob.yaml` | L3 bridge, hourly, validated against the provider |
| Forgejo package-to-repo links | `forgejo-package-link-reconciler.cronjob.yaml` | CronJob |
| OpenBao policies, auth roles (`ci-unfold`, the Forgejo OIDC signing role, `access-plane`) | `kubernetes/apps/security/openbao/bootstrap/` | bootstrap CronJob running `config.sh` |
| Authentik groups, Harbor group memberships, OIDC capability projections | `kubernetes/apps/security/access-plane/` | tofu-controller with the `authentik`, `harbor` and `vault` providers |
| Renovate jobs, presets wiring, GitHub App token minting | `kubernetes/apps/renovate/renovate-operator/jobs/` | RenovateJob CRs; CronJob `renovate-github-app-token` mints installation tokens every 15 minutes |
| Delivery verify alerts (P4 slice 1) | `prometheusrule-delivery-verify.yaml` | VMRule |

## A. Inventory of state git does not reconcile

"Fresh install" answers: could a rebuild from git alone, plus the L0 floor, recreate it?

### GitHub (`ploeg-hq/ploeg`, `webgrip` mirrors)

| # | What | Where | Created by today | Fresh install | Failure if missing or drifted |
| --- | --- | --- | --- | --- | --- |
| G1 | Ruleset **Protect development** (id 24451069): no deletion, no force push, required check `verify`, admin bypass | GitHub repo rulesets | hand, 2026-10-04; modelled in `github-config/ploeg-hq` (import proven 0-change), applies once the App exists | after the App step | `development` accepts red or rewritten history; candidates cut from unverified code |
| G2 | Ruleset **Protect main** (24445411), same rules | GitHub | hand; modelled, as G1 | after the App step | same for stables |
| G3 | Ruleset **Release tags are immutable** (24445407): `refs/tags/v*`, no bypass | GitHub | hand; modelled, as G1 | after the App step | a moved tag changes what a pinned version means; Harbor and Unfold pins stop being reproducible |
| G4 | Repo settings: public, default branch `development`, Actions on, default workflow permission `read`, Actions may not approve PRs | GitHub | hand; modelled (repository, default branch, Actions and workflow permissions), as G1 | after the App step | wrong default branch breaks the release workflows; write-default tokens widen every job |
| G5 | Visibility of GHCR packages `ploegd`, `claude-runner`, `charts/ploeg`, `ploeg-contract` (all public today) | GHCR package settings | hand, per package, after its first push | no | Harbor's `ghcr` proxy and Unfold's bundle pull get 401/404; a new package is private until someone clicks |
| G6 | Repo variable `RELEASE_CONSUMERS` (JSON consumer list, D5) | GitHub Actions variables | **not set**; modelled behind `release_consumers_enabled: false` until the switch in the [runbook](../runbooks/github-app-ploeg-hq.md#switching-ploeg-unfold-bumps-to-the-producer-d5); branch `ci/notify-release-consumers` (ploeg#173) reads it | after the App step and the switch | consumer job skips silently: no Unfold bump PR is opened |
| G7 | Repo secret `RELEASE_CONSUMER_TOKEN_FORGEJO` (Forgejo token of the producer bot, D6) | GitHub Actions secrets | **not set**; CronJob `github-secrets-bridge/github-secrets-bridge` publishes it from `secret/forgejo/ploeg-release` and no-ops until the App exists | after the App step | consumer job cannot open or schedule the Unfold PR |
| G8 | Renovate GitHub App (registration, private key, installation on the `webgrip` org) | GitHub App settings; key in OpenBao `renovate/operator` | hand | key: provided L1; app: no | `webgrip-gitops` RenovateJob and GHCR lookups for Renovate fail (`RenovateTokenMinterFailing`) |
| G9 | Classic PAT `github/ci-pat` (`repo` + `write:packages`) | GitHub user settings; OpenBao `github/ci-pat` | hand | provided L1 | Forgejo CI cannot mirror Unfold images to `ghcr.io/webgrip/*` or mirror Releases |
| G10 | PAT `GH_MIRROR_TOKEN` for Forgejo → GitHub push mirrors | a person's shell when running `forgejo-sync.sh --only mirror` | hand | no | new push mirrors cannot be created; existing ones keep the token they were made with |
| G11 | Mirror repos `github.com/webgrip/*` (e.g. `webgrip/unfold`) | GitHub | hand | no | push mirror errors; GitHub copies of releases vanish |

### Forgejo (`forgejo.webgrip.dev`)

| # | What | Where | Created by today | Fresh install | Failure if missing or drifted |
| --- | --- | --- | --- | --- | --- |
| F1 | Branch protection on `homelab-cluster` `main`: push `ryangr0`, merge `ryangr0`,`renovate`, the four `e2e /` status contexts | Forgejo DB | **repo-config module** (`homelab` profile, applied hourly since 2026-10-18); lock-out guard in the schema and a module precondition | yes, from the model | owner lock-out (happened 2026-08-05), or `platformAutomerge` merges a red Renovate PR (P1b prerequisite 1, D8) |
| F2 | Branch protection on `webgrip/unfold` `development` and `main`, with `ploeg-docs` required on `development` | Forgejo DB | **repo-config module** (`repos.yaml` `unfold.branches`). Neither rule has a push or merge whitelist live: anyone with write pushes and merges, status checks gate the PR | yes, from the model | a Ploeg bump with a vocabulary clash merges red (ADR-0041) |
| F3 | Branch protection on the other chain repos (`semantic-release-config`, `workflows`, `renovate-config`, `infrastructure`) | Forgejo DB | `workflows` `main` (no whitelists) is in the repo-config module; the others have no rule live | partly | `webgrip-ci` missing from the push whitelist stops semantic-release; unprotected library tags move |
| F4 | Per-repo webhook → `renovate-operator` with a top-level `authorization_header` | Forgejo DB | script: `--only webhook` | no | Dependency Dashboard clicks wait for the hourly run; a nested header 401s silently |
| F5 | Repo units and merge settings (PRs, Releases, Actions on; merge styles; delete branch after merge) | Forgejo DB | **repo-config module** for PRs, Releases, Actions and merge settings; `forgejo-sync.sh --only settings` is retired | yes, from the model | Renovate skips repos with PRs off; semantic-release has no Releases tab |
| F6 | Topics (`renovate`) used for discovery | Forgejo DB | hand; `scripts/renovate-discovery-drift.sh` detects | no | repo drops out of Renovate autodiscovery |
| F7 | Push mirrors Forgejo → GitHub | Forgejo DB | script: `--only mirror` with G10 | no | GitHub copies go stale |
| F8 | Pull mirror of `ploeg-hq/ploeg` on Forgejo | Forgejo DB | hand, New Migration form | no | read-only copy only; nothing in the chain reads it after D2, so low impact |
| F9 | Unfold repo Actions variables `UNFOLD_RELEASES_ENABLED`, `UNFOLD_DOCS_PUBLISH_ENABLED` | Forgejo DB | hand, repo settings | no | releases and docs publishing are skipped without an error |
| F10 | Producer bot `ploeg-release`: merging on `unfold` `development`. The user, its collaboration and its token are reconciled since VIK-2222, see above | Forgejo | no whitelist entry needed today: `development` has no merge whitelist, so the bot merges as a write collaborator. If a merge whitelist is ever modelled there, it must list `ploeg-release` | n/a | the producer bot cannot schedule the merge of its Unfold bump |

### OpenBao provided values (L1, typed once by a person)

These are read by ExternalSecrets in git, so the *wiring* is declarative; the *value* is not.

| # | KV path | Holds | Origin | Failure if lost |
| --- | --- | --- | --- | --- |
| V1 | `forgejo/admin` | Forgejo admin username, password | seeded from SOPS, PushSecret round-trip | every Forgejo provisioner stops; Forgejo chart cannot create its admin |
| V2 | `forgejo/oidc` | Authentik client for Forgejo login | seeded from SOPS | SSO login fails; local admin still works |
| V3 | `renovate/operator` | Renovate GitHub App id, installation id, private key; Docker Hub user and token | provided | G8 failure; Docker Hub rate limits |
| V4 | `renovate/webhook-auth` | bearer token list for the operator's webhook receiver | seeded from SOPS; a PushSecret writes the K8s copy back to KV | release relay and every F4 hook get 401; the chain falls back to the hourly schedule |
| V5 | `harbor/registry-proxy` | Docker Hub and GHCR pull credentials for Harbor's proxy projects | provided | proxy pulls fall back to anonymous limits or fail for private GHCR |
| V6 | `cloudflare/tunnel`, `cloudflare/manager` (and the tunnel object at Cloudflare) | tunnel token in front of `forgejo.webgrip.dev`; the token that mints the rolled deploy and DNS tokens | provided | GitHub-hosted runners cannot reach Forgejo (G6/G7 calls, npm registry, `semantic-release-config` clone); Unfold site deploys stop |
| V7 | `openvsx/unfold`, VS Marketplace PAT and Azure ids | extension publishing for Unfold | provided | extension publish steps fail or skip |
| V8 | `github/ci-pat` | see G9 | provided | see G9 |

V8 is the vault copy of G9 and is counted once below.

### Count

| Category | Hand or script, not reconciled | Of which not yet created |
| --- | --- | --- |
| GitHub (G1–G11) | 11 | 2 (G6, G7) |
| Forgejo (F1–F10) | 10 | 1 (F10) |
| OpenBao provided values (V1–V7) | 7 | 0 |
| Harbor | 0 | 0 |
| Authentik | 0 | 0 |
| **Total** | **28** | **3** |

Plus one stale item: P1b of the RFC named a Ploeg secret `RENOVATE_TRIGGER_TOKEN` and variable
`RENOVATE_TRIGGER_URL`. D5 replaced that hop with the producer opening the PR; neither is set and
neither should be.

### External services the chain depends on

| Service | Used by | What breaks without it |
| --- | --- | --- |
| GitHub (api.github.com, hosted `ubuntu-24.04` runners, Releases) | Ploeg CI and releases; Renovate `webgrip-gitops`; mise and tofu provider downloads | Ploeg cannot release at all |
| GHCR (`ghcr.io/ploeg-hq/*`, `ghcr.io/webgrip/*`) | Ploeg images, chart, contract bundle; Unfold's public mirror; Harbor `ghcr` proxy | Unfold cannot fetch the bundle; homelab cannot pull Ploeg |
| Cloudflare (tunnel, DNS, Workers) | public reach of `forgejo.webgrip.dev` from GitHub runners; Unfold site | Ploeg → Unfold hop stops; site deploy stops |
| Let's Encrypt (cert-manager ClusterIssuer) | TLS on `forgejo.*`, `harbor.*` | certificates expire after 90 days |
| proxy.golang.org, PyPI, npmjs, the Forgejo npm registry | Go module `github.com/ploeg-hq/ploeg`, uv, pnpm, `@webgrip/semantic-release-config` | builds fail at dependency fetch |
| Docker Hub, quay.io, registry.k8s.io, mcr, code.forgejo.org, dhi.io, mirror.gcr.io | Harbor proxy-cache upstreams | pulls of uncached images fail |
| registry.opentofu.org | tofu-controller `tofu init` | every tofu module in part B stops planning |
| Open VSX, VS Marketplace (Azure) | Unfold extension | extension release only |
| Garage off-site (Hetzner) | OpenBao snapshots, CNPG WAL | recovery of L1 values, not the live chain |

## B. Plan: one owner per item

### Mechanisms

| Mechanism | Owns | Exists today? | Bootstrap credential it needs |
| --- | --- | --- | --- |
| **Forgejo repo-config module** ([RFC](../rfc/rfc-forgejo-repo-config-gitops.md), epic VIK-1302): tofu-controller + `svalabs/forgejo` provider, `profiles.yaml` + `repos.yaml` model, Terraform object `repo-config` in namespace `repo-config` | F1, F2, F5, the `workflows` part of F3 | **yes** since 2026-10-18: 27 repositories and 5 branch protection rules, `approvePlan: auto`, hourly. `ForgejoRepoConfigNotReady` and `ForgejoRepoConfigApplyChangedSomething` watch it | a `forgejo-repo-config` bot token, minted by a provisioner from V1 and read through OpenBao Kubernetes auth |
| **Forgejo identity provisioners** (the `unfold-reports-provisioner` pattern) | F10 user, collaboration and token | **yes**, the pattern runs in production | V1 |
| **GitHub module**: tofu-controller + `integrations/github` provider, app auth (`kubernetes/apps/github-config/ploeg-hq`) | G1–G4, G6 for `ploeg-hq`; later G11 and the `webgrip` mirrors with a second App | **built 2026-10-18** (VIK-2223), suspended until the `ploeg-hq` App exists | one GitHub App per owner (`ploeg-hq`, `webgrip`) with Administration, Actions variables and Secrets write on the listed repos; its private key in OpenBao |
| **GitHub L3 bridge** (`kubernetes/apps/github-secrets-bridge`) | G7 and any other GitHub Actions secret | **built 2026-10-18** (VIK-2224), runs hourly, no-ops with `GitHubAppPloegHqPending` (info) until the App exists | the same GitHub App; encrypts each value with the repo public key (sealed box), so no value enters tofu state |
| **Harbor provisioner** | Harbor | **yes** | `harbor/admin`, generated |
| **Access plane** | Authentik, Harbor memberships | **yes** | already wired |
| **ESO generators** | V1, V2, V4 once re-homed | **yes** | none |

Secrets stay out of tofu state, as the repo-config RFC §8.1 rows 18 and 21 decided: tofu owns
shape (rules, whitelists, variables, hooks), provisioners and bridges own values.

### The irreducible floor

After part B, a rebuild needs exactly this from a person:

1. **L0**, unchanged: age key, `talsecret`, `cluster-secrets`, OpenBao unseal key.
2. **External accounts that only their provider can issue a credential for**, stored once in L1:
   - one GitHub App private key per GitHub owner (`ploeg-hq` for the GitHub module and bridge;
     the existing Renovate App on `webgrip`). Creating and installing a GitHub App needs the
     GitHub web UI, even through the manifest flow.
   - the Cloudflare manager token (it mints every other Cloudflare token already).
   - the Docker Hub token, the Open VSX PAT, the VS Marketplace PAT.
   - the classic PAT in G9, unless GHCR accepts installation tokens of the GitHub App for push;
     test that before retiring it.
3. **One click per new GHCR package** (G5). GitHub has no REST endpoint that changes a container
   package's visibility. The best git can do is detect it: an anonymous `tags/list` probe per
   package, alerting on non-200.

Everything else, including V1, V2 and V4, can be born in-cluster from generators: Forgejo creates
its admin from the Secret it is given, Authentik's client secret for Harbor already comes from a
generator, and the webhook bearer list can be several generator outputs joined by the
ExternalSecret template.

### The `ploeg-release` bot today

| Piece | Declarative with what exists? | How, or what is missing |
| --- | --- | --- |
| Forgejo user `ploeg-release` | **yes** | copy `unfold-reports-provisioner.cronjob.yaml`: generator password, `POST /admin/users`, idempotent |
| Write on `webgrip/unfold` only | **yes** | same provisioner: `PUT /repos/webgrip/unfold/collaborators/ploeg-release` with `write`; not a team member |
| Token (`write:repository`, `write:issue`, `read:user`) | **yes** | same provisioner: keep while it authenticates, otherwise re-mint and revoke the rest; Secret → PushSecret → OpenBao `forgejo/ploeg-release` |
| Merge-whitelist entry on `development` | **not needed** | `development` has no merge whitelist live, so the write collaboration is enough. The rule itself (including `ploeg-docs`) is owned by the repo-config module, and `forgejo-sync.sh --only protect` is retired, so no hand sweep can rewrite it |
| GitHub secret `RELEASE_CONSUMER_TOKEN_FORGEJO` | **after the App step** | the GitHub L3 bridge is built; it waits only for the `ploeg-hq` GitHub App ([owner steps](../runbooks/github-app-ploeg-hq.md#owner-steps-the-one-ui-step)). GitHub-hosted runners cannot reach the LAN-only OpenBao, so an L4 OIDC read is not available |
| GitHub variable `RELEASE_CONSUMERS` | **after the App step and the switch** | the GitHub module holds it behind `release_consumers_enabled`; the same App |

So three of six pieces can land today with one new CronJob; the other three wait on two missing
mechanisms. Until then the honest interim is one ordered hand step list run by the owner, recorded
on the ticket, with the token copied from OpenBao (not re-minted) so the provisioner stays its
owner.

### Order of work

1. **Repo-config module, branch protection first** (VIK-1310, VIK-1311): **done 2026-10-18.**
   `homelab-cluster` `main` is the `homelab` profile with the four `e2e /` contexts live (the owner
   kept four, not seven); `webgrip/unfold` `development` requires `ploeg-docs`. `forgejo-sync.sh`
   refuses `--only protect` and `--only settings`. Turning on merge whitelists on `unfold` is an
   open owner decision: it would restrict merging, which is open to every writer today.
2. **`ploeg-release` provisioner**, the pattern above, with a staleness alert like
   `unfold-reports`.
3. **`ploeg-hq` GitHub App and the GitHub module**: import G1–G4 into state with `import` blocks,
   prove an empty plan, then own G6. Plan-only first, as the repo-config RFC does.
4. **GitHub L3 bridge** for G7, validated against the Forgejo API with the token it publishes, and
   alerting when stale. D5 goes live after this.
5. **Rest of the repo-config scope**: F4 webhooks (bearer from OpenBao), F6 topics, F9 variables,
   F5 settings, then F7 push mirrors (VIK-1325) with G10 replaced by the GitHub App.
6. **Re-home seeded values to generators**: V4 (drop the write-back PushSecret, as P1b already
   asks), V2, V1.
7. **GHCR visibility probe** for G5, and a test that GHCR accepts App installation tokens (retire
   G9 if so).
8. **Rebuild rehearsal**: on a scratch Forgejo and a fixture GitHub repo, apply the modules from an
   empty state and check that the chain cuts an rc and opens the Unfold PR with no other step.
   Until that passes, "reproducible" is a claim, not a property.

## Related

- [ADR-0050](../adr/adr-0050-per-repo-delivery-contract.md) branch protection contract and
  [rollout runbook](../runbooks/forgejo-branch-protection-rollout.md)
- [ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md) and the
  [L3 bridge runbook](../runbooks/secrets-level-3-bridge.md)
- [Renovate runbook](../runbooks/renovate.md), [Harbor runbook](../runbooks/harbor.md)
- Unfold ADR-0041 and Ploeg ADR 0119 (producer opens the consumer's PR)
