# The Vikunja board is the roadmap system of record; roadmap.md is retired

* Status: accepted
* Date: 2026-07-12

Technical Story: follows [ADR-0040](adr-0040-vikunja-task-management.md) (Vikunja adopted) and the
2026-07-12 board bootstrap: all 101 open roadmap items imported to the Vikunja **Homelab Roadmap**
project via the `vikunja` MCP, then refined to a Definition of Ready (evidence-cited problem,
checkbox acceptance criteria, approach, live verification — the `vikunja-refiner` skill) by a
fan-out of research agents.

## Context and Problem Statement

The roadmap lived in `docs/techdocs/docs/general/roadmap.md`: a flat, git-owned file of ~100
`title — [P · I · E]` lines maintained by the `roadmap-topup` skill. After the board bootstrap the
same content existed twice, and the two copies diverged on day one: the refinement pass surfaced
~15 stale counts/claims in the file and ~8 items whose work had already shipped. A flat file also
cannot carry what agent-driven execution needs — per-item acceptance criteria, labels, assignment,
comments, relations, webhooks. Which copy is the system of record?

## Considered Options

* The Vikunja board becomes the system of record; delete `roadmap.md`
* Keep `roadmap.md` as the system of record; the board is a generated mirror (the bootstrap's
  original contract)
* Keep both, bidirectionally synced by title

## Decision Outcome

Chosen option: "The Vikunja board becomes the system of record; delete `roadmap.md`", because the
mirror contract was already broken on day one (the refinement pass found ~15 stale claims in the
file and ~8 already-shipped items), a flat file cannot carry assignment/comments/webhooks that
agent execution needs, and a title-keyed bidirectional sync is standing drift-reconciliation work
with no consumer — nothing reads the file that couldn't read the board.

`roadmap.md` is deleted; its full history, including the Done log, remains in git history.

* Ticket lifecycle lives on the board: `needs-refinement` → `ready` (Definition of Ready, the
  `vikunja-refiner` skill) → done (`task_complete`). Priority P0–P3 maps to Vikunja priority
  5–2; `theme/*`, `impact/*`, `effort/*`, `do-next` labels carry the old tag taxonomy.
* The `roadmap-topup` skill now reconciles the **board** (complete shipped work, add new findings
  as `needs-refinement` tickets, keep ~100 open) instead of rewriting a file.
* Agents discover the roadmap through the `vikunja` MCP (see `AGENTS.md` and the `vikunja` skill);
  ticket titles are no longer a sync key and may be edited on the board.
* Durability: the board is CNPG `vikunja-db` (Tier 2, barman backups to Garage) — the DR story
  replaces "it's in git". Strategy-shaped decisions still get ADRs/RFCs in git; the board holds
  work items, not decisions.

### Consequences

* Good: one source of truth; items carry DoR, labels, priorities, comments, and (next) assignment
  and Forgejo links; webhooks make the backlog automatable.
* Trade-off (accepted): roadmap changes no longer pass git review. Task state is operational data
  — the same standing as Forgejo issues in ADR-0040's division of labour, which this ADR amends:
  strategy *items* now live on the board too; only decision *records* (ADR/RFC) stay in git.
* The board becomes availability-sensitive: if Vikunja is down, the backlog is unreadable (mitigated
  by Tier 2 backups + the restore-test component; acceptable for a homelab).

## Links

* Amends [ADR-0040](adr-0040-vikunja-task-management.md) (division-of-labour clause: "the
  git-owned roadmap stays" is superseded)
* Supersedes the roadmap.md contract in [RFC: task management](../rfc/rfc-task-management.md) §"Division of labour"
* 2026-07-12 — accepted; roadmap.md deleted, skills (`roadmap-topup`, `vikunja`,
  `vikunja-refiner`) repointed at the board, `AGENTS.md` added
* 2026-07-12 — the three skills consolidated into `vikunja-product-owner`
* 2026-07-12 — the skill moved to the `webgrip-ai-skills` marketplace (generic, board-contract
  driven); homelab instance ops → `runbooks/mcp-vikunja.md`
