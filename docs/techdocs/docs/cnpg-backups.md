# CloudNativePG & Backups

This page documents how PostgreSQL is provided as a platform service via CloudNativePG (CNPG) and how this repo models S3-compatible backups.

- CNPG operator is installed cluster-wide in the `cnpg-system` namespace via Helm + Flux.
- Application databases are created as namespace-scoped CNPG `Cluster` resources (one cluster per app).
- Backup credentials (if/when enabled) are provided via a reusable Secret named `cnpg-backup-s3` (S3-compatible, not provider-specific).
- Backups are validated continuously via an in-cluster restore drill (`cnpg-restore-test`).
- For a warm-standby option, each app namespace can also run an always-on disaster recovery cluster (`cnpg-disaster-recovery`).

---

## CloudNativePG operator

### Location in repo

- Namespace and app:
  - `kubernetes/apps/cnpg-system/kustomization.yaml`
  - `kubernetes/apps/cnpg-system/namespace.yaml`
  - `kubernetes/apps/cnpg-system/cloudnative-pg/ks.yaml`
  - `kubernetes/apps/cnpg-system/cloudnative-pg/app/{kustomization,helmrepository,helmrelease}.yaml`

### Behavior

- Operator is installed as a HelmRelease in namespace `cnpg-system`.
- `clusterWide: true` is set so CNPG `Cluster` resources in any namespace are managed by this single operator.
- Monitoring is enabled:
  - Prometheus `PodMonitor` for CNPG metrics.
  - A Grafana dashboard is published as a `ConfigMap` labeled `grafana_dashboard=1` so existing Grafana sidecars/operators can auto‑import it.

CNPG is used for application-scoped PostgreSQL clusters (for example, FreshRSS, Backstage, SparkyFitness).

---

## Backup credentials component (`cnpg-backup-s3`)

This repository includes a reusable component you can include in any namespace that should have backup credentials available:

 - `kubernetes/components/cnpg-backup/`

Backups are configured via CNPG's `backup.barmanObjectStore` and a reusable Secret component.

### Location

- `kubernetes/components/cnpg-backup/kustomization.yaml`
- `kubernetes/components/cnpg-backup/backup-credentials.sops.yaml`

### Secret schema

The component defines a Secret named `cnpg-backup-s3` with generic S3 field names:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cnpg-backup-s3
stringData:
  S3_ACCESS_KEY_ID: CHANGE_ME_ACCESS_KEY
  S3_SECRET_ACCESS_KEY: CHANGE_ME_SECRET_KEY

  # Connection parameters for your S3-compatible endpoint
  S3_REGION: "local"                      # arbitrary label, kept consistent everywhere
  S3_ENDPOINT: "https://s3.example.local"  # S3-compatible endpoint URL
  S3_BUCKET: "cnpg-backups-bucket"        # bucket dedicated to CNPG backups
```

These keys are plain S3-style names that will be mapped explicitly into CNPG's `barmanObjectStore.s3Credentials`.

### How to fill and encrypt

Edit the SOPS-encrypted file in place so no plaintext Secret is committed.

1. Edit the secret with SOPS:

  ```bash
  sops kubernetes/components/cnpg-backup/backup-credentials.sops.yaml
  ```

2. Set/update these keys under `stringData`:

- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_REGION` (for Garage, commonly `garage`)
- `S3_ENDPOINT` (for example `http://10.0.0.110:3900`)
- `S3_BUCKET` (in this homelab: `cnpg-backups-bucket`)

### How to include in a namespace

Any namespace that will host CNPG `Cluster` resources should include this component in its Kustomization, for example:

```yaml
# kubernetes/apps/my-app-namespace/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: my-app-namespace
components:
  - ../../components/sops
  - ../../components/cnpg-backup   # adds cnpg-backup-s3 Secret to this namespace
resources:
  - namespace.yaml
  - my-app/ks.yaml
```

Flux will then render the `cnpg-backup-s3` Secret into that namespace, ready to be referenced by CNPG.

---

## How CNPG will use this (example)

When you are ready to create a PostgreSQL cluster, you'll define a CNPG `Cluster` with `backup.barmanObjectStore` pointing at your S3 bucket and using the `cnpg-backup-s3` Secret for credentials.

Below is an example fragment (not currently applied in the repo) showing how to wire the secret into CNPG:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: example-db
  namespace: my-app-namespace
spec:
  instances: 3

  # [...] storage, resources, and ingress omitted for brevity

  backup:
    retentionPolicy: 30d
    barmanObjectStore:
      # NOTE: endpointURL is a plain string in CNPG (not a SecretKeySelector)
      endpointURL: http://10.0.0.110:3900
      destinationPath: s3://cnpg-backups-bucket/homelab-cluster/example-db/
      s3Credentials:
        accessKeyId:
          name: cnpg-backup-s3
          key: S3_ACCESS_KEY_ID
        secretAccessKey:
          name: cnpg-backup-s3
          key: S3_SECRET_ACCESS_KEY
        region:
          name: cnpg-backup-s3
          key: S3_REGION
      wal:
        compression: gzip
      data:
        compression: gzip
