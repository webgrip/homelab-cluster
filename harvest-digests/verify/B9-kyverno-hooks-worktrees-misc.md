## Kyverno / policy

### Enforce mechanics + the test-harness allowlist that hid untested enforced policies
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Policies set spec-level `validationFailureAction: Audit|Enforce`; rules can override with `failureAction: Audit` inside an Enforce policy (effective = rule's if set, else spec-level). No per-rule "action" knob beyond `failureAction`. Promotion levers: whole-policy flip, `validationFailureActionOverrides` (per-namespace), or split (clean rules → `-enforce.yaml`). Autogen duality: every Pod policy emits `<rule>` (Pod/background) AND `autogen-<rule>` (controller/admission) findings — a `PolicyException` must waive both. The CLI test harness (`scripts/lib/kyverno-tests.sh` `prepare_kyverno_test_workspace()`) hardcoded a policy allowlist that silently omitted 6 enforced-capable policies (`workload-hardening-audit`, `workload-advanced-hardening-audit`, `secrets-observability-ops-audit`, `image-hygiene-audit`, `image-verify-harbor-audit`, `storage-cnpg-governance`) — so those could be promoted to Enforce with zero CLI coverage and CI stayed green; replaced with discovery by kind over `policies/app/*.yaml`. New guard `scripts/check-kyverno-test-coverage.sh` fails if an enforcing ClusterPolicy lacks a `result: fail` CLI test.
- **Snippet:** `grep -rlZ -E '^kind: (ClusterPolicy|Policy|PolicyException|ClusterCleanupPolicy)$' "${policy_dir}"/*.yaml`
- **Sources:** batch 2 (copy 8)

---

## Safety hooks & agent constraints

### Safety hooks block kubectl/Longhorn/talosctl mutations (string-match — even `--help`/comments)
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] across batches)
- **What:** `.claude/hooks/guard-destructive.sh` blocks any `kubectl patch/delete/edit/apply/scale/uncordon` and Longhorn volume/replica/node mutations and destructive talosctl ops — regardless of in-chat user approval (even a one-off maintenance Job). The match is **string-based**: `talosctl upgrade --help` and even a read-only diagnostic merely *containing* "upgrade" in an echo comment got blocked. Read-only `kubectl get/describe/logs`, `exec wget`, `get --raw /readyz`, `talosctl get/read/version/etcd members` are fine. The agent must make changes in Git (GitOps) or hand the exact command to the human, and strip trigger words from benign diagnostics. (The auto-mode classifier also blocks extracting cluster secrets — plan live-verification via in-cluster jobs with their own mounted secrets + read-only reads + source inspection.)
- **Sources:** batches 4 (Talos upgrade digest), 2 (copy 8, copy 2), 1 (copy 11)

### Apply + live-verify a Flux change immediately; verify by real status, not a proxy artifact
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** After committing+pushing to `main`, Flux reconciles within ~minutes — confirm via the Kustomization status (`Applied revision: ...@sha1:<your-sha>`); to exercise a CronJob's script now, spawn a one-off job from it, read its logs, clean up. The `hc()` curl wrapper uses `curl -fsS` (non-zero on HTTP ≥400), so a logged success branch with no WARN is direct evidence of a 2xx. Verify by REAL status, not a proxy artifact: a published tag/Release object is NOT proof of a green CI run (publish creates them before a later-failing step), and "I updated the IaC" ≠ "the running resource changed."
- **Snippet:** `kubectl -n harbor create job --from=cronjob/harbor-proxy-config harbor-proxy-config-verify; kubectl -n harbor logs job/... | grep -iE 'robot|sbom|converged|WARN'; kubectl -n harbor delete job ...`
- **Sources:** batches 2 (copy 2, copy 14), 1 (copy 11)

---

## Git worktrees for parallel work

