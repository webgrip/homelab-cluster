# Top-up / inventory — reconcile the board to ~100 open

Strategic pass (multi-item, not single-task): re-inventory live state, complete shipped tickets,
refill with verified findings. Run after a big sprint or on request.

## Process

### 1. Ground truth (don't trust ticket text)

```bash
git log --oneline <last-topup-commit>..HEAD          # what shipped since last run
./scripts/posture-counts.sh                          # verified posture counts
```

Cross-check live via read-only MCPs (`mcp__kubernetes__*`, `mcp__grafana__query_prometheus`) —
e.g. confirm a metric exists before proposing an alert on it.

### 2. Read the board

`tasks_list {projectId: 3, show: "all", limit: 200}` — index open tickets AND recent completions
by title (the dedup pool). Verify "Found N" covers the whole board (pagination gotcha, SKILL.md).

### 3. Fan out 3 parallel deep audits (one message, 3 `Agent` calls, `subagent_type: Explore`)

Dimensions: **(a) security/hardening**, **(b) reliability/HA/backup-DR**, **(c) CI/shift-left/DX**.
Brief each with the full ALREADY-DONE list (completed tickets + step-1 git log) so they only
return *open* gaps; ask for 25–40 candidates each as `title · file:line · Impact · Effort`; tell
them to verify, not guess.

### 4. Reconcile

- **Shipped** → `task_complete` + closing comment citing the commit/evidence.
- **Stale premise** (work exists but unverified) → rewrite as verify-and-close ([refine.md](refine.md)),
  don't silently complete.
- **New findings** — filter agent noise against the repo first (they over-report), dedupe against
  ALL open + recently-completed titles, then `task_create` with theme/impact/effort labels +
  `needs-refinement`, priority per the P-mapping. Refinement is a separate pass.
- **Re-tag honestly** — both directions; P0 discipline per SKILL.md heuristics.
- **do-next rebalance** — set on ≤10 highest-leverage unblocked tickets, remove stale picks.

### 5. Report

Counts (completed/created/re-tagged), the new do-next set, and any audit evidence that belongs in
docs (ADR/runbook), not tickets. This pass *plans*; implementing a ticket is a separate change.
