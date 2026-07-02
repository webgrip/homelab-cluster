# CloudNativePG & Backups

The CNPG ops runbook: how Postgres is provided (one namespace-scoped `Cluster` per app, cluster-wide operator), how backups run (barman-cloud **plugin** → Garage S3), and how to verify and restore. Authoring a new database/backup belongs to the `cnpg-database` skill — this page is triage + ops.

> **Retention is set per database by tier.** How long each cluster's backups and
> WAL are kept — and why — is defined in [Database Backup Tiers](../general/database-backup-tiers.md).

## The moving parts

| Thing | Where |
| --- | --- |
| CNPG operator (`clusterWide: true`) | `kubernetes/apps/cnpg-system/cloudnative-pg/` |
| barman-cloud plugin | `kubernetes/apps/cnpg-system/plugin-barman-cloud/` |
| App database | `kubernetes/apps/<ns>/<app>/app/database/cluster.yaml` (CNPG `Cluster`) |
| Backup target | Garage S3 `http://10.0.0.110:3900`, bucket `cnpg-backups-bucket` — **external** to the cluster (see [Garage outage triage](synthetic-probes-blackbox.md#garage-s3-cnpg-backup-wal-target-unavailable)) |
| Backup config | one `ObjectStore` CR per app (`<app>-db-store`) + a `plugins:` block on the `Cluster` + a `ScheduledBackup` |
| Credentials | Secret `cnpg-backup-s3` — `kubernetes/components/cnpg-backup/cnpg-backup-s3.externalsecret.yaml`, ESO ← OpenBao KV `s3/cnpg-backup` |
| Restore drill | `kubernetes/components/cnpg-restore-test/` (CronJob per app namespace) |
| Warm standby | `kubernetes/components/cnpg-disaster-recovery/` |

Monitoring: CNPG `PodMonitor` + a Grafana dashboard ConfigMap ship with the operator HelmRelease.

## Backup credentials (`cnpg-backup-s3`)

Credentials come from **OpenBao via ESO** — there is no SOPS file. The component
`kubernetes/components/cnpg-backup/` renders an `ExternalSecret` into every namespace that
includes it; ESO materialises Secret `cnpg-backup-s3` with keys `S3_ACCESS_KEY_ID`,
`S3_SECRET_ACCESS_KEY`, `S3_REGION` (`garage`), `S3_ENDPOINT`, `S3_BUCKET` from OpenBao path
`s3/cnpg-backup` (one path, fan-out to all namespaces).

- Include in a namespace: add `- ../../components/cnpg-backup` to `components:` in
  `kubernetes/apps/<ns>/kustomization.yaml`.
- Rotate the key: one `bao kv put`/`patch` on `secret/s3/cnpg-backup` — see
  [Secret rotation](secret-rotation.md#51-component-shared-secrets-that-fan-out-to-many-namespaces),
  then verify a backup completes.

## How a Cluster wires backups (plugin form)

Backups use CNPG's **plugin** method (`barman-cloud.cloudnative-pg.io`), not the legacy in-`Cluster`
`backup.barmanObjectStore`. Real example: `kubernetes/apps/authentik/app/database/{objectstore,cluster,scheduled-backup}.yaml`.

```yaml
# objectstore.yaml — per-app ObjectStore CR (endpoint/path/creds/retention live here)
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: <app>-db-store
spec:
  retentionPolicy: 30d          # per the backup tier
  configuration:
    endpointURL: http://10.0.0.110:3900
    destinationPath: s3://cnpg-backups-bucket/homelab-cluster/<app>-db/
    s3Credentials:
      accessKeyId: {name: cnpg-backup-s3, key: S3_ACCESS_KEY_ID}
      secretAccessKey: {name: cnpg-backup-s3, key: S3_SECRET_ACCESS_KEY}
      region: {name: cnpg-backup-s3, key: S3_REGION}
    wal: {compression: gzip, maxParallel: 1}
    data: {compression: gzip}
---
# cluster.yaml fragment — the Cluster references the ObjectStore via the plugin
spec:
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: <app>-db-store
        serverName: <app>-db
---
# scheduled-backup.yaml fragment
spec:
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
```

Notes: `endpointURL`/`destinationPath` are plain strings (not Secret refs); CNPG writes objects
under `<destinationPath>/<serverName>/...`. Full authoring recipe (walStorage, tiers, drills):
`cnpg-database` skill.

## Force-prune orphaned pre-first-backup WAL

CNPG's `retentionPolicy` (and the barman-cloud plugin's `retentionPolicy` on an
`ObjectStore`) is a **recovery window** (e.g. `3d`), not a WAL age cutoff. It
keeps the oldest base backup needed to restore to N days ago as the window
**anchor**, and only garbage-collects WAL when it actually **deletes a base
backup**.

The trap: **WAL archived before the first-ever base backup is orphaned** (it can
never anchor a restore) but is NOT pruned by normal retention — it only clears
when the anchor backup is deleted, i.e. after it ages fully past the window. A
freshly-enabled backup config therefore leaves a large orphaned-WAL tail that
lingers for the entire window length.

Signs to confirm before acting:

- Bucket usage far larger than the live databases justify, concentrated in the
  WAL prefix.
- The plugin logs `Applying backup retention policy` every ~5 min but deletes
  nothing — running ≠ pruning:

  ```bash
  kubectl logs <db>-1 -c plugin-barman-cloud
  ```

### Force-prune technique (pure GitOps)

Temporarily lower `retentionPolicy` below the anchor backup's age so the anchor
ages out and barman deletes it, GC-ing all WAL before the new oldest backup.
Barman decides what is safe to delete.

1. On the `ObjectStore` (or the `Cluster`'s `backup.retentionPolicy`), commit a
   retention value shorter than the anchor's age — e.g. drop `3d`/`7d` to `2d`.
2. Wait for the next ~5-min retention pass. The anchor ages out, barman deletes
   it and GCs the orphaned WAL. Confirm via the `plugin-barman-cloud` logs
   showing an actual deletion (not just "Applying backup retention policy").
3. **Restore the intended retention value** (per
   [Database Backup Tiers](../general/database-backup-tiers.md)) in a follow-up
   commit.

Alternatively (or additionally), take a fresh base backup to move the anchor
forward, then let retention GC the WAL that precedes it.

Worked example (2026-06-15, `cnpg-backups-bucket` on Garage S3): a newly-added
backup config for `guac-db` + `dependency-track-db` left ~52 GiB of orphaned
pre-first-backup WAL. Dropping retention to `2d` took the bucket
**80 → 20 GiB** (freed ~60 GiB) in ~10 min, after which the documented retention
was restored.

> **Disk reclaim lags the S3 delete.** Garage frees the underlying blocks (and
> thus shrinks the Proxmox backup of the Garage VM) asynchronously via its own
> block GC, up to ~a day after the logical S3 delete.

## Restore / DR drill

### Inspect what's in the bucket

Garage requires SigV4 requests signed with its configured region (`garage`):

```bash
aws --profile garage --region garage --endpoint-url http://10.0.0.110:3900 \
  s3 ls s3://cnpg-backups-bucket/homelab-cluster/ --recursive | head -50
```

### Restore a backup into a temporary cluster

Create a new `Cluster` that bootstraps from the app's existing `ObjectStore` CR via the plugin —
same form the automated drill uses (`kubernetes/components/cnpg-restore-test/cronjob.yaml`):

```yaml
# restore-cluster.yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: <app>-db-restore
  namespace: <ns>              # same ns as the ObjectStore + cnpg-backup-s3 Secret
spec:
  instances: 1
  storage: {size: 10Gi, storageClass: longhorn}
  bootstrap:
    recovery:
      source: clusterBackup
  externalClusters:
    - name: clusterBackup
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: <app>-db-store
          serverName: <app>-db
```

```bash
kubectl apply -f restore-cluster.yaml          # (human step — hook-blocked for agents)
kubectl -n <ns> get cluster <app>-db-restore -w
kubectl -n cnpg-system logs deploy/cloudnative-pg --tail=100   # operator view
```

For **PITR**, add a target under `recovery`:

```yaml
    recovery:
      source: clusterBackup
      recoveryTarget:
        targetTime: "2026-07-01T12:34:00Z"   # must be within the retention window's WAL
```

### Verify, then clean up

```bash
kubectl -n <ns> port-forward svc/<app>-db-restore-rw 5432:5432 &
psql "host=127.0.0.1 port=5432 user=<owner> dbname=<db> password=<from the -app secret>" -c "SELECT count(*) FROM <known_table>;"
kubectl -n <ns> delete cluster.postgresql.cnpg.io <app>-db-restore   # (human step — hook-blocked for agents)
```

Troubleshooting: `Command failed to fetch object` → wrong creds/endpoint/`destinationPath`, or Garage
unreachable from the cluster; `WAL archive missing` during PITR → the target time predates the
retention window or WAL archiving was broken then (check `CNPGWALArchivingFailed` history).

## Restore drills (`cnpg-restore-test`)

The component creates a CronJob per app namespace that is **backup-driven**: it polls for a newly
*completed* CNPG `Backup`, restores it into a temporary cluster (plugin form above), validates
(`SELECT 1` + optional expected DB/role), deletes the temp cluster, and records the tested backup
name in ConfigMap `cnpg-restore-test-state` — one run per new backup, no-op otherwise.

Per-app knobs (`.../app/database/backup/restore-test/cronjob-patch.yaml`): `SOURCE_CLUSTER`,
`RESTORE_CLUSTER`, `BARMAN_OBJECT_NAME` (defaults to `<source>-store`), `EXPECTED_DATABASE`,
`EXPECTED_ROLE`. Some apps ship it `suspend: true` to limit storage pressure — flip in Git to enable.

```bash
# Run a drill now instead of waiting
kubectl -n <ns> create job --from=cronjob/cnpg-restore-test cnpg-restore-test-manual
kubectl -n <ns> logs -l job-name=cnpg-restore-test-manual -c restore-test -f

# "latest completed backup already tested" — force a re-test of the same backup
kubectl -n <ns> delete configmap cnpg-restore-test-state
```

## Always-on disaster recovery (`cnpg-disaster-recovery`)

The component runs a warm-standby `Cluster` named `cnpg-disaster-recovery` in the app namespace:
bootstraps from the same object-store path, stays in recovery, continuously replays WAL, and exports
lag metrics. Per-app patches: `.../app/database/backup/disaster-recovery/{cluster-patch,check-patch}.yaml`.
DR proves "we can stay close to current"; restore drills prove "we can rebuild from backups" — they
don't replace each other.

## Alerting

The CNPG monitoring rules in this repo include three groups:

- `cnpg-backup.rules`: operator down, backup/WAL archiving errors, no recent backup.
- `cnpg-disaster-recovery.rules`: DR metrics missing, promoted DR (not in recovery), WAL receiver down, replay lag high.
- `cnpg-restore-test.rules`: restore drill failed recently, restore drill stale (no recent successful run).

The restore-drill alerts depend on kube-state-metrics exporting CronJob/Job series (for example `kube_cronjob_status_last_successful_time` and `kube_job_status_failed`). If your kube-state-metrics version uses different series or labels, adjust the expressions accordingly.

## Day-2 checks (operator routine)

Use this checklist after upgrades, storage/network changes, or periodically to confirm backups + recovery are actually working.

### 1) Backups are being produced

In the app namespace:

```bash
kubectl -n <ns> get scheduledbackup
kubectl -n <ns> get backups.postgresql.cnpg.io -l cnpg.io/cluster=<cluster> --sort-by=.metadata.creationTimestamp
```

What "good" looks like:

- Backups exist and recent ones show `status.phase=completed`.

### 2) Restore drill is succeeding (and not stale)

```bash
kubectl -n <ns> get cronjob cnpg-restore-test
kubectl -n <ns> get jobs --sort-by=.metadata.creationTimestamp | tail -n 20
kubectl -n <ns> get configmap cnpg-restore-test-state -o yaml
```

If you need to see the last run:

```bash
kubectl -n <ns> logs -l job-name=<job-name> -c restore-test --tail=200
```

What "good" looks like:

- CronJob has a recent `LAST SCHEDULE`.
- Recent Jobs complete successfully.
- `cnpg-restore-test-state` contains the most recent tested backup name.

### 3) Disaster recovery cluster is healthy (warm standby)

```bash
kubectl -n <ns> get cluster cnpg-disaster-recovery
kubectl -n <ns> get pods -l cnpg.io/cluster=cnpg-disaster-recovery
```

What "good" looks like:

- Cluster reports Ready.
- Pods are Running/Ready.
- DR metrics are present in the metrics backend (see `cnpg-disaster-recovery.rules`).

### 4) Alerts are quiet for the right reason

Validate these are not firing:

- `CNPGNoRecentBackup`
- `CNPGWALArchivingFailed`
- `CNPGRestoreTestFailed`
- `CNPGRestoreTestStale`
- `CNPGDisasterRecoveryNotInRecovery`
- `CNPGDisasterRecoveryReplayLagHigh`

## See also

- `cnpg-database` skill — authoring: new DB, walStorage, backup tiers, drills.
- [Dynamic DB credentials](dynamic-db-credentials.md) — OpenBao-minted Postgres creds (freshrss pilot).
- [Secret rotation](secret-rotation.md) — rotating `s3/cnpg-backup`.
- [Garage outage triage](synthetic-probes-blackbox.md#garage-s3-cnpg-backup-wal-target-unavailable) — WAL-archive SPOF behaviour.
