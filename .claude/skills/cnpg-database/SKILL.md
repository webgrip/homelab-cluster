---
name: cnpg-database
description: Add or manage a PostgreSQL database with CloudNativePG, including backups and disaster recovery. Use when an app needs a Postgres DB, or when working with CNPG Cluster resources, backups, or restore drills.
---

# CloudNativePG database

Operator in `cnpg-system`. One `Cluster` per app namespace; wire backups/monitoring via shared components, not hand-rolled Jobs.

## Add a database
1. `kubernetes/apps/<ns>/<app>/app/database/cluster.yaml` — `kind: Cluster` (`postgresql.cnpg.io/v1`): `instances: 2`, `storage.storageClass: longhorn` (the reserved class, **not** longhorn-general), and **always `walStorage`** (own volume, same class). Both rules enforced by `guard-skills.sh`.
   - **Why walStorage:** WAL only recycles after archiving to Garage S3; if Garage is down, `pg_wal` on a shared volume fills the data disk → DB CrashLoops `no free disk space for WALs` (took Grafana + Dependency-Track down). 5Gi default, ~10Gi heavy writers (Grafana, Dependency-Track). Addable in-place (rolling restart), **never removable**.
   - Operator auto-creates `<app>-db-app` / `<app>-db-rw` / `<app>-db-ro` secrets — reference via `existingSecret`/`envFromSecret`, never inline.
2. Add `database/` to the app `kustomization.yaml`; app `ks.yaml` `dependsOn` the DB.

## Backups & DR — TWO parts, both required
1. **Destination** (components): `components: [../../../components/cnpg-backup]` — also `cnpg-monitoring`,
   `cnpg-disaster-recovery`, `cnpg-restore-test`. Provides the `ObjectStore` + `cnpg-backup-s3` creds.
   **This does NOT schedule backups** — it only configures *where* they'd go + continuous WAL archiving.
2. **Schedule** (per-app file, NOT in any component — easy to forget → DB silently never backed up):
   add `app/database/scheduled-backup.yaml`, wired in the `database/kustomization.yaml` `resources`:
   ```yaml
   apiVersion: postgresql.cnpg.io/v1
   kind: ScheduledBackup
   metadata: {name: <cluster>-daily, namespace: <ns>}
   spec:
     schedule: "0 0 2 * * *"   # 6-field cron (sec min hr ...); STAGGER across apps (02:0x, 02:15, …)
     immediate: true           # take a first backup at deploy, then on schedule
     backupOwnerReference: cluster
     cluster: {name: <cluster>}
     method: plugin
     pluginConfiguration: {name: barman-cloud.cloudnative-pg.io}
   ```
   Backups go through the **barman-cloud plugin** (`plugin-barman-cloud` in `cnpg-system`), not in-tree barmanObjectStore. Omitting this is the gap that left authentik-db/dependency-track-db/guac-db unbacked.

## Gotchas
- Backup S3 creds: Secret `cnpg-backup-s3` (`S3_*` keys). `barmanObjectStore.endpointURL` is a **plain string**, not a SecretKeySelector. (`cnpg-backup-s3` is now ESO-backed from OpenBao via the component — see [[external-secrets-eso-openbao]].)
- Objects double-nest: `destinationPath/<cluster>/<cluster>/…`.
- Restore drills no-op once tested — delete ConfigMap `cnpg-restore-test-state` in the ns to force a re-test. The `cnpg-disaster-recovery` cluster sitting in "error/hibernated" with "Continuous archiving is working" is **normal** post-test (hibernated to 0 instances), not a failure.
- **Verifying backups: the Cluster's `.status.lastSuccessfulBackup` does NOT populate on the plugin path** — check `kubectl get backups.postgresql.cnpg.io -n <ns>` (`PHASE=completed`) or the ScheduledBackup's `lastScheduleTime`, NOT the Cluster status. A large DB's first base backup can take 10–20 min (`pg_basebackup` force-wait checkpoints in the pod log = progressing, not stuck).
- The bootstrap `*-db-secret` you point `bootstrap.initdb.secret` at is used **once** at init; changing it later doesn't reconcile the role. `managed.roles[].passwordSecret` DOES reconcile on change.

## Validate
Schema `kubernetes/schemas/cnpg-cluster.schema.json` (via `# yaml-language-server: $schema=`). PITR: `docs/techdocs/docs/cnpg-restore-playbook.md`. `./scripts/run-flux-local-test.sh`.
