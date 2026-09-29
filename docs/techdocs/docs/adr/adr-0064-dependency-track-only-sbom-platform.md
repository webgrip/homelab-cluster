---
status: accepted
date: 2026-09-29
---

# Dependency-Track is the only SBOM platform; GUAC is removed

Technical Story: VIK-29. Answers proposal 3 of
[RFC: Image signing & verification](../rfc/rfc-image-signing-verification.md) and closes the
"DT + GUAC duplication is undecided" gap it names. The incident that forced the question is
VIK-1405.

## Context and Problem Statement

One SBOM source fed two platforms. The weekly `trivy-sbom-uploader` CronJob posts a CycloneDX SBOM
per running image to Dependency-Track and was meant to copy the same SBOM into a GUAC bucket, which
the weekly `guac-s3-collector` then ingested. The RFC recorded that nobody had weighed whether the
second platform earned its footprint, and leaned towards consolidating on Dependency-Track.

Nobody had to weigh it in the abstract, because GUAC's cost became concrete on 2026-09-28. The
questions for this record are whether GUAC delivered anything Dependency-Track does not, and what
keeping it would take.

### What GUAC cost

| Item | Evidence |
| --- | --- |
| Workloads | 9 Deployments (graphql-server, ingestor, collectsub, oci-collector, depsdev-collector, osv-certifier, cd-certifier, rest-api, visualizer), a NATS JetStream StatefulSet with a 10Gi volume, the `guac-s3-collector` and `guac-db-backup` CronJobs, the `guac-sample-data` Job |
| Database | CNPG `guac-db`, 20Gi data + 5Gi WAL, Tier 4 (no WAL archiving, nightly `pg_dump` of about 1.9 GB gzip to the off-site `guac` bucket) |
| Write load | Chart 0.8.0 ships `guac.common.certifier.dayBetweenRescan: "0"`, which renders `last-scan: 0`. GUAC v1.0.1 reads 0 as "no last scan", so both certifiers re-certified every package on every run, and the chart hard-codes a 5-minute interval. Each document embeds its scan time, so every run produced new content-addressed keys. VictoriaLogs counted about 437,000 blob writes a day from `osv-certifier` and about 270,000 from `cd-certifier` between 2026-09-15 and 2026-09-28 |
| Off-site storage | Once `blobAddr` pointed at the off-site Garage (2026-08-02), those writes landed in bucket `guac`: 36,841,849 objects, 83.4 GiB, average 2.4 KB. Garage stores objects that small inline in its LMDB metadata, which grew to a 115 GB `data.mdb` |
| Outage | The garage-fsn1 root filesystem filled at 2026-09-28 02:33Z. For about 38 hours CNPG WAL archiving failed in 11 clusters, every Longhorn backup failed, OpenBao snapshot uploads failed and Forgejo Actions lost job logs (VIK-1405). The full disk also left 41 data blocks unreadable, 10 of them outside `guac`: 8 CNPG WAL segments (forgejo-db, ploeg-db, vikunja-db), one Longhorn backup block and one Forgejo repository archive |

### What GUAC delivered

- **No cluster SBOM ever reached it.** The uploader installed `mc` from Alpine, which is Midnight
  Commander, not the MinIO client, and it only attempted the copy after Dependency-Track accepted
  the SBOM. Every uploader run retained in VictoriaLogs, the five Sundays from 2026-08-30 to
  2026-09-27, reports 0 uploads out of 242 to 250 images. The `guac-s3-collector` runs of 2026-09-20 and
  2026-09-27 each finished within seconds without downloading a document.
- **The graph held sample data.** The `guac-sample-data` Job ingested the upstream `guac-data`
  documents; the certifiers then scanned the roughly 1,700 package versions those documents name.
- **Triage never used it.** The
  [CVE triage flow](../general/supply-chain-cve-triage.md) runs entirely on Dependency-Track, and no
  runbook, dashboard or alert queried GUAC.

## Decision Drivers

- The off-site Garage is the target of every backup; nothing that is not a backup should be able to
  fill it.
