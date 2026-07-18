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

## Same-file variant: committing one hunk around someone else's WIP

Pathspec staging can't separate changes **inside one file**. When a file carries another
stream's uncommitted work and you need to commit a surgical change to it (proven 2026-07-12
on `.claude/settings.json`, commit `11bda139`):

```bash
git stash push -m their-wip -- <file>   # park their change
# edit the clean HEAD version with ONLY your change; commit it
git stash pop                            # re-apply theirs; may conflict near your edit
# resolve keeping BOTH (their layout + your change), then:
git stash drop
```

Their work stays uncommitted in the working tree, exactly as found.

## Recovery: your commit landed on someone else's branch

Another stream can switch the shared tree's checked-out branch mid-task; your next commit
then lands on **their** branch, and `git push origin main` reports "Everything up-to-date"
(the tell — local `main` never advanced). Proven recovery (2026-07-17, commit `01745acc`),
non-destructive to both streams:

```bash
git worktree add --detach /tmp/wt origin/main   # hand-run: .worktreeinclude does NOT apply
git -C /tmp/wt cherry-pick <your-sha>           # or re-stage + commit -C <your-sha>
git -C /tmp/wt push origin HEAD:main
git worktree remove /tmp/wt
```

Leave the stray commit on their branch — a later rebase drops it by patch-id. Never reset
or switch their branch: their uncommitted files are in the shared tree. The same detached
temp worktree is the right way to commit **any** file to main while the shared tree sits on
someone else's branch. Corollary: check `git branch --show-current` before every commit
round in a shared tree.
