Thread Digest: Git worktrees for parallel work in a GitOps homelab repo
One-line summary: How to run multiple isolated work streams in one repo using git worktrees — the tooling landscape, the gitignored-secrets gap specific to this repo, and how it works inside the VSCode Claude extension.
Approx date / status: 2026-06-24 → 2026-06-26 — done (advice given; .worktreeinclude created, not committed)

Items
[GOTCHA] Fresh git worktrees lack this repo's gitignored bootstrap files
Type: GOTCHA
Verification: [VERIFIED] (inspected .gitignore + git status --ignored)
What: A new git worktree is a clean checkout containing only tracked files. This repo's entire local toolchain depends on gitignored files that therefore do NOT appear in a new worktree, breaking SOPS decrypt / kubectl / talosctl / mise / validation. The required-but-ignored files are: age.key, kubeconfig, .mise.local.toml, .claude/settings.local.json, talos/talosconfig, and talos/clusterconfig/ (per-node kubernetes-*.yaml + talosconfig).
Why it matters: Without bootstrapping these, any worktree-based parallel workflow fails the moment it touches secrets or the cluster — silently looks set up but isn't.
Snippet: git status --ignored --short (lists !! entries: age.key, kubeconfig, .mise.local.toml, .claude/settings.local.json, talos/talosconfig, talos/clusterconfig/kubernetes-*.yaml)
Suggested home: CLAUDE.md
[FACT] The age key is resolved per-worktree via {{config_root}}
Type: FACT
Verification: [VERIFIED] (grepped .mise.toml)
What: .mise.toml sets SOPS_AGE_KEY_FILE = "{{config_root}}/age.key". {{config_root}} resolves to each worktree's own root, so SOPS decryption requires an age.key present in every worktree (a copy or symlink at the root resolves correctly).
Why it matters: Explains why the age key must be reproduced into each worktree rather than referenced from a fixed absolute path; a copied/symlinked age.key at the worktree root "just works."
Snippet: .mise.toml: SOPS_AGE_KEY_FILE = "{{config_root}}/age.key"
Suggested home: CLAUDE.md
[PROCEDURE] .worktreeinclude — Claude Code's native fix for the gitignored-files gap
Type: PROCEDURE
Verification: [ASSERTED] (file created from official docs; not yet exercised by an actual worktree creation)
What: Place a .worktreeinclude file at the repo root. It uses .gitignore syntax; Claude Code copies any file that matches a pattern AND is itself gitignored into every worktree it creates (--worktree, EnterWorktree, isolation: worktree subagents, desktop parallel sessions). Tracked files are never duplicated. This replaces a manual symlink script. NOTE: it copies (does not symlink), so rotated files (kubeconfig/tokens) can drift in long-lived worktrees; static key material (age key) is fine.
Why it matters: One committed file makes all Claude-driven worktrees come up validation-ready; safe to commit (filenames only, no secrets).
Snippet: /home/ryan/projects/webgrip/homelab-cluster/.worktreeinclude:

