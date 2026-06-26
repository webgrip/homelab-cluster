# Git Worktrees

Git worktrees give parallel streams of work their own isolated working
directory backed by the same repository — so two agents (or two terminals) can
edit, validate, and commit at once without stepping on each other's files.

A fresh worktree is a clean checkout of **tracked** files only, so it silently
lacks this repo's gitignored bootstrap files (toolchain config, kubeconfig,
the age key, talos config) and would break SOPS / kubectl / talosctl / mise /
validation the moment it touched secrets or the cluster.

## `.worktreeinclude`

This repo ships a root-level `.worktreeinclude` (`.gitignore` syntax, filenames
only — safe to commit). When **Claude** creates a worktree (`claude --worktree`),
the gitignored bootstrap files it lists are **copied** into the new worktree, so
the worktree is usable immediately.

This applies to **Claude-created worktrees only**. A hand-run `git worktree add`
does not consult `.worktreeinclude` — you'd copy the bootstrap files yourself.

Because the files are copied (not symlinked), rotated material (kubeconfig,
tokens) can drift in a long-lived worktree; static key material (the age key) is
fine.

## `claude --worktree` defaults

`claude --worktree <name>` creates a worktree under `.claude/worktrees/<name>/`
on branch `worktree-<name>`, branching from `origin/HEAD` (which tracks remote
`main` in this trunk-based repo). The name is auto-generated if omitted. Keep
`.claude/worktrees/` gitignored.

## Important limit: worktrees do NOT solve push-to-main collisions

Worktrees isolate the **working directory**. They do **not** serialize merges.

This repo is trunk-based on an **unprotected `main`** (no feature branches, no
PRs by policy), and concurrent agents/worktrees pushing to `main` have **reverted
each other's pushed work**. Isolation does not change that — the same discipline
still applies on every push:

- `git fetch` and verify you are **not behind** `origin/main`.
- Stage **explicit pathspecs** for the files you changed — never `git add -A`
  blindly (it can sweep in or clobber another stream's work).
- `git rebase origin/main` before you push.
