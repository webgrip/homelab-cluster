# Forgejo CI console

One page at `forgejo.<domain>/-/ci` that shows CI for every repository you can see, lets you
stop and re-run runs (one, or many at once), and embeds the Grafana CI panels next to it.
A **CI** link sits in the Forgejo navbar for signed-in users.

## What is on it

| View | Shows | Acts |
| --- | --- | --- |
| Stat strip | running and queued runs (oldest wait), failures, success rate, median run time and queue wait over 24 hours, runners busy of online | each tile filters the run list or opens the Runners view |
| Runs | every run across repositories, in-progress first, then grouped by day; title, repository, workflow, run number, branch or pull request, trigger, actor, duration | stop (two clicks), re-run, select many (checkbox, Shift+click, `x`) and stop or re-run them together; expand a run to see its jobs and re-run one job |
| Repositories | default-branch health, failures in a row on trunk, the last 20 runs as a strip, 24 h success rate and median duration | jump to that repository's runs |
| Runners | jobs waiting for a runner, by label; every runner with status, labels, scope, version | — |
| Insights | Grafana panels from the `forgejo-ci-console` dashboard, with a 6 h / 24 h / 7 d / 30 d range | open any panel or the full Forgejo CI board in Grafana |

Keyboard: `/` search, `j`/`k` move, `x` select, `Enter` jobs, `o` open, `Esc` clear.
Filters live in the URL, so a filtered view can be bookmarked or shared.

## How it is built

Forgejo has no custom routes, so the page is a static asset:

- `wg-ci.html`, `wg-ci.js`, `wg-ci.css` and the generated `wg-ci-panels.json` ship in the
  `forgejo-custom-assets` ConfigMap next to the rest of the [Actions UI customisation](forgejo.md)
  and are served from `/assets/wg/`. Updating them needs no Forgejo restart.
- The `forgejo` HTTPRoute rewrites the exact path `/-/ci` to `/assets/wg/wg-ci.html`.
- The page loads Forgejo's own `index.css` and the signed-in user's theme, so it follows
  light, dark and auto like the rest of Forgejo.

### Reading: OAuth2 with PKCE

The Forgejo API does not accept the browser session cookie, so reading every repository,
private ones included, needs a token. The page is an OAuth2 public client:

1. `ci-console-oauth-provisioner` (CronJob in `forgejo-actions-secrets`, every 20 minutes)
   makes sure an OAuth2 application named `CI console` exists, public (no client secret),
   with the redirect URI `<ROOT_URL>/-/ci`. It reads `ROOT_URL` from Forgejo's OpenID
   discovery document, so no domain is written in git.
2. It writes the client id into the ConfigMap `forgejo-ci-console-oauth`, which is projected
   into the same `/assets/wg/` directory as `wg-ci-oauth.json`. The ConfigMap carries the
   Reloader ignore annotation, so a rewrite does not restart Forgejo.
3. The page sends you through Forgejo's authorize screen once per browser, asking for
   `read:repository read:user read:organization read:admin` only. Forgejo shows that screen
   on every new authorization for a public client (RFC 6749 §10.2); after that the page
   refreshes its token in the background, and a refresh token is valid for 30 days of
   inactivity.
4. Tokens live in the browser's `localStorage`. Token refresh runs under a Web Lock, so
   several open tabs never spend the same single-use refresh token twice.

### Acting: Forgejo's own web routes

Stop and re-run use the same endpoints as the Actions page
(`/{owner}/{repo}/actions/runs/{n}/cancel|rerun` and `/jobs/{i}/rerun`) with the session
cookie. Forgejo 15 checks these with Go's cross-origin protection (`Sec-Fetch-Site`), which
a same-origin page passes, and authorises each one against your write access to that
repository. The read token cannot stop or re-run anything.

### Polling budget

The run list endpoint returns about 13 KB per run (it embeds the repository and the event
payload) and Forgejo does not compress API responses. The page therefore polls
adaptively instead of re-reading everything:

| Repository state | Poll | Page size |
| --- | --- | --- |
| a run is in progress | every 8 s | 5 newest runs, plus each in-progress run by id |
| had a run in the last 14 days | every 45 s | 5 newest runs; reads further pages only when all 5 are new |
| quiet | every 10 min | 5 newest runs |
| first load | once | pages of 20 until the 24-hour window is covered (at most 5 pages) |

Polling stops while the tab is hidden and can be paused from the header. Runners and the
job queue are read every 15 s.

`limit` on `/repos/{owner}/{repo}/actions/runs` is ignored unless `page` is also given:
without `page`, Forgejo 15 returns every run the repository ever had (44 MB for
homelab-cluster). The page always sends both.

### Stats

All 24-hour numbers are computed in the browser from the runs it has loaded, which cover
the full 24 hours for every repository. Success rate counts success against failure only;
cancelled and skipped runs are left out. Queue wait is `started − created`, ignoring
samples over six hours, because a re-run keeps its original `created` time.

Trends over longer ranges come from the exporter metrics behind the Grafana panels; see
[Forgejo CI telemetry](forgejo-ci-telemetry.md).

### Grafana panels

`scripts/dashboards/forgejo_ci.py` builds the `forgejo-ci-console` dashboard from the same
panel functions as the Forgejo CI board, gives each panel a fixed id, and writes
`wg-ci-panels.json` next to the page. The page embeds each panel with `/d-solo/`, so a panel
moved or added in the generator moves on the console too, and `generate.py --check` fails CI
if the two drift.

Embedding needs `security.allow_embedding` on the Grafana instance, which drops Grafana's
`X-Frame-Options: deny`. Grafana is only on the internal gateway. Forgejo and Grafana share a
registrable domain, so Grafana's `SameSite=Lax` session cookie is sent inside the frame; if
you have no Grafana session yet, the frame stays blank until you sign in to Grafana once in
a normal tab.

## Version coupling

The page depends on Forgejo 15.x behaviour: the run list and run view JSON shapes, the
web routes for cancel and re-run, the navbar markup the CI link is inserted into, and
OAuth2 scope handling. Re-check them on a Forgejo major upgrade, as for the rest of the
Actions UI customisation.

## Verifying it

- `kubectl -n forgejo get configmap forgejo-ci-console-oauth -o yaml` shows the client id.
- Open `/-/ci`, connect once, and the stat strip should read every repository
  (`across N repositories` under it, with no repositories failing to load).