- The hardware is small and memory-constrained; nine workloads, a queue and a database need a
  purpose.
- Evidence of use, not the promise of graph queries, decides what stays.

## Considered Options

- Consolidate on Dependency-Track and remove GUAC
- Dual-run with recorded roles: Dependency-Track for triage and alerting, GUAC for graph forensics
- Keep GUAC and drop Dependency-Track

## Decision Outcome

Chosen option: "Consolidate on Dependency-Track and remove GUAC", because GUAC delivered nothing
the cluster used while its default configuration took down the backup target, and keeping it
would take four repairs before it could deliver its first graph question.

- `kubernetes/apps/security/guac/ks.yaml` is unwired from `kubernetes/apps/security/kustomization.yaml`;
  Flux pruned the Helm release, the collectors, certifiers, ingestor, NATS and both GUAC CronJobs.
- The uploader keeps its Dependency-Track upload and loses the GUAC bridge, the `mc` install and the
  off-site Garage key.
- `guac-db` carries `policy.webgrip.io/allow-stateful-delete: "true"` on the Cluster and, through
  `inheritedMetadata`, on its PVCs, so unwiring `guac/database/ks.yaml` prunes the Cluster and its
  volumes. No final dump is kept: the graph is derived data and the owner does not need it. The
  nightly dumps in `s3://guac/_db-backups/` go with the bucket.
- The off-site bucket `guac` is emptied and deleted, then the Garage key `security` and the OpenBao
  path `secret/s3/security-offsite` are retired.
- `kubernetes/apps/security/guac/`, `kubernetes/components/security-s3/` and the two guac-db Kyverno
  waivers (`exception-guac-db-backup-tier*.yaml`) are deleted once the prune is verified.

### Consequences

- Good, because about ten workloads, a JetStream queue and a CNPG database leave the cluster.
- Good, because the off-site Garage carries backups only; no application writes a work queue to it.
- Good, because one SBOM platform has one pipeline to keep green, and its failures are visible:
  the uploader now logs the HTTP status of a rejected upload.
- Bad, because there is no dependency graph to ask "which images share this package, through
  which path". Dependency-Track's portfolio component search answers the flat version of that
  question.
- Bad, because re-adding GUAC later means solving what this record found: a non-zero rescan window,
  a blob store with expiry and a quota that is not the backup target, and a bridge that works.

### Confirmation

- `kubectl -n security get pods` lists no GUAC workload and `kubectl get clusters.postgresql.cnpg.io -A`
  lists no `guac-db`.
- On garage-fsn1, `garage bucket list` no longer shows `guac`.
- The weekly `trivy-sbom-uploader` Job completes, and `dt_portfolio_projects{state="total"}` in
  VictoriaMetrics does not drop below its 2026-09-29 value of 453.

## Pros and Cons of the Options

### Dual-run with recorded roles

- Good, because graph queries across provenance, SBOMs and advisories stay available.
- Bad, because it needs four repairs first: a rescan window, a bounded blob store, a working
  bridge, and a backup tier for `guac-db`.
- Bad, because it keeps the footprint for a use nobody has had.

### Keep GUAC and drop Dependency-Track

- Bad, because triage, policy evaluation, the metrics exporter and the CI SBOM uploads all run on
  Dependency-Track, and GUAC never held a cluster SBOM.

## More Information

- Technical story: VIK-29; incident VIK-1405.
- 2026-08-02 — `blobAddr` moved under `guac:`, which sent certifier documents to the off-site
  Garage for the first time.
- 2026-09-28 — garage-fsn1 root filesystem full at 02:33Z (VIK-1405).
- 2026-09-29 — the owner decides to consolidate on Dependency-Track; the GUAC release is unwired
  and pruned (3021eaed); the uploader bridge is removed and guac-db armed for deletion (ed21b2cb).
- Mooted by this record: roadmap #59 / VIK-60 (guac-db backup tier), the guac half of VIK-14
  (cnpg-netpol on the guac DB layer) and the guac entry of VIK-58.
- Refines: [RFC: Image signing & verification](../rfc/rfc-image-signing-verification.md),
  proposal 3.
