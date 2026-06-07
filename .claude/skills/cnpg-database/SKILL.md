---
name: cnpg-database
description: Add or manage a PostgreSQL database with CloudNativePG, including backups and disaster recovery. Use when an app needs a Postgres DB, or when working with CNPG Cluster resources, backups, or restore drills.
---

# CloudNativePG database

Operator lives in `cnpg-system`. One `Cluster` per app namespace; wire backups/monitoring via shared components rather than hand-rolling Jobs.

## Add a database
1. Create `kubernetes/apps/<ns>/<app>/app/database/cluster.yaml`:
   ```yaml
   apiVersion: postgresql.cnpg.io/v1
   kind: Cluster
   metadata: { name: <app>-db }
   spec:
     instances: 2
     storage: { size: <N>Gi, storageClass: longhorn }       # CNPG uses 'longhorn', not longhorn-general
     walStorage: { size: 5Gi, storageClass: longhorn }      # ALWAYS give pg_wal its own volume (see below)
     # ...
   ```
   The operator auto-creates credential secrets: `<app>-db-app` (app user), `<app>-db-rw` / `<app>-db-ro` (services). Reference these from the app's HelmRelease via `existingSecret`/`envFromSecret` — never inline credentials.

   **Always set `walStorage`.** WAL is only recycled after it's archived to Garage S3; if Garage is unreachable, `pg_wal` grows unbounded. On a shared volume that fills the data disk and the database CrashLoops with `no free disk space for WALs` (this took Grafana + Dependency-Track down — see the [Garage runbook](../../../docs/techdocs/docs/runbooks/synthetic-probes-blackbox.md)). A dedicated WAL volume keeps that pressure off data and lets you resize WAL independently. Size 5Gi default; ~10Gi for heavy writers (Grafana, Dependency-Track). It can be **added to an existing cluster in-place** (rolling restart migrates `pg_wal`) but can **never be removed**.
2. Add the `database/` dir (or `cluster.yaml`) to the app's `kustomization.yaml`.
3. The app's `ks.yaml` should `dependsOn` the database so Flux orders them.

## Backups & DR (shared components — mix into the namespace/app kustomization)
- `kubernetes/components/cnpg-backup` — scheduled backups to Garage S3.
- `kubernetes/components/cnpg-monitoring` — metrics/alerts.
- `kubernetes/components/cnpg-disaster-recovery` — always-on DR.
- `kubernetes/components/cnpg-restore-test` — periodic restore drills.

Add with:
```yaml
components:
  - ../../../components/cnpg-backup
```

## Backup wiring gotchas
- Backup S3 credentials: Secret `cnpg-backup-s3` (generic `S3_*` keys).
- `barmanObjectStore.endpointURL` is a **plain string**, not a SecretKeySelector.
- Objects nest as `destinationPath/<cluster>/<cluster>/…` (double nesting) — account for it when setting paths.
- Restore drills no-op on a backup they've already tested; delete ConfigMap `cnpg-restore-test-state` in the namespace to force a re-test.

## Schema/validation
Local schema: `kubernetes/schemas/cnpg-cluster.schema.json` (reference via `# yaml-language-server: $schema=`). Restore/PITR procedure: `docs/techdocs/docs/cnpg-restore-playbook.md`. Validate with `./scripts/run-flux-local-test.sh`.