### Fresh git worktrees lack this repo's gitignored bootstrap files; `.worktreeinclude` copies them (Claude-created only)
- **Type:** GOTCHA + PROCEDURE · **Confidence:** HIGH (gap [VERIFIED]; `.worktreeinclude` [ASSERTED] — not yet exercised)
- **What:** A new worktree is a clean checkout of tracked files only, so it silently lacks the gitignored toolchain files and breaks SOPS/kubectl/talosctl/mise/validation the moment it touches secrets or the cluster: `age.key`, `kubeconfig`, `.mise.local.toml`, `.claude/settings.local.json`, `talos/talosconfig`, `talos/clusterconfig/` (per-node `kubernetes-*.yaml` + `talosconfig`). A root-level `.worktreeinclude` (`.gitignore` syntax) makes Claude Code COPY matching gitignored files into worktrees IT creates (`claude --worktree`, `EnterWorktree`, `isolation: worktree` subagents, desktop parallel sessions) — the native fix, safe to commit (filenames only). It copies (not symlinks), so rotated files (kubeconfig/tokens) can drift in long-lived worktrees; static key material (age key) is fine. It does NOT fire for hand-run `git worktree add`, third-party TUIs (Claude Squad), or the VSCode-extension "Open in New Tab" — those need a post-checkout git hook or a copy-env/copy-configs/git-worktreeinclude tool. The age key resolves per-worktree via `.mise.toml: SOPS_AGE_KEY_FILE = "{{config_root}}/age.key"`, which is exactly why a copied `age.key` at each worktree root works.
- **Snippet:** `git config --global core.hooksPath ~/.git-hooks` (universal post-checkout fallback)
- **Sources:** batch 5 (worktrees digest)

### Claude Code `--worktree` defaults; true parallel+isolated in VSCode = integrated-terminal `claude --worktree`
- **Type:** REFERENCE + PROCEDURE · **Confidence:** HIGH ([VERIFIED] from docs)
- **What:** `claude --worktree <name>` creates a worktree at `.claude/worktrees/<name>/` on branch `worktree-<name>` (auto-generated name if omitted), branching from `origin/HEAD` (matches remote `main` in a trunk-based repo — set `worktree.baseRef: "head"` to carry unpushed commits). `claude --worktree "#1234"` branches from a PR. Add `.claude/worktrees/` to `.gitignore`; `--worktree` ones are never auto-swept. The VSCode extension's "Open in New Tab/Window" gives parallel chats but SHARES one working directory (no isolation — the exact collision worktrees prevent). Real in-window parallel+isolated work = integrated terminal split panes each running `claude --worktree <name>`; or `EnterWorktree` relocates one session mid-conversation (no parallelism).
- **Sources:** batch 5 (worktrees digest)

### Worktrees solve working-dir collisions but NOT push-to-main collisions
- **Type:** DECISION · **Confidence:** HIGH ([ASSERTED]; reinforces existing `concurrent-agents-main-collisions` memory documenting real reverts)
- **What:** This repo is trunk-based on `main` (no feature branches/PRs by policy) with a history of parallel streams reverting each other's pushed work. Worktrees isolate the working directory but do not serialize merges — parallel worktree work must still `git fetch && git rebase origin/main` before each push.
- **Sources:** batch 5 (worktrees digest); corroborates memory `concurrent-agents-main-collisions.md`

### Parallel-AI-agent worktree tooling landscape (mid-2026)
- **Type:** REFERENCE · **Confidence:** LOW ([ASSERTED] — web research, not hands-on)
- **What:** Git worktrees became the de-facto isolation primitive for parallel AI agents ~Q1 2026. Native: Claude Code built-in (~v2.1.49); Cursor 2.0; Zed Parallel Agents; JetBrains 2026.1; VS Code. TUI: Claude Squad (tmux+worktrees), workmux, parallel-code, Conduit, agent-deck. GUI/kanban: Vibe Kanban, Crystal, Conductor (predicts cross-worktree merge conflicts). For non-Claude worktree creation: a global post-checkout git hook, copy-env, copy-configs, git-worktreeinclude (reuses `.worktreeinclude`), or per-worktree `.git/worktrees/<name>/info/exclude`.
- **Sources:** batch 5 (worktrees digest)

---

## Forge choice (Forgejo vs GitLab)

