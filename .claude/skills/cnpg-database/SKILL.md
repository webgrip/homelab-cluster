---
name: cnpg-database
description: Add or manage a PostgreSQL database with CloudNativePG — Cluster, walStorage, ScheduledBackup via barman-cloud, PITR/restore drills.
when_to_use: Use when an app needs a Postgres DB, or when working with CNPG Cluster resources, walStorage, backups, ScheduledBackup, barman-cloud, or pg_dump/PITR restore drills.
---

# CloudNativePG database

Operator in `cnpg-system`. One `Cluster` per app namespace; wire backups/monitoring via shared components, not hand-rolled Jobs.

## Add a database
1. `kubernetes/apps/<ns>/<app>/app/database/cluster.yaml` — `kind: Cluster` (`postgresql.cnpg.io/v1`): `instances: 2`, `storage.storageClass: longhorn` (the reserved class, **not** longhorn-general), and **always `walStorage`** (own volume, same class). Both rules enforced by `guard-skills.sh`.
   - **Why walStorage + sizing:** WAL only recycles after archiving to Garage S3 — if archiving stalls, `pg_wal` fills its volume and the DB CrashLoops `no free disk space for WALs` (took Grafana + Dependency-Track down); a dedicated volume keeps that off the data disk, but an *undersized* one deadlocks the same way. 5Gi default, ~10Gi heavy writers (Grafana, Dependency-Track). Adding one to an *already-backlogged* writer: size it ≥ the **current** `pg_wal` backlog (measure via `kubelet_volume_stats_used_bytes`), not steady state — on first start CNPG *migrates* `pg_wal` into it, and a backlog > `walStorage.size` kills the instance-manager (`no space left on device`) **before Postgres starts**, so it can never archive out. Addable in-place (rolling restart), **never removable**.
   - Operator auto-creates `<app>-db-app` / `<app>-db-rw` / `<app>-db-ro` secrets — reference via `existingSecret`/`envFromSecret`, never inline.
2. Add `database/` to the app `kustomization.yaml`; app `ks.yaml` `dependsOn` the DB.

## Placement
A CNPG DB is a stateful app → **worker pool**: add `components/placement/worker-pool` to the kustomization
that builds `database/` (it patches `Cluster.spec.affinity.nodeSelector`). CNPG DBs use the `longhorn` SC
(Immediate binding → no PV node lock), so an *existing* DB pins **immediately** — no eviction wait, the WFFC
caveat doesn't apply. StorageClass guidance → the `longhorn` skill. Full placement/sequencing rule → the
`workload-placement` skill.

## Backups & DR — TWO parts, both required
1. **Destination** (components): `components: [../../../components/cnpg-backup]` — also `cnpg-monitoring`,
   `cnpg-disaster-recovery`, `cnpg-restore-test`. Provides the `ObjectStore` + `cnpg-backup-s3` creds.
   **This does NOT schedule backups** — it only configures *where* they'd go + continuous WAL archiving.
2. **Schedule** (per-app file, NOT in any component — easy to forget → DB silently never backed up):
   add `app/database/scheduled-backup.yaml` (wired in `database/kustomization.yaml`). Copy
   `kubernetes/apps/authentik/app/database/scheduled-backup.yaml`. Must-not-miss: `method: plugin` +
   `pluginConfiguration.name: barman-cloud.cloudnative-pg.io` (the **barman-cloud plugin** in `cnpg-system`,
   NOT in-tree barmanObjectStore); 6-field cron `schedule` (sec min hr …) **staggered** across apps
   (02:0x, 02:15, …); `immediate: true`. Omitting this is the gap that left
   authentik-db/dependency-track-db/guac-db unbacked.

## Gotchas
- Backup S3 creds: Secret `cnpg-backup-s3` (`S3_*` keys). `barmanObjectStore.endpointURL` is a **plain string**, not a SecretKeySelector. (`cnpg-backup-s3` is now ESO-backed from OpenBao via the component — see the `external-secrets` skill.)
- Objects double-nest: `destinationPath/<cluster>/<cluster>/…`.
- **Recovery-window retention won't GC pre-first-backup WAL** until the anchor backup ages out — WAL can pile up in S3. Force-prune via a temporary lower retention (`docs/techdocs/docs/runbooks/cnpg-backups.md`).
- **Zero-trust namespace?** the DB-layer ks needs `components/cnpg-netpol` or cnpg-system can't poll the instance :8000 → `ClusterIsNotReady` deadlock — see the `network-policy` skill.
- Restore drills no-op once tested — delete ConfigMap `cnpg-restore-test-state` in the ns to force a re-test. The `cnpg-disaster-recovery` cluster sitting in "error/hibernated" with "Continuous archiving is working" is **normal** post-test (hibernated to 0 instances), not a failure.
- **Verifying backups: the Cluster's `.status.lastSuccessfulBackup` does NOT populate on the plugin path** — check `kubectl get backups.postgresql.cnpg.io -n <ns>` (`PHASE=completed`) or the ScheduledBackup's `lastScheduleTime`, NOT the Cluster status. A large DB's first base backup can take 10–20 min (`pg_basebackup` force-wait checkpoints in the pod log = progressing, not stuck).
- The bootstrap `*-db-secret` you point `bootstrap.initdb.secret` at is used **once** at init; changing it later doesn't reconcile the role. `managed.roles[].passwordSecret` DOES reconcile on change.
- **Operator + `plugin-barman-cloud` both run 1 replica → leader election OFF.** Their HelmRelease values set `additionalArgs: [--leader-elect=false]`. With a single replica, leader election only *causes* "leader election lost" restarts (a missed lease renewal during a transient API/etcd blip → the controller-runtime manager exits/restarts → can interrupt an in-progress backup). Keep this on any reinstall/upgrade. The chart hardcodes `--leader-elect`; the appended `--leader-elect=false` wins (pflag last value).

## Validate
Schema `kubernetes/schemas/cnpg-cluster.schema.json` (via `# yaml-language-server: $schema=`). PITR/restore drill: `docs/techdocs/docs/runbooks/cnpg-backups.md`. `./scripts/run-flux-local-test.sh`.
