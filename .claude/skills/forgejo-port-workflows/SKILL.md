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

The two load-bearing lines (full real config: `webgrip/infrastructure` `.releaserc.js`):

```js
const onForgejo = !!process.env.GITEA_ACTIONS;   // the gate — intrinsic; never a vars.* lookup
// commit-back (Forgejo only): message: 'chore(release): v${nextRelease.version} [skip ci]\n\n${nextRelease.notes}'
```

Always `.releaserc.js`, never `.json` (logic needs a module; the action's config-picker prefers `.js`).
The shared Forgejo `semantic-release.yml` reusable sets `GITEA_URL`/`GITEA_TOKEN` for the gitea plugin —
don't unset them.

## Settings parity

Post-port parity (`scripts/forgejo-sync.sh`) → the **forgejo-leading** skill. Port-specific fact: without
the **Releases** unit (`has_releases`) the Releases tab/API **404s** and semantic-release has nowhere to publish.

## Gotchas

- **Never copy — move.** A leftover `.github/workflows/` release job → GitHub double-releases on every
  mirrored commit and diverges from Forgejo. (infra keeps zero `.github/workflows/`.)
- **`[skip ci]` on the commit-back is load-bearing:** the push-mirror replays it to GitHub; without it
  GitHub re-triggers. Honoured by both forges.
- Historical GitHub **releases do not backfill** — only git tags mirror over. New releases start at the
  next bump; consumers that pin `github>owner/repo#vX.Y.Z` resolve by tag, so they keep working.
- Don't migrate a `uses:`-consumer before **webgrip/workflows** is Forgejo-leading (resolve the lib first).
- **Semantic Release `verifyConditions` fails in ~1 min?** The gitea plugin needs `GITEA_URL`; set it to
  `github.server_url`, the runner's intrinsic Forgejo instance URL. (Plugin *selection* is the
  `GITEA_ACTIONS` gate — separate concern from its *URL*.)

## Hard-won facts — 2026-07-18 port campaign (telemetry/common-charts/a-t-t/traefik/ledgerflow)

- **Secrets: Forgejo RESERVES the `FORGEJO_`/`GITHUB_`/`GITEA_` prefixes** — a stored secret named
  `FORGEJO_TOKEN` cannot exist (PUT 400), so `${{ secrets.FORGEJO_TOKEN }}` resolves **empty**. The CI
  bot token is the org secret **`WEBGRIP_CI_TOKEN`**; callers pass
  `FORGEJO_TOKEN: ${{ secrets.WEBGRIP_CI_TOKEN }}` into reusables (declaring `FORGEJO_TOKEN` as a
  workflow_call *parameter* is fine). The semantic-release composite survives an empty token
  (`inputs.token || github.token`); **`update_techdocs`/`techdocs-deploy-gh-pages` do NOT** (raw
  `git push https://bot:$TOKEN@…`). Provisioned org secrets: `WEBGRIP_CI_TOKEN`,
  `HARBOR_ROBOT_USER/TOKEN` (→ `helm-chart-push` REGISTRY_* + `registry: harbor.webgrip.dev`),
  `DT_API_KEY`; var `WEBGRIP_CI_BOT_NAME` (provisioner: `forgejo-actions-secrets.cronjob.yaml`).
- **JS actions cannot run inside a `container:` whose image lacks Node** (`actions/checkout`,
  `actions/cache`, `setup-*` all die before step logic). Fix: plain `git clone` step + per-job
  dependency install; for PHP use `container: composer:2.8.5` (ships php 8.4 + composer + **git** —
  `php:*-cli` has NEITHER git nor composer). The **native `docker` runner** has node v20 (externals,
  on PATH), php 8.3, composer, git, buildx — JS actions work there; `webgrip/techdocs-runner` also
  ships node (COPY'd from its node build stage), so the techdocs reusables keep `actions/checkout`.
- **The composite installs a FIXED plugin set** (`npm install --no-save`: changelog,
  commit-analyzer, exec, git, gitea, helm3, release-notes-generator, conventionalcommits). A
  `.releaserc.js` Forgejo branch referencing anything else (`@semantic-release/npm`,
  `semantic-release-github-actions-tags`) **fails at plugin-load on every run**, releasable commit or
  not — keep those GitHub-branch-only.
- **Services are addressed by NAME, not 127.0.0.1**: on this runner every job is a container job, so
  `services:` join the job network (`DB_HOST=postgres`, `REDIS_HOST=redis`). GitHub's
  host-port-mapping idiom (`127.0.0.1:5432`) silently can't connect.
- **Observing runs**: `GET /repos/<o>/<r>/actions/tasks` lists only **runner-ASSIGNED** tasks
  (statuses running/success/failure/skipped — never "waiting"), so queued work is INVISIBLE and the
  apparent "lag" is really queue depth: minutes when idle, **hours** when the 2–6-runner pool is
  saturated. `total_count: 0` can mean "still queued" just as well as "never created" — the two are
  indistinguishable from this API; only the web UI (`/<o>/<r>/actions`) shows waiting/blocked runs.
  Never conclude "didn't trigger" from it (cost two misdiagnoses). No job-log API, no artifacts API —
  step output is web-UI-only. Agent-debuggable substitute: a probe job that captures output to a
  file and force-pushes it to a `ci-diag` branch (readable via the contents API), plus pass/fail
  isolation jobs (one suspect step each).
- **Cascade tell**: a matrix job "failing" with **no per-entry tasks** (no Unit/Integration/…) means
  the matrix never ran — the failure is upstream in `needs:`, not in the tests.
- **Caller job id must ≠ the reusable's inner job id** (v15 flattens; e.g. caller `semantic-release`
  calling semantic-release.yml → rename the caller `release`). Inner ids: composer-install→
  `composer-install-on-container`, static-analysis→`static-analysis-run`(+`composer-normalize`),
  tests→`tests-run`, semantic-release→`semantic-release`, gha-javascript-lint→`eslint`,
  techdocs-generate→`generate-techdocs`, techdocs-deploy-gh-pages→`deploy-gh-pages`.
- **Reality check that reframed risk**: the org's GitHub CI had been dead for months (`arc-runner-set`
  runners no longer exist; runs sit `queued` forever), so ports are CI *restoration* — removing
  `.github/workflows` protects nothing and cannot double-release in practice. Keep move-not-copy anyway.