### Forgejo chosen over GitLab for the homelab forge — rationale + counter-case
- **Type:** DECISION · **Confidence:** MEDIUM ([ASSERTED]; footprint/OOM rationale corroborated by soyo-OOM memories; conceptual Q&A — no tooling run)
- **What:** Forgejo preferred over GitLab on four grounds: (1) **footprint** — single Go binary (~100–300 MB RAM) vs GitLab's multi-service stack (Puma/Gitaly/Sidekiq/Workhorse + bundled Postgres/Redis), 4 GB floor / ~8 GB realistic, untenable on RAM-tight OOM-prone soyo nodes; (2) **FOSS ethos** — nonprofit, fully copyleft GPL, no open-core (vs GitLab's open-core), consistent with prior OSS pivots (off Infisical, off SOPS); (3) **GitHub interop** — Forgejo Actions is GitHub-Actions-compatible, enabling workflow reuse where GitLab CI would force a rewrite; (4) **best-of-breed already assembled** — Harbor/Renovate/Grafana already run, so GitLab's bundling is redundant. **Counter-case (GitLab wins):** you need the integrated DevOps suite AND matching hardware — complex multi-stage CI (DAG/child pipelines, environments, approval gates), built-in SAST/DAST/dependency/container scanning, compliance/audit, or a larger team wanting one vendor-supported platform. The conceded trade-off is Forgejo's weaker CI maturity, acceptable because cluster CI is GitOps-light (semantic-release cuts releases; Flux deploys).
- **Sources:** batch 5 (Forgejo vs GitLab digest)

---

## Repo conventions, tooling & cross-cutting

