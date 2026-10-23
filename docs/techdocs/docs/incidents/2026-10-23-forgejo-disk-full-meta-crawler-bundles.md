# Incident 2026-10-23 — Meta's crawler downloads a git bundle per commit → `forgejo-data` full → releases and PR checks fail

**Severity:** SEV2 (Forgejo could not write: the Unfold rc.109 release failed, PR status checks could not be queued, mirror syncs failed; reads kept working)
**Duration:** 2026-10-23 ~21:41 UTC (first write error) → open at the time of writing. Growth started 2026-10-22 ~13:00 UTC.
**Data loss:** none. Every write that failed was a retryable one (package blob uploads, queue entries, archive generation).

## Summary

`meta-externalagent/1.1`, Meta's AI-training crawler, walked the commit pages of the public mirrors on
Forgejo and fetched the "download bundle" link of each commit it found, mostly on `webgrip/renovate`
(a 167 MB mirror with a long history) and `tj-actions/changed-files`. Forgejo generates a git bundle per
requested commit and caches it under `/data/repo-archive` until the `archive_cleanup` cron removes it,
which by default runs at midnight and only removes archives older than 24 hours. The crawler asked for
438 bundles in about 33 hours, 21.6 GB of cache, on the 40 GiB `forgejo-data` volume that also holds
the package registry (13.6 GB), repositories, LFS and action logs. The volume hit 100 % at 21:41 UTC.

