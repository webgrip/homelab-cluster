# The unfold-hq GitHub Apps: Unfold moves to its own GitHub organisation

Unfold moves from Forgejo `webgrip/unfold` to [github.com/unfold-hq/unfold](https://github.com/unfold-hq/unfold),
which becomes its source of truth. GitHub Actions there publishes `ghcr.io/unfold-hq/unfold`,
`ghcr.io/unfold-hq/unfold-agent` and the chart `oci://ghcr.io/unfold-hq/charts/unfold`, signed
keyless through GitHub OIDC. The homelab only pulls. Forgejo keeps a read-only pull mirror,
`webgrip/unfold-mirror`, as it does for Ploeg (`webgrip/ploeg-mirror`).

This page follows the `ploeg-hq` precedent ([github-app-ploeg-hq](github-app-ploeg-hq.md)) and
covers three stages:

1. **PR 1 (this preparation, inert).** Everything below is built and does nothing until the owner
   stores credentials. The one live change: the homelab stops recreating the push mirror to
   `github.com/webgrip/unfold`.
2. **PR 2 (cutover day).** The model and the bridges switch to `unfold-hq`.
3. **PR 3 (after cutover).** Staging Unfold, docs and the remaining Forgejo leftovers follow
   ([what it changed](#what-pr-3-changed-after-cutover)).

## Two Apps, not one

| App | Repository permissions | Key in OpenBao | Used by |
| --- | --- | --- | --- |
| `unfold-hq-gitops` | Administration: read and write; Secrets: read and write; Variables: read and write; Metadata: read | `secret/github/unfold-hq-app` | `Terraform/unfold-hq` (rulesets, settings) and the [GitHub secrets bridge](#the-secrets-bridge) writing into `unfold-hq/unfold` |
| `unfold-hq-bot` | Contents, Pull requests, Issues, Workflows: read and write; Checks, Commit statuses, Dependabot alerts: read; Metadata: read | `secret/github/unfold-hq-bot-app` | Renovate on `unfold-hq/unfold`, and Ploeg's release-consumers job in `ploeg-hq/ploeg`, which opens the Ploeg-pin pull request in `unfold-hq/unfold` |

They are separate for the reason given in
[the ploeg-hq Renovate App section](github-app-ploeg-hq.md#the-renovate-app): the gitops key can
edit the rulesets that require `gate`, the bot key can push code. On one App, whoever holds the
key could switch off the required check and merge past it.

`unfold-hq` holds no Webgrip secret except what this repository's bridge writes. The Cloudflare
account stays the current one for now.

## What PR 1 built, and what it does until the keys exist

| Piece | Path | Without credentials |
| --- | --- | --- |
| Model owner | `github.owners.unfold-hq.app_secret_path: github/unfold-hq-app` in `kubernetes/apps/repo-config/repo-config/model/repos.yaml` | no repository under `unfold-hq/` yet, so no Terraform object plans anything for it |
| Terraform object | `kubernetes/apps/github-config/unfold-hq/` (`Terraform/unfold-hq`, `vars.github_owner: unfold-hq`, own ServiceAccount, Role, network policies and `GitHubConfigUnfoldHqNotReady`) | `spec.suspend: true`: no runner pod, no plan |
| OpenBao | policies `github-config-unfold-hq`, `renovate-github-app-token-unfold-hq`, and four more read paths on `github-secrets-bridge` (`kubernetes/apps/security/openbao/bootstrap/`) | grants on paths that are empty |
| Renovate | `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token-unfold-hq.cronjob.yaml`, `unfold-hq.yaml`, `configmap-unfold-hq.yaml` | the minter logs `app credentials absent` and exits 0; the RenovateJob reads its token Secret as optional and discovers nothing; `GitHubAppUnfoldHqBotPending` (info) |
| Secrets bridge | five new targets in `kubernetes/apps/github-secrets-bridge/github-secrets-bridge/app/targets.json` | `unfold-hq/unfold` targets: `app credentials absent`, `GitHubAppUnfoldHqPending` (info). `ploeg-hq/ploeg` bot targets: `source absent`, `GitHubSecretsBridgeSourcePending` (info) |
| Image signatures | `kubernetes/apps/kyverno/policies/app/image-verify-unfold-hq-audit.yaml` | matched no running image until PR 3; Audit only |
| No push mirror | `unfold-distribution.job.yaml` removed from `forgejo-actions-secrets`; `scripts/forgejo-sync.sh --only mirror` skips `unfold` | live: nothing in this repository creates a push mirror to `github.com/webgrip/unfold` again |

Why the push mirror had to go first: GitHub redirects git and API calls for a transferred
repository. A Forgejo push mirror to `ssh://git@github.com/webgrip/unfold.git` would follow that
redirect and force-push stale Forgejo state over `unfold-hq/unfold`, and its deploy key moves with
the repository, so the push would be accepted. The removed Job recreated that mirror and its
deploy key whenever they were missing. Its other step, `OVSX_PAT` on Forgejo `webgrip/unfold`, is
already bridged hourly by `forgejo-actions-secrets.cronjob.yaml` (`VSCODE_EXTENSION_REPO`), so
nothing else was lost. The `github-mirrors` reconciler never creates mirrors: it reads Forgejo's
push mirrors and copies missing releases to GitHub. It does write releases to the tracked
`webgrip/unfold` entry, which is why PR 2 removes that entry on the same day as the transfer.

The existing push mirror on Forgejo is still live and keeps pushing to `github.com/webgrip/unfold`
until the owner deletes it on cutover day (step 2 below). That is deliberate: until the transfer,
the GitHub copy is a mirror of Forgejo and should stay current.

## Owner steps: create the Apps

Both Apps can be created now. Install them, and store their keys, only after the repository has
been transferred to `unfold-hq` (cutover day, step 4): the installation ID only exists once the
App is installed on `unfold-hq/unfold`, and the bridge starts writing the moment the key is stored.

### `unfold-hq-gitops`

1. Open <https://github.com/organizations/unfold-hq/settings/apps/new>.
2. Fill in:
   - **GitHub App name:** `unfold-hq-gitops`
   - **Homepage URL:** `https://github.com/unfold-hq/unfold`
   - **Webhook:** untick **Active**. Leave the URL empty.
   - **Repository permissions:**
     - **Administration:** Read and write
     - **Secrets:** Read and write
     - **Variables:** Read and write
     - **Metadata:** Read-only (GitHub sets this itself)
     - every other repository permission: No access
   - **Organization permissions** and **Account permissions:** No access for all.
   - **Where can this GitHub App be installed?** Only on this account.
3. **Create GitHub App**. Note the **App ID**.
4. **Private keys → Generate a private key**. A `.pem` file downloads.

### `unfold-hq-bot`

1. Open <https://github.com/organizations/unfold-hq/settings/apps/new> again.
2. Fill in:
   - **GitHub App name:** `unfold-hq-bot` (it becomes the PR author `unfold-hq-bot[bot]`)
   - **Homepage URL:** `https://github.com/unfold-hq/unfold`
   - **Webhook:** untick **Active**.
   - **Repository permissions:**
     - **Contents:** Read and write
     - **Pull requests:** Read and write
     - **Issues:** Read and write (the Dependency Dashboard issue)
     - **Workflows:** Read and write (pinned Actions bumps in `.github/workflows/`)
     - **Checks:** Read-only
     - **Commit statuses:** Read-only
     - **Dependabot alerts:** Read-only
     - **Metadata:** Read-only
     - every other repository permission, including **Administration** and **Secrets**: No access
   - **Organization permissions** and **Account permissions:** No access for all.
   - **Where can this GitHub App be installed?** Only on this account.
3. **Create GitHub App**, note the **App ID**, then **Generate a private key**.

Keep both `.pem` files somewhere only you can read until cutover day, or generate the keys on
that day instead.

### Install and store (only after the transfer)

For each App: on its settings page click **Install App**, then **Install** next to `unfold-hq`,
choose **Only select repositories**, pick `unfold-hq/unfold`, and click **Install**. The browser
lands on `https://github.com/organizations/unfold-hq/settings/installations/<number>`; that number
is the **installation ID**.

```bash
mise exec -- just bao-login
export BAO_ADDR="$(mise exec -- just bao-addr)"
mise exec -- bao kv put secret/github/unfold-hq-app \
  app_id=<gitops App ID> installation_id=<gitops installation ID> private_key=@<path to the gitops .pem>
mise exec -- bao kv put secret/github/unfold-hq-bot-app \
  app_id=<bot App ID> installation_id=<bot installation ID> private_key=@<path to the bot .pem>
```

Delete both `.pem` files afterwards. OpenBao and its snapshots hold the copies.

The bot key also reaches `ploeg-hq/ploeg` as the Actions secrets
`RELEASE_CONSUMER_GITHUB_APP_ID` and `RELEASE_CONSUMER_GITHUB_APP_PRIVATE_KEY`, written by the
bridge through the existing `ploeg-hq-gitops` App. The names are generic on purpose: Ploeg's
ADR-0069 forbids naming a consumer in its workflows, and its release-consumers workflow
([ploeg-hq/ploeg#415](https://github.com/ploeg-hq/ploeg/pull/415)) reads these names. It mints a
short installation token from them with `actions/create-github-app-token` (`owner: unfold-hq`,
`repositories: unfold`). The installation covers `unfold` only, so that token cannot reach any
other repository.

## The secrets bridge

The bridge (`kubernetes/apps/github-secrets-bridge/`) runs hourly at :41 and walks the targets in
`app/targets.json`. Each target names a GitHub owner and repository, the Actions secret, the
OpenBao path of the App that may write it, and where the value comes from. A target whose App
key is absent, or whose OpenBao source is absent, is skipped with exit 0; a target that fails
does not stop the others, and the run exits 1 once all have been tried.

| Repository | Secret | Source in OpenBao | App |
| --- | --- | --- | --- |
| `ploeg-hq/ploeg` | `RELEASE_CONSUMER_TOKEN_FORGEJO` | `forgejo/ploeg-release` `token`, through ExternalSecret `github-secrets-bridge-source` | `ploeg-hq-gitops` |
| `ploeg-hq/ploeg` | `RELEASE_CONSUMER_GITHUB_APP_ID` | `github/unfold-hq-bot-app` `app_id` | `ploeg-hq-gitops` |
| `ploeg-hq/ploeg` | `RELEASE_CONSUMER_GITHUB_APP_PRIVATE_KEY` | `github/unfold-hq-bot-app` `private_key` | `ploeg-hq-gitops` |
| `unfold-hq/unfold` | `CLOUDFLARE_API_TOKEN` | `cloudflare/deploy` `CLOUDFLARE_API_TOKEN` | `unfold-hq-gitops` |
| `unfold-hq/unfold` | `CLOUDFLARE_ACCOUNT_ID` | `cloudflare/deploy` `CLOUDFLARE_ACCOUNT_ID` | `unfold-hq-gitops` |
| `unfold-hq/unfold` | `CLOUDFLARE_DNS_READ_TOKEN` | `cloudflare/dns/unfoldhq-dev-ro` `token` | `unfold-hq-gitops` |

The Cloudflare deploy token is the one the Forgejo org secrets use today. The token roller
replaces it every month, so a hand-set GitHub secret would go stale; the bridge sees the new
fingerprint and rewrites the secret within the hour. The DNS read token is minted by
`cloudflare-dns-token-minter`. New sources are read straight from OpenBao by the bridge's own
Kubernetes-auth role, so a source that does not exist yet is a clean skip, not a failing
ExternalSecret.

Each target keeps only a SHA-256 fingerprint of its source, in its own state ConfigMap
(`state_configmap` in `targets.json`; the Role lists each name). The Ploeg target keeps the
existing `github-secrets-bridge-state`, so its first run after this change writes nothing.
`scripts/test-github-secrets-bridge.sh` checks that every state ConfigMap is in the Role and
every OpenBao path is in `github-secrets-bridge.hcl`, and mutates the bridge so each check is
seen to fail.

To add a target: add it to `targets.json`, its state ConfigMap to `app/rbac.yaml`, and any new
OpenBao path to `kubernetes/apps/security/openbao/bootstrap/github-secrets-bridge.hcl`.

## Cutover day

Do these in order, with no Unfold or Ploeg release in flight. Steps 1 to 4 are owner steps in
the GitHub and Forgejo UIs; step 5 is PR 2.

1. **Freeze.** Merge nothing on Forgejo `webgrip/unfold` from here on. Note its `development` and
   `main` heads (`git ls-remote https://forgejo.webgrip.dev/webgrip/unfold.git`) and check that
   `github.com/webgrip/unfold` has the same heads (`git ls-remote https://github.com/webgrip/unfold.git`).
2. **Delete the Forgejo push mirror.** On
   <https://forgejo.webgrip.dev/webgrip/unfold/settings>, under **Mirror settings → Push mirrors**,
   remove the `github.com/webgrip/unfold` entry. Check the list is empty:
   `curl -fsS -H "Authorization: token $FORGEJO_TOKEN" https://forgejo.webgrip.dev/api/v1/repos/webgrip/unfold/push_mirrors`
   returns `[]`.
3. **Transfer on GitHub.** <https://github.com/webgrip/unfold/settings> → **Danger Zone →
   Transfer**, new owner `unfold-hq`. Then on
   <https://github.com/unfold-hq/unfold/settings/keys> delete the deploy key **Forgejo Unfold push
   mirror**: it came along with the repository and is the one credential that could still push
   from Forgejo.
4. **Install the Apps and store the keys** ([above](#install-and-store-only-after-the-transfer)).
5. **Merge PR 2** with the changes listed below, then:
   - run the bridge and read its log:

     ```bash
     mise exec -- kubectl -n github-secrets-bridge create job --from=cronjob/github-secrets-bridge github-secrets-bridge-cutover
     mise exec -- kubectl -n github-secrets-bridge logs job/github-secrets-bridge-cutover
     ```

     Expect five `written (absent on GitHub)` lines for the new targets and `already matches the
     source; no write` for `RELEASE_CONSUMER_TOKEN_FORGEJO`.
   - run the Renovate token minter:

     ```bash
     mise exec -- kubectl -n renovate create job --from=cronjob/renovate-github-app-token-unfold-hq renovate-github-app-token-unfold-hq-first
     mise exec -- kubectl -n renovate logs job/renovate-github-app-token-unfold-hq-first
     ```

     Expect `installation token for unfold written to Secret renovate/renovate-unfold-hq-token`.
     Renovate does nothing on `unfold-hq/unfold` unless `renovate.json` is on `development`
     (`requireConfig: required`). Unfold's `renovate.json` extends only Renovate's built-in
     presets (`config:recommended`, `abandonments:recommended`, `mergeConfidence:all-badges`) and
     carries the former Webgrip preset rules inline, so it needs no Webgrip preset on GitHub.
   - read the first plan of `Terraform/unfold-hq`:

     ```bash
     mise exec -- kubectl -n github-config get terraform unfold-hq -o jsonpath='{.status.plan.pending}'
     mise exec -- kubectl -n github-config get cm tfplan-default-unfold-hq -o jsonpath='{.data.tfplan}'
     ```

     It should import the repository, its default branch and its Actions and workflow
     permissions, change only the settings the model sets differently, and create the three
     rulesets. Once a person has read it, set `spec.approvePlan: auto` in a follow-up pull
     request, as `Terraform/ploeg-hq` has. A plan id names the Git revision it was planned at, so
     the approving commit itself would make an exact id stale; the plan at the approving commit
     is the same one, because `approvePlan` is not an input of the module.

### What PR 2 changes

| Change | Where | Why |
| --- | --- | --- |
| Forgejo `unfold` entry becomes `forge: forgejo` plus `settings.archived: true`: it drops `kind` and `staged` (the validator refuses them on an archived repository) and `renovate`. It keeps `branches`, spelled out as the rules the `protected` profile and the `staged` layer gave it, because an archived repository is on `baseline`, which derives no branch rule, and every `forgejo_branch_protection` has `prevent_destroy`: dropping `unfold/main` and `unfold/development` would fail the whole `Terraform/repo-config` plan. With the rules spelled out they plan no change. The tag protection `unfold/*` has no `prevent_destroy` and is deleted, as for every archived repository. Do not rename the entry: `forgejo_repository` has `prevent_destroy` too, so a rename plans a destroy and fails | `kubernetes/apps/repo-config/repo-config/model/repos.yaml` | Forgejo `webgrip/unfold` becomes read-only history |
| Remove the `webgrip/unfold` GitHub entry (`mirror_of: unfold`) | same | the GitHub repository is no longer a Webgrip mirror; the `github-mirrors` reconciler must stop copying releases to it |
| Add the `unfold-hq/unfold` entry (below), together with the `tofu-github` change that lets a ruleset without an `id` be created instead of imported | same, and `kubernetes/apps/repo-config/repo-config/tofu-github/imports.tf`, `model/schema/github-rulesets.schema.json` | rulesets, settings and default branch from git |
| Remove `spec.suspend: true` from `Terraform/unfold-hq` | `kubernetes/apps/github-config/unfold-hq/app/terraform.yaml` | first plan, read by hand, then `approvePlan: auto` as above |
| Switch `release_consumers` of `ploeg-hq/ploeg` to `[{"forge":"github","url":"https://github.com","repo":"unfold-hq/unfold","base":"development","recipe":"scripts/consume-ploeg-release.sh","message":"fix(ploeg): update Ploeg to {version}","merge":"by-consumer"}]` | `repos.yaml`, entry `ploeg-hq/ploeg` | Ploeg's release opens the pin PR on GitHub with the `unfold-hq-bot` token. Needs the matching change in `ploeg-hq/ploeg`'s workflow (`actions/create-github-app-token`): merged in [ploeg-hq/ploeg#415](https://github.com/ploeg-hq/ploeg/pull/415) and in releases from `v0.2.0-rc.106` |
| Point the Unfold DNS source at the pull mirror: `unfoldhq-dev|webgrip/unfold-mirror|development|apps/site/ops/dns` | `kubernetes/apps/forgejo/forgejo-actions-secrets/app/dns-reconciler.cronjob.yaml` | the archived repository stops changing; the mirror follows GitHub |
| Two validator test cases that mutated the `unfold` entry's branch rules mutate `semantic-release-config` instead: the archived entry is skipped by the push and Renovate-gate checks, so the cases would no longer fail for the reason they name | `scripts/test-validate-repo-config-model.sh` | the test keeps testing what it says |
| Keep `GITHUB_IS_SOURCE_REPOS="unfold"` in `scripts/forgejo-sync.sh`: `--all` still lists an archived repository | `scripts/forgejo-sync.sh` | no change |

The pull mirror itself is created in the Forgejo UI, the way `webgrip/ploeg-mirror` was: **New
Migration → GitHub**, URL `https://github.com/unfold-hq/unfold.git`, owner `webgrip`, name
`unfold-mirror`, tick **This repository will be a mirror**, no token (the repository is public).
The repo-config model does not list pull mirrors: `forgejo-sync.sh --all` and the inventory skip
repositories with `mirror: true`.

The `unfold-hq/unfold` entry for PR 2. The rulesets carry no `id` because they do not exist yet;
after the first apply, add the ids GitHub assigned (`gh api repos/unfold-hq/unfold/rulesets`) so
a later rebuild imports them:

```yaml
  unfold-hq/unfold:
    forge: github
    kind: service
    renovate:
      config_file: renovate.json
      presets:
        - "config:recommended"
        - "abandonments:recommended"
        - "mergeConfidence:all-badges"
    settings:
      default_branch: development
      has_discussions: true
    rulesets:
      protect-development:
        name: Protect development
        target: branch
        include:
          - refs/heads/development
        deletion: true
        non_fast_forward: true
        update: false
        required_status_checks:
          - context: gate
            integration_id: 15368
        bypass_repository_role_ids:
          - 5
      protect-main:
        name: Protect main
        target: branch
        include:
          - refs/heads/main
        deletion: true
        non_fast_forward: true
        update: false
        required_status_checks:
          - context: gate
            integration_id: 15368
        bypass_repository_role_ids:
          - 5
      release-tags-immutable:
        name: Release tags are immutable
        target: tag
        include:
          - refs/tags/unfold-v*
          - refs/tags/unfold-site-v*
        deletion: true
        non_fast_forward: true
        update: true
        required_status_checks: []
        bypass_repository_role_ids: []
```

`renovate.presets` lists what Unfold's `renovate.json` extends: Renovate's built-in presets only.
`unfold-hq` repositories never extend a Webgrip preset; the organisations stay apart.

`integration_id: 15368` is GitHub Actions. The required check `gate` must be reported by a
GitHub Actions workflow on `unfold-hq/unfold` before the ruleset applies, or every pull request
waits forever; the admin bypass (role 5) is the way out if it does not. The module change that
lets these be created: in `tofu-github/imports.tf` the ruleset import becomes
`for_each = { for key, rule in local.rulesets : key => rule if try(rule.id, null) != null }`, and
`id` leaves the `required` list of `github-rulesets.schema.json`. Every existing ruleset has an
id, so the `ploeg-hq` and `webgrip` plans do not change; check that with their next plan.

### What PR 3 changed, after cutover

The first release from GitHub is `unfold-v0.4.0-rc.132`. Its images
`ghcr.io/unfold-hq/unfold` and `ghcr.io/unfold-hq/unfold-agent` and its chart
`oci://ghcr.io/unfold-hq/charts/unfold` are public and signed keyless by
`https://github.com/unfold-hq/unfold/.github/workflows/on_release_published.yml@refs/tags/unfold-v0.4.0-rc.132`
(issuer `https://token.actions.githubusercontent.com`). Nothing publishes to Harbor's `webgrip/unfold`
repositories any more.

| Change | Where |
| --- | --- |
| Staging Unfold pulls its chart from `oci://harbor.${SECRET_DOMAIN}/ghcr/unfold-hq/charts/unfold` and its images from `harbor.${SECRET_DOMAIN}/ghcr/unfold-hq/unfold` and `.../unfold-agent`, Harbor's GHCR proxy, each pinned to `0.4.0-rc.132` by digest. The lockstep check and the Renovate release group follow the new names | `kubernetes/apps/ploeg/unfold/app/helmrelease.yaml`, `ocirepository.yaml`, `scripts/check_release_lockstep.py`, `scripts/test-release-lockstep.sh`, `.renovaterc.json5` |
| Staging Unfold's connected repository `ploeg` names `https://github.com/unfold-hq/unfold.git` | `kubernetes/apps/ploeg/unfold/app/helmrelease.yaml` |
| The verifier probes exception accepts `unfoldhq.dev/network: none` as well as `dev.webgrip.unfold/network: none` | `kubernetes/apps/kyverno/exceptions/app/exception-unfold-verifier-cel.yaml` |
| `docs.${SECRET_DOMAIN}/glide/<path>` answers 301 to `https://docs.unfoldhq.dev/<path>`; the renamed-page redirects go straight to the new names there | `kubernetes/apps/garage/docs-site/app/httproute.yaml`, `unfold-renamed-pages.httproute.yaml` |
| The TechDocs bootstrap Job, the repo-keys PushSecret and `DOCS_REPOS` no longer carry `glide`; estate search no longer merges `/glide/pagefind` | `kubernetes/apps/garage/garage/bootstrap/techdocs.job.yaml`, `techdocs-repos.pushsecret.yaml`, `forgejo-actions-secrets.cronjob.yaml`, `docs/techdocs/docs/estate-search.md` |
| The Forgejo Actions secrets bridge no longer writes to `webgrip/unfold` (`SECRET_REPOS`, `PLOEG_RELEASE_TOKEN`, `OVSX_PAT`, the agent-standards survey key and its org variables) and deletes those copies through `RETIRED_REPO_SECRETS` | `kubernetes/apps/forgejo/forgejo-actions-secrets/app/forgejo-actions-secrets.cronjob.yaml` |
| The CVE rescan reads Unfold's budgets from `raw.githubusercontent.com/unfold-hq/unfold` at `unfold-v<version>`; the Unfold Loop dashboard links its KPI definitions on `docs.unfoldhq.dev` | `kubernetes/apps/security/unfold-cve-rescan/app/rescan.sh`, `prometheusrule.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/glide-loop.yaml` |

Forgejo accepts Actions-secret writes on an archived repository: the bridge run at 20:23 UTC on
2026-11-16, an hour after `webgrip/unfold` was archived, set every secret on it. The bridge
removal was therefore clean-up, not a fix.

**Unfold's network label.** Unfold's identifier migration (its ADR-0067) moves the verifier
Pods' deny-all label from `dev.webgrip.unfold/network` to `unfoldhq.dev/network`. Release 1, in
`0.4.0-rc.132`, sets both; Unfold's release 2 drops the old key. The exception accepts either, so
it holds before and after that release. Once a release 2 build runs here, drop the
`dev.webgrip.unfold/network` clause from the exception.

**Image admission.** Harbor's `webgrip/unfold` images were under `image-verify-harbor-enforce`.
The GitHub images are checked only by `image-verify-unfold-hq-audit`, which already matches the
Harbor-proxied path and the keyless attestor of the release workflow. Until it is promoted,
Unfold's images are admitted on an Audit result. Promote it to enforce, as
[ADR-0073](../adr/adr-0073-image-admission-signatures-enforced.md) describes, once the
PolicyReports for the rc.132 Pods in `ploeg` and `unfold-workspaces` show `pass`.

#### Still open after PR 3

| Item | Where | Why it is open |
| --- | --- | --- |
| Ploeg's targets (`config.targets.unfold`, the Vikunja project `Ploeg Test`), the `silver` team and every task source with `ploeg.target` still name Forgejo `webgrip/unfold`; Runs against it cannot push | `kubernetes/apps/ploeg/unfold/app/helmrelease.yaml` | this Ploeg has only a Forgejo forge (`executor.forge: forgejo`). Moving the targets to `unfold-hq/unfold` needs a GitHub forge for Ploeg with an App installed on `unfold-hq/unfold` ([Ploeg ADR-0086](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0086-github-is-a-forge-and-a-run-pushes-with-its-own-github-app-installation-token.md)) |
| Report a problem files issues on Forgejo `webgrip/unfold` (`config.reports`), and the `unfold-reports`, `ploeg-forge-webhook-registration` and `forge-revocation-probe` jobs act on it | `helmrelease.yaml`, `kubernetes/apps/forgejo/forgejo-actions-secrets/app/`, `kubernetes/apps/ploeg/ploeg/app/forge-revocation-probe/` | follows the forge decision above |
| `RELEASE_CONSUMER_TOKEN_FORGEJO`, its bridge target and the `ploeg-release` bot | `github-secrets-bridge/.../targets.json`, `externalsecret.yaml`, `forgejo-actions-secrets/app/ploeg-release-*` | Ploeg no longer consumes on Forgejo (its only consumer is `unfold-hq/unfold`), so these can go; they still succeed and harm nothing |
| `OVSX_PAT` for the VS Code extension on `unfold-hq/unfold`, and the agent-standards survey key | OpenBao `openvsx/unfold`, `litellm/keys/agent-standards-survey` | whether the GitHub secrets bridge carries them to `unfold-hq/unfold` |
| The Garage buckets `docs-glide`, `docs-glide-trash`, the key `docs-publish-glide`, the `glide_*` properties of OpenBao `garage/docs-repo-keys`, and Harbor's `webgrip/unfold`, `webgrip/unfold-agent` and `webgrip/charts/unfold` repositories | Garage, OpenBao, Harbor | data; nothing in git deletes them. The owner removes them by hand, or lists the Harbor repositories in `retired-repositories`. Not `webgrip/unfold-delivery-inputs`: staging still pins it for governed delivery |
| The TechDocs and Backstage entry for Unfold | the Backstage catalog location that registers Unfold's `catalog-info.yaml` | not in this repository |

## Rotate an App key

1. On the App's settings page, **Generate a private key** (the old one keeps working).
2. `mise exec -- bao kv patch secret/github/unfold-hq-app private_key=@<new .pem>`
   (or `secret/github/unfold-hq-bot-app`).
3. Run the bridge and, for the bot, the token minter by hand (above) and check they succeed. A
   new bot key also reaches `ploeg-hq/ploeg` within the hour as `RELEASE_CONSUMER_GITHUB_APP_PRIVATE_KEY`.
4. Delete the old key on the App's settings page, and the `.pem` from your machine.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `GitHubAppUnfoldHqPending` | no `secret/github/unfold-hq-app`, or one of its keys empty | [install and store](#install-and-store-only-after-the-transfer) |
| `GitHubAppUnfoldHqBotPending` | no token Secret `renovate/renovate-unfold-hq-token`: the bot key is absent or the minter fails | same; then the minter log |
| `GitHubSecretsBridgeSourcePending` on `RELEASE_CONSUMER_GITHUB_APP_*` | `secret/github/unfold-hq-bot-app` not stored yet | same |
| bridge log `OpenBao denied reading secret/... (403)` | the path is in `targets.json` but not in `github-secrets-bridge.hcl`, or `config.sh` has not run yet | the `openbao-config` CronJob runs every five minutes; check its log |
| bridge log `GitHub refused an installation token … (404)` or `(422)` | the App is not installed on the target repository | install it on `unfold-hq/unfold` (or `ploeg-hq/ploeg` for the bot targets) |
| minter log `(422) The permissions requested are not granted` | the bot App lacks one of the permissions listed above | add it on the App, then approve it on the installation page |