### Concurrent agents on unprotected `main` — fetch, verify survival, stage explicit paths
- **Type:** GOTCHA + PROCEDURE · **Confidence:** HIGH ([VERIFIED] across many threads; matches `concurrent-agents-main-collisions.md`)
- **What:** Another actor (or a parallel agent in the same working tree) commits to `main` mid-session — files you never touched appear staged (e.g. `scaledjob.yaml`, RFC/ADRs, `mkdocs.yml`; an ADR was renamed live; commit `04c6151` appeared during a session; HEAD advanced via others' commits). A reflexive `git add -A` sweeps them in. Defenses: stage only your own files by explicit pathspec (never `git add -A`); leave pre-existing uncommitted files (`.mise.toml`, `talos/talenv.yaml`) untouched; before pushing `git fetch origin main` + verify `git rev-list --count HEAD..origin/main == 0` (clean fast-forward). Recovery: `git reset -q HEAD .` then stage own paths; if a prior `add -A` may have run before a commit, `git reset --soft HEAD~N && git reset -q` then stage per-commit.
- **Snippet:** `git fetch -q origin main && [ "$(git rev-list --count HEAD..origin/main)" = "0" ] && git push -q origin main && echo PUSHED || echo DIVERGED`
- **Sources:** batches 1 (copy 13, copy 16), 2 (copy 8), 3 (copy 9/10, copy 5), 4 (all)

### Repo validate/commit conventions
- **Type:** REFERENCE · **Confidence:** HIGH ([VERIFIED] across threads)
- **What:** Validate manifests with `./scripts/run-flux-local-test.sh` (builds ~72 kustomizations; ~3–4 min; docs-only changes skip it). Commit via mise so lefthook's zizmor resolves: `mise exec -- git -c commit.gpgsign=false commit` (pinentry hangs non-interactively); a lefthook pre-commit (`format-yaml`/yamlfmt `stage_fixed=true`, format-mise/format-just, `zizmor --offline` on `.github/workflows/`) may reformat + stage into the same commit (`git add -A` + recommit). `zizmor` is NOT pre-installed — `python3 -m pip install zizmor` into the repo `.venv`. Trunk-based directly on `main` (unprotected); no feature branches/PRs (PR/review path explicitly declined for these homelab repos). Co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Renovate: `npx --yes --package renovate@latest renovate-config-validator .renovaterc.json5`; isolated lookup `npx renovate@latest --platform=local --dry-run=lookup`.
- **Sources:** batches 1 (copy 16, copy 11, copy 13), 2 (copy 8, copy 2, copy 14), 4 (all)

### Per-app Flux Kustomizations live in the APP namespace; `${SECRET_DOMAIN}` won't expand without substituteFrom
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Each per-app Kustomization is created in the app's own namespace (`flux suspend ks harbor -n flux-system` → "not found"; correct is `-n harbor`). And a ks with no `postBuild.substituteFrom` (e.g. `forgejo-runner/ks.yaml`) won't expand `${SECRET_DOMAIN}` in its `app/` manifests — it renders blank, a silent breakage flux-local won't flag; either add `substituteFrom: cluster-secrets` or use cluster-internal service names.
- **Sources:** batch 1 (copy 11, copy 16)

### Bash/git tool gotchas (cwd reset, zsh globs, `commit -- pathspec` ordering)
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Each Bash call resets cwd to project root — use `git -C <path>` per command. The shell is zsh: unquoted globs with no match hard-error (`ls ops/docker/*/` → "no matches found") — quote glob args or use `find`. To commit only specific files, put `-m` BEFORE the `--` pathspec: `git commit -m "msg" -- path1 path2` (`-m` after `--` makes git treat it as a pathspec). Validate YAML without pyyaml/ruby via `npx --yes js-yaml@4 <file>`; for `.releaserc.js` use `node --check` + exercise the env-gated branch (`BUILD_CACHE_REF=… node -e "…require('./.releaserc.js')…"`).
- **Sources:** batches 1 (copy 6, copy 13), 2 (copy 14)

### Documentation conventions: ADRs + RFCs in this repo
- **Type:** REFERENCE · **Confidence:** MEDIUM (mechanics [VERIFIED] in-thread; exact next-ADR-number claims vary by batch — verify against the live index)
- **What:** ADRs at `docs/techdocs/docs/adr/adr-NNNN-<kebab>.md` (zero-padded, monotonic, never reused; a reversal gets a superseding ADR). RFCs at `docs/techdocs/docs/rfc/rfc-<topic>.md` (no number). No front-matter; open with `# H1` then a `> Status: **Accepted** · Date: YYYY-MM-DD · Part of [RFC: …]` banner. ADR sections: Context / Decision / Consequences / Alternatives. Must ALSO register in the ADR/RFC tables in `adr/index.md` AND the explicit `nav:` in `mkdocs.yml` (a rename touches both); RFC wiring is a 3-edit convention (nav block + `redirect_maps` + `adr/index.md` "### RFCs" table). Decisions get an ADR number only when ratified — list pending ones as unnumbered "candidate ADRs". (The `adr/index.md` Conventions text still says files live under `docs/techdocs/docs/architecture/` — stale; actual files live in `adr/` + `rfc/` with redirects.) markdownlint: MD031 blank lines around fences (incl. in `>` blockquotes), MD049 wants `_emphasis_` (existing RFCs use `*` — don't "fix" repo-wide style), MD060 long-row table warnings cosmetic. The github-script build-summary step uses `String(content).replace(/```/g, '\u200b``')` — keep the `\u200b` **escape**, not a literal zero-width space.
- **Sources:** batches 1 (copy 13), 2 (copy 8), 4 (both Talos digests)

### TechDocs / mkdocs build: in-cluster only; plugins must be pinned in the image before enabling
- **Type:** GOTCHA + PROCEDURE · **Confidence:** MEDIUM ([VERIFIED] mechanics; some [ASSERTED])
- **What:** `mise exec -- mkdocs build` fails (no local mkdocs) — TechDocs is built by Backstage in-cluster, so `mkdocs build --strict` is unavailable locally; fall back to a relative-link existence check. The TechDocs image installs `mkdocs-techdocs-core==1.5.3` (+mermaid2, macros, dracula) but NOT `mkdocs-redirects`/`awesome-pages` — declaring `plugins: [- redirects]` while the deployed image lacks the package fails `unknown plugin "redirects"`; correct order = add the pin to the image Dockerfile (`mkdocs-redirects==1.2.2` in `infrastructure/ops/docker/techdocs-builder/Dockerfile`), rebuild+publish, THEN enable. Mermaid (via `pymdownx.superfences`): flat node-chains render; subgraph-chaining + commas-in-unquoted-labels + `&` break it (use `<br/>`, `·` separators, simple labels). When moving docs into a new taxonomy, rewrite links **file-relative** (mkdocs convention even with `use_directory_urls: true`); neutralize genuinely-missing targets (`[text](dead)` → `text`) rather than invent. Docs taxonomy: `adr/ rfc/ blogs/ incidents/ runbooks/ general/`; nest a repo's coherent topical IA under `general/`, don't flatten ("don't bulldoze good IA").
- **Sources:** batches 3 (copy 5), 4 (Talos hardware digest)

### roadmap-topup maintains roadmap.md at exactly 100 items via posture-counts.sh
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** `docs/techdocs/docs/general/roadmap.md` is a living backlog held at exactly 100 open items (roadmap-topup skill). Ground truth via `./scripts/posture-counts.sh` (PDB / NetworkPolicy / CiliumNetworkPolicy / ResourceQuota / SecurityPolicy counts + Kyverno Audit-vs-Enforce split + namespaces-with-a-NetworkPolicy). Move shipped work to the Done log, reframe partials, add findings to hold at 100. Don't manually renumber it. Snapshot (2026-06-21): PDB 2 · NetworkPolicy 17/11 ns · CiliumNetworkPolicy 1 · ResourceQuota 4 · SecurityPolicy 0 · Kyverno 11 Audit / 6 Enforce.
- **Sources:** batch 2 (copy 8)

### Skill authoring (skillsmith): loader executes bang-backtick injection; substitutes `${CLAUDE_SKILL_DIR}`/`$ARGUMENTS`
- **Type:** GOTCHA + FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** The Claude Code skill loader executes the bang-backtick dynamic-injection pattern found in a SKILL.md body at load time — skillsmith/SKILL.md documented that very syntax with the live token, so invoking `/skillsmith` ran the literal example (`zsh: command not found: cmd`), blocking the skill. Only SKILL.md is scanned (sibling reference.md is not). Fix: never write the literal bang-backtick token in a SKILL.md body — name the feature, put the literal syntax in reference.md. On load, `${CLAUDE_SKILL_DIR}` expands to the absolute skill path and `$ARGUMENTS` to invocation args; the command name derives from the **directory name**, not frontmatter `name:`.
- **Sources:** batch 4 (node-taxonomy migration digest)

---

## Conflicts (cross-batch)

### Was the cosign-sign-attest Harbor SBOM step committed/exercised?
- **Conflict:** Batch 2's copy 3 (earlier "column not populated" thread) said the code change was made but not yet committed or run; copy 2 (later "403 fix" thread, same date) treats the step as live and resolves the permission via the robot grant (commit 9938e09). Batch 3's copy 4 independently confirms the grant via recent commit `fix(harbor): grant CI robot sbom:create`.
- **More credible:** The later state — the SBOM step exists, `sbom:create` is granted+verified (commit 9938e09 is in the repo's recent-commits list) — supersedes the earlier `[OPEN]` permission concern. The only genuinely-unexercised piece is the next real release turning the `::warning:: HTTP 403` into a populated Harbor SBOM column.
- **Sources:** batches 2 (copy 2, copy 3), 3 (copy 4)

### Runner advertised labels: `docker` only vs `docker, default, ubuntu-latest`
- **Conflict:** Batch 3 copy 7 read the config as advertising three labels; copy 5 established (by live `action_runner` DB query, post-sweep) that it advertises only `docker`.
- **More credible:** Single `docker` — verified against the live DB and the post-sweep config, and matches the explicit "labels must be TRUE" preference. copy 7's reading predates the sweep.
- **Sources:** batch 3 (copy 5 authoritative, copy 7)

### ADR-0035 scope: "pre-baked action cache + offline mode" vs "scoped LAN action mirror"
- **Conflict:** Batch 1 copy 16 described ADR-0035 as pre-baking the action set + runner offline mode; copy 13 proved offline mode impossible and repointed the ADR (file renamed to `adr-0035-action-clone-wall.md`).
- **More credible:** copy 13 — it inspected the exact runner image three ways and the file rename is in-tree. Treat the scoped-mirror framing as authoritative.
- **Sources:** batch 1 (copy 13 authoritative, copy 16)

---
