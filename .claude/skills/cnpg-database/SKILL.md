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

## Backups & DR (mix in as components)
`components: [../../../components/cnpg-backup]` — also `cnpg-monitoring`, `cnpg-disaster-recovery`, `cnpg-restore-test`.

## Gotchas
- Backup S3 creds: Secret `cnpg-backup-s3` (`S3_*` keys). `barmanObjectStore.endpointURL` is a **plain string**, not a SecretKeySelector.
- Objects double-nest: `destinationPath/<cluster>/<cluster>/…`.
- Restore drills no-op once tested — delete ConfigMap `cnpg-restore-test-state` in the ns to force a re-test.

## Validate
Schema `kubernetes/schemas/cnpg-cluster.schema.json` (via `# yaml-language-server: $schema=`). PITR: `docs/techdocs/docs/cnpg-restore-playbook.md`. `./scripts/run-flux-local-test.sh`.
