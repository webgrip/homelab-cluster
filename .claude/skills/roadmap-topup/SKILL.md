---
name: roadmap-topup
description: Re-inventory the whole cluster/repo and reconcile the Vikunja "Homelab Roadmap" board — complete shipped tickets, add new findings as needs-refinement tickets, keep ~100 open. The board is the roadmap system of record (ADR-0043); there is no roadmap.md.
when_to_use: Use when asked to "inventarize" / "take inventory", "refresh/top-up the roadmap", prioritize or triage the backlog, decide what to work on, or "what should we work on/do next" at a strategic (multi-item, not single-task) level.
---

# Inventory → reconcile the board to ~100 open

The roadmap IS the Vikunja board: project `Homelab Roadmap`, reached through the `vikunja` MCP
(transport, label taxonomy, priority mapping → the `vikunja` skill; decision → ADR-0043). Each run
re-inventories live state, completes shipped tickets, and refills so ~100 stay open.

## Process

### 1. Capture ground truth (don't trust ticket text)
```bash
git log --oneline <last-topup-commit>..HEAD          # what shipped since last run
./scripts/posture-counts.sh                          # verified posture counts
```
Cross-check live via the read-only MCPs (`mcp__kubernetes__*`, `mcp__grafana__query_prometheus`)
— e.g. confirm a metric exists before proposing an alert on it.

### 2. Read the board
`tasks_list {projectId, show: "all", limit: 200}` — index open tickets AND recent completions by
title (dedup pool). Verify the reported count covers the whole board (vikunja skill gotcha).

### 3. Fan out 3 parallel deep audits (one message, 3 `Agent` calls, `subagent_type: Explore`)
Dimensions: **(a) security/hardening**, **(b) reliability/HA/backup-DR**, **(c) CI/shift-left/DX**.
Brief each with the full ALREADY-DONE list (completed tickets + step-1 git log) so they only return
*open* gaps; ask for 25–40 candidates each as `title · file:line · Impact · Effort`. Tell them to
verify, not guess.

### 4. Reconcile the board
- **Shipped** → `task_complete` + a closing comment citing the commit/evidence.
- **Stale premise** (work exists but unverified) → rewrite the ticket as verify-and-close
  (`vikunja-refiner` conventions), don't silently complete.
- **New findings** — filter agent noise against the repo first (they over-report), dedupe against
  ALL open + recently-completed titles, then `task_create` with `theme/*`, `impact/*`, `effort/*`
  labels + `needs-refinement`, priority per the P-mapping. New tickets get refined later
  (`vikunja-refiner`), not inline.
- **Re-tag honestly**: priority drift both ways; P0 = live risk or cheap correctness now.
- **Do next**: set the `do-next` label on ≤10 highest-leverage tickets, remove it from stale picks.

### 5. Report
Counts (completed/created/re-tagged), the new do-next set, and any evidence the audits produced
that belongs in docs (ADR/runbook), not tickets.

## Notes
- ~100 open is a forcing function: it makes you keep finding real work, not pad. If you genuinely
  can't find 100 real items, hold fewer and say so.
- This skill *plans*; it doesn't implement. Implementing a ticket is a separate, normal change.
- Run cadence: after a big sprint, or on request.
