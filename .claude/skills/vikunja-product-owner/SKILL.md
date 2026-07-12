---
name: vikunja-product-owner
description: Own the Vikunja "Homelab Roadmap" board — the roadmap system of record (ADR-0043) — end-to-end through the in-cluster `vikunja` MCP: ticket CRUD, Definition-of-Ready refinement, prioritization/do-next curation, dependency sequencing, backlog top-up/inventory, and the dark-factory agent protocols (VIK trailers, claim/completion).
when_to_use: Use when creating/updating/completing/listing Vikunja tickets, "make a ticket for X", "what's on the board/roadmap", refining/grooming tickets to the Definition of Ready, splitting an oversized ticket, prioritizing or triaging the backlog, "take inventory"/"top up the roadmap", "what should we work on next", handling a stale-premise ticket, or when the vikunja MCP fails to connect / returns 401 / needs its token rotated.
---

# Vikunja product owner — the board operating manual

The board IS the roadmap (ADR-0043; no roadmap file exists). Everything below runs through the
`vikunja` MCP (LAN-only, **write-capable** — acts as Ryan's user). Tool schemas are deferred:
`ToolSearch "select:mcp__vikunja__tasks_list,mcp__vikunja__task_create"` before calling; for bulk
work or when tools aren't loaded, run [scripts/mcp_client.py](scripts/mcp_client.py).

## The PO loop

**intake** (create, `needs-refinement`) → **refine** to DoR ([refine.md](refine.md)) →
**prioritize** (heuristics below) → **sequence** (`precedes` relations, not prose) →
**dispatch-ready** (`agent-ready` gate) → **close with evidence** ([playbook.md](playbook.md)).
Periodic: **top-up/inventory** ([topup.md](topup.md)) keeps ~100 open and honest.

## Board conventions

| Concept | Convention |
|---|---|
| Project | `Homelab Roadmap` (id 3) |
| Priority | P0/P1/P2/P3 → task `priority` 5/4/3/2 (Vikunja shows 4+ as "Urgent") |
| Tags | labels `theme/<kebab>`, `impact/H\|M\|L`, `effort/S\|M\|L` — every open ticket has all three |
| Top of stack | label `do-next`, hard cap 10 |
| Lifecycle | `needs-refinement` → `ready` (DoR met) → done via `task_complete` + evidence comment |
| Kanban | buckets `Backlog / Ready / In progress (agent) / Review / Done` (view 12) |
| Descriptions | TipTap **HTML only** — raw markdown renders literally; first para = `<p><strong>theme</strong> — <code>[P · I · E]</code></p>` |
| Titles | plain text, no links; rename only with reason + a comment (others reference by title) |

## Definition of Ready (all seven, or it isn't `ready`)

1. **Problem** — what's wrong *today* + evidence (`file:line`, live symptom, ADR/RFC); no evidence found = say so.
2. **Outcome** — one sentence.
3. **Acceptance criteria** — 2–6 HTML checkboxes, each verifiable against real state ("improve X" is not one).
4. **Approach** — 3–7 steps naming real repo paths + applicable skills.
5. **Verification** — the exact command/check proving it live (never a proxy).
6. **Gates & links** — blockers by exact title, ADR/RFC/runbook paths.
7. **Sized** — honest S/M; an L names its first shippable slice or gets split.

**Agent-assignability gate** (DoR-v2 → grants `agent-ready`): also states allowed paths/blast
radius · a verification an agent can run itself · the escalation point (what needs the owner) ·
size ≤ M.

## Prioritization heuristics

- **P0** = live risk or cheap correctness *now* — don't inflate; there are rarely more than a few.
- Within a band, order by impact/effort; `effort/S` unblocked tickets are do-next bait.
- **do-next** = highest-leverage *unblocked* tickets, cap 10 — remove stale picks when adding.
- **~100 open is a forcing function**: keep finding real work; if you genuinely can't, hold fewer
  and say so — never pad.
- Stale premise ≠ done: rewrite as verify-and-close (the verification IS the remaining work);
  never silently complete. Refinement's chief value is invalidating stale work (60/92 flagged in
  the 2026-07-12 full-board pass).

## Board invariants (audit these — recipes in [playbook.md](playbook.md))

open ⇒ theme+impact+effort labels · `ready` ⇒ DoR sections present · `do-next` ≤ 10 · dependencies
as `precedes`/`blocked` relations · every completion has an evidence comment · "Found N" from
`tasks_list` matches expected board size (pagination gotcha below).

## Dark-factory protocol contracts (wiring = board tickets 107/109; the contract lives here)

- **Linking**: commits touching a ticket carry a `VIK-<taskID>` trailer; PR bodies reference it;
  bare Vikunja task URLs autolink in Forgejo.
- **Completion**: HTML comment with commit/PR links → `task_complete`. Never claim done without
  the ticket's own Verification evidence.
- **Claim** (agents): add `agent/claude` label + comment with session id + move to
  "In progress (agent)"; progress comments at milestones; on done → completion comment + "Review"
  bucket (human merges/accepts). One ticket per agent run; skip if a claim comment exists.

## Gotchas (details → [reference.md](reference.md))

- `tasks_list`/`search` return ONE server page (cap raised to 250; `limit: 0` falls back to 50;
  search only matches in-window) — always check the reported "Found N".
- Tools return **formatted text, not JSON**: creates emit `ID: <n>`; list entries end
  `[ID: <n>, Project: <m>]`; `labels_list` appends hex colors to titles.
- Deletes are soft (server safe mode; Vikunja has no trash): `project_delete`→archive,
  `task_delete`→complete, `label_delete`→blocked.
- `labels_bulk_set_on_task` REPLACES the whole label set — include everything you want kept.
- 401 = API token expired/rotated (human-seeded; agent can't write OpenBao) → rotation in
  [reference.md](reference.md).