age.key
kubeconfig
.mise.local.toml
.claude/settings.local.json
talos/talosconfig
talos/clusterconfig/
Suggested home: doc (+ note in CLAUDE.md)
[FACT] .worktreeinclude is honored only for Claude-CREATED worktrees, not all worktrees
Type: FACT
Verification: [VERIFIED] (confirmed against code.claude.com/docs/en/worktrees)
What: .worktreeinclude fires for worktrees created via claude --worktree, the EnterWorktree tool, subagent worktrees, and desktop parallel sessions. It does NOT fire for hand-run git worktree add, third-party TUI managers (e.g. Claude Squad), or VSCode-extension "Open in New Tab" sessions. For those, use a universal post-checkout git hook or a tool like copy-env/copy-configs/git-worktreeinclude (the last reuses the same .worktreeinclude file).
Why it matters: Prevents the false assumption that the committed file covers every worktree path; non-Claude creation needs a separate trigger.
Snippet: none
Suggested home: doc
[GOTCHA] VSCode extension "Open in New Tab/Window" gives parallel chats but SHARES the working directory
Type: GOTCHA
Verification: [VERIFIED] (confirmed via claude-code-guide against docs)
What: In the Claude Code VSCode extension, Command Palette → "Open in New Tab / New Window" starts additional conversations, but they all share one working directory — no worktree, no file isolation. This is the exact collision worktrees are meant to prevent.
Why it matters: The obvious-looking "parallel" UI in the extension does not give isolation; relying on it reintroduces the cross-stream collision problem.
Snippet: none
Suggested home: doc
[PROCEDURE] True parallel+isolated work inside the VSCode window = integrated terminal + claude --worktree
Type: PROCEDURE
Verification: [VERIFIED] (mechanism confirmed against docs)
What: For genuine simultaneity with file isolation in the VSCode extension, open the integrated terminal (Ctrl+\``), split panes, and run the bundled CLI per task. Each is a fully isolated worktree session that honors .worktreeinclude. Alternatively, move the current session into a worktree mid-conversation by asking Claude to "work in a worktree" (invokes the EnterWorktree` tool) — but that relocates one session, it doesn't create parallelism.
Why it matters: Identifies the only in-window path that delivers both parallelism and isolation.
Snippet:

claude --worktree taskA     # terminal pane 1
claude --worktree taskB     # terminal pane 2
Suggested home: doc
[REFERENCE] Claude Code --worktree defaults and base-branch behavior
Type: REFERENCE
Verification: [VERIFIED] (from official docs)
What: claude --worktree <name> (or -w) creates a worktree at .claude/worktrees/<name>/ on branch worktree-<name>. Omitting the name auto-generates one (e.g. bright-running-fox). Worktrees branch from origin/HEAD (clean, matches remote) by default; set worktree.baseRef: "head" in settings to carry unpushed commits instead. claude --worktree "#1234" branches from a PR into .claude/worktrees/pr-1234. First interactive use in a dir requires accepting the trust dialog (run claude once first); claude -p --worktree skips the trust check. Add .claude/worktrees/ to .gitignore. Cleanup: clean worktrees (no changes/untracked/commits) are auto-removed; dirty ones prompt keep/remove; --worktree ones are never swept automatically.
Why it matters: Exact knobs for adopting the native workflow; the origin/HEAD default matters in a trunk-based repo (worktrees start from remote main, not your local state, unless baseRef: "head").
Snippet: settings: {"worktree": {"baseRef": "head"}} ; gitignore: .claude/worktrees/
Suggested home: doc
[DECISION] Worktrees solve working-dir collisions but NOT push-to-main collisions
Type: DECISION
Verification: [ASSERTED]
What: This repo is trunk-based on main (no feature branches/PRs by policy) and has a history of parallel streams reverting each other's pushed work. Worktrees isolate the working directory but do not serialize merges. So parallel worktree work must still git fetch && git rebase origin/main before each push, serializing pushes — or use short-lived scratch branches fast-forwarded into main.
Why it matters: Prevents the false sense that a worktree manager makes parallel merge-to-main safe; the merge discipline is still required.
Snippet: git fetch && git rebase origin/main (before pushing each worktree's work)
Suggested home: CLAUDE.md / memory
[GOTCHA] isolation: worktree subagents hit the same secrets gap
Type: GOTCHA
Verification: [ASSERTED]
What: Spawning a subagent with isolation: worktree gives it an auto-managed worktree, but that worktree has the same gitignored-secrets gap. With .worktreeinclude in place it's covered; without it, such subagents are best limited to self-contained edits that don't need SOPS/kubectl/talosctl.
Why it matters: Sets expectations for delegating cluster-touching work to isolated subagents in this repo.
Snippet: subagent frontmatter: isolation: worktree
Suggested home: doc
[REFERENCE] Parallel-AI-agent worktree tooling landscape (mid-2026)
Type: REFERENCE
Verification: [ASSERTED] (web research, not hands-on)
What: Git worktrees became the de-facto isolation primitive for parallel AI agents ~Q1 2026. Native: Claude Code built-in worktrees (~v2.1.49, Feb 2026); Cursor 2.0 (Oct 2025, up to ~8 agents); Zed Parallel Agents (native editor panel, per-thread worktree isolation); JetBrains 2026.1; VS Code (Jul 2025). Terminal/TUI managers: Claude Squad (tmux + worktrees, most established), workmux, parallel-code (MIT, johannesjo/parallel-code), Conduit, agent-deck. GUI/kanban: Vibe Kanban (community-maintained after Bloop shutdown), Crystal, Conductor (predicts cross-worktree merge conflicts). Lists: github.com/andyrewlee/awesome-agent-orchestrators, github.com/no-fluff/awesome-vibe-coding.
Why it matters: Menu of options if hand-rolled worktrees become insufficient; Conductor's conflict-prediction maps onto this repo's main-collision pain.
Snippet: none
Suggested home: doc
[REFERENCE] Tools that copy gitignored files into hand-made worktrees
Type: REFERENCE
Verification: [ASSERTED] (web research)
What: For non-Claude worktree creation: a global post-checkout git hook (detects new-worktree via null prev-HEAD, copies ignored files) — git config --global core.hooksPath ~/.git-hooks; copy-env (therohitdas/copy-env); copy-configs (gapurov/copy-configs); git-worktreeinclude (reuses the .worktreeinclude file); autowt (post_create hook); per-worktree ignore at .git/worktrees/<name>/info/exclude.
Why it matters: Covers worktrees created outside Claude Code, complementing .worktreeinclude.
Snippet: git config --global core.hooksPath ~/.git-hooks
Suggested home: doc
Open questions / unfinished
.worktreeinclude was created at the repo root but left untracked/uncommitted for review; not yet validated by actually creating a worktree. [OPEN]
Whether to also add a universal post-checkout git hook (so hand-made / Claude-Squad worktrees get the same bootstrap) — offered, not decided. [OPEN]
Whether to add a scripts/new-worktree.sh (worktree add + symlink bootstrap) and/or document the workflow in CLAUDE.md — offered, not decided. [OPEN]
Copy-vs-symlink trade-off for rotated files (kubeconfig/tokens drift in long-lived worktrees) — flagged; no resolution chosen. [OPEN]
Explicit preferences/feedback I gave
Wants to work on multiple things at once in this repo without streams interfering (motivation for adopting worktrees).
Works primarily inside the VSCode Claude extension window; asked specifically whether the workflow is usable there (answer: via integrated-terminal claude --worktree, not the extension's New-Tab feature).
Asked to research the external landscape ("what are people doing online," OSS projects, non-VSCode tools like Zed/Cursor) rather than accept a hand-rolled solution — prefers checking for established/upstream fixes before bespoke scripts.
