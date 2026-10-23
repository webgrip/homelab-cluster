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

1. The gateway answers `403` to `meta-externalagent` and `facebookexternalhit` on `forgejo.<domain>`
   before the request reaches Forgejo (`HTTPRouteFilter` `forgejo-deny-meta-crawlers`, a header-matched
   rule in the Forgejo `HTTPRoute`). Nothing legitimate shares links to the forge through Meta.
2. `cron.archive_cleanup` runs every hour and removes archives older than one hour, so the cache can
   hold at most one hour of downloads.

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
  the archive links are not covered by the default file anyway.
- Caches that grow per request belong on a bounded schedule, not the upstream default.
- The `AppPersistentVolumeLowFree` rule in `prometheusrule-apps.yaml` covers `forgejo-data`; whether it
  paged before 21:41 is worth checking when the alert history is next reviewed.

Related: [ADR-0065](../adr/adr-0065-forgejo-objects-on-its-own-volume.md) (what shares the volume).
