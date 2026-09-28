# Forgejo branch protection rollout (ADR-0050 delivery contract)

Applies the per-repo delivery contract from
[ADR-0050](../adr/adr-0050-per-repo-delivery-contract.md) as **server-side branch protection**.
Docs describe who may push where; only a protection rule can actually reject the push.

| Term | Meaning |
| --- | --- |
| **Push whitelist** | Identities allowed to push the branch directly — everyone else must open a PR. |
| **Merge whitelist** | Identities allowed to merge PRs into the branch. |
| **Converge** | Re-running the script PATCHes an existing rule to the desired state — safe to repeat. |

The contract in one table:

| Repo class | Branches | Push whitelist | Merge whitelist |
| --- | --- | --- | --- |
| Product repos (script default) | `main` + `development` (if the branch exists) | `webgrip-ci` (on `development` also `ryangr0`) | `ryangr0,renovate` |
| **homelab-cluster** (override — run LAST) | `main` | `ryangr0` | `ryangr0` |

`agent-builder` is deliberately in **no** list anywhere: the agent fleet delivers via PRs
(ADR-0048) and never merges its own work. Whitelisting `webgrip-ci` (the CI/release bot)
grants nothing to `agent-builder` — distinct identities by design.

## Prerequisites

- `FORGEJO_TOKEN` exported in the shell: scope `write:repository`, plus `read:organization`
  for `--all`, and the token's **user must be repo admin** on the target repos. On
  fine-grained tokens that is *repository: Read and Write* + *organization: Read*.
- Credentials live in OpenBao under `secret/forgejo/*` — fetch with
  `bao kv get -field=<field> secret/forgejo/<name> | pbcopy` (`BAO_ADDR=https://openbao.webgrip.dev`);
  never echo values.

## Rollout — order is load-bearing

`--all` means every org repo that is not a mirror, a fork or **private**. Private repos such as
`webgrip/obsidian-vault` are never swept, so a sweep can never add a GitHub push-mirror to one;
[test-forgejo-sync-skips-private.sh](../../../../scripts/test-forgejo-sync-skips-private.sh) proves it
in pre-commit and CI. Name a private repo with `--repo` when it really needs a setting.

Step 3 must run **after** any `--all` sweep: the sweep writes the product-repo default
(`webgrip-ci`) to every repo it touches, which on homelab-cluster would lock the owner's
trunk pushes out until the override re-runs.

```bash
cd ~/projects/webgrip/homelab-cluster

# 1. Product repos — dry-run first, then apply
./scripts/forgejo-sync.sh --all --only protect
./scripts/forgejo-sync.sh --all --only protect --apply

# 2. (Optional) personal repos where the owner also pushes directly
for r in .profile .profile-private claude-config Tenants; do
  PUSH_WHITELIST=webgrip-ci,ryangr0 ./scripts/forgejo-sync.sh --repo "$r" --only protect --apply
done

# 3. LAST — homelab-cluster owner override (trunk-based, ADR-0050 §1)
#    `renovate` MUST stay in MERGE_WHITELIST (this line used to read MERGE_WHITELIST=ryangr0,
#    which would have revoked Renovate's ability to merge its own PRs — the one repo where
#    automerge does all the dependency work). The owner trunk-pushes; Renovate still merges.
#    STATUS_CHECK_CONTEXTS is what actually makes e2e a merge gate — see "Why status checks".
PUSH_WHITELIST=ryangr0 MERGE_WHITELIST=ryangr0,renovate \
STATUS_CHECK_CONTEXTS='e2e / Lint & static validation (pull_request),e2e / Flux-local render (pull_request),e2e / Kyverno Chainsaw (KinD) (pull_request),e2e / Validate Renovate config (pull_request)' \
  ./scripts/forgejo-sync.sh --repo homelab-cluster --only protect --apply
```

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

## Verify

```bash
curl -s -H "Authorization: token $FORGEJO_TOKEN" \
  "https://forgejo.webgrip.dev/api/v1/repos/webgrip/homelab-cluster/branch_protections" |
  python3 -c 'import json,sys; [print(r["rule_name"], r["push_whitelist_usernames"], r["merge_whitelist_usernames"]) for r in json.load(sys.stdin)]'
```

Expect `main ['ryangr0'] ['ryangr0', 'renovate']` on homelab-cluster and `['webgrip-ci']` /
`['ryangr0', 'renovate']` on product repos. Behavioral check, both directions: a direct push
from a non-whitelisted identity is rejected, **and** the next semantic-release run still
commits its `chore(release)` bump — the `webgrip-ci` whitelist is what makes protection
release-safe.

## Repo merge defaults (`--only settings`)

Owner decision 2026-09-28: every webgrip repo has `default_delete_branch_after_merge: true`
and `default_merge_style: merge`. The merge commit is only the pre-selected button; squash,
rebase and fast-forward stay allowed wherever they already are. `sync_settings` PATCHes
`/repos/webgrip/<repo>` with **only those two fields**, skips repos that already match, and
prints per-repo drift as `field: current -> desired` in the dry-run. It never touches branch
protection, so it is safe to sweep with `--all` at any time — unlike `protect`, it cannot
lock the owner out of homelab-cluster. It is part of the default action set, so a plain
parity run converges it too.

```bash
./scripts/forgejo-sync.sh --all --only settings
./scripts/forgejo-sync.sh --all --only settings --apply
```

Override per run with `DEFAULT_MERGE_STYLE=<merge|rebase|rebase-merge|squash|fast-forward-only>`
or `DEFAULT_DELETE_BRANCH_AFTER_MERGE=false`. A `WARN` line means the repo has that merge style
disabled, so the default would point at a greyed-out button — enable the style or pick another.

Verify:

```bash
curl -s -H "Authorization: token $FORGEJO_TOKEN" \
  "https://forgejo.webgrip.dev/api/v1/repos/webgrip/<repo>" |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["default_delete_branch_after_merge"], d["default_merge_style"])'
```

Expect `True merge`.

## Symptom → cause

| Symptom | Cause / fix |
| --- | --- |
| `403` on apply — even as org **owner** | Role ≠ API permission: the **token** lacks scopes. Re-mint with *repository: Read and Write* + *organization: Read*, or mint a short-lived token from the admin account (OpenBao `secret/forgejo/admin`), apply, then revoke it. *(Scope fix inferred from the API's requirements, not yet confirmed by a successful run — verify on first rollout and update this row.)* |
| A repo never appears in the `--all` sweep | Pre-2026-07-26 the script fetched a single page (silent truncation past 100 repos — ploeg, ai-skills, previews, semantic-release-config were invisible). Current script paginates; if it recurs, check the resolved repo list first. |
| A release job suddenly can't push | The repo got the default whitelist but its release bot isn't `webgrip-ci` — re-run with the right `PUSH_WHITELIST` (rules converge via PATCH). |
| No `development` rule was created | That branch doesn't exist on the repo — `sync_protect` skips it by design. |

## Related

- [ADR-0050 — per-repo delivery contract](../adr/adr-0050-per-repo-delivery-contract.md) — the why, and the #438 post-mortem.
- `scripts/forgejo-sync.sh` header — payload details and override examples.
- Weekly janitor `.forgejo/workflows/scheduled-maintenance.yml` — closes zombie PRs, prunes merged branches (Mondays 06:00 UTC).
- `forgejo-leading` skill — repo cutover; protection is its step-4 parity item.
