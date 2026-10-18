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

| Term | Meaning |
| --- | --- |
| **Push whitelist** | Identities allowed to push the branch directly — everyone else must open a PR. `push` in the model; absent means no whitelist. |
| **Merge whitelist** | Identities allowed to merge PRs into the branch. `merge` in the model; absent means no whitelist. |
| **Status checks** | `status_checks` in the model: contexts that must be green before a merge. |

The rules owned today:

| Rule | Push whitelist | Merge whitelist | Required contexts |
| --- | --- | --- | --- |
| `homelab-cluster` `main` (`homelab` profile) | `ryangr0` | `ryangr0`, `renovate` | the four `e2e / … (pull_request)` jobs |
| `unfold` `development` | none | none | `checks`, `release-policy`, `ploeg-pin`, `ploeg-docs` |
| `unfold` `main` | none | none | `checks`, `release-policy`, `ploeg-pin` |
| `workflows` `main`, `claude-config` `main` | none | none | none |

`agent-builder` is deliberately in **no** list anywhere: the agent fleet delivers via PRs
(ADR-0048) and never merges its own work.

## Changing a rule

1. Edit `profiles.yaml` (a profile's `branches`) or `repos.yaml` (a repo's `branches`, which
   replaces the profile's rule per branch). A rule that does not exist live yet needs no import;
   a rule that already exists by hand must be added to `branch_protections_live_before_tofu` in
   `tofu/imports.tf` first, or the create fails.
2. `./scripts/validate-repo-config-model.sh` (pre-commit runs it with the mutation cases).
3. Push. The next reconcile plans and applies; read the plan with
   `kubectl -n repo-config get configmap tfplan-default-repo-config -o jsonpath='{.data}'`.

## Lock-out guard

Three layers keep the owner's trunk push on homelab-cluster:

- the JSON Schema requires `homelab-cluster` on the `homelab` profile, forbids it a
  `branches` or `settings` override, and requires `ryangr0` in that profile's `main` push list;
- every `forgejo_branch_protection` instance has a precondition that reads the model and fails
  the plan, before anything is applied, when `homelab-cluster/main` is missing or its push list
  lacks `ryangr0`;
- every rule has `prevent_destroy`, so deleting a rule from the model fails the plan.

Break-glass if the owner is locked out anyway: an admin token from OpenBao
`secret/forgejo/admin`, a PATCH of `/repos/webgrip/homelab-cluster/branch_protections/main` with
`{"push_whitelist_usernames":["ryangr0"]}`, then fix the model, or the next apply reverts the PATCH.

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
gated by exactly the contexts the `homelab` profile requires.

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
commits. Behavioral check, both directions: a direct push from a non-whitelisted identity is
rejected on homelab-cluster, **and** the owner's trunk push still lands.

## Repo merge defaults

`default_delete_branch_after_merge` and `default_merge_style` are profile settings in the same
model (`baseline`: `true`, `merge`; per-repo deviations in `repos.yaml`). `--only settings`
is retired with `protect`.

## Symptom → cause

| Symptom | Cause / fix |
| --- | --- |
| `403` on apply — even as org **owner** | Role ≠ API permission: the **token** lacks scopes. Re-mint with *repository: Read and Write* + *organization: Read*, or mint a short-lived token from the admin account (OpenBao `secret/forgejo/admin`), apply, then revoke it. *(Scope fix inferred from the API's requirements, not yet confirmed by a successful run — verify on first rollout and update this row.)* |
| A repo never appears in the `--all` sweep | Pre-2026-07-26 the script fetched a single page (silent truncation past 100 repos — ploeg, ai-skills, previews, semantic-release-config were invisible). Current script paginates; if it recurs, check the resolved repo list first. |
| A rule changed back an hour after a hand edit | Expected: tofu owns it and `ForgejoRepoConfigApplyChangedSomething` fired. Change the model instead. |
| Plan fails with "must keep ryangr0 in the push list" | The lock-out guard: the model dropped the owner from `homelab-cluster/main`. Nothing was applied; revert the model change. |

## Related

- [ADR-0050 — per-repo delivery contract](../adr/adr-0050-per-repo-delivery-contract.md) — the why, and the #438 post-mortem.
- `kubernetes/apps/repo-config/repo-config` — the model, the tofu module and the alerts.
- Weekly janitor `.forgejo/workflows/scheduled-maintenance.yml` — closes zombie PRs, prunes merged branches (Mondays 06:00 UTC).
- `forgejo-leading` skill — repo cutover; protection is now a model entry, not a script run.