The first visible failure was the Unfold release job for `unfold-v0.4.0-rc.109`
([run 2180, job 5](https://forgejo.webgrip.dev/webgrip/unfold/actions/runs/2180/jobs/5)): `regctl image copy`
of `unfold-agent` from Harbor to the Forgejo registry got `500` on the blob upload, then `416 Requested
Range Not Satisfiable` on every retry, because Forgejo had written a partial upload file and could not
append to it. Forgejo's own log says why: `write /data/tmp/package-upload/...: no space left on device`.

## Impact

- Unfold rc.109 published nothing: the Forgejo registry is the first destination, so GHCR, the
  evidence asset and the GitHub mirror were never reached. A re-run of the job after the volume is
  freed publishes everything (the copies are idempotent).
- Every PR's status checks could not be queued (`AddToTaskQueue ... no space left on device`), and the
  repository mirrors stopped syncing (`MirrorsIterate: write /data/queues/common/...`).
- Archive downloads for everyone, including the crawler, answered 500.

## Timeline (UTC)

| Time | Event |
| --- | --- |
| 2026-10-22 ~13:00 | First cached bundles for `webgrip/renovate` appear in `/data/repo-archive/53`. |
| 2026-10-23 19:50 → 21:56 | In the two hours the gateway log still holds, `meta-externalagent` makes 5968 of the 8001 requests to `forgejo.webgrip.dev` (75 %). |
| 21:41:25 | `EndUploadBlob ... no space left on device` while the rc.109 release copies `unfold-agent`. |
| 21:43:24 | Release job fails after regctl's retries end in HTTP 416. |
| 21:56 | PR check queue and mirror queue writes fail on the same volume. |
| 22:10 | Diagnosis: `/data/repo-archive` 21.6 GB, all files younger than 33 hours, all `.bundle`; the gateway access log names the crawler. |

## Root cause

Forgejo's per-commit bundle download is an unbounded cache keyed by commit, and a crawler that follows
every "download" link turns a repository's history into disk usage: the bundle for a 167 MB repository
is 100–400 MB, and the mirror has thousands of commits. The default cleanup (once a day, older than 24
hours) allows a day of growth, which at the observed rate is about 15 GB, more than the volume had free.
`robots.txt` does not help: Forgejo's default disallows `/*/*/src/` but not `/*/*/archive/`, and the
commit pages that link the bundles are allowed.

## Fix

1. The gateway answers `403` to AI-training and data crawlers on `forgejo.<domain>` before the request
   reaches Forgejo (`HTTPRouteFilter` `forgejo-deny-meta-crawlers`, a user-agent-matched rule in the
   Forgejo `HTTPRoute`). The list is the training and bulk-scraping agents from
   [ai-robots-txt/ai.robots.txt](https://github.com/ai-robots-txt/ai.robots.txt), plus Meta's three
   agents. Deliberately not on it: agents a person triggers (`ChatGPT-User`, `Claude-User`,
   `Perplexity-User`), coding agents (`Claude-Code`, `opencode`, `Codex`, `Cursor`, `Devin`) that
   Unfold and the owner's own tooling use against this forge, and search engines. The match runs on
   the honest user-agent only; a crawler that spoofs a browser passes it and is a separate problem
   (rate limits on expensive paths or a proof-of-work gate such as Anubis).
2. `cron.archive_cleanup` runs every hour and removes archives older than one hour, so the cache can
   hold at most one hour of downloads.
3. The gateway rate-limits the expensive paths per route, whatever the user agent says
   (`BackendTrafficPolicy` `forgejo-expensive-paths`, Envoy local rate limit, answers `429`):
   archives 10 a minute, compare pages 20, blame and commit-list pages 30 each. People browsing
   stay far below these (the busiest human minute in the gateway log was 6 blame pages), the
   crawler peaked at 22 commit-list pages a minute. Git over HTTP, the API, the registry, raw files
   and LFS are not limited. The limit is per Envoy replica, not per client, so it caps the damage a
   spoofed-browser botnet can do rather than identifying it. Such a botnet is already here: in the
   half hour after the user-agent block went live, 611 distinct addresses with browser user agents
   hit the forge, 585 of them exactly once, Chrome versions 101 to 140, many from Alibaba Cloud
   ranges.
4. (2026-10-24) A crawler that spoofs a browser now meets [Anubis](https://github.com/TecharoHQ/anubis),
   a proof-of-work gate in front of Forgejo's web UI (`kubernetes/apps/forgejo/anubis`). The
   catch-all rule of the Forgejo `HTTPRoute` sends traffic to Anubis, which proxies to
   `forgejo-http:3000`. Anubis runs its default policy: a client whose user-agent looks like a browser
   (`Mozilla`/`Opera`) solves a challenge once and gets a signed cookie for a week; git, docker,
   Forgejo runners, `tea`, `curl` and other non-browser clients pass without one. The registry paths
   (`/v2`, `/api/packages`) bypass Anubis at the gateway, so image and package traffic never depends
   on it. The gateway sets `X-Real-IP` from Envoy's client address (after the one trusted
   `X-Forwarded-For` hop of the Cloudflare tunnel), and the cookie is bound to that IP. One replica,
   in-memory challenge store; the HS512 signing secret comes from `password-generator`, so cookies
   survive restarts. Anubis down means the Forgejo web UI answers 503; `blackbox-forgejo` probes
   `/api/healthz` through the same route and catches it.

## Recovery

Free the volume by deleting the cached archives. Forgejo regenerates any it still needs, and a missing
file behind a `repo_archiver` row makes Forgejo regenerate it rather than fail:

```sh
kubectl -n forgejo exec deploy/forgejo -c forgejo -- find /data/repo-archive -type f -delete
kubectl -n forgejo exec deploy/forgejo -c forgejo -- df -h /data
```

The same can be done from the web UI as the admin: Site administration → Monitoring → Cron tasks →
"Delete all repositories' archives". Then re-run the failed release job; its copies are idempotent.

## Lessons

- A public Forgejo with big mirrors needs crawler rules at the gateway. `robots.txt` is advisory and
  the archive links are not covered by the default file anyway. The same crawler filled a public
  Forgejo mirror's disk with 573 GB of archives in 2026-08 while ignoring that instance's `robots.txt`
  ([blog.philipp.info](https://blog.philipp.info/2026/08/residential-proxy-crawlers-on-a-public-forgejo-mirror/)),
  and that write-up reports `DISABLE_DOWNLOAD_SOURCE_ARCHIVES` only hides the button, not the
  `/archive/` endpoint.
- Caches that grow per request belong on a bounded schedule, not the upstream default.
- The `AppPersistentVolumeLowFree` rule in `prometheusrule-apps.yaml` covers `forgejo-data`; whether it
  paged before 21:41 is worth checking when the alert history is next reviewed.

Related: [ADR-0065](../adr/adr-0065-forgejo-objects-on-its-own-volume.md) (what shares the volume).
