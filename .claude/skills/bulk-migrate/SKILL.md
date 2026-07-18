---
name: bulk-migrate
description: Orchestrate a bulk mechanical transformation across many files — query-language migrations, API/datasource swaps, mass rewrites — via a validated spec, parallel no-commit agents on disjoint filesets, and central verification before batched commits.
when_to_use: Use when rewriting/translating/migrating many files at once (dashboards, queries, configs, workflows), swapping one language/API/endpoint for another repo-wide, or fanning out agents for a mass change that must not regress silently. NOT for single-file edits or changes without a repeated pattern.
---

# Bulk migrate — spec → fan-out → verify centrally

Proven on the 14-dashboard LogQL→LogsQL migration (2026-07-10: 66 targets, zero regressions;
ADR-0041). The failure mode this prevents: plausible-looking translations that parse but silently
return nothing.

## Procedure

1. **Hand-validate the 2–3 hardest patterns first** against the live target system (API/CLI), before
   writing any spec. What you learn (real field names, escaping rules, semantic mismatches) rewrites
   the spec; skipping this poisons every agent downstream.
2. **Prove the verifier can fail — and can pass.** Feed it a known-bad input and confirm it rejects
   (e.g. LogsQL parse errors return HTTP 400), then a known-**good** input and confirm it accepts.
   A verifier that crashes rejects *everything*, which is indistinguishable from a strict one when
   you only test the bad case (and a crash exits non-zero, so the failure test still "passes").
3. **Write one spec file** (scratchpad) containing: exact transformation rules as a table, the
   mandatory per-item live-verification command(s), what counts as acceptable-empty vs must-have-data,
   and a file-integrity check. Agents follow the spec, not their priors.
4. **Fan out parallel agents on disjoint filesets** (no shared files ⇒ no conflicts). Instruct each:
   edit raw text with Edit (**never round-trip YAML/JSON through a parser-dumper** — it reformats the
   whole file and buries the diff), verify every transformed item live, report old→new pairs +
   verification result per item, and **do not commit**.
5. **Re-verify centrally**: rerun the integrity check + repo validation (`./scripts/run-flux-local-test.sh`
   here) yourself over all touched files, sweep for leftovers (`grep -rn '<old-pattern>'`), then commit
   in reviewable batches with explicit pathspecs.
6. **Close the loop end-to-end**: confirm the deployed system serves the new content (not just that
   files changed) — e.g. read a rewritten query back from the live API.

## Signals & gotchas

- Two agents independently reporting the same surprising discovery = strong correctness signal;
  one agent's unique "discovery" that contradicts the spec = verify yourself before accepting.
- **A one-pass `sed` is safe or catastrophic depending on a check that costs one command.** Before a
  blanket rename, enumerate every context the old string appears in (`grep -rn '<old>' --exclude-dir=.git . | head -60`)
  and confirm the naive replacement is right in *each* — often the prefixed forms (`org/<old>`,
  `@scope/<old>`, `~/.cfg/<old>`, `<pkg>@<old>`) all resolve correctly, which is exactly what makes
  one pass safe. **Exclude append-only history**: CHANGELOGs, ADR history entries, dated comments and
  incident notes record what was true *then*; rewriting them to the new name falsifies the record.
  Update live pointers, leave the record (2026-07-18 repo rename: 57 live refs rewritten, 3 dated
  entries deliberately left naming the old repo).
- Acceptable-empty results need a documented upstream reason (feature not deployed, no traffic since
  cutover) — otherwise treat empty as a failed translation.
- Agents inherit spec errors silently: when one finds a spec rule wrong, fix the spec file before
  the next fan-out, not just that agent's output.
- Integrity check for GrafanaDashboard-style embedded JSON:
  `python3 -c "import yaml,json,sys; d=[x for x in yaml.safe_load_all(open(sys.argv[1])) if x][0]; json.loads(d['spec']['json'])" <file>`
