---
name: forgejo-leading
description: Migrate a webgrip repo from GitHub-leading (gitea-mirror pull-mirror into Forgejo) to Forgejo-leading — stop the mirror, un-mirror in Forgejo, re-point local git remotes (origin→Forgejo SSH, github→GitHub). Needed because in-cluster Forgejo CI must git-push tags/releases, which a read-only pull-mirror rejects.
when_to_use: Use when making a repo Forgejo-leading, cutting a repo over from GitHub to Forgejo, stopping gitea-mirror for one repo, un-mirroring a pull-mirror, fixing "remote: mirror repository is read-only" (403) on push, or re-pointing origin to forgejo-ssh.webgrip.dev. Also covers post-cutover parity: enabling Forgejo Actions to match GitHub, push-mirroring back to GitHub, and branch protection (scripts/forgejo-sync.sh). webgrip/workflows is first (reusable-workflow library); infrastructure already done.
allowed-tools: Bash(git status:*), Bash(git remote -v), Bash(git fetch:*), Bash(git rev-parse:*), Bash(git log:*)
---

# Forgejo-leading repo migration

Flip one repo from **GitHub-leading** (Forgejo holds a read-only pull-mirror, fed by gitea-mirror) to
**Forgejo-leading** (Forgejo is writable origin; in-cluster CI cuts releases by pushing tags). Per repo,
~5 min: 2 UI clicks + a scriptable git re-point + verify. Do **webgrip/workflows first** — it's the
reusable-workflow library every other repo consumes via `uses: webgrip/workflows/...@ref`, so its
consumers' Forgejo CI must resolve it on Forgejo before they migrate.

## Order is load-bearing (mirror-clobber race)

