---
name: adr-writer
description: Write, amend, or supersede an Architecture Decision Record in MADR 4.0.0 — numbering, frontmatter status/date semantics, Confirmation section, dated history in More Information, index + nav registration.
when_to_use: Use when creating a new ADR, recording or ratifying a decision, updating an ADR's status after a rollout/revert/supersession, or fixing ADR structure. NOT for design exploration (that's an RFC) or operational procedure (runbook).
---

# ADR writer — MADR 4.0.0, house conventions

Format = faithful [MADR 4.0.0](https://adr.github.io/madr/). Template:
`docs/techdocs/docs/adr/adr-0000-template.md`. Gold-standard exemplar (structure + voice):
`docs/techdocs/docs/adr/adr-0017-adopt-harbor.md`. Status legend + conventions:
`docs/techdocs/docs/adr/index.md`. This file carries only THIS repo's wiring; the portable
generalization (bootstrap, templates, validator) ships as the `adr-writer` plugin in
webgrip-ai-skills — point other repos there.

## New ADR

1. Number = next free (`ls docs/techdocs/docs/adr/`). Filename `adr-NNNN-<kebab-title>.md`;
   H1 = bare title stating problem+solution (no `ADR-NNNN:` prefix).
2. Copy the template. Frontmatter: `status:` lowercase — proposed | accepted | rejected |
   deprecated | superseded by [ADR-NNNN](file); `date:` = **last-updated** date (MADR
   semantics, not creation). Omit decision-makers/consulted/informed (one-person lab).
3. `## Considered Options` must include the chosen option, listed first. `## Decision Outcome`
   opens `Chosen option: "…", because …` then the load-bearing specifics (component, config,
   `kubernetes/apps/<ns>/<app>/…` paths). `### Consequences` = `* Good/Bad, because …` bullets.
   `### Confirmation` = the concrete check proving the decision is implemented — a live
   kubectl/MCP read, flux-local test, dashboard/alert, Kyverno policy, CI job. Name the real
   check, not a proxy (house verify ethos); include it whenever the decision is checkable.
   Why-nots → `## Pros and Cons of the Options` (1–3 `Good/Neutral/Bad, because` bullets per
   option; omit the section when no real alternative was weighed).
4. `## More Information` (house-required): parent RFC first as `* Technical story: [RFC …](…)`,
   then dated history bullets `* YYYY-MM-DD — <event> (<commit>)` oldest first, plus cross-ADR
   relations (Supersedes / Refined by / Supported by).
5. Register: row in the index.md Records table (pick the matching **layer section** — the set
   was re-baselined 2026-07-03 into layer order, but a new ADR just takes the next free number)
   + `docs/techdocs/mkdocs.yml` nav (numeric slot). Verify: `./scripts/check-docs-links.sh`
   and `python3 scripts/validate_adr_consistency.py .` (status/date ↔ index drift, legal
   status, required sections — also runs in e2e CI).

## Amend / status change

Reality changed (revert, partial rollout, ratification)? Append a dated More Information bullet
citing the commit, update frontmatter `status:` + `date:`, mirror the index.md row. **The body
stays as decided** — never rewrite it to match new reality. A reversed decision gets a *new*
superseding ADR; the old one's status becomes `superseded by [ADR-NNNN](…)`.

Records dated before 2026-07-12 are MADR 2.1.2 (`* Status:`/`* Date:` bullets, Positive/Negative
Consequences, `## Links`) — amend those **in their own format**; don't retro-migrate. Sole
exception on record: ADR-0017, restructured 2026-07-12 to serve as the 4.0.0 exemplar.

## Gotchas

- MkDocs/TechDocs does NOT render frontmatter — `status`/`date` are invisible on the page.
  Reader-visible status = the index.md row + the dated More Information history; never skip
  those two mirrors.
- Frontmatter is YAML — quote `status:` whenever it contains a markdown link (`[`/`]`).
- Dates come from `git log --follow --oneline -- <file>` or the triggering commit — never from
  memory. No ratification commit exists? Log `status corrected in audit YYYY-MM-DD`; don't
  backdate acceptance.
- Table delimiter rows need spaced pipes (`| --- |`) — repo markdownlint MD060.
- Numbers are never reused; files never renamed (inbound links). Sole exception on record: the
  2026-07-03 layered re-baseline renumbered 0001–0039 once (old→new map in index.md; mkdocs
  redirects cover old URLs). Pre-re-baseline references (commits, PRs) use old numbers.
