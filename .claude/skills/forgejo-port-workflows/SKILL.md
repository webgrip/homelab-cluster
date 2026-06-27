---
name: forgejo-port-workflows
description: Port a repo's .github/workflows to .forgejo/workflows when making it Forgejo-leading — the move-not-copy transform (runs-on docker, checkout@v5, FORGEJO_TOKEN bot, .forgejo reusables, gh CLI to Forgejo REST) and the GITEA_ACTIONS-gated .releaserc.js so semantic-release publishes via the Gitea plugin not @semantic-release/github.
when_to_use: Use when a repo goes Forgejo-leading and its CI/release still lives in .github/workflows, when a Forgejo release picks the wrong semantic-release plugin (@semantic-release/github 404s on /api/v1/graphql), when porting GitHub Actions to Forgejo, or converting .releaserc.json to a forge-gated .releaserc.js. NOT the git cutover (forgejo-leading) nor engine-quirk debugging (forgejo-actions).
---

# Forgejo-port-workflows — move CI from .github to .forgejo

Do this AFTER the git cutover (**forgejo-leading**) so the repo is writable on Forgejo. **Move, don't
copy:** delete each `.github/workflows/*` as you add its `.forgejo/workflows/*`. GitHub Actions stays
enabled-but-empty on the mirror, so the push-mirror runs nothing and can't double-release. Reference
impl: `webgrip/infrastructure` `.forgejo/workflows/` (it has **no** `.github/workflows/` left).

## Transform (per workflow file)

| GitHub | Forgejo | Note |
|---|---|---|
| `runs-on: arc-runner-set` / `ubuntu-latest` | `runs-on: docker` | only label the runner advertises (direct-step jobs); pure-`uses:` orchestrator jobs OMIT `runs-on` — see **forgejo-actions** |
| `actions/checkout@v6` | `@v5` + `token: ${{ secrets.FORGEJO_TOKEN }}` | v6 broken on non-GitHub runners; bot token, not a GitHub App |
| `actions/setup-node@v6` | `@v4` | v6 broken off GitHub |
| `uses: webgrip/workflows/.github/workflows/X.yml@main` | `.../.forgejo/workflows/X.yml@main` | the Forgejo reusable tree |
| GitHub-App auth (`WEBGRIP_CI_APP_ID`/`_PRIVATE_KEY` → minted token) | drop; `secrets: FORGEJO_TOKEN: ${{ secrets.FORGEJO_TOKEN }}` | `webgrip-ci` bot has org-wide write |
| `gh` CLI (`gh pr create`, `gh api`) | Forgejo REST: `curl -H "Authorization: token $FORGEJO_TOKEN" ${GITHUB_SERVER_URL}/api/v1/...` | `gh` is GitHub-only |

Engine quirks hit *during* the port (caller/inner job-id collision, `data.forgejo.org` 404 → pin
absolute URLs, empty `github.sha` on dispatch, `workflow_call.secrets` parser bug, CI-release fires no
release event) → **forgejo-actions** skill. Runner / KEDA / DinD → forgejo-runner runbook.

## .releaserc — convert .json → .js, gate the publish plugin

semantic-release must publish via `@saithodev/semantic-release-gitea` on Forgejo,
`@semantic-release/github` on GitHub (the latter 404s on Forgejo's missing GraphQL API). Gate on
**`GITEA_ACTIONS`** — an intrinsic Forgejo-runner env var: `=true` on Forgejo, **unset** on GitHub
(`GITHUB_ACTIONS` is set on *both*, so it can't discriminate). Verified on the cluster runner 2026-06-27.
Zero config: no org var, no composite-action edit, no literal to maintain.

```js
const onForgejo = !!process.env.GITEA_ACTIONS;              // intrinsic; never a vars.* lookup
const publishPlugin = onForgejo ? '@saithodev/semantic-release-gitea' : '@semantic-release/github';
// version bump + commit-back ONLY on Forgejo (sole release authority); the GitHub mirror must never re-version
const commitBack = onForgejo ? [['@semantic-release/git', { assets: ['CHANGELOG.md'],
  message: 'chore(release): v${nextRelease.version} [skip ci]\n\n${nextRelease.notes}' }]] : [];
module.exports = { branches, plugins: [commitAnalyzer, releaseNotes, changelog, ...commitBack, publishPlugin] };
```

Always `.releaserc.js`, never `.json` (logic needs a module; the action's config-picker prefers `.js`).
Full real example: `webgrip/infrastructure` `.releaserc.js`. The shared Forgejo `semantic-release.yml`
reusable sets `GITEA_URL`/`GITEA_TOKEN` for the gitea plugin — don't unset them.

## Settings parity + Releases unit

After porting: `scripts/forgejo-sync.sh --repo <name> --apply` enables the Actions + **Releases** units
(gitea-mirror leaves both OFF), the Forgejo→GitHub push-mirror, and branch protection. Without the
Releases unit (`has_releases`) the Releases tab/API **404s** and semantic-release has nowhere to publish.

## Gotchas

- **Never copy — move.** A leftover `.github/workflows/` release job → GitHub double-releases on every
  mirrored commit and diverges from Forgejo. (infra keeps zero `.github/workflows/`.)
- **`[skip ci]` on the commit-back is load-bearing:** the push-mirror replays it to GitHub; without it
  GitHub re-triggers. Honoured by both forges.
- Historical GitHub **releases do not backfill** — only git tags mirror over. New releases start at the
  next bump; consumers that pin `github>owner/repo#vX.Y.Z` resolve by tag, so they keep working.
- Don't migrate a `uses:`-consumer before **webgrip/workflows** is Forgejo-leading (resolve the lib first).
