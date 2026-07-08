---
name: harvest-knowledge
description: Three-phase workflow to mine durable, reusable knowledge from Claude conversations and fold it into repo docs, CLAUDE.md, skills, and memory — distill one thread into a structured digest, consolidate many digests into one deduped truth-checked knowledge set, then synthesize docs + new-skill candidates.
when_to_use: Use when distilling/harvesting durable learnings from a Claude thread, extracting a thread digest, consolidating multiple digests into one knowledge set, running the integration thread, or turning collected learnings into docs/skills/memory.
---

# Harvest Knowledge — distill Claude threads into docs + skills

Mine durable learnings out of Claude conversations and fold them into this repo. Three phases, each
**run in a different context**. Pick by where you are and what you have, open the matching prompt file,
and adopt it **VERBATIM** as your task — the prompts are tuned and their output format is load-bearing
(uniform digests are what let Phase 2 consolidate cleanly).

| Phase | Run it in | Input | Produces | Prompt (use verbatim) |
|---|---|---|---|---|
| **1 · Distill** | the working thread you want to mine (at its end) | the whole current conversation | one self-contained thread digest | [prompt-1-distill.md](prompt-1-distill.md) |
| **2 · Consolidate** | a fresh "integration" thread | every Phase-1 digest, pasted together | one deduped, truth-checked knowledge set | [prompt-2-consolidate.md](prompt-2-consolidate.md) |
| **3 · Synthesize** | this repo (write access) | the Phase-2 knowledge set | doc / CLAUDE.md / skill / memory updates + new-skill candidates | [prompt-3-synthesize.md](prompt-3-synthesize.md) |

The Phase-1 digest is the unit that flows downstream: collect digests from many threads → paste into
Phase 2 → feed Phase 2's knowledge set into Phase 3.

## Run a phase
1. Identify the phase from the table.
2. `Read` the matching prompt file and **execute it exactly as written** — do not paraphrase, trim,
   reorder, or "improve" it. If a prompt genuinely needs changing, edit the prompt file, not the run.
3. Honor the phase contract:
   - **1** audits THIS conversation; the digest must stand alone (the integrator can't see this thread).
   - **2** operates ONLY on the pasted digests and **modifies no files** — output only.
   - **3** inventories existing docs/skills FIRST, then shows the item→action PLAN table and **waits for
     approval before writing**.

## Where Phase 3 lands things (this repo)
Docs → `docs/techdocs/docs/` (+ `runbooks/`, `adr/`) · always-on rules → `CLAUDE.md` · repeatable
procedure or behavior-changing gotcha → a new skill under `.claude/skills/<name>/` (use the `skillsmith`
skill, installed as a plugin) · preferences / incident state → memory (`MEMORY.md` index) · open items → a TODO list, not docs.

New skills here: adopt `when_to_use`, sibling `reference.md`/`scripts/`, and `allowed-tools` for
read-only diagnostics (`kubectl get`/`talosctl health`); skip `paths:` (skills trigger on intent, not
file edits), `context: fork` (inline guides), bang-backtick injection (how-to skills, not state
dashboards), and `disable-model-invocation`/`user-invocable`.

## Gotchas
- **Verbatim is the whole point.** The three prompts are the deliverable; reproduce them unchanged.
- **Phase 2 is read-only** — "Output only — modify no files." Don't let it touch the repo.
- **Phase 3 never writes before the PLAN is approved.** LOW-confidence / "needs verification" items are
  proposals — verify against the repo or leave them out (deferred); never enshrine guesses.
- **Don't collapse the phases into one pass.** They run in separate contexts on purpose (Phase 1 sees a
  thread; Phase 2 sees only digests; Phase 3 writes the repo). Skipping the digest step loses the
  self-contained, uniform structure consolidation depends on.
