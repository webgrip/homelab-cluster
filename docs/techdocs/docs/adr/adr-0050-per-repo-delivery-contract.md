---
status: accepted
date: 2026-07-26
---

# Per-repo delivery contract, server-enforced

Related: ADR-0048 (execution layer: agents are PR-only), ADR-0049 (failure states).

## Glossary (read this first)

| Term | Meaning |
| --- | --- |
| **Delivery path** | How a change reaches `main`: a direct trunk push, or a PR that gets merged. |
| **Trunk-based** | Committing straight to `main` — no feature branch, no PR. Fast, but nothing arbitrates between concurrent writers. |
| **Zombie PR** | A PR whose head branch holds zero commits absent from the target branch. Forgejo shows *"This branch is already included in the target branch. There is nothing to merge."* |
| **Contained branch** | A branch whose head is an ancestor of `main` — fully merged, deletable with zero loss. |
| **Branch protection** | A server-side Forgejo rule on a branch: who may push directly, who may merge PRs. |
| **Push / merge whitelist** | The exception lists on a protection rule: identities allowed to push directly / to merge. |
| **Janitor** | The weekly `scheduled-maintenance` workflow that closes zombie PRs and prunes contained branches. |

## Context and Problem Statement

*What actually happened, 2026-07-24 → 26.* Two *documented, individually correct* protocols
collided on this repo:

- **CLAUDE.md** mandates trunk-based direct pushes to `main` for interactive (human + AI) sessions — no PRs.
- **ADR-0048** mandates the opposite for the agent fleet: *"PR-only, never direct to `main`."*

On 2026-07-24 the CI-health-alerts work landed on `main` at 16:50Z as commit `6077fed9`
(owner trunk push). At 21:23Z `agent-builder` opened PR #438 for the same work item, from a
branch cut off a pre-work snapshot of `main` — zero unique commits, a zombie at birth. This
was the *n*-th occurrence, not the first: the 2026-07-26 audit found **31 stale branches**
(10 contained, 6 superseded from the pre-Forgejo era, 15 Renovate fossils) and confirmed
**zero lost work** — every diverged branch had been re-landed on `main` in equal-or-better
form. The failure mode is structural: two sanctioned delivery paths, no arbiter. Prose
(CLAUDE.md, an ADR) cannot reject a push; only the server can.

## Decision

Every repo declares **one delivery contract**, and Forgejo **enforces it server-side**
via branch protection. Documentation describes the contract; it never *is* the enforcement.

1. **homelab-cluster** (GitOps repo — `main` is the deployed truth, there is no
   `development` branch and no release pipeline): the **owner identity** (`ryangr0` —
   humans and interactive AI sessions pushing over the owner's SSH key) stays
   **trunk-based**. The **agent fleet is PR-only**. Enforced by a protection rule on
   `main`: push whitelist = `ryangr0`, merge whitelist = `ryangr0`. The merge whitelist
   additionally server-enforces ADR-0048's *builder ≠ judge*: `agent-builder` cannot merge
   its own PRs.
2. **Product repos** (`development` branch cuts RC releases): protect `main` **and**
   `development`; push whitelist = the **`forgejo-ci` bot only** (semantic-release must
   commit the `chore(release)` bump + tag back to the branch — see the warning header in
   `scripts/forgejo-sync.sh`). Humans and agents alike deliver via PRs. The CI bot and the
   agent bot are **distinct identities by design**: whitelisting `forgejo-ci` grants
   nothing to `agent-builder`.
3. **Janitor backstop** (`.forgejo/workflows/scheduled-maintenance.yml`, weekly): closes
   zombie PRs with an explanatory comment and prunes contained branches (never `main`,
   never `renovate/*`, mass-deletion fuse at 15). Runs as `forgejo-ci` — *janitor ≠
   builder*, mirroring the ADR-0048 role split.
4. **Empty-diff guard** in the agent harness (`webgrip/infrastructure`,
   `ops/docker/agent-runner`): after rebasing onto the target branch, if the diff is
   empty the run comments on its ticket and exits — a zombie PR is never opened.

## Considered Options

- **Server-enforced per-repo contract + janitor + harness guard** (chosen)
- PR-only everywhere, including the owner
- Work-item claiming/labeling protocol between the delivery paths
- Do nothing (close zombies by hand as they appear)

## Decision Outcome

Chosen option: **"Server-enforced per-repo contract + janitor + harness guard"**, because
the two prior protocols failed precisely where they relied on discipline: nothing mechanical
arbitrated between writers. Protection moves the conflict from discovery-time (a mystery
zombie PR days later) to push-time, where the pusher has context and a 30-second fix. The
per-repo split honors the real difference between repos: homelab-cluster's `main` is a
deployed system where the owner iterates at trunk speed; product repos gate releases through
`development`.

- PR-only-everywhere was rejected for homelab-cluster: it taxes every owner iteration to
  solve a problem only the fleet path has, and this repo has no `development`/staging tier
  to absorb the friction.
- Claiming/labeling was rejected as coordination-by-discipline: it adds work per ticket and
  fails exactly like the prose protocols did — silently, when someone forgets.
- Do-nothing was rejected: zombies recur mechanically (this was the *n*-th), and each one
  costs an investigation plus a duplicate agent run.

### Consequences

- Good, because the collision class is closed by the server, not by memory or convention.
- Good, because `builder ≠ judge` and `janitor ≠ builder` are now enforced, not promised.
- Good, because stale-branch inventory self-heals weekly instead of accumulating for months.
- Bad, because duplicate *work* (two writers executing the same ticket) is reduced but not
  eliminated — the harness guard kills the empty PR, not the wasted run. Dispatch-level
  dedup stays with the ploeg plane (ADR-0048/0049 territory).
- Bad, because protection adds one break-glass step (lift the rule) if the owner account is
  ever unavailable and an emergency push must come from elsewhere.

### Confirmation

- `curl -s $API/repos/webgrip/homelab-cluster/branch_protections` (authed) lists a `main`
  rule with `push_whitelist_usernames == merge_whitelist_usernames == ["ryangr0"]`.
- Janitor mutation drill (both directions, per the CLAUDE.md gate-testing rule): (fail-side)
  push a throwaway branch already contained in `main`, open a PR from it, dispatch the
  workflow live → PR is closed with the janitor comment and the branch is deleted;
  (pass-side) dispatch on a clean repo → log ends `PRs closed=0, branches pruned=0` and the
  job exits 0. Trigger reality: schedules fire from the default branch — the workflow lives
  on `main`, and a manual `workflow_dispatch` proves the path end-to-end.
- `python3 scripts/validate_adr_consistency.py .` passes (this record ↔ index parity).

## More Information

- Technical story: PR #438 post-mortem, 2026-07-26 (zombie-PR root cause: trunk-push vs
  ADR-0048 PR-only collision; 31-branch garbage collection, zero lost work).
- 2026-07-26 — janitor implemented in `scheduled-maintenance.yml`; repo GC executed; this
  record accepted.
- Pending at acceptance: homelab-cluster protection rule (owner UI/API action);
  `sync_protect` payload upgrade + product-repo rollout (`forgejo-sync.sh --all --only
  protect`); empty-diff guard in `webgrip/infrastructure`.
- Supported by: ADR-0048 (role bots, PR-only fleet), ADR-0049 (dispatch failure states).
