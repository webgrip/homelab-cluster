---
name: forgejo-leading
description: Migrate a webgrip repo from GitHub-leading (gitea-mirror pull-mirror into Forgejo) to Forgejo-leading — stop the mirror, un-mirror in Forgejo, re-point local git remotes (origin→Forgejo SSH, github→GitHub). Needed because in-cluster Forgejo CI must git-push tags/releases, which a read-only pull-mirror rejects.
when_to_use: Use when making a repo Forgejo-leading, cutting a repo over from GitHub to Forgejo, stopping gitea-mirror for one repo, un-mirroring a pull-mirror, fixing "remote: mirror repository is read-only" (403) on push, or re-pointing origin to forgejo-ssh.webgrip.dev. Also covers post-cutover parity: enabling Forgejo Actions to match GitHub, push-mirroring back to GitHub, and branch protection (scripts/forgejo-sync.sh).
allowed-tools: Bash(git status:*), Bash(git remote -v), Bash(git fetch:*), Bash(git rev-parse:*), Bash(git log:*)
---

# Forgejo-leading repo migration

Flip one repo from **GitHub-leading** (Forgejo holds a read-only pull-mirror, fed by gitea-mirror) to
**Forgejo-leading** (Forgejo is writable origin; in-cluster CI cuts releases by pushing tags). Per repo,
~5 min: 2 UI clicks + a scriptable git re-point + verify. Migrate **webgrip/workflows before any
consumer** — it's the reusable-workflow library every other repo consumes via
`uses: webgrip/workflows/...@ref`, so consumers' Forgejo CI must resolve it on Forgejo first.

## Order is load-bearing (mirror-clobber race)

**Stop the driver → take one final sync → make writable → re-point.** Un-mirroring in Forgejo *before*
stopping gitea-mirror lets the next sync re-assert the read-only mirror. gitea-mirror state is a private
SQLite DB with **no REST API** — don't script DB edits.

## Procedure (copy-paste blocks + verify details → [reference.md](reference.md))

**Two shapes.** Repo is a Forgejo pull-mirror → start at step 1. **Never mirrored** (GET
`/api/v1/repos/webgrip/<r>` → 404) → skip step 1: create an **empty** Forgejo repo (match GitHub
visibility) and populate it in step 2 with `git push origin --all && git push origin --tags`.

1. **Stop the mirror + un-mirror (UI — PAUSE here, can't automate):**
   - **gitea-mirror UI** (`gitea-mirror.${SECRET_DOMAIN}`): remove the repo from the managed set
     (non-destructive). ⚠️ If gitea-mirror auto-imports the whole org, **exclude** the repo or the next
     discovery pass re-creates the pull-mirror.
   - **Forgejo → repo → Settings**: **Synchronize now** (final pull), wait, then **Danger Zone →
     Convert to a regular repository**. Only the convert flips `is_mirror=false` — the Mirror-settings
     panel has no un-mirror button (mechanics + bulk `POST .../convert` API → reference.md).
2. **Re-point local remotes** — `origin` → Forgejo over **SSH** (HTTPS can't push), keep a `github`
   remote for manual mirroring until GitHub is archived → block in reference.md.
3. **Verify writable** — API `mirror: false` + `git push origin main`. A 403
   `mirror repository is read-only` is the only proof the convert did/didn't land → reference.md.
4. **Settings parity to GitHub** — gitea-mirror creates repos with the Actions unit OFF. Run
   `scripts/forgejo-sync.sh --repo <name>` (dry-run first, then `--apply`): enables the Actions +
   PRs + Releases units, adds the Forgejo→GitHub push-mirror. Branch protection is **opt-in**
   (`--only protect`) and applies the ADR-0050 delivery-contract whitelists (CI bot pushes,
   owner+Renovate merge) — NOT a mirror of GitHub's rules; order + 403 triage →
   [branch-protection rollout runbook](../../../docs/techdocs/docs/runbooks/forgejo-branch-protection-rollout.md).
   Token env (`~/.config/webgrip/forgejo.env`) lives **on the operator machine**, not in the repo → reference.md.
5. **Port the CI/release workflows** — `.github/workflows/` still targets GitHub (ARC label, GitHub-App
   auth, `@semantic-release/github`) and won't release on Forgejo. **Move** to `.forgejo/workflows/` +
   a `GITEA_ACTIONS`-gated `.releaserc.js` → the **forgejo-port-workflows** skill. Skipping this leaves
   the repo Forgejo-leading in git only (the gap that hid on renovate-config until 2026-06-27).
6. **Record state** in the migration memory (personal — not a committed link).

## Gotchas

- **Test, don't assume, the un-mirror:** `git push origin main` returning 403 `mirror repository is
  read-only` means step 1's convert didn't take — redo it.
- **No per-repo token needed for CI:** the `webgrip-ci` bot has org-wide write via the `webgrip/ci` team
  (forgejo-ci-provisioner), so semantic-release can push tags once the repo is writable.
- **`forgejo-sync.sh` token scopes:** `FORGEJO_TOKEN` = `write:repository` (+ repo admin for
  `protect`/`webhook`). A `/user` call 403s with a repo-scoped token — expected, the script doesn't
  use it. `--all` (org sweep) additionally needs `read:organization`; without it, pass `--repo
  <name>` explicitly.
- **`--all` paginates the org listing** (50/page). Before 2026-07-26 it fetched one page — past 100
  repos, ploeg/ai-skills/previews/semantic-release-config were silently invisible to every sweep.
  If a repo seems skipped, first confirm it appears in the resolved list.
- **Never copy GitHub `status_check_contexts` into Forgejo branch protection** — they're GitHub job
  names; Forgejo's checks differ, so requiring them deadlocks every merge. (`sync_protect` no longer
  mirrors GitHub protection at all — it applies the ADR-0050 contract payload; add required checks
  under Forgejo check names only after CI has run once.)
