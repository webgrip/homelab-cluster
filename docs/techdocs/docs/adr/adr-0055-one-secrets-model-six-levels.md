---
status: accepted
date: 2026-10-04
---

# One secrets model for the estate: six levels, the vault as the only source, repo-scoped delivery by default

Technical Story: owner request (2026-09-05), raised while deciding where a Brevo API key for
`twente.dev` should live. That question had no answer because no document describes the levels
a secret can live at, which one a new secret goes to, or what each level promises. The estate
already runs six mechanisms; the only org-wide text
([`ai-skills/org/org-guidelines.md`](https://forgejo.webgrip.dev/webgrip/ai-skills/src/branch/main/org/org-guidelines.md),
line 11) describes one of them, and per-repo ADRs have started deciding locally on assumptions
that are false for this estate.

## Context and Problem Statement

Counted on 2026-09-05 across the fifteen repos checked out locally, secrets are held by six
distinct mechanisms:

| Where | Mechanism | Size |
| --- | --- | --- |
| In Git, encrypted | SOPS with one age key ([`.sops.yaml`](../../../../.sops.yaml)) | 7 files: 3 are the deliberate floor, 4 are live-wired stragglers |
| The vault | OpenBao at `openbao.security.svc.cluster.local:8200`: KV v2 at `secret/`, a `database` engine minting leases, a `transit` engine holding the cosign key | root revoked at bootstrap, config reconciled by CronJob |
| The cluster | External Secrets Operator: `ExternalSecret` reads, `PushSecret` writes, `ClusterGenerator` entropy | 101 ExternalSecrets (58 from KV, 24 from generators), 46 PushSecrets |
| CI, static | Forgejo Actions org and repo secrets, published hourly from the vault by [`forgejo-actions-secrets`](../../../../kubernetes/apps/forgejo/forgejo-actions-secrets/app/forgejo-actions-secrets.cronjob.yaml) | 34 distinct secret names referenced in `webgrip/workflows`, `secrets: inherit` used nowhere |
| CI, short-lived | Forgejo Actions OIDC exchanged at `auth/forgejo` for a 10-minute token bound to repository and event ([infrastructure ADR-0004](https://forgejo.webgrip.dev/webgrip/infrastructure/src/branch/main/docs/adrs/0004-supply-chain-on-forgejo-harbor-openbao.md)) | one role, `cosign-signer` |
| Outside the cluster | CronJob bridges that push vault values to stores that cannot pull: Forgejo Actions, Cloudflare Worker secrets ([`counterscale-worker-secrets`](../../../../kubernetes/apps/forgejo/forgejo-actions-secrets/app/counterscale-worker-secrets.cronjob.yaml)); a monthly roller for the Cloudflare deploy token | 3 bridges, 1 roller |
| A laptop | Keychain entries exported into the shell from `~/.zshrc`; `just bao-login` for humans who need the vault | undocumented anywhere |

Three ADRs govern parts of this: [ADR-0015](adr-0015-secret-rotation-model.md) (rotation is
one vault write), [ADR-0016](adr-0016-openbao-dynamic-postgres-credentials.md) (mint what can
be minted), and [ADR-0030](adr-0030-forgejo-static-bot-pat.md) (a static PAT where the forge
has no app concept). The per-class rotation doc
([secret-rotation-strategy](../general/secret-rotation-strategy.md)) is the best description of
the vault tier and says nothing about CI, bridges or laptops.

The gap has costs already paid. `twente.dev` ADR 0017 (2026-09-04) decided that a Brevo key
"stays out of CI" because a CI secret would be a static value in the Forgejo store readable by
every job; that assumption ignores the OIDC path that has signed every release since July and
the bridge that validates and re-publishes tokens hourly. The bridge itself is a 27 KB shell
script that grows by three hand-written blocks per secret. Most of what it publishes is
org-wide, so every repo's workflows can read the npm publish token and the GitHub PAT. The
`openbao-push` store is documented as "migration only, remove afterwards" in
[`push.hcl`](../../../../kubernetes/apps/security/openbao/bootstrap/push.hcl) while three
rollers now depend on it. Four `*.sops.yaml` files that are live-wired into kustomizations sit
outside the floor the migration blog declared closed. And the `guard-secrets` hook's third rule
is a gitleaks scan that silently skips on every machine where gitleaks is not installed, which
today includes the owner's.

The question this record answers: **at which level does a secret live, what does each level
promise, and what has to change so the answer holds for the next hundred secrets without a
human re-deriving it.**

## Decision Drivers

* One value, one source. Every copy is either a cache that can be regenerated from the source
  or a bridge that is reconciled from it. Never a second original.
* Least privilege by default. A credential that one repo needs is visible to one repo.
* The human sits exactly where judgment is needed, and nowhere else. Provided values enter
  through a person once; everything after that is a controller.
* Adding a secret is a small, reviewable diff, not a script edit.
* A consumer keeps running when the vault is down (the ESO cache property from the migration).
* Static credentials are validated against their provider on a timer and fail loud; the
  direction for anything mintable is short-lived.
* The model must be true of what exists on 2026-09-05, so it can be enforced from day one.

## Considered Options

* Six named levels, the vault as the only source, repo-scoped CI delivery by default, bridges
  driven by a manifest table, humans read the vault instead of keeping copies.
* Codify the status quo as it stands, with no rule changes.
* Retire the Forgejo bridge: every CI job reads the vault directly over OIDC.
* Make the forge's own secret store the source for CI, and keep the vault for the cluster only.

## Decision Outcome

Chosen option: "Six named levels, the vault as the only source, repo-scoped CI delivery by
default, bridges driven by a manifest table, humans read the vault instead of keeping copies",
because it is the only option that both describes what runs today and removes the four
weaknesses the count exposed, without adding a runtime dependency on the vault for consumers
or an external-runner problem for CI.

### The six levels

| Level | Holds | Who writes | Who reads | Promise |
| --- | --- | --- | --- | --- |
| **L0 Floor** | What must exist before the vault does: `bootstrap/sops-age`, `talos/talsecret`, `kubernetes/components/sops/cluster-secrets` (build-time `${SECRET_DOMAIN}`), and the unseal key in the `openbao-keys` Secret. `AGENTS.md` also names a GitHub deploy key; no file by that name exists in the tree, so where it rests is the first open item for the L0 runbook | A person, by ADR only | Flux, Talos, the unsealer | Closed list. Nothing joins it without a new record. |
| **L1 Vault** | Every provided value (class B), every at-rest key that must be preserved (class D), the dynamic engines, the transit key | A person over OIDC and MFA, or a roller by PushSecret; never an agent | ESO, bridges, rollers, humans over OIDC | The single original. Rotation is one write here ([ADR-0015](adr-0015-secret-rotation-model.md)). Snapshot nightly to Garage, 14 kept. |
| **L2 Cluster** | Kubernetes Secrets materialised by ESO, from L1 or from a generator | ESO only | Pods, by `existingSecret` / `envFrom` | A cache. Survives a vault outage. Entropy (class C) is born here and never touches L1. |
| **L3 Bridge** | Copies in stores that cannot pull: Forgejo Actions secrets, Cloudflare Worker secrets | A CronJob, from an L2 copy of an L1 value | The target platform | Reconciled hourly, validated against the provider, alerts when stale. Repo-scoped unless a row says why not. |
| **L4 Short-lived** | Nothing at rest: OIDC tokens exchanged at the vault, `database` leases, per-run forge tokens ([ploeg ADR-0013](https://forgejo.webgrip.dev/webgrip/ploeg/src/branch/main/docs/adrs/0013-push-rights-are-minted-per-run.md)), transit signatures | The vault, per request | The requesting job, for its TTL | The direction for everything mintable. Bound to repository and event, never to a runner. |
| **L5 Person** | A session export on a laptop | A person, from L1 over `just bao-login` | That person's shell | A cache of an L1 value, never the only copy. Personal identity tokens (a Vikunja PAT) are not estate secrets and live in the Keychain without an L1 original. |

### Rules that follow

**Placement is decided by origin, then by consumer.** Entropy no human needs to know is L2 by
generator. A value the outside world issued is L1. Anything a vault engine can mint is L4. Only
then ask who consumes it: a pod reads L2, a workflow reads L3 or L4, a person reads L5.

**CI secrets are repo-scoped by default.** The bridge publishes to
`/repos/webgrip/<repo>/actions/secrets/` unless the row names the reason it must be org-wide.
Today's org-wide set (`HARBOR_ROBOT_*`, `WEBGRIP_CI_TOKEN`, `DT_API_KEY`) earns it: every
release-path workflow needs them. `NPMJS_TOKEN`, `GHCR_TOKEN`, `GH_RELEASE_TOKEN`,
`CLOUDFLARE_API_TOKEN` and `CODEBERG_TOKEN` do not, and move to the repos that use them.

**A bridge is a table, not a script.** `forgejo-actions-secrets` reads its work from a manifest
of rows, `{vaultPath, key, name, scope, verify}`, so that adding a secret is one row plus one
`ExternalSecret`, reviewable in a diff. The validate-then-publish stance and the
`ForgejoActionsSecretsReconcileStale` alert stay exactly as they are; they move from per-block
prose into a per-row field. Rows without a `verify` endpoint say so, so a reviewer can see which
tokens fail only at use.

**Humans read the vault; they do not keep originals.** `just bao-login` then
`just secret-env <path>` exports an L1 value into the current shell. A Keychain entry is
allowed as a cache for a value the person needs off-VPN, and the runbook says which path it
mirrors; rotation happens at L1 and the cache is refreshed, never edited. An agent has no vault
token and never enters a provided value; that step is a person's.

**The floor is closed.** The four wired stragglers, `erfbeeld` dev/staging/production and
`zomboid`, are migrated or deleted; they are live SOPS secrets outside the floor and the
migration is not done until they are gone.

**Every static credential is verified on a timer.** The bridge already does this for
Cloudflare, GitHub and npm. The rule generalises: a row without a verify endpoint is an accepted
exception, written down, not a default.

**`openbao-push` is a roller store, not a migration store.** Its purpose is rewritten and its
policy narrowed to the paths the rollers write. The "remove after migration" note is retired.

**`gitleaks` is pinned in every repo's `.mise.toml`**, and the `guard-secrets` hook reports when
it is absent instead of skipping silently.

**Naming.** L1 paths are `secret/<provider>/<purpose>`. CI names are `<PROVIDER>_<PURPOSE>` and
never carry the reserved `FORGEJO_`, `GITHUB_`, `GITEA_` prefixes. A repo-scoped secret uses the
same name it would have had org-wide; Forgejo resolves repo over org, which is the mechanism
`TECHDOCS_S3_*` already relies on.

### The first instance

The Brevo key that raised the question lands as: `secret/brevo/twente-dev` written once by a
person over OIDC; `ExternalSecret/forgejo-brevo` in the `forgejo` namespace; one bridge row
publishing `BREVO_API_KEY` repo-scoped to `twente.dev`, verified against `GET /v3/account`;
`pnpm mail:draft` runs in that repo's workflow and stops at a draft, as its ADR 0017 already
requires. The same person reads it locally with `just secret-env brevo/twente-dev`. One
original, two caches, no laptop copy that outlives the shell.

### Consequences

* Good, because the answer to "where does this secret go" is a table lookup, and the runbooks
  and the agent skill can be written against a fixed set of levels.
* Good, because least privilege becomes the default shape of the bridge instead of an
  exception three rows deep.
* Good, because a new CI secret is one row and one ExternalSecret, which a reviewer can read
  in a diff, instead of three blocks in a script that already exceeds 500 lines.
* Good, because the migration is finally closed on the floor it declared, and the one stale
  claim in the vault's own policy file is retired.
* Good, because the hook's silent skip becomes a visible warning, on every machine.
* Bad, because moving five secrets from org to repo scope touches every workflow that reads
  them; a workflow in a repo that was never listed will lose the secret and fail. That is the
  point, and it is the migration cost.
* Bad, because the bridge refactor is real work on a script that is load-bearing for every
  release; it is sequenced behind a mutation test that proves the table form publishes the
  same set the script form does.
* Bad, because vault-first for humans requires VPN or LAN for the first read; the Keychain
  cache is the concession, and it reintroduces a copy that a person has to remember to
  refresh. The runbook names the path so at least the copy knows its source.
* Neutral, because none of this changes what pods see: L2 is untouched.

### Confirmation

* `find . -name '*.sops.yaml' -not -name '.sops.yaml'` returns exactly three paths:
  `bootstrap/sops-age.sops.yaml`, `talos/talsecret.sops.yaml`,
  `kubernetes/components/sops/cluster-secrets.sops.yaml`. Any other path fails the check.
* Every `put_secret` in the bridge corresponds to a row with a `scope`; `grep -c orgs/`
  against the bridge equals the number of rows whose reason field is non-empty.
* The bridge publishes the same names before and after the table refactor, proven by a
  mutation test that removes one row and watches that name stop being reconciled, plus one
  run that must pass.
* `bao policy read external-secrets-push` lists only the paths the rollers write.
* `mise exec -- gitleaks version` succeeds in every repo, and running the `guard-secrets` hook
  on a machine without it prints a warning that names the missing scan.
* `just secret-env brevo/twente-dev` exports `BREVO_API_KEY` after `just bao-login`, and the
  Forgejo repo settings for `twente.dev` show `BREVO_API_KEY` while the org settings do not.
* `ForgejoActionsSecretsReconcileStale` fires when a verify endpoint rejects a value; tested by
  writing a known-bad value to a scratch path once.

## Pros and Cons of the Options

### Six levels, vault as source, repo-scoped bridges, vault-first humans

* Good, because it names what exists and changes only the defaults that the count showed to be
  wrong.
* Good, because every level has one writer and one reader class, so an incident has a short
  list of places to look.
* Bad, because it is a policy with six parts, and six parts need six runbooks to be usable by
  a person under pressure.

### Codify the status quo

* Good, because it is a day of writing and no migration.
* Bad, because it enshrines org-wide as the CI default and a script as the bridge, the two
  things that make the next hundred secrets cost more than the last hundred.
* Bad, because it leaves ADR 0017's false premise standing as the estate's only written
  position on CI secrets.

### Retire the bridge, CI reads the vault over OIDC

* Good, because it is the L4 endgame: nothing at rest in Forgejo at all, and every read is
  bound to repository and event.
* Bad, because it makes every workflow depend on the vault being reachable from the runner at
  run time; that holds for the in-cluster runner and fails for any external runner, and the
  estate still has GitHub-hosted lanes in transition.
* Bad, because it needs a reusable "fetch secrets" action in `webgrip/workflows` and a role per
  repo in `config.sh` before a single workflow can move. This record keeps it as the direction
  for L4 and names the trigger: the day a secret needs per-job scoping the bridge cannot give,
  or the bridge table passes thirty rows.

### The forge store as the CI source

* Good, because it is how most teams start, and the Forgejo UI is a fine place to paste a
  token.
* Bad, because it creates a second original: a value in Forgejo that the vault does not know,
  cannot rotate, cannot snapshot, and the bridge would overwrite on its next tick. It is exactly
  the state this estate migrated away from in June.

## More Information

* 2026-06-12 — the SOPS-to-ESO migration declared the floor
  ([blog](../blogs/2026-06-12-the-long-goodbye-to-sops.md)); four wired files were left outside
  it.
* 2026-07-01 — rotation settled as one vault write ([ADR-0015](adr-0015-secret-rotation-model.md)).
* 2026-07-02 — dynamic Postgres credentials as the mintable endgame
  ([ADR-0016](adr-0016-openbao-dynamic-postgres-credentials.md)).
* 2026-07-31 — CI signing moved onto Forgejo OIDC exchanged at the vault, the first L4 use in
  CI ([infrastructure ADR-0004](https://forgejo.webgrip.dev/webgrip/infrastructure/src/branch/main/docs/adrs/0004-supply-chain-on-forgejo-harbor-openbao.md)).
* 2026-09-02 — the Cloudflare deploy token became the first fully machine-rotated L1 value, and
  the Worker secrets the first non-Forgejo bridge (`824cd150`).
* 2026-09-04 — `twente.dev` ADR 0017 chose "the key stays out of CI" on the premise that CI
  secrets are static and org-readable; this record supersedes that half of it and leaves its
  draft-not-send decision intact.
* 2026-09-05 — proposed, after counting every mechanism across fifteen repos.
* Refines [ADR-0015](adr-0015-secret-rotation-model.md) and
  [ADR-0016](adr-0016-openbao-dynamic-postgres-credentials.md), which stay accepted: they
  describe L1 and L4; this record places them among the other four.
* Consistent with [ADR-0030](adr-0030-forgejo-static-bot-pat.md): a static PAT is an L1 value
  with an L3 copy, minted in-cluster, which is the shape this record prescribes.
* Supported by [workflows ADR-0004](https://forgejo.webgrip.dev/webgrip/workflows/src/branch/main/docs/adrs/0004-ci-bot-identity-and-forgejo-package-distribution.md)
  (the un-shadowable `CI_TOKEN` contract is what repo-scoping relies on) and
  [ploeg ADR-0013](https://forgejo.webgrip.dev/webgrip/ploeg/src/branch/main/docs/adrs/0013-push-rights-are-minted-per-run.md)
  (per-run tokens are L4 applied to agents).
* 2026-09-05 — accepted by the owner on all four changes. Runbooks per level:
  [L0](../runbooks/secrets-level-0-floor.md), [L1](../runbooks/secrets-level-1-vault.md),
  [L2](../runbooks/secrets-level-2-cluster.md), [L3](../runbooks/secrets-level-3-bridge.md),
  [L4](../runbooks/secrets-level-4-short-lived.md), [L5](../runbooks/secrets-level-5-person.md);
  the `secrets-levels` skill in `webgrip/ai-skills`; `org-guidelines.md` line 11 rewritten to
  point here. The first instance (`secret/brevo/twente-dev`) is wired as
  `forgejo-brevo.externalsecret.yaml` plus a repo-scoped bridge block, fail-soft until seeded.
* Still to execute from the accepted set, tracked separately: the bridge table refactor, the
  five org-to-repo scope moves, the `openbao-push` policy narrowing, and the four floor
  stragglers.
* 2026-10-04 — the level-4 trigger fired: per-zone Cloudflare DNS tokens minted in-cluster and a CI OIDC read role (2f50f76b), recorded as [ADR-0061](adr-0061-ci-reads-over-oidc-writes-from-the-cluster.md) (logged in audit 2026-10-04)
