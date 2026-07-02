# Forgejo-leading — copy-paste blocks & verify steps

Contents: [Step 2 — re-point local remotes](#step-2--re-point-local-remotes)
· [Step 3 — verify writable](#step-3--verify-writable)
· [Step 4 — settings parity via forgejo-sync.sh](#step-4--settings-parity-via-forgejo-syncsh)
· [Un-mirror mechanics](#un-mirror-mechanics)

## Step 2 — re-point local remotes

Matches the `infrastructure` precedent — SSH origin, `github` kept. Origin must be **SSH**: the operator's
ed25519 key is already on Forgejo and the `forgejo-ssh.webgrip.dev` host key is trusted (from the infra
migration); HTTPS prompts for creds and can't push.

```bash
R=webgrip/<repo>                             # owner/repo
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

## Step 3 — verify writable

```bash
# mirror flag must be false. Do NOT trust permissions.push — that's the ANON caller's perm, always false.
curl -fsS https://forgejo.webgrip.dev/api/v1/repos/$R \
  | python3 -c 'import sys,json;print("mirror:",json.load(sys.stdin)["mirror"])'   # want: mirror: False
git push origin main                         # no-op if synced. 403 "mirror repository is read-only"
                                             #   ⇒ Danger-Zone convert (step 1) didn't take — redo it
git push github main                         # still mirrors to GitHub until it's archived
```

## Step 4 — settings parity via forgejo-sync.sh

`~/.config/webgrip/forgejo.env` lives **on the operator machine** (per-machine, not in the repo):
`FORGEJO_TOKEN` (`write:repository`) + `GH_MIRROR_TOKEN` (GitHub PAT, `repo`).

```bash
set -a; source ~/.config/webgrip/forgejo.env; set +a
scripts/forgejo-sync.sh --repo <name>            # dry-run: shows the planned Actions/mirror/protect changes
scripts/forgejo-sync.sh --repo <name> --apply
```

## Un-mirror mechanics

Verified on Forgejo 15.0.2 (gitea-1.22): the repo **Mirror settings** panel offers only Synchronize /
interval / prune — it has **no un-mirror button**. What flips `is_mirror=false` and makes the repo writable
is the **Danger Zone → Convert to a regular repository** (type the repo name to confirm), or the API
`POST /repos/{owner}/{repo}/convert` (Forgejo PR #8932, backported to 15.0/16.0; cluster runs chart 17.1.0) —
useful for a bulk fleet sweep; keep the Danger-Zone convert as the verified per-repo path.