```

Key points:

- The only coupling between CNPG and your object store is the S3 API (endpoint + credentials).
- All sensitive values live in `cnpg-backup-s3`, encrypted with SOPS and injected by the `cnpg-backup` component.
- No AWS‑specific names or services are used; everything is expressed in terms of generic S3 semantics.

Notes:

- `endpointURL` and `destinationPath` are not secret and are set directly in each `Cluster` manifest.
- This repo's `cnpg-backup-s3` Secret may also contain `S3_ENDPOINT` / `S3_BUCKET` for human convenience, but CNPG's `barmanObjectStore` API does not support sourcing those as Secret references.

When you introduce or update application databases, copy this pattern into their CNPG `Cluster` definitions and adjust only:

- `metadata.name` / `namespace`
- `destinationPath` (e.g. per‑cluster prefix)
- any performance/retention tuning under `backup.barmanObjectStore`.

---

## Restore & PITR

See [docs/techdocs/docs/cnpg-restore-playbook.md](cnpg-restore-playbook.md) for a practical restore/PITR playbook.

---

## Restore drills (`cnpg-restore-test`)

This repo includes a reusable restore drill component:

- `kubernetes/components/cnpg-restore-test/`

It creates a `CronJob` named `cnpg-restore-test` inside the application namespace.

### What it does

- Polls for a newly *completed* CNPG Backup object for the source cluster.
- When a new completed backup appears, it creates a temporary restore cluster (for example `backstage-db-restore`) using `bootstrap.recovery` + `externalClusters.barmanObjectStore`.
- Waits for it to become Ready, then runs a validation query.
- Optionally verifies an expected database and role exist.
- Deletes the temporary restore cluster.
- Records the last tested backup name in a namespace ConfigMap `cnpg-restore-test-state` so it runs once per new backup.

### How it is configured per app

Each app database kustomization includes the component and patches it (example layout):

- `kubernetes/apps/<app>/<app>/app/database/backup/restore-test/cronjob-patch.yaml`

The patch sets:

- `SOURCE_CLUSTER` (the production CNPG Cluster name)
- `RESTORE_CLUSTER` (the temporary restore cluster name)
- `DESTINATION_PREFIX` (usually `homelab-cluster`)
- `EXPECTED_DATABASE` (optional)
- `EXPECTED_ROLE` (optional)

### Operational notes

- This is intentionally backup-driven (not “run at 02:45 and hope the backup finished”). The CronJob can run frequently and will no-op unless it sees a new completed backup.
- To force a rerun for the most recent backup, delete the state ConfigMap in that namespace:

```bash
kubectl -n <ns> delete configmap cnpg-restore-test-state
```

---

## Always-on disaster recovery (`cnpg-disaster-recovery`)

This repo includes a reusable always-on DR component:

- `kubernetes/components/cnpg-disaster-recovery/`

It creates a CNPG `Cluster` named `cnpg-disaster-recovery` in the app namespace.

### What it does

- Bootstraps from the object-store backup + WAL path for the source cluster.
- Stays in recovery mode and continuously replays WAL (warm standby).
- Exposes metrics using CNPG’s built-in exporter plus custom queries.

### How it is configured per app

Each app patches the externalClusters destinationPath so the DR cluster follows the correct production cluster backup path:

- `kubernetes/apps/<app>/<app>/app/database/backup/disaster-recovery/cluster-patch.yaml`

Optionally, each app also patches the DR “synthetic check” CronJob schedule and lag threshold:

- `kubernetes/apps/<app>/<app>/app/database/backup/disaster-recovery/check-patch.yaml`

### Operational notes

- Because this repo uses one namespace per app, `cnpg-disaster-recovery` can be the same name in every namespace without collisions.
- DR does not replace restore drills: DR proves “we can stay close to current,” restore drills prove “we can rebuild from backups.”

---

## Alerting

The CNPG monitoring rules in this repo include three groups:

- `cnpg-backup.rules`: operator down, backup/WAL archiving errors, no recent backup.
- `cnpg-disaster-recovery.rules`: DR metrics missing, promoted DR (not in recovery), WAL receiver down, replay lag high.
- `cnpg-restore-test.rules`: restore drill failed recently, restore drill stale (no recent successful run).

The restore-drill alerts depend on kube-state-metrics exporting CronJob/Job series (for example `kube_cronjob_status_last_successful_time` and `kube_job_status_failed`). If your kube-state-metrics version uses different series or labels, adjust the expressions accordingly.

---

## Day-2 checks (operator routine)

Use this checklist after upgrades, storage/network changes, or periodically to confirm backups + recovery are actually working.

### 1) Backups are being produced

In the app namespace:

```bash
kubectl -n <ns> get scheduledbackup
kubectl -n <ns> get backups.postgresql.cnpg.io -l cnpg.io/cluster=<cluster> --sort-by=.metadata.creationTimestamp
```

What “good” looks like:

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

What “good” looks like:

- CronJob has a recent `LAST SCHEDULE`.
- Recent Jobs complete successfully.
- `cnpg-restore-test-state` contains the most recent tested backup name.

### 3) Disaster recovery cluster is healthy (warm standby)

```bash
kubectl -n <ns> get cluster cnpg-disaster-recovery
kubectl -n <ns> get pods -l cnpg.io/cluster=cnpg-disaster-recovery
```

What “good” looks like:

- Cluster reports Ready.
- Pods are Running/Ready.
- DR metrics are present in Prometheus (see `cnpg-disaster-recovery.rules`).

### 4) Alerts are quiet for the right reason

In Prometheus/Alertmanager, validate these are not firing:

- `CNPGNoRecentBackup`
- `CNPGWALArchivingFailed`
- `CNPGRestoreTestFailed`
- `CNPGRestoreTestStale`
- `CNPGDisasterRecoveryNotInRecovery`
- `CNPGDisasterRecoveryReplayLagHigh`
