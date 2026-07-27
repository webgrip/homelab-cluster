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
PUSH_WHITELIST=ryangr0 MERGE_WHITELIST=ryangr0 \
  ./scripts/forgejo-sync.sh --repo homelab-cluster --only protect --apply
```

## Verify

```bash
curl -s -H "Authorization: token $FORGEJO_TOKEN" \
  "https://forgejo.webgrip.dev/api/v1/repos/webgrip/homelab-cluster/branch_protections" |
  python3 -c 'import json,sys; [print(r["rule_name"], r["push_whitelist_usernames"], r["merge_whitelist_usernames"]) for r in json.load(sys.stdin)]'
```

Expect `main ['ryangr0'] ['ryangr0']` on homelab-cluster and `['webgrip-ci']` /
`['ryangr0', 'renovate']` on product repos. Behavioral check, both directions: a direct push
from a non-whitelisted identity is rejected, **and** the next semantic-release run still
commits its `chore(release)` bump — the `webgrip-ci` whitelist is what makes protection
release-safe.

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
