---
name: skillsmith
description: Author, edit, and audit Claude Code skills (.claude/skills/<name>/SKILL.md) for token-efficient, high-trigger-accuracy LLM ingestion. The house standard for this repo's skills.
when_to_use: Use when creating a new skill, refactoring/auditing an existing one, writing or tuning a frontmatter description, cutting a skill's token weight, splitting a skill into supporting files, or deciding what belongs in a skill vs CLAUDE.md vs memory vs a runbook.
---

# Skillsmith — write skills for the model, not the reader

A skill is a procedure injected into another model's context. Optimize for *its* ingestion. Every
rule here derives from the **verified loading/token model** (sources at bottom) — not folklore.

## Cost model (internalize this; everything follows)

Three tiers, by when tokens are paid:

- **Skill names** — always in context, every session. Negligible.
- **`description` (+`when_to_use`)** — loaded for discovery, but they **share a budget ≈ 1% of the
  context window**. Per-entry cap **1,536 chars**. Over budget, the **least-used** skills'
  descriptions are shortened/dropped first. → A bloated description steals budget from *every* skill.
  `/doctor` shows what's being dropped.
- **SKILL.md body** — loads when the skill fires and **stays in context for the whole session**
  (not re-read per turn). After auto-compaction only the **first 5,000 tokens** of each skill survive
  (**25,000** combined, most-recent-first). → Every body line is a *recurring* cost.
- **Supporting files** (`reference.md`, `scripts/`) — cost **~0 until the model opens them**. Cheapest
  tier; push bulk/rare detail here.

