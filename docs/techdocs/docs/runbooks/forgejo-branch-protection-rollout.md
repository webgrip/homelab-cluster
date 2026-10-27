# Forgejo branch protection rollout (ADR-0050 delivery contract)

Applies the per-repo delivery contract from
[ADR-0050](../adr/adr-0050-per-repo-delivery-contract.md) as **server-side branch protection**.
Docs describe who may push where; only a protection rule can actually reject the push.

**Since 2026-10-18 protection is data.** The rules live in the repo-config model
(`kubernetes/apps/repo-config/repo-config/model`): a `branches` map per profile or repo, applied
hourly by the `repo-config` Terraform object in namespace `repo-config` with
`approvePlan: auto`. `scripts/forgejo-sync.sh --only protect` and `--only settings` are
**retired** and refuse before any API call: a hand PATCH was a second writer on the same rule,
and an `--all --only protect` sweep locked the owner out of homelab-cluster on 2026-08-05.
Nothing scheduled ever ran the script.

Every entry in `repos.yaml` names its `forge`. Forgejo entries are keyed by repository name and
read the `forgejo` block of their profile; GitHub entries are keyed `<owner>/<name>` and are
applied by a separate module (since 2026-10-24, VIK-2320): see
[github-app-ploeg-hq](github-app-ploeg-hq.md#one-model-for-both-forges-since-2026-10-24) and
[github-app-webgrip](github-app-webgrip.md).

| Term | Meaning |
| --- | --- |
| **Push whitelist** | Identities allowed to push the branch directly. `push` in the model. Since [ADR-0083](../adr/adr-0083-nobody-pushes-to-main-and-core-repositories-need-a-second-person.md) every active rule says `push: []`: nobody pushes, the owner and the bots included, and the validator refuses anything else. |
| **Required approvals** | `required_approvals` in the model: approving reviews a pull request needs before it merges. `1` on `protected-core`, with `dismiss_stale_approvals`, `block_on_rejected_reviews` and `block_on_outdated_branch`; `0` elsewhere. An author cannot approve their own pull request. |
| **Tag protection** | `tags` in a profile or repo: a pattern (`*` is every tag) and the users who may create or update matching tags. Applied as `restapi_object.tag_protection`, because the svalabs/forgejo provider has no tag resource. |
| **Merge whitelist** | Identities allowed to merge PRs into the branch. `merge` in the model; absent means no whitelist. |
| **Status checks** | `status_checks` in the model: contexts that must be green before a merge. Forgejo reads each entry as a glob pattern, so a literal `[` or `]` must be escaped (`"\\[Workflow\\] On Pull Request / checks (pull_request)"` in YAML). Unescaped, `[Workflow]` is a character class, the context never matches, and "merge when checks succeed" waits forever; the schema refuses it. |

The rules owned since 2026-10-26 (ADR-0083):

| Profile | Repositories | Push | Merge | Approvals | Tags |
| --- | --- | --- | --- | --- | --- |
| `protected-core` | agent-standards, workflows, renovate-config, homelab-cluster, unfold-cluster | nobody | `ryangr0`, `yon`, `renovate` (unfold-cluster: `ryangr0` only) | 1 | `webgrip-ci` only |
| `protected` | every other active Forgejo repository | nobody | `ryangr0`, `yon`, `renovate` (unfold `development` adds `ploeg-release`) | 0 | `webgrip-ci` only |
| `baseline` | archived repositories | unchanged | unchanged | 0 | none |

Required contexts stay per repository: homelab-cluster `main` the four `e2e / … (pull_request)` jobs, unfold `development` and `main` only `* / gate (pull_request)`, the job that waits for all the others ([ADR-0084](../adr/adr-0084-a-branch-rule-requires-one-gate-and-forgejo-merges-renovate-on-it.md)), unfold-cluster `main` its seven checks, talos-kata-extension `main` its source-change check; every other repository none, because a required context that never reports blocks every merge.

Private repositories are in the model with `settings.private: true`, so tofu keeps them private: compyutah, erfbeeld, omnigraph-explorer, ploeg-bench, ploeg-bench-world and talos-kata-extension. ploeg-bench-world's default branch is `bench/void`, which the bench harness resets, so only its unused `main` carries the rule. Two private repositories stay outside the model on purpose, because a protected `main` would break how they are written: `obsidian-vault`, which the Obsidian git plugin pushes straight to `main`, and `previews`, which `agent-builder` publishes to by pushing `main`. Either joins the model once its writer delivers through a pull request.

`agent-builder` is deliberately in **no** list anywhere: the agent fleet delivers via PRs
(ADR-0048) and never merges its own work.

## Changing a rule

1. Edit `profiles.yaml` (a profile's `branches` or `tags`) or `repos.yaml` (a repo's `branches`
   or `tags`, which add to and override the profile's rule field by field). A rule that does not exist live yet needs no import;
   a rule that already exists by hand must be added to `branch_protections_live_before_tofu` in
   `tofu/imports.tf` first, or the create fails.
2. `./scripts/validate-repo-config-model.sh` (pre-commit runs it with the mutation cases).
3. Push. The next reconcile plans and applies; read the plan with
   `kubectl -n repo-config get configmap tfplan-default-repo-config -o jsonpath='{.data}'`.

## Lock-out guard

Nobody pushes to `main`, so the owner lands a change in homelab-cluster only by merging a pull request. Three layers keep that possible:

- the JSON Schema requires `homelab-cluster` on `protected-core`, allows its `main` override only `status_checks`, and requires `ryangr0` in both protected profiles' merge lists;
- every `forgejo_branch_protection` instance has a precondition that fails the plan, before anything is applied, when `homelab-cluster/main` is missing or its merge list lacks `ryangr0`;
- every rule has `prevent_destroy`, so deleting a rule from the model fails the plan.

## Break-glass

A change that cannot wait for the other developer's approval, or a merge path that is broken:

1. A repository administrator can force-merge a pull request past approvals and checks in the web UI: the provider cannot set `apply_to_admins`, which stays off, so Forgejo keeps its administrator override. The merge stays visible on the pull request.
2. If no pull request can merge at all: an admin token from OpenBao `secret/forgejo/admin`, a PATCH of `/repos/webgrip/<repo>/branch_protections/main` that lifts the rule (`{"enable_push": true, "enable_push_whitelist": true, "push_whitelist_usernames": ["ryangr0"]}`), the fix, then wait for the hourly apply or reconcile `Terraform/repo-config`: it puts the rule back. Say in the fix's commit that it went past the rule.

## Why status checks (added 2026-08-04)

Branch protection is the **only** mechanism in Forgejo that makes CI a merge gate. The merge
path — including the background auto-merge job — consults protected-branch rules. With no
required contexts a red PR is mergeable, and enabling Renovate's `platformAutomerge` would merge
PRs the moment they are scheduled, **without waiting for e2e**. So status checks are a hard
prerequisite for `platformAutomerge`, not a nicety.

Contexts must match the reported names **exactly**. Per forgejo#9288 a pattern matching zero
tasks counts as *matched*, so a typo produces a rule that looks correct in the UI and gates
nothing — this is exactly how forgejo#11224 ended up merging PRs with failing checks. Get the
live names from a real PR rather than typing them:

```bash
sha=$(curl -s -H "Authorization: token $FORGEJO_TOKEN" \
  "$FORGEJO_API/repos/webgrip/homelab-cluster/pulls/<n>" | python3 -c 'import json,sys;print(json.load(sys.stdin)["head"]["sha"])')
curl -s -H "Authorization: token $FORGEJO_TOKEN" \
  "$FORGEJO_API/repos/webgrip/homelab-cluster/commits/$sha/status" |
  python3 -c 'import json,sys;[print(s["context"]) for s in json.load(sys.stdin)["statuses"]]'
```

`renovate/stability-days` is deliberately **excluded**: it is Renovate's own soak status, and
requiring it would block a human merging during a soak window.

## Mutation test — required before enabling platformAutomerge

A rule that only ever passes cannot be distinguished from a rule that does nothing. Test both
directions on homelab-cluster:

1. **Must BLOCK:** take a PR whose e2e is red and attempt a merge via the UI/API. Expect refusal.
   (If none is red, push a deliberate break to a scratch PR branch.)
2. **Must PASS:** take a PR whose e2e is fully green and merge it. Expect success.

Only after **both** behave correctly, set `platformAutomerge: true` in `.renovaterc.json5`. That
removes Renovate's one-merge-per-run ceiling (merging one PR flips every other PR's Forgejo
`mergeable` flag to false for the rest of the run), letting Forgejo merge each PR as soon as its
checks pass.

`platformAutomerge: true` is set on one group so far: `ploeg-unfold-release` (2026-10-18). It is
gated by exactly the contexts homelab-cluster's `main` rule requires.

## Verify

```bash
for rb in homelab-cluster/main unfold/development; do
  curl -s "https://forgejo.webgrip.dev/api/v1/repos/webgrip/${rb%/*}/branches/${rb#*/}" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["name"], d["protected"], d["status_check_contexts"])'
done
kubectl -n repo-config get terraform repo-config
```

The whitelists are not readable anonymously; the plan in `tfplan-default-repo-config` shows
them as tofu reads them. Expect the Terraform object Ready with `Plan no changes` between model
commits. Behavioral check, both directions: a direct push to `main`, the owner's included, is rejected,
**and** a pull request with green checks (and, on a core repository, an approval) merges.
`curl -s -H "Authorization: token $FORGEJO_TOKEN" "$FORGEJO_API/repos/webgrip/<repo>/tag_protections"` lists `*` with `webgrip-ci`.

## Repo merge defaults

`default_delete_branch_after_merge` and `default_merge_style` are profile settings in the same
model (`baseline`: `true`, `merge`; per-repo deviations in `repos.yaml`). `--only settings`
is retired with `protect`.

## Renovate policy (since 2026-10-26, VIK-2478)

Every active repo entry states which `webgrip/renovate-config` presets its Renovate config
extends. The field is version-agnostic: a `#vX.Y.Z` pin is Renovate's job, so the schema refuses
one here.

```yaml
ai-skills:
  renovate:
    profile: profile-library
unfold:
  renovate:
    presets:
      - "local>webgrip/renovate-config"
      - "local>webgrip/renovate-config:automerge-non-major"
      - "local>webgrip/renovate-config:apm"
homelab-cluster:
  renovate:
    config_file: ".renovaterc.json5"
    presets: [...]
```

| Key | Meaning |
| --- | --- |
| `profile` | One of `profile-app`, `profile-site`, `profile-library`, `profile-image-set`; expands to the single preset `local>webgrip/renovate-config:<profile>`. |
| `presets` | The exact ordered `extends` list without pins, for repos on a legacy combination or a profile plus extras. |
| `absent: true` | The repo deliberately has no Renovate config. |
| `config_file` | Where the config lives on the default branch; default `renovate.json`. JSON5 files are read too. |

Exactly one of `profile`, `presets`, `absent` is set. `scripts/validate-repo-config-model.sh`
requires the field on every active repo except push mirrors, which take the policy of their
source. When the renovate-config gate/risk/capability redesign lands, add its profile names to
`model/schema/renovate.schema.json`.

`tofu/renovate.tf` reads each anonymously readable repo's config from Forgejo every hourly run
and never writes. Two `check` blocks warn without blocking an apply:

- `renovate_policy_matches_live`: the live `extends`, with pins stripped, differs from the model,
  the file is missing, or a repo modelled `absent` has one.
- `renovate_extends_pinned`: a repository preset (`local>`, `github>`) has no `#vX.Y.Z` pin and
  follows the preset repository's default branch.

Both lists are also the output `renovate_policy_drift`. A plan with no resource changes does not
log its warnings, but a change to that output is a plan change: the next run applies it (state
only), the readable plan in `tfplan-default-repo-config` shows the new lists, the runner log
carries the check warnings, and `ForgejoRepoConfigApplyChangedSomething` fires. Read the current
lists with:

```text
{namespace="repo-config", container="tf-runner"} "Renovate"
```

in VictoriaLogs, or from the readable plan after a change.

Not covered: private repos (the six above, unreadable without a token in a data
source) and GitHub entries (`ploeg-hq/ploeg`), which are modelled but not compared.

## Symptom → cause

| Symptom | Cause / fix |
| --- | --- |
| `403` on apply — even as org **owner** | Role ≠ API permission: the **token** lacks scopes. Re-mint with *repository: Read and Write* + *organization: Read*, or mint a short-lived token from the admin account (OpenBao `secret/forgejo/admin`), apply, then revoke it. *(Scope fix inferred from the API's requirements, not yet confirmed by a successful run — verify on first rollout and update this row.)* |
| A repo never appears in the `--all` sweep | Pre-2026-07-26 the script fetched a single page (silent truncation past 100 repos — ploeg, ai-skills, previews, semantic-release-config were invisible). Current script paginates; if it recurs, check the resolved repo list first. |
| A rule changed back an hour after a hand edit | Expected: tofu owns it and `ForgejoRepoConfigApplyChangedSomething` fired. Change the model instead. |
| Plan fails with "must keep ryangr0 in the merge list" | The lock-out guard: the model dropped the owner from `homelab-cluster/main`'s merge list. Nothing was applied; revert the model change. |
| A release job fails to push its tag | The tag rule allows `webgrip-ci` only: the job pushed as another identity. Releases tag as `webgrip-ci`. |
| Renovate's automerge never lands on a core repository | Expected: `protected-core` needs an approval, Renovate's included. Approve the pull request. |

## Related

- [ADR-0050 — per-repo delivery contract](../adr/adr-0050-per-repo-delivery-contract.md) — the why, and the #438 post-mortem.
- [ADR-0083 — nobody pushes to main](../adr/adr-0083-nobody-pushes-to-main-and-core-repositories-need-a-second-person.md) — the profiles, approvals and tag rules in force since 2026-10-26.
- `kubernetes/apps/repo-config/repo-config` — the model, the tofu module and the alerts.
- Weekly janitor `.forgejo/workflows/scheduled-maintenance.yml` — closes zombie PRs, prunes merged branches (Mondays 06:00 UTC).
- `forgejo-leading` skill — repo cutover; protection is now a model entry, not a script run.
