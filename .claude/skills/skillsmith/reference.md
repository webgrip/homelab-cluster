# Skillsmith reference — full frontmatter catalog, substitutions, advanced levers

Contents: [Frontmatter fields](#frontmatter-fields) · [Command name & discovery](#command-name--discovery)
· [String substitutions](#string-substitutions) · [Advanced levers + when each fits](#advanced-levers--when-each-fits)
· [Adopt/skip for this repo](#adoptskip-for-this-repos-skills) · [Measure trigger accuracy & cost](#measure-trigger-accuracy--cost)

## Frontmatter fields

All optional; only `description` is recommended. Accepts space-separated string OR YAML list where noted.

| Field | Type | Meaning / notes |
|---|---|---|
| `name` | string | Display label in listings. Defaults to dir name. Does **not** set the `/command` (dir name does), except a plugin-root `SKILL.md`. |
| `description` | string | What it does + when to use. Used for discovery. Falls back to first body paragraph. Combined with `when_to_use`, capped **1,536 chars** in the listing (`maxSkillDescriptionChars`). |
| `when_to_use` | string | Extra trigger phrases / example requests. Appended to `description`; counts toward the 1,536 cap. |
| `argument-hint` | string | Autocomplete hint, e.g. `[issue-number]`. UI only. |
| `arguments` | string\|list | Named positional args for `$name` substitution; map to positions in order. |
| `disable-model-invocation` | bool | `true` → only the user can invoke; removes description from Claude's context; also blocks subagent preload. Default `false`. |
| `user-invocable` | bool | `false` → hide from `/` menu (Claude-only background knowledge). Default `true`. Does NOT block Skill-tool access — use `disable-model-invocation` for that. |
| `allowed-tools` | string\|list | Pre-approve tools while active (no per-use prompt). **Additive, not restrictive.** Project skills need workspace-trust accepted. E.g. `Bash(git add *) Read`. |
| `disallowed-tools` | string\|list | Remove tools from the pool while active; clears on next user message. |
| `model` | string | Model while active (same values as `/model`, or `inherit`). Resets next prompt. |
| `effort` | enum | `low\|medium\|high\|xhigh\|max` while active. |
| `context` | `fork` | Run skill in a forked subagent; skill body becomes the subagent prompt. |
| `agent` | string | Subagent type when `context: fork` (`Explore`/`Plan`/`general-purpose`/custom). |
| `hooks` | map | Hooks scoped to the skill lifecycle (same format as settings hooks). |
| `paths` | string\|list | Globs that **limit auto-activation to matching file edits** (path-specific-rules format). |
| `shell` | enum | `bash` (default) / `powershell` for `` !`cmd` `` blocks. |

## Command name & discovery

- `/command` = **directory name** (`.claude/skills/deploy-staging/` → `/deploy-staging`).
- Precedence: enterprise > personal (`~/.claude/skills/`) > project (`.claude/skills/`); any overrides a
  bundled skill of the same name. Plugin skills are namespaced `plugin:skill` (no clash).
- Nested `.claude/skills/` below cwd load on demand; on name clash the nested one becomes `path:name`.
- **Live change detection:** edits to an existing `SKILL.md` apply within the session. A *new* top-level
  skills dir needs a restart. (Project-skill `allowed-tools`/plugin bits need trust / `/reload-plugins`.)

## String substitutions

Expanded before Claude sees the body (preprocessing):

| Variable | Expands to |
|---|---|
| `$ARGUMENTS` | full arg string as typed (if absent in body, appended as `ARGUMENTS: <value>`) |
| `$ARGUMENTS[N]` / `$N` | 0-based positional arg (`$0` first). Shell-quote multi-word args. |
| `$name` | named arg declared in `arguments:` |
| `${CLAUDE_SESSION_ID}` | current session id (logging, session files) |
| `${CLAUDE_EFFORT}` | `low…max` (ultracode reports `xhigh`) |
| `${CLAUDE_SKILL_DIR}` | the skill's own dir — use to call bundled `scripts/` regardless of cwd |

Escape a literal `$` before a digit/`ARGUMENTS`/declared name with one backslash: `\$1.00`.

## Advanced levers + when each fits

- **`paths:`** — auto-activate only when editing matching files. Fits a skill tied to a file type/tree
  (e.g. a linter for `*.tsx`). **Limits** triggering — wrong for skills that must fire on conversational
  intent with no file open.
- **`context: fork` + `agent:`** — run the skill as an isolated subagent; body is the prompt, no
  conversation history. Fits a self-contained task (research, a one-shot generator). Wrong for inline
  reference/guidance, or a skill that must write back into the main conversation.
- **Dynamic injection `` !`cmd` ``** (or fenced ` ```! `) — runs a shell command at invocation and
  inlines its output before Claude reads the body. Fits state-grounded skills (summarize *this* diff,
  show *current* cluster state). Cost: runs every invocation + adds the output's tokens. Wrong for
  how-to skills that only sometimes need the state. Disable globally via `disableSkillShellExecution`.
- **`disable-model-invocation` / `user-invocable`** — invocation control for side-effecting `/commands`
  or pure background knowledge. Most procedure skills want neither (let Claude auto-load).

## Adopt/skip for this repo's skills

This repo's skills are **intent-triggered procedure/reference** guides for a GitOps homelab. Decisions:

| Feature | Decision | Reason |
|---|---|---|
| Supporting files (`reference.md`, `scripts/`) | **ADOPT** | Progressive disclosure; the core token win. |
| `allowed-tools` (read-only diagnostics) | **ADOPT** | Cut prompts on safe `kubectl get`/`talosctl health`. |
| `when_to_use` | **ADOPT** | Separate triggers from "what it does"; tighter routing. |
| `paths:` | **SKIP** | Must trigger on intent ("upgrade k8s", "DB down"), not only file edits. |
| `context: fork`/`agent` | **SKIP** | Inline guides; `roadmap-topup` fans out its own Explore agents and writes back in main context. |
| `` !`cmd` `` injection | **SKIP** | How-to skills, not state dashboards. (Right tool for a future `cluster-status` skill.) |
| `disable-model-invocation`/`user-invocable` | **SKIP** | No dangerous auto-trigger; all benefit from auto-load. |

## Measure trigger accuracy & cost

- **`skill-creator` plugin** (`/plugin install skill-creator@claude-plugins-official`) — writes
  `evals/evals.json`, runs each prompt in an isolated subagent **with vs without** the skill, grades
  assertions, and reports pass-rate + token/time overhead + a blind A/B between two versions. Use it to
  prove an edit is an improvement and to tune a description that mis-triggers.
- **`/doctor`** — shows how many skill descriptions are being shortened/dropped from the listing budget,
  and which. Run after adding/editing skills to confirm none you rely on got squeezed out.
- Budget knobs: `skillListingBudgetFraction` (default 1% of context window), `maxSkillDescriptionChars`
  (1,536), `SLASH_COMMAND_TOOL_CHAR_BUDGET`; demote low-priority skills to `"name-only"` via
  `skillOverrides` to free budget.

Source of truth: <https://code.claude.com/docs/en/skills>. Re-verify here before changing the SKILL.md guide.