→ Maximize description trigger-accuracy; keep the body to "what's needed to act"; defer everything else
to siblings. Official tip: **keep SKILL.md < 500 lines** (this repo's bar is much tighter — see split rule).

## The `description` is a router, not a summary

Its one job: load this skill **exactly when relevant, never otherwise**.
- `description` = *what it does* + the highest-signal nouns (tool/CRD/file names, the domain).
- `when_to_use` = *trigger phrases* the user would actually say + symptoms. (Same 1,536 cap — trim both.)
- Third person, present tense, verb-first. **Never** "this skill", "helps you", "designed to".
- A word absent from description/when_to_use can't match. A word that's pure filler costs the whole set.

## Body rules

- **Decision first, procedure second.** Lead with the branch ("if X do Y"); models act top-down.
- **Imperative, present tense, articles dropped** where unambiguous. No intro/overview/summary/motivation.
- **State what to do, not how or why** — one clause of *why* only when it changes the action.
- **Concrete beats abstract:** exact paths, field names, commands, `file:line`. A path the model can
  open out-earns a paragraph describing it.
- **One real in-repo example by path** beats an inlined synthetic template (which rots and costs tokens).
- **Anchors for skimming:** bold the scan keywords, tables for name→value lookups, bullets over prose.
- **Guardrails as `Never`/gotchas** — the expensive mistake the model can't infer is the highest-ROI line.
- **Don't duplicate** CLAUDE.md, the codebase, or git history — link to a **committed in-repo doc** (ADR/runbook/incident under `docs/`). **Never link `[[memory]]` from a committed skill** — memory lives in `~/.claude`, per-user/per-machine, so the link dangles on anyone else's clone. `[[memory]]` is portable only inside *personal* (`~/.claude`) skills + memory files.

## Single source of truth

No fact lives in two skills. Pick one **canonical home**; everywhere else is a one-line summary + "see
the X skill". Duplication multiplies token cost *and* drifts out of sync. When you catch the same rule
in two skills, that's a bug — consolidate.

## Progressive disclosure (supporting files)

Split when the body **exceeds ~60 lines** *or* carries **lookup tables / reference catalogs / link
lists** — anything needed only sometimes. Move it to a sibling and reference it:

```markdown
## Additional resources
- Deep query/panel/table detail → [reference.md](reference.md)
```

- **Keep references one level deep** (SKILL.md → reference.md, not → a → b). The model may `head -100`
  a nested file and miss the rest.
- For a reference file > 100 lines, put a short **table of contents** at top so a partial read sees scope.
- **Scripts** the model *runs* (output consumed, code never loaded) are the cheapest reference of all —
  ship a `scripts/foo.sh` and say "run it", with `allowed-tools` pre-approving the command.

## What does NOT go in a skill

- Always-on project rules → `CLAUDE.md`. Mutable state / incident history → the memory system (but a *committed* skill links the in-repo incident doc/runbook, never the `[[memory]]`).
- Long-form human reference → `docs/…/runbooks/`. One-off facts / anything derivable from the repo → omit.
- Generic knowledge a competent model already has → omit. Skills carry only the *specific* and *non-obvious*.

## Frontmatter — the fields worth knowing

`name` and `description` cover most skills. The high-value extras:

| Field | Use it for |
|---|---|
| `when_to_use` | Trigger phrases/symptoms, kept out of `description`. Adopt by default. |
| `allowed-tools` | **Additive** pre-approval of safe commands (cuts prompts). Needs workspace-trust for project skills. NOT a restriction. |
| `disable-model-invocation: true` | Manual-only `/cmd` with side effects (deploy/commit). Removes it from Claude's auto-context. |
| `user-invocable: false` | Background knowledge Claude should auto-load but isn't a user command. |

Full field catalog, string substitutions (`$ARGUMENTS`, `${CLAUDE_SKILL_DIR}`…), and the advanced
levers (`paths`, `context: fork`/`agent`, dynamic bang-backtick shell injection) with **when each fits**
→ [reference.md](reference.md). Note: command name comes from the **directory name**, not `name:`.

<!-- Don't write the literal bang-backtick token in THIS file: the loader executes that pattern at
     skill-load time, so a documentation example self-triggers ("command not found: cmd"). The syntax
     is shown safely in reference.md (a sibling — not scanned for injection). -->


## Create

1. `.claude/skills/<name>/SKILL.md`. `<name>` kebab-case, == dir, reads as `/<name>`.
2. Frontmatter: `description` (+ `when_to_use`); add others only with a reason from the table.
3. Body: decision → procedure → gotchas; point at one real example.
4. Heavy/rare detail → sibling file, referenced one level deep.
5. No registration — Claude Code auto-discovers `.claude/skills/*/SKILL.md` (live, no restart for edits).

## Edit / audit

- **Trigger to update:** a gotcha cost a failure loop, a recommended pattern proved wrong, paths drifted.
  Bake the **root cause** as a `Never`/gotcha at the relevant step. Date incident-derived rules.
- **Token-diet pass:** cut human-only prose, generic LLM knowledge, duplication (apply single-source),
  stale paths. Tighten description/when_to_use. Confirm cited examples still exist (`test -e`).
- **Measure, don't guess:** the `skill-creator` plugin runs with/without A/B on real prompts and reports
  trigger hit-rate + token/time overhead; `/doctor` flags dropped descriptions. (See reference.md.)

## Skeleton

```markdown
---
name: <kebab-name>
description: <verb> <what it does> + highest-signal nouns.
when_to_use: Use when <trigger phrases + symptoms>.
---

# <Name> — <one-line what/for-whom>

## <Decision or cost model that drives everything>
## <Do the thing>   (numbered steps)
## Gotchas          (**Never** …)
```

## Smells → cut on sight

- `## Overview` / `## Introduction` / "This skill helps you…"
- Inlined templates duplicating a real file; a fact restated in another skill.
- A paragraph of *why* where one clause suffices.
- A description that summarizes instead of triggering, or repeats the skill name.
- Walls of prose where a table or bullets parse faster.
- A lookup table or link list sitting in the always-on body instead of a sibling.

Density exemplars in-repo: `external-secrets`, `workload-placement`, `longhorn`. This skill obeys its
own rules (lean body; full catalog in reference.md).

## Sources

Official: <https://code.claude.com/docs/en/skills> · best practices
<https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices>. Verify mechanics
there before changing this guide — don't trust memory.
