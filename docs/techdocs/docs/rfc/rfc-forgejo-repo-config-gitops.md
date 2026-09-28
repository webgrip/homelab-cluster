# RFC: Forgejo repository settings as GitOps — profiles in git, one reconciler

> Status: **Accepted** (2026-09-28, option B; [decisions](#7-decisions-2026-09-28)) · Date: 2026-09-28 ·
> Epic: VIK-1302 · Refines the
> enforcement half of [ADR-0050](../adr/adr-0050-per-repo-delivery-contract.md) · Reuses the
> shape of [ADR-0058](../adr/adr-0058-access-plane-one-module-one-model.md)

> **TL;DR.** Every repository setting that `scripts/forgejo-sync.sh` pushes by hand today becomes
> a declared profile in a small YAML model in this repo, and one OpenTofu module run by the
> tofu-controller that is already deployed makes Forgejo match it every hour. Git decides
> which profile a repo gets; Forgejo topics are written *from* the model as a visible label, never
> read *as* the selector. The owner's `homelab-cluster` whitelist is a first-class repo entry
> guarded by a precondition that makes a lock-out plan fail before it can apply. Parity is proven
> by importing every live object and requiring an empty plan before the first apply.

| Term | Meaning |
| --- | --- |
| **Profile** | A named bundle of repo settings and branch-protection rules (`product`, `homelab`, …). |
| **Model** | The YAML files in git that list profiles and assign one to every managed repo. |
| **Reconciler** | The thing that reads the model and makes Forgejo agree with it, on a loop. |
| **Drift** | A live setting that differs from the model — someone clicked, or a script ran. |
| **Plan** | OpenTofu's diff: what the next apply would add, change or destroy. |
| **Topic** | Forgejo's free-form repo label (GitHub calls them topics too). |

## 1. Why

Repository configuration is the one estate plane still applied imperatively. Everything below is
what `scripts/forgejo-sync.sh` does today, run from a laptop with a PAT in the shell
(`scripts/forgejo-sync.sh` header, lines 1–56):

| Section | Manages | Input | Default set? |
| --- | --- | --- | --- |
| `actions` | `has_actions`; **forced off** for `ACTIONS_OFF_REPOS="workflows"` | reads **GitHub** (`gh api …/actions/permissions`) for parity | yes |
| `prs` | `has_pull_requests` on (un-mirroring leaves it off; Renovate skips PR-less repos) | none | yes |
| `releases` | `has_releases` on (semantic-release needs the Releases unit) | none | yes |
| `mirror` | a Forgejo → GitHub push-mirror, `sync_on_commit`, 8h fallback | `GH_MIRROR_TOKEN` | yes |
| `protect` | `main` + `development` (if it exists) rules; push/merge whitelists; optional status checks | `PUSH_WHITELIST`, `DEV_PUSH_WHITELIST`, `MERGE_WHITELIST`, `STATUS_CHECK_CONTEXTS` env vars | **opt-in** |
| `webhook` | per-repo hook → `renovate-operator` receiver, bearer in top-level `authorization_header` | `RENOVATE_WEBHOOK_AUTH_TOKEN` or the in-cluster Secret | yes |

Settings managed **nowhere** in git today:

- **Merge style and branch cleanup.** On 2026-09-28 the owner set `default_merge_style=merge` and
  `default_delete_branch_after_merge=true` for every repo. No script or manifest records it
  (`git log -S default_merge_style` on `main` is empty), so it is already undeclared state.
- **Team access.** The `ci` team (write, all repos) is created and PATCHed by
  `kubernetes/apps/forgejo/forgejo-actions-secrets/app/forgejo-ci-provisioner.job.yaml`; any
  other team is click-ops.
- **Renovate enrollment** is already topic-driven: the `renovate` topic is the selector in
  `kubernetes/apps/renovate/renovate-operator/jobs/webgrip-forgejo.yaml` (`discoverTopics`),
  guarded weekly by `scripts/renovate-discovery-drift.sh`. Nothing sets the topic; a human does.

### 1.1 The failure this design must make impossible

On 2026-08-05 an `--all --only protect` sweep wrote the product default (`push=webgrip-ci`) to
`homelab-cluster` and locked the owner out of trunk pushes until the override was re-run
([rollout runbook](../runbooks/forgejo-branch-protection-rollout.md) "Rollout — order is
load-bearing"; `CLAUDE.md` rule on protected `main`). The root cause is structural, not a typo:

1. **Per-repo config lives in env vars of a run, not in data.** The override exists only as a
   copy-paste command in a runbook, so the default and the exception are two separate runs.
2. **Order is load-bearing.** Correctness depends on running the override *after* the sweep.
3. **Nothing re-asserts.** Once wrong, it stays wrong until a human notices a rejected push.
4. **Partial payloads have side effects.** `sync_protect` must omit the status-check keys when
   empty because a PATCH carrying `enable_status_check:false` wipes hand-set contexts
   (`scripts/forgejo-sync.sh` `sync_protect`). Hand-set contexts are themselves undeclared state.

A worse variant is reachable: Flux reads this repo from in-cluster Forgejo
([Flux source → Forgejo](rfc-flux-forgejo-source.md)). A continuous reconciler that locks the owner
out of `homelab-cluster` `main` also blocks the commit that would fix it. The break-glass path
therefore must not depend on pushing to `homelab-cluster`.

## 2. Requirements

| # | Requirement |
| --- | --- |
| R1 | Git is the only source: which profile a repo has, and what a profile means. |
| R2 | Reconciled continuously; drift is corrected, and each correction is visible. |
| R3 | Per-repo exceptions (the `homelab-cluster` whitelist, per-repo status-check names) are data in the same model, applied in the same run. No ordering between runs. |
| R4 | A model that would lock the owner out of `homelab-cluster` fails before any write. |
| R5 | Break-glass works with Forgejo and Flux both wedged. |
| R6 | Removing a repo from the model never deletes or unprotects it silently. |
| R7 | Credential from OpenBao via ESO or the Vault provider; least privilege; no laptop PAT. |
| R8 | Parity with today is provable: the first run is a zero-diff plan. |
| R9 | New repos are noticed, not silently unmanaged. |

## 3. Selecting repos: topics as selector vs git as selector

The owner's sketch labels repos with a Forgejo topic (`profile-product`) and has the reconciler
select by it. It is attractive because a new repo opts in once, with no git edit — the same
reason Renovate moved to `discoverTopics` on 2026-09-18.

It is the wrong selector for this plane:

- **Who can change it.** Topics are set through `PUT /repos/{owner}/{repo}/topics`, which Forgejo
  gates on **repo admin** (`routers/api/v1/api.go`, the `/topics` group under `reqAdmin()`;
  on Forgejo 15.0.2 the spike's `write:repository` PAT could not even list org teams without
  `read:organization`). Today only org owners are repo admin: `webgrip-ci` has
  write via the `ci` team, and `agent-builder` has no admin anywhere. So the risk today is low.
  But the selector would move a security control (who may push to `main`) out of reviewed git
  and into a field any future repo admin can edit, with no history in this repo.
- **It fails open.** Deleting the topic, or a typo (`profile-prodcut`), drops the repo out of the
  selection. For a reconciler with withdrawal semantics that means *branch protection removed on
  the next tick*. Renovate's topic failing open means "no dependency PRs"; here it means "anyone
  with write can push to `main`".
- **It moves the exception out of git.** The `homelab-cluster` exception would be a topic value,
  the exact "config lives outside data" shape that caused 2026-08-05.

**Proposal:** git assigns profiles; the reconciler **writes** a `profile-<name>` topic onto each
repo as a read-only projection, so the label is visible in the Forgejo UI and search, and a
hand-edited topic is just drift that the next run reverts. New repos are caught by a check
(§5.4) rather than by selection, and get the `baseline` profile only when listed.

## 4. Options

### A. Custom reconciler CronJob reading a profile file

A CronJob in `forgejo` (same shape as `forgejo-package-link-reconciler.cronjob.yaml`,
`kubernetes/apps/ploeg/ploeg/app/tracker-wiring.cronjob.yaml`, and the Harbor
`harbor-proxy-config` of [ADR-0046](../adr/adr-0046-harbor-proxy-credential-convergence.md))
reads the model from a ConfigMap, GETs each repo, computes a diff, logs it, PATCHes, and exits
non-zero on a failed write so a `ForgejoRepoConfigReconcileStale` alert (`time() -
kube_cronjob_status_last_successful_time > 2h`, as `HarborProxyReconcileStale` in
`kubernetes/apps/harbor/harbor/app/prometheusrule.yaml`) fires.

- Covers everything, including push mirrors and topics, because we write every call.
- Every behaviour is our code: diffing, withdrawal, the status-check wipe quirk, masked webhook
  headers, pagination (the script already lost repos past page one once, fixed 2026-07-26). This
  is `forgejo-sync.sh` rewritten, and the access-plane decision rejected exactly this shape after
  the staging cluster built it and deleted 3,900 lines (ADR-0058 context).
- No plan: the "diff" is whatever we log.
- Removal from the model does nothing unless we write deletion code, which is where lock-out and
  fail-open bugs live.

### B. tofu-controller + the Forgejo OpenTofu provider (recommended)

One module under `kubernetes/apps/forgejo/repo-config/tofu/`, one `Terraform` object reconciled
by the tofu-controller that already runs here (`kubernetes/apps/flux-system/tofu-controller`,
v0.16.5, pod Running on 2026-09-28) and already applies the access plane
(`kubernetes/apps/security/access-plane/app/terraform-broker.yaml`: `interval: 15m`,
`approvePlan: auto`, `storeReadablePlan: human`, OpenBao via Kubernetes auth, no standing token).

Provider fit, [`svalabs/forgejo`](https://registry.terraform.io/providers/svalabs/forgejo/latest)
v1.6.1 (released 2026-09-18,
[repo](https://github.com/svalabs/terraform-provider-forgejo)):

| Need | Provider | Notes |
| --- | --- | --- |
| Units (`has_actions`, `has_pull_requests`, `has_releases`) | `forgejo_repository` | [docs](https://github.com/svalabs/terraform-provider-forgejo/blob/main/docs/resources/repository.md) |
| `default_merge_style`, `default_delete_branch_after_merge`, `allow_*` merge styles | `forgejo_repository` | same |
| Branch protection: push/merge/approval whitelists (users + teams), `status_check_contexts`, `required_approvals`, `block_on_*` | `forgejo_branch_protection` | import `owner/repo/branch` ([docs](https://github.com/svalabs/terraform-provider-forgejo/blob/main/docs/resources/branch_protection.md)) |
| Teams | `forgejo_team` (`permission`, `includes_all_repositories`, `units_map`), `forgejo_team_member` | [docs](https://github.com/svalabs/terraform-provider-forgejo/blob/main/docs/resources/team.md) |
| Renovate webhook incl. `authorization_header` (sensitive) | `forgejo_repository_webhook` | [docs](https://github.com/svalabs/terraform-provider-forgejo/blob/main/docs/resources/repository_webhook.md) |
| Topics | **no** | not in the `forgejo_repository` schema |
| Push mirrors | **no** | `mirror` is pull-mirror creation only |

The Gitea provider [`go-gitea/gitea`](https://registry.terraform.io/providers/go-gitea/gitea/latest)
v0.8.1 (2026-07-29) is the weaker fit: `gitea_repository` has `default_merge_style` but no
`default_delete_branch_after_merge`, no `has_actions`, no topics
([docs](https://github.com/go-gitea/terraform-provider-gitea/blob/main/docs/resources/repository.md)).

Gaps and how B closes them:

- **Topics**: a `restapi_object` (Mastercard/restapi provider) or `terraform_data` resource that
  PUTs `/repos/{o}/{r}/topics`. Small and isolated; the spike confirmed topics are absent from the
  provider schema. Topics are a projection (§3), so
  this is not on the safety path.
- **Push mirrors** stay out: they are a one-time cutover action needing a GitHub PAT, and GitHub
  is on the way out ([GitHub Actions retirement](rfc-github-actions-retirement.md)).
  `forgejo-sync.sh --only mirror` stays in the `forgejo-leading` cutover recipe.
- **Lifecycle danger.** `forgejo_repository` owns the repository object; removing it from
  `for_each` plans a **destroy of the repo**. Every repository resource gets
  `lifecycle { prevent_destroy = true }` and `archive_on_destroy = true`; unmanaging a repo is a
  `removed { lifecycle { destroy = false } }` block, and a rename is a `moved` block. A plan that
  would destroy a repo fails.
- **Provider maturity.** v1.6.1 fixed a bug where an empty `wiki_branch` 500'd every repository
  update. Optional attributes that the provider defaults instead of reading back would flip live
  settings. The import-then-empty-plan gate (§6) catches both before any write.
- **Masked webhook header.** Forgejo masks `authorization_header` on GET
  (`forgejo-sync.sh` `sync_webhook`). The spike showed the provider never reads it back: import
  plans no drift, a changed value in config plans an update, and a change made in Forgejo is never
  seen. Rotation therefore goes through OpenBao (the config value changes); live tampering is out of
  the plan's sight (§6.1).

What B gives that A cannot: a real plan before every apply, withdrawal by deleting a line (the
ADR-0058 driver), one mechanism for access plane and repo plane, and no custom diff code.

### C. Keep `forgejo-sync.sh`, run it as a scheduled Job

Wrap the script in a CronJob with the PAT from OpenBao.

- Continuous, cheap, zero rewrite.
- Not GitOps: the per-repo overrides are still env vars of a run. To keep `homelab-cluster`
  correct the Job would need two ordered invocations, which is the 2026-08-05 bug running every
  hour instead of once. `actions` still reads GitHub. No diff, no withdrawal, and protection stays
  opt-in because a default sweep is unsafe.
- Rejected; it automates the failure.

### Comparison

| Criterion | A: custom CronJob | B: tofu-controller + provider | C: scheduled script |
| --- | --- | --- | --- |
| Git is the source, incl. exceptions | yes | yes | no (env vars) |
| Drift corrected | yes | yes, every `interval` | yes, but to a per-run default |
| Drift visible | our log lines | stored plan + controller events | script output |
| Lock-out class removed | if we write it right | one plan, precondition, no run order | **no** |
| Withdrawal semantics | hand-written | declarative, guarded by `prevent_destroy`/`removed` | none |
| Secrets | ESO Secret env | OpenBao via Vault provider, Kubernetes auth (ADR-0058) | ESO Secret env |
| Own code | ~300 lines shell/Python | model + ~150 lines HCL | 0 new |
| Topics, push mirrors | yes, yes | via restapi, no | no, yes |
| Fit with estate | package-link / Harbor reconcilers | access plane (ADR-0058) | none |
| Effort | M | M (plus a spike) | S |

## 5. Design (option B)

### 5.1 Layout

```text
kubernetes/apps/forgejo/repo-config/
  ks.yaml
  app/terraform.yaml             Terraform object, runner SA, NetworkPolicy
  model/profiles.yaml            profile definitions
  model/repos.yaml               every managed repo -> profile + per-repo fields
  model/schema/*.json            JSON Schema, validated in e2e Lint
  tofu/                          versions.tf providers.tf main.tf imports.tf checks.tf
```

The module reads the model with `yamldecode(file(...))`, as the access plane reads its roster.

### 5.2 First profile set

Today's estate-wide decision is part of `baseline`, and every other profile extends it.

| Profile | Extends | Settings | `main` rule | `development` rule |
| --- | --- | --- | --- | --- |
| `baseline` | — | `has_pull_requests`, `has_releases`, `has_actions` on; `default_merge_style: merge`; `default_delete_branch_after_merge: true`; Renovate webhook and topic `renovate` (from slice 5, decision 3) | none | none |
| `library` | baseline | `has_actions: false` (reusable-workflow repos: runs belong to callers) | as `product` | — |
| `product` | baseline | — | push `webgrip-ci`; merge `ryangr0`, `renovate`; status checks from the repo entry | push `webgrip-ci`, `ryangr0`; merge `ryangr0`, `renovate` |
| `agent-driven` | product | `required_approvals: 1`; approvals whitelist `ryangr0`, `agent-reviewer` (one agent approval counts as one review; the merge whitelist stays owner-only); `block_on_rejected_reviews`, `dismiss_stale_approvals` | as `product` + approvals | as `product` |
| `personal` | baseline | — (`baseline` settings only, decision 5) | none | none |
| `homelab` | baseline | — | push `ryangr0`; merge `ryangr0`, `renovate`; the four `e2e / … (pull_request)` contexts | — |

`agent-builder` appears in no whitelist in any profile (ADR-0048, ADR-0050). `renovate` stays in
every merge whitelist; the old override that dropped it would have stopped Renovate automerge on
the repo where it does all the dependency work (runbook step 3).

A repo entry carries what legitimately differs per repo and nothing else:

```yaml
repos:
  homelab-cluster:
    profile: homelab
  workflows:
    profile: library
  erfbeeld:
    profile: product
    branches: [main, development]
    status_checks:
      main: ["ci / build (pull_request)"]
```

`branches` is explicit, replacing the script's "protect `development` if it exists" probe, so the
plan never depends on a live lookup. Status-check contexts must match reported names exactly
(forgejo#9288: a pattern matching zero tasks counts as matched), so the spike copies them from a
real PR per the runbook recipe; today's hand-set contexts become declared ones.

### 5.3 Owner lock-out guard (R4) and break-glass (R5)

Three layers, cheapest first:

1. **Schema.** `repos.yaml` JSON Schema requires `homelab-cluster` to have profile `homelab`.
   Checked in e2e Lint on PRs, and by the `./scripts/run-flux-local-test.sh`-adjacent local
   validator for trunk pushes (a PR-only check does not gate the owner's direct commits).
2. **Precondition in the module**, which runs on the reconciler and therefore gates trunk pushes
   too:

   ```hcl
   resource "forgejo_branch_protection" "rule" {
     for_each = local.rules

     lifecycle {
       precondition {
         condition     = each.key != "homelab-cluster/main" || contains(each.value.push, "ryangr0")
         error_message = "homelab-cluster main must keep ryangr0 in its push whitelist"
       }
     }
   }
   ```

   A failing precondition fails the plan; nothing applies, the `Terraform` object goes
   `Ready=False`, and the alert fires. A mutation test proves it both ways (§6 step 5).
3. **Break-glass, independent of Forgejo and Flux**: `kubectl -n forgejo patch terraform
   repo-config --type merge -p '{"spec":{"suspend":true}}'`, then fix the rule with the Forgejo
   admin token (`secret/forgejo/admin` in OpenBao, as the runbook's 403 row already does), push
   the model fix, unsuspend. The Kubernetes API does not depend on Forgejo, so this works when
   Flux cannot fetch. Documented in the replacement runbook.

Single plan, single apply: there is no run order to get wrong. The 2026-08-05 sequence (default,
then override) cannot be expressed.

### 5.4 Coverage of new repos (R9)

An OpenTofu `check` block lists `GET /orgs/webgrip/repos` (paginated, `hashicorp/http` data
source), drops forks, mirrors and archived repos, and warns for every repo not in `repos.yaml`.
The warning lands in the stored plan and the controller log. `scripts/renovate-discovery-drift.sh`
already runs the same query weekly; extend it to also report unmodelled repos, so a missing entry
surfaces in the Monday scheduled-maintenance run either way. Unmodelled repos are left alone,
never auto-assigned: a default applied to an unknown repo is the 2026-08-05 bug in another form.

### 5.5 Identity and secrets (R7)

- A dedicated bot `webgrip-repo-config`, member of a team `repo-config` with `permission: admin`
  and `includes_all_repositories: true` (repo admin is required for protection and hooks). It is
  not an org owner, and it is in no whitelist.
- Minted by a provisioner Job cloned from `forgejo-ci-provisioner.job.yaml` (provisioner-job
  skill: idempotent, fail-soft, `force` + `retry-failed` labels), token pushed to OpenBao at
  `secret/forgejo/repo-config` with a `PushSecret`.
- The module reads it with an ephemeral `vault_kv_secret_v2` through Kubernetes auth, role
  `forgejo-repo-config`, as the access-plane providers do (`tofu/broker/providers.tf`). No token
  in a Kubernetes Secret, none on a laptop.
- Token scopes: `write:repository`, `read:organization` (+ `write:organization` only if teams move
  into this module; the `ci` team can stay with its provisioner in phase 1).
- The Renovate webhook bearer is read from OpenBao the same way instead of from
  `renovate/renovate-webhook-auth` via kubectl.
- Runner pod: worker pool, a CiliumNetworkPolicy allowing egress to `forgejo-http:3000` and
  OpenBao only.

### 5.6 Observability (R2)

- **Stale/failed:** alert `ForgejoRepoConfigNotReady` when the `Terraform` object is not
  `Ready` for > 3h (two hourly intervals plus margin, the `HarborProxyReconcileStale` threshold
  logic).
  The metric name from tofu-controller's enabled ServiceMonitor is picked in slice 2; the blackbox
  rule in `kubernetes/apps/observability/blackbox-exporter/app/prometheusrule-blackbox.yaml`
  already points operators at `kubectl -n security get terraform access-broker`.
- **Drift made visible:** every apply that changes anything is drift corrected and alerts
  (decision 6). Count applies
  with a non-empty plan from the controller log in VictoriaLogs; a Grafana stat "repo-config
  drift corrections, 7d" (a stat, not a timeseries). The readable plan is stored per reconcile
  (`storeReadablePlan: human`).
- **Behavioural check, weekly:** the scheduled-maintenance workflow asserts the rollout runbook's
  verify line: `homelab-cluster` reads `main ['ryangr0'] ['ryangr0','renovate']`.
- Delivery caveat: the warning leg was dropping batches on 2026-09 (413 from ntfy, see
  `vmalertmanager-config.externalsecret.yaml`); that fix is a precondition for trusting any
  new warning alert.

## 6. Migration from `forgejo-sync.sh`

| Step | What | Proof |
| --- | --- | --- |
| 0. Spike | Provider v1.6.1 against Forgejo 15: import, plan (done 2026-09-28, §6.1; VIK-1309) | Empty plan after import |
| 1. Identity | Bot, team, provisioner Job, OpenBao path, Vault role, NetworkPolicy | Provisioner log line; token readable by the role only |
| 2. Model + plan-only | Write `profiles.yaml`/`repos.yaml` for every active repo; `imports.tf` for every repo, rule and hook; `Terraform` object **without** `approvePlan: auto` (plan only) | **Plan: N to import, 0 to add, 0 to change, 0 to destroy.** Every non-zero line is resolved explicitly: either the model is wrong or live has drifted; each resolution recorded in the ticket |
| 3. Enable apply | `approvePlan: auto` | First apply is a no-op; the next reconcile is too |
| 4. Move sections | Delete `prs`, `releases`, `actions`, `protect`, `webhook` from the script; it keeps only `mirror` | Script diff; `forgejo-leading` skill step 4 now says "add the repo to `repos.yaml`" |
| 5. Mutation tests | (a) set a scratch repo to `squash` by hand → reverted within one interval; (b) a model dropping `ryangr0` from `homelab-cluster` → plan fails, nothing applied (**must FAIL**); (c) the unchanged model → Ready (**must PASS**); (d) delete a repo line without `removed` → plan fails on `prevent_destroy` | Plan output and live API reads for each |
| 6. Docs | New ADR (repo config is reconciled by tofu-controller from a git model; supersedes ADR-0050's enforcement mechanics, keeps its contract); rewrite the rollout runbook as the break-glass runbook; update `renovate-operator/jobs/README.md` (webhook section) | ADR index validator green |

Order matters only within step 2: `homelab-cluster` is in the first import batch, not the last,
because the plan is one unit.

### 6.1 Spike result (2026-09-28, VIK-1309)

Run on a workstation, read-only: OpenTofu 1.12.6, `svalabs/forgejo` 1.6.1, Forgejo
`15.0.2+gitea-1.22.0`, the owner's PAT (`write:repository`, no `read:organization`) exported as
`FORGEJO_API_TOKEN`. Import blocks for `glide`, `homelab-cluster`, `erfbeeld` (product), the
`main` rules of `homelab-cluster` and `workflows`, three webhooks and the `ci` team; `tofu plan`
only, never `apply`.

| Setting | Resource | Modelled | Read back on refresh |
| --- | --- | --- | --- |
| `has_actions`, `has_pull_requests`, `has_releases` (and issues, wiki, projects, packages) | `forgejo_repository` | yes | yes |
| `default_merge_style`, `allow_merge_commits`, `allow_rebase`, `allow_rebase_explicit`, `allow_squash_merge` | `forgejo_repository` | yes | yes |
| `default_delete_branch_after_merge`, `allow_fast_forward_only_merge`, `default_update_style`, `allow_rebase_update` | `forgejo_repository` | yes, written on every update | **no**: write-only; import records the provider default |
| Push/merge/approval whitelists (users, teams), `status_check_contexts`, `required_approvals`, `block_on_*`, `dismiss_stale_approvals`, file patterns, signed commits | `forgejo_branch_protection` (import `owner/repo/branch`) | yes | yes, exact |
| Webhooks: URL, events, active, type, branch filter | `forgejo_repository_webhook` (import `owner/repo/id`) | yes | yes |
| Webhook `authorization_header` | same | yes, sensitive | **no**: never read; rotation works through the config value, a change made in Forgejo is invisible |
| Team permission, `units_map`, `includes_all_repositories` | `forgejo_team` (import `org/team`) | yes; `units_map` required | needs `read:organization`: the PAT got 403 "Unable to list teams" |
| Per-repo team grants (a team on some repos only) | — | **no** | — |
| Topics | — | **no** | — |
| Push mirrors | — | **no** (pull-mirror creation only) | — |

**Plan after import.** With the model's values (`default_delete_branch_after_merge = true`,
`allow_fast_forward_only_merge = true`, `archive_on_destroy = true`) the plan was
`8 to import, 0 to add, 3 to change, 0 to destroy`: one in-place update per repository, and only
those three write-only fields differ. `GET /repos/{o}/{r}` confirms live already holds `true` for
both merge fields, so that first update writes what Forgejo already has. One more line appeared on
`homelab-cluster`: `clone_addr` is read from the repo's GitHub original URL and planned to `null`;
`ignore_changes = [clone_addr]` removes it. With the write-only fields set to the import defaults
and that ignore, the plan was **`8 to import, 0 to add, 0 to change, 0 to destroy`**. Branch
protections, including the `homelab-cluster` rule with its four status-check contexts, and all
webhooks imported with zero diff.

**Lock-out precondition, mutation-tested.** With `ryangr0` in the push list the plan passes; with
`["webgrip-ci"]` it fails with `Resource precondition failed` and exits 1. A precondition must
reference a variable or object; a literal-only condition is rejected at validate time.

Consequences for the slices:

- Parity is provable; option B stands and option A is not needed.
- Slice 2's first plan shows exactly one update per repo for the write-only fields; the ticket
  records each against a live read. After it, drift in those fields is invisible to the plan, so
  slice 3 adds a `check` block that reads them through `hashicorp/http`.
- Every repository resource carries `ignore_changes = [clone_addr]`.
- The bot token needs `read:organization` for the `ci` team import and the unmodelled-repo check.
- Only 3 of 36 active non-mirror repos carry any branch protection today (`homelab-cluster`,
  `workflows`, `claude-config`); `glide` has none and no Renovate webhook.
- `tofu init` downloads from registry.opentofu.org and GitHub releases. Glide workers have no
  internet egress, so no slice that runs OpenTofu is Glide-runnable until providers are mirrored
  in-cluster; the tf-runner itself uses the ADR-0058 registry-egress exception.

### 6.2 How slice 2 follows the access plane

- `Terraform` object (`infra.contrib.fluxcd.io/v1alpha2`) in the app namespace, `sourceRef` the
  `flux-system` GitRepository, `path` to the module, `storeReadablePlan: human`,
  `alwaysCleanupRunnerPod: true`, `interval: 1h`, plan-only until slice 3.
- State: tofu-controller's default Kubernetes Secret backend in the object's namespace (ADR-0058).
- Runner: `harbor.webgrip.dev/ghcr/flux-iac/tf-runner` v0.16.5, set in
  `kubernetes/apps/flux-system/tofu-controller/app/helmrelease.yaml` (controller v0.16.5,
  `watchAllNamespaces`, `allowCrossNamespaceRefs`, concurrency 2); runner pod on the worker pool
  via `runnerPodTemplate`.
- Token: a dedicated runner ServiceAccount logs in to OpenBao with `auth_login` on
  `auth/kubernetes/login` and reads the secret with an ephemeral `vault_kv_secret_v2`
  (`kubernetes/apps/security/access-plane/tofu/broker/providers.tf`); the Forgejo provider gets
  `api_token` from it, and nothing lands in a Kubernetes Secret.
- NetworkPolicy: allow `flux-system` to the runner on TCP 30000
  (`kubernetes/apps/security/access-plane/app/networkpolicy.yaml`).
- Wiring: `ks.yaml` with `dependsOn: tofu-controller` in `flux-system`.

## 7. Decisions (2026-09-28)

The owner accepted option B and answered the open questions:

1. **Selector.** Git selects the profile. Topics are written as display labels only and are never
   read as the selector (§3).
2. **`agent-driven`.** An `agent-reviewer` approval counts as one review toward
   `required_approvals`; it never replaces the owner's merge, so the merge whitelist stays
   `ryangr0`, `renovate`. The profile starts on `webgrip/glide` only.
3. **Renovate enrollment** moves into the model (topic and webhook), in a later slice (slice 5).
4. **Teams.** The `ci` team stays with `forgejo-ci-provisioner` for now.
5. **Personal repos** (`.profile`, `.profile-private`, `claude-config`, `Tenants`) are modelled
   with the `baseline` profile only: settings, no branch protection.
6. **Cadence.** Reconcile hourly (`interval: 1h`), with a drift alert when an apply changed
   something and `ForgejoRepoConfigNotReady` after 3h.

Delivery is the epic VIK-1302, in order: VIK-1309 provider spike (done, §6.1) → VIK-1310 identity,
model and `baseline` imported, plan-only → VIK-1311 branch protection, lock-out guard,
`approvePlan: auto`, drift alert → VIK-1312 remaining profiles → VIK-1313 Renovate enrollment →
VIK-1314 retire the migrated `forgejo-sync.sh` sections, ADR and break-glass runbook.

## 8. References

- `scripts/forgejo-sync.sh`; [branch-protection rollout runbook](../runbooks/forgejo-branch-protection-rollout.md);
  [ADR-0050](../adr/adr-0050-per-repo-delivery-contract.md); `forgejo-leading` skill
- Reconciler precedents: `kubernetes/apps/forgejo/forgejo-actions-secrets/app/forgejo-package-link-reconciler.cronjob.yaml`,
  `kubernetes/apps/ploeg/ploeg/app/tracker-wiring.cronjob.yaml`,
  [ADR-0046](../adr/adr-0046-harbor-proxy-credential-convergence.md), `provisioner-job` skill
- tofu-controller precedent: [ADR-0058](../adr/adr-0058-access-plane-one-module-one-model.md),
  [access plane RFC](rfc-access-plane.md), `kubernetes/apps/security/access-plane/`
- Providers: [svalabs/forgejo](https://registry.terraform.io/providers/svalabs/forgejo/latest)
  ([source](https://github.com/svalabs/terraform-provider-forgejo)),
  [go-gitea/gitea](https://registry.terraform.io/providers/go-gitea/gitea/latest)
