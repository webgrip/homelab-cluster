## Forgejo-leading repo migration (off gitea-mirror)

### Forgejo-leading repo cutover (order is load-bearing; un-mirror is Danger-Zone "Convert")
- **Type:** PROCEDURE + GOTCHA · **Confidence:** HIGH ([VERIFIED] on Forgejo 15.0.2)
- **What:** Per repo, in order (un-mirroring before stopping gitea-mirror lets the next sync re-assert read-only): (1) in gitea-mirror UI disable/remove the repo; (2) Forgejo Settings → `Synchronize now` (final pull) → **Danger Zone → "Convert to a regular repository"** (type repo name; flips `is_mirror=false`) — the Mirror-settings panel has NO un-mirror button (only Synchronize/interval/prune; interval 0 only stops periodic sync, stays read-only); (3) re-point local git remotes. gitea-mirror disable alone does NOT stop Forgejo's own scheduled pull — the convert does. Without this, push returns `403 remote: mirror repository is read-only`. Two shapes: convert-mirror (exists as pull-mirror) vs create-and-push (404 → create empty repo, `git push --all && --tags`, re-point).
- **Snippet:** `git remote rename origin github; git remote set-url github git@github.com:webgrip/<repo>.git; git remote add origin ssh://git@forgejo-ssh.webgrip.dev/webgrip/<repo>.git; git rev-parse origin/main github/main  # MUST match`
- **Sources:** batch 3 (copy 9/10)

### Verify un-mirror via the `.mirror` flag, NOT anon `permissions.push`
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** `GET /api/v1/repos/<o>/<r>` field `permissions.push` reflects the **anonymous caller**, so it reads `false` even for converted writable repos. The reliable signal is the top-level `.mirror` boolean (or `git push` succeeding).
- **Snippet:** `curl -fsS .../repos/webgrip/<r> | python3 -c 'import sys,json;print(json.load(sys.stdin)["mirror"])'`
- **Sources:** batch 3 (copy 9/10)

### GitHub push-mirror PAT needs the `workflow` scope, not just `repo`
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** A Forgejo→GitHub push-mirror pushes all refs. GitHub rejects any ref creating/updating `.github/workflows/` unless the PAT has the `workflow` scope. Tags/releases don't touch workflow files so they sync ("the release appears on GitHub"), but a commit changing a workflow file is rejected → code/branch doesn't land — the literal cause of "release mirrors but code doesn't." Fix: add `workflow` to the existing classic PAT (same value → Forgejo's stored creds gain the scope).
- **Snippet:** `last_error: ! [remote rejected] ... refusing to allow a Personal Access Token to create or update workflow .github/workflows/<file> without 'workflow' scope`
- **Sources:** batch 3 (copy 9/10)

### Converting a pull-mirror leaves Actions AND Pull-Requests units OFF; library repos keep Actions OFF
- **Type:** GOTCHA + DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** gitea-mirror creates the Forgejo repo with `has_actions=false`, and converting leaves `has_pull_requests=false`. PRs-disabled makes Renovate skip the repo ("pull requests are disabled") and blocks normal PRs. Re-enable both via `PATCH /repos/{o}/{r}` `{"has_actions":true}`/`{"has_pull_requests":true}`. EXCEPTION: reusable-workflow library repos (webgrip/workflows) force Actions OFF — their workflows are `on: workflow_call` and run in the caller's runner, so disabling the unit doesn't break `uses:` consumers but prevents stray in-repo runs (encoded as `ACTIONS_OFF_REPOS="workflows"`; commit `feat(forgejo): force Actions unit OFF for reusable-workflow library repos`).
- **Sources:** batch 3 (copy 9/10)

### Don't copy GitHub `status_check_contexts` into Forgejo branch protection
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Copying GitHub's `required_status_checks.contexts` (e.g. `validate (default.json)`) deadlocks every Forgejo merge — those are GitHub job names; Forgejo's checks are named differently and never report them. Keep only structural rules (require PR + approvals, block force-push/deletion); re-add status checks later under actual Forgejo check names.
- **Snippet:** baseline `{"rule_name":"main","enable_push":true}`; strict `{"rule_name":"main","enable_push":false,"required_approvals":1}`
- **Sources:** batch 3 (copy 9/10)

### Forgejo PAT granular scopes — `/user` 403s, org-list needs `read:organization`
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** A Forgejo PAT scoped only `write:repository` (correct for repo ops) 403s on `GET /api/v1/user` (needs `read:user`). Don't validate the token via `/user` — probe a repo endpoint. `GET /orgs/{org}/repos` (for `--all` sweeps) needs `read:organization`. A 403 (not 401) = valid-token-but-missing-scope.
- **Sources:** batch 3 (copy 9/10)

### `gitea-mirror` config/state is in its own SQLite DB — no API, UI-only; `.profile`/`.profile-private`
- **Type:** FACT · **Confidence:** MEDIUM ([ASSERTED])
- **What:** `ghcr.io/raylabshq/gitea-mirror:v3.8.4` (ns `forgejo`, data `/app/data/gitea-mirror.db`, mem 2Gi) stores its repo list + sync settings in a private SQLite DB — no REST API/CLI to disable a repo (web-UI action only, or unsupported direct SQLite edits); a per-repo disable can re-appear on the next discovery pass (exclude instead). Forgejo org profile README = a repo named `.profile` with root `README.md` (NOT `profile/README.md`); members-only = `.profile-private`. There is NO Forgejo equivalent of GitHub's `.github` org-wide defaults repo — shared CI is `uses: webgrip/workflows/.forgejo/workflows/<name>@<ref>`.
- **Sources:** batch 3 (copy 9/10)

### `forgejo-sync.sh` + migration API shapes; migrate webgrip/workflows first
- **Type:** REFERENCE + DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** `scripts/forgejo-sync.sh` brings a Forgejo repo to GitHub parity: `actions` (enable, except `ACTIONS_OFF_REPOS`), `prs`, `mirror` (Forgejo→GitHub push-mirror), `protect`. Dry-run by default; `--apply`; idempotent. Push-mirror `remote_username` must be the **token owner** (from `https://api.github.com/user`), not the org. API base `https://forgejo.webgrip.dev/api/v1`, `Authorization: token $FORGEJO_TOKEN`: push-mirror `POST /repos/{o}/{r}/push_mirrors` (+ `-sync`), protection `GET/POST .../branch_protections`, units `PATCH /repos/{o}/{r}`, status `push_mirrors[].last_error`. Origin SSH `ssh://git@forgejo-ssh.webgrip.dev/webgrip/<repo>.git` (host key trusted); tokens in `~/.config/webgrip/forgejo.env` (`FORGEJO_TOKEN` + `GH_MIRROR_TOKEN`, never echoed). The `webgrip-ci` bot has org-wide write via the `webgrip/ci` team. **Migrate webgrip/workflows first** (the library every repo consumes via `uses:`; 0 tags) so consumers' Forgejo CI resolves it before they migrate.
- **Sources:** batch 3 (copy 9/10)

### `gh api` prints error body to stdout on 404 — fallback must be outside `$(...)`
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** On HTTP error, `gh api` writes error JSON to stdout and exits non-zero. `x=$(gh api ... || echo '{}')` concatenates error JSON with `{}` → a "two JSON docs" parse crash. Put the fallback outside the substitution: `ghp=$(gh api "..." 2>/dev/null) || ghp='{}'`.
- **Sources:** batch 3 (copy 9/10)

---
