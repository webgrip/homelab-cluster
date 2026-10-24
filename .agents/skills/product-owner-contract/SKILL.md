---
name: product-owner-contract
description: Webgrip's board contract for the product-owner skill - the default team's Vikunja stage ladder with pull criteria per stage, label dimensions (theme, repo, kind, value, impact, estimation), epics, pick-up queue, and the ratified Definition of Ready, ticket template, golden tickets and Definition of Done, plus the per-repo overlay hook. Use when working a webgrip Vikunja board alongside product-owner - making, refining, grooming, gating, splitting or closing a VIK ticket, "make a ticket for X" in a webgrip repo, asking which labels or stages a webgrip ticket needs, or deciding what a repo's own ticket rules add on top of the team default.
---

# Webgrip board contract

Facts only; the craft is the `product-owner` skill. Load it first — this skill is its
contract layer for webgrip and never replaces a step of its procedure.

## Context

```text
Context: webgrip
Applies when: the `vikunja` MCP is in play, a repo remote points at the webgrip Forgejo,
  a ticket id looks like VIK-<id>, or the user says "webgrip"
```

## Teams

| Team | When | Contract |
|---|---|---|
| **default** | every webgrip Vikunja project, unless an overlay names another team | [teams/default/board.md](teams/default/board.md) |

A new team gets `teams/<team>/board.md` (+ `assets/` only where its hand-over docs differ)
and a row here. A team file carries its deltas over `default`, never a copy of it.

## Resolve in this order — most specific wins

1. **Repo overlay** — `.agents/product-owner/` in the consuming repo, when present:
   - `board.md` opens with `Extends: webgrip/<team>` (no line → `default`) and carries
     **only additions and overrides**: extra pull criteria, extra ticket kinds, protected
     paths, the project id, fixture projects, a different WIP cap.
   - `assets/` may add files next to the team's: an extra DoR line set, a template variant
     for the repo's own ticket kind, extra golden tickets. A file with the same name as a
     team asset **replaces** it for that repo; say so when you use it.
   - Anything the overlay does not mention falls through to the team.
2. **Repo contract** — `.agents/contracts/product-owner.md` or the `Board contract` block in
   the repo's `AGENTS.md`: ids and small facts. Where it disagrees with the overlay, the
   overlay wins; flag the disagreement once.
3. **Team** — `teams/<team>/board.md` and its `assets/`.
4. **The product-owner skill's portable defaults** for anything left.

State the resolved layers in one line before the first write ("default team + overlay
`.agents/product-owner/` + AGENTS.md block"), so a wrong layer is caught before it costs a
ticket.

## The repo overlay, as a repo maker writes it

```markdown
Extends: webgrip/default

## Additions
- Project: `<name>` (id <N>)
- Extra kind: `kind/migration` — needs a Rollback section and a dry-run Verification
- Protected paths for agents: `deploy/`, `.forgejo/`
- Into `ready`: a linked ADR for any change under `docs/adr/`
```

Keep it to what differs. A rule that would hold for every webgrip repo belongs in the team
file instead — propose it there.

## Gates

- Ready: `python3 <product-owner>/scripts/ticket_lint.py body.md --gate ready --title "…"`,
  then the label half against the team's pull-criteria table.
- The overlay's extra criteria are checked by hand and reported as MANUAL lines.
- Golden tickets are the regression set: `test.sh` holds every team's examples to the ready
  gate.
