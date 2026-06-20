---
name: skillsmith
description: Author, edit, or audit Claude Code skills (.claude/skills/<name>/SKILL.md) for token-efficient, high-trigger-accuracy LLM consumption. Use when creating a new skill, refactoring an existing one, writing a frontmatter description, cutting a skill's token weight, or deciding what belongs in a skill vs CLAUDE.md vs memory vs a runbook.
---

# Skillsmith — write skills for the model, not the reader

A skill is a procedure injected into another model's context. Optimize for *its* ingestion, not human reading. Every rule below derives from the cost model.

## Cost model (the only thing to internalize)
Three tiers, by when tokens are paid:
- **`description`** (frontmatter) — loaded into **every** session for **every** skill, **always**. Most expensive real estate in the repo. Spend it only on triggering.
- **SKILL.md body** — loaded **only when the skill fires**. Mid-cost. Holds the operating procedure.
- **Sibling files** (`reference.md`, templates, scripts) — loaded **only when the body tells the model to open them**. Cheapest, because conditional.

→ Maximize the description's trigger accuracy; shrink the body to "what's needed to act"; push bulk/rare detail to siblings. Token weight ≈ words; cut accordingly.

## The `description` is a router, not a summary
Its one job: load this skill **exactly when relevant, never otherwise**.
- Shape: `<verb the task>… Use when <trigger phrases the user would actually say or imply>`.
- Pack the **trigger surface**: synonyms, the tool/CRD/file names involved, the symptoms. Those are the tokens the matcher sees — a word not present can't match.
- Start with a verb, third-person present. **Never** "this skill", "helps you", "designed to" — pure overhead, paid every session.

## Body rules
- **Decision first, procedure second.** Models act top-down; lead with the branch ("if X do Y"), not background.
- **Imperative, present tense, articles dropped** where unambiguous. No intro/overview/summary/motivation, no restating the H1.
- **Concrete beats abstract.** Exact paths, field names, commands, `file:line`. A path the model can open out-earns a paragraph describing it.
- **One real in-repo example by path** beats an inlined synthetic template (which rots and costs tokens). Link it; don't paste it.
- **Anchors for skimming:** bold the scan keywords, tables for name→value lookups, bullets over prose.
- **Guardrails as `Never`/gotchas.** Negative space (the expensive mistake, the failure loop) is the highest-ROI content in a skill — it's what the model can't infer.
- **Don't duplicate** CLAUDE.md, the codebase, or git history — link instead (cheaper, rots slower). Use `[[memory-slug]]` for mutable state/history.
- Give the **exact validate + commit commands** so runs are deterministic, not improvised.

## What does NOT go in a skill
- Always-on project rules → `CLAUDE.md`.
- Mutable state, incident history, "current status" → memory `[[slug]]`.
- Long-form human reference → `docs/…/runbooks/`.
- A one-off fact, or anything derivable from the repo → nowhere; omit it.
- Generic knowledge a competent model already has → omit. Skills carry only what's *specific* and *non-obvious*.

## Create
1. `.claude/skills/<name>/SKILL.md`. `name` kebab-case, == dir, reads as a command (`/<name>`).
2. Frontmatter: `name` + `description` (this repo uses only these two).
3. Body: decision → procedure → gotchas; point at one real example.
4. Heavy/rare detail → sibling file, referenced by relative path (loads on demand).
5. No registration — Claude Code auto-discovers `.claude/skills/*/SKILL.md`.

## Edit / audit
- **Trigger to update:** a gotcha cost a failure loop, a recommended pattern proved wrong, paths drifted. Bake the **root cause** as a `Never`/gotcha at the relevant step (model: the folderRef fix in `grafana-dashboard`). Date incident-derived rules.
- **Token diet pass:** delete human-only prose, generic LLM knowledge, duplication of CLAUDE.md/codebase, stale paths. Tighten the description's trigger surface. Confirm cited examples still exist (`test -e <path>`).

## Skeleton
```markdown
---
name: <kebab-name>
description: <verb the task>… Use when <trigger phrases + tool/file names + symptoms>.
---

# <Name> — <one-line what/for-whom>

## <Decision or cost model that drives everything>
...

## <Do the thing>
1. ...

## Gotchas
- **Never** ...
```

## Smells → cut on sight
- `## Overview` / `## Introduction` / "This skill helps you…"
- Inlined templates duplicating a real file.
- A paragraph of *why* where one clause suffices.
- A description that summarizes instead of triggering.
- Walls of prose where a table or bullets parse faster.
- Density exemplars in-repo: `external-secrets`, `workload-placement`, `longhorn`. This file obeys its own rules.