**Stop the driver → take one final sync → make writable → re-point.** Un-mirroring in Forgejo *before*
stopping gitea-mirror lets the next sync re-assert the read-only mirror. gitea-mirror state is a private
SQLite DB with **no REST API** — don't script DB edits. The Forgejo convert is the documented UI route
below, but it is **no longer strictly UI-only**: Forgejo added `POST /repos/{owner}/{repo}/convert` (PR
#8932, backported to 15.0/16.0; cluster runs chart 17.1.0) which can automate bulk un-mirroring — keep
the Danger-Zone convert as the verified per-repo path, reach for the API only for a fleet sweep.

## Procedure

**Two shapes.** If the repo is a Forgejo pull-mirror, do step 1. If it was **never mirrored** (GET
`/api/v1/repos/webgrip/<r>` → 404), skip step 1 — instead create an **empty** repo on Forgejo (match
GitHub visibility), and in step 2 populate it with `git push origin --all && git push origin --tags`.

**1. Stop the mirror + un-mirror (UI — PAUSE here, can't automate):**
   - **gitea-mirror UI** (`gitea-mirror.${SECRET_DOMAIN}`): disable sync / remove the repo from the
     managed set. Non-destructive — leaves the Forgejo repo intact. This does **not** stop Forgejo's own
     scheduled pull (that interval lives in Forgejo); the convert below is what actually stops it.
   - **Forgejo → repo → Settings**: in the **Mirror settings** panel click **Synchronize now** (final
     pull), wait, then scroll to the **Danger Zone** → **Convert to a regular repository** (type the repo
     name to confirm). ⚠️ The Mirror-settings panel has **no un-mirror button** (only Synchronize /
     interval / prune) — the Danger-Zone convert (or the `POST .../convert` API) is what flips
     `is_mirror=false` and makes it writable, not the Mirror-settings panel. Verified on Forgejo 15.0.2
     (gitea-1.22).
   - ⚠️ If gitea-mirror **auto-imports the whole org**, a per-repo disable can be re-added on the next
     discovery pass — exclude the repo, or it re-creates the pull-mirror.

**2. Re-point local remotes** (matches the `infrastructure` precedent — SSH origin, `github` kept):
```bash
R=webgrip/workflows                          # owner/repo
cd ~/projects/$R
git status -sb                               # MUST be clean & on main before touching remotes
git remote rename origin github
git remote set-url github git@github.com:$R.git          # drop any stray ":/"
git remote add origin ssh://git@forgejo-ssh.webgrip.dev/$R.git
git fetch origin && git fetch github
git rev-parse origin/main github/main        # MUST match — Forgejo synced to GitHub HEAD in step 1
git branch --set-upstream-to=origin/main main
git config remote.pushDefault origin         # repo-local: plain push/pull/fetch now hit Forgejo
```

**3. Verify writable:**
```bash
# mirror flag must be false. Do NOT trust permissions.push — that's the ANON caller's perm, always false.
curl -fsS https://forgejo.webgrip.dev/api/v1/repos/$R \
  | python3 -c 'import sys,json;print("mirror:",json.load(sys.stdin)["mirror"])'   # want: mirror: False
git push origin main                         # no-op if synced. 403 "mirror repository is read-only"
                                             #   ⇒ Danger-Zone convert (step 1) didn't take — redo it
git push github main                         # still mirrors to GitHub until it's archived
```

**4. Settings parity to GitHub** — gitea-mirror creates repos with the **Actions unit OFF**; this turns
it back on (matching GitHub), adds a Forgejo→GitHub push-mirror (auto-backup), and mirrors GitHub's `main`
branch protection. Run `scripts/forgejo-sync.sh` (dry-run first, then `--apply`):
```bash
set -a; source ~/.config/webgrip/forgejo.env; set +a   # FORGEJO_TOKEN (write:repository) + GH_MIRROR_TOKEN (GitHub PAT, repo)
scripts/forgejo-sync.sh --repo <name>            # dry-run: shows the planned Actions/mirror/protect changes
scripts/forgejo-sync.sh --repo <name> --apply
```

**5. Port the CI/release workflows** — git hosting is now on Forgejo, but `.github/workflows/` still
targets GitHub (ARC runner label, GitHub-App auth, `@semantic-release/github`) and won't release on
Forgejo. **Move** `.github/workflows/*` → `.forgejo/workflows/*` and convert `.releaserc.json` →
a `GITEA_ACTIONS`-gated `.releaserc.js` → see **forgejo-port-workflows**. Skipping this leaves the repo
"Forgejo-leading" in git only; releases stay on GitHub (the gap that hid on renovate-config until 2026-06-27).

**6. Record state** in the migration memory (repo now Forgejo-leading; what's left). Personal memory —
not a committed link.

## Gotchas

- **Never use HTTPS for `origin`.** Push needs SSH — Ryan's ed25519 key is already on Forgejo and the
  `forgejo-ssh.webgrip.dev` host key is already trusted (RSA, from the infra migration). HTTPS prompts
  for creds and can't push.
- **Test, don't assume, the un-mirror.** `git push origin main` returning 403 `mirror repository is
  read-only` is the only proof step 1's un-mirror landed.
- **Keep the `github` remote** until GitHub is archived — `git push github main` is the manual mirror.
- **No per-repo token needed** for CI: the `webgrip-ci` bot has org-wide write via the `webgrip/ci` team
  (forgejo-ci-provisioner), so semantic-release can push tags once the repo is writable.
- **Don't migrate a consumer before `webgrip/workflows`** — its CI `uses:` the workflows lib; resolve
  that on Forgejo first.
- **`forgejo-sync.sh` token scopes:** `FORGEJO_TOKEN` = `write:repository` (repo edit/mirror/protection).
  A `/user` call 403s with a repo-scoped token — expected, the script doesn't use it. `--all` (org sweep)
  additionally needs `read:organization`; without it, pass `--repo <name>` explicitly.
- **Never copy GitHub `status_check_contexts` into Forgejo branch protection** — they're GitHub job names;
  Forgejo's checks differ, so requiring them deadlocks every merge. `forgejo-sync.sh` drops them and warns;
  re-add under Forgejo check names after CI has run once.
