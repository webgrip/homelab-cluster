---
name: vikunja-refiner
description: Refine Homelab Roadmap tickets in Vikunja to a Definition of Ready — researched problem statement, checkbox acceptance criteria verifiable against real state, file-level approach, live verification step — written as HTML descriptions via the vikunja MCP.
when_to_use: Use when asked to refine/groom/flesh out Vikunja tickets, make board items actionable, apply the definition of ready, prep the next work batch, split an oversized ticket, or when a ticket is too vague to start. NOT for board↔roadmap sync or MCP transport (vikunja skill).
---

# Vikunja refiner — raw items → Definition of Ready

## Definition of Ready (all seven, or the ticket is not `ready`)

1. **Problem** — what is wrong/missing *today*, with evidence: `file:line`, live symptom, or ADR/RFC path. No evidence found = say so in the ticket, don't invent.
2. **Outcome** — the end-state in one sentence.
3. **Acceptance criteria** — 2–6 checkboxes, each independently verifiable against real state (a `kubectl`/MCP read, a passing drill, a rendered manifest). "Improve/harden X" is not a criterion.
4. **Approach** — 3–7 steps naming actual repo paths and which skills apply (`add-app`, `network-policy`, `external-secrets`, …).
5. **Verification** — the exact command/check that proves it live (CLAUDE.md: real state, not a proxy).
6. **Gates & links** — blocking tickets (by exact title), roadmap sequencing notes, ADR/RFC/runbook paths.
7. **Sized** — honest effort S/M; an L ticket must name its first shippable slice (or be split: new tasks + `relation_create` kind `subtask`).

## Rules

- **Never rename a ticket.** Title is the roadmap↔board match key (vikunja skill). Better title = edit roadmap.md first, sync, then refine.
- **Descriptions are HTML** (TipTap editor — raw markdown renders literally). Section template + checkbox markup + a worked example → [reference.md](reference.md). Keep paragraph 1 = theme + `[P · I · E]` tag (the import contract).
- **Research before writing.** Fan out `Explore` agents over the repo (manifests, ADRs, RFCs, runbooks, sequencing notes) and check live state via the read-only MCPs; every Problem/criterion cites what they found. Respect recorded deferrals — an item deferred by an ADR/sequencing note gets that gate stated, not "fixed" away.
- **Labels:** refined = add `ready`, remove `needs-refinement` — via `label_add_to_task`/`label_remove_from_task` (`labels_bulk_set_on_task` REPLACES the whole set; only use it with the full list).
- Sanity-check `priority` and the `impact/·` `effort/·` labels against what research showed; correct drift in Vikunja AND flag it for roadmap.md (don't silently diverge).

## Procedure

1. **Batch** — user-named tickets; else `do-next` label; else highest-priority `needs-refinement`. 5–10 per run — refinement is research-bound, don't skim 50.
2. Research (rule above), then write the description per [reference.md](reference.md) via `task_update`.
3. Swap labels; split/slice if rule 7 tripped.
4. Report per ticket: one-line what-changed + any evidence gap left open (a ticket can be refined and still honest about unknowns).
