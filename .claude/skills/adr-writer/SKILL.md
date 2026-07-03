---
name: adr-writer
description: Write, amend, or supersede an Architecture Decision Record in MADR 2.1.2 — numbering, Status/Date semantics, dated history in Links, index + nav registration.
when_to_use: Use when creating a new ADR, recording or ratifying a decision, updating an ADR's status after a rollout/revert/supersession, or fixing ADR structure. NOT for design exploration (that's an RFC) or operational procedure (runbook).
---

# ADR writer — MADR 2.1.2, house conventions

Format = faithful [MADR 2.1.2](https://adr.github.io/madr/). Template:
`docs/techdocs/docs/adr/adr-0000-template.md`. Gold-standard example:
`docs/techdocs/docs/adr/adr-0017-adopt-harbor.md`. Status legend + conventions:
`docs/techdocs/docs/adr/index.md`.

## New ADR

1. Number = next free (`ls docs/techdocs/docs/adr/`). Filename `adr-NNNN-<kebab-title>.md`;
   H1 = bare title stating problem+solution (no `ADR-NNNN:` prefix).
2. Copy the template. `* Status:` lowercase — proposed | accepted | rejected | deprecated |
   superseded by [ADR-NNNN](file). `* Date:` = **last-updated** date (MADR semantics, not
   creation). Omit `Deciders` (one-person lab). Parent RFC → `Technical Story:` line.
3. `## Considered Options` must include the chosen option, listed first. `## Decision Outcome`
   opens `Chosen option: "…", because …` then the load-bearing specifics (component, config,
   `kubernetes/apps/<ns>/<app>/…` paths). Consequences → `### Positive/Negative Consequences`.
   Why-nots → `## Pros and Cons of the Options` (1–3 `Good/Bad, because` bullets per option;
   omit the section when no real alternative was weighed).
4. History → `## Links`: dated bullets `* YYYY-MM-DD — <event> (<commit>)`, oldest first;
   cross-ADR relations (Supersedes / Refined by / Supported by) live here too.
5. Register: row in the index.md Records table (pick the matching **layer section** — the set
   was re-baselined 2026-07-03 into layer order, but a new ADR just takes the next free number)
   + `docs/techdocs/mkdocs.yml` nav (numeric slot). Verify: `./scripts/check-docs-links.sh`.

## Amend / status change

Reality changed (revert, partial rollout, ratification)? Append a dated Links bullet citing the
commit, update `* Status:` + `* Date:`, mirror the index.md row. **The body stays as decided** —
never rewrite it to match new reality. A reversed decision gets a *new* superseding ADR; the old
one's Status becomes `superseded by [ADR-NNNN](…)`.

## Gotchas

- Dates come from `git log --follow --oneline -- <file>` or the triggering commit — never from
  memory. No ratification commit exists? Log `status corrected in audit YYYY-MM-DD`; don't
  backdate acceptance.
- Table delimiter rows need spaced pipes (`| --- |`) — repo markdownlint MD060.
- Numbers are never reused; files never renamed (inbound links). Sole exception on record: the
  2026-07-03 layered re-baseline renumbered 0001–0039 once (old→new map in index.md; mkdocs
  redirects cover old URLs). Pre-re-baseline references (commits, PRs) use old numbers.
