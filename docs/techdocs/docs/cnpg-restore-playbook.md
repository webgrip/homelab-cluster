# CNPG Restore & PITR Playbook

This short playbook shows how to restore a CloudNativePG backup stored in S3-compatible object storage and how to perform a PITR (point-in-time recovery) test.

It also documents the automated “restore drill” and the always-on disaster recovery pattern used in this repo.

## Prerequisites

- CNPG operator installed and healthy in `cnpg-system`.
- S3 backup Secret `cnpg-backup-s3` present in the same namespace as the Cluster (or referenced appropriately).
- A backup exists in your S3 bucket.

For Garage, AWS SigV4 requests generally must be signed with the region that Garage is configured for (commonly `garage`). For example:

```bash
aws --profile garage --region garage --endpoint-url http://10.0.0.110:3900 \
  s3 ls s3://cnpg-backups-bucket/homelab-cluster/ --recursive
```

## Restore full backup to a new temporary cluster

1. Prepare a temporary namespace (optional):

```bash
kubectl create ns cnpg-restore || true
```

1. Create a new Cluster that bootstraps from the object store (example below). Adjust storage size/class and Cluster name.

Example `restore-cluster.yaml` (edit then apply):

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: backstage-db-restore
  namespace: cnpg-restore
spec:
  instances: 1
  storage:
    size: 10Gi
    storageClass: longhorn

  bootstrap:
    recovery:
      source: clusterBackup

  externalClusters:
    - name: clusterBackup
      barmanObjectStore:
        # S3 destination path that contains BOTH base backups and WAL for this source cluster
        destinationPath: s3://cnpg-backups-bucket/homelab-cluster/backstage-db/
        # NOTE: endpointURL is a plain string in CNPG (not a SecretKeySelector)
        endpointURL: http://10.0.0.110:3900
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

Notes:

- CNPG will create objects under a subdirectory for the cluster name. For example, with the `destinationPath` above you will typically see objects under `homelab-cluster/backstage-db/backstage-db/...`.

## Repo restore overlays

This repo also contains app-scoped restore manifests that are not applied by default. For example, Tandoor has:

- `kubernetes/apps/tandoor/tandoor/app/database/restore/`

Those manifests restore into a new cluster named `tandoor-db-restore` in the `tandoor` namespace.

## Automated restore drill (recommended)

This repo includes an automated restore drill CronJob (`cnpg-restore-test`) in each app namespace.

### What it does

- Detects the newest *completed* CNPG Backup object for the production cluster.
- If it hasn’t tested that backup yet, it restores into a temporary cluster, runs validation, then deletes the temporary cluster.
- Records the last tested backup name in a ConfigMap (`cnpg-restore-test-state`) so it runs once per completed backup.

### Manually trigger a drill now

You can run it immediately without waiting for the schedule:

```bash
kubectl -n <ns> create job --from=cronjob/cnpg-restore-test cnpg-restore-test-manual
kubectl -n <ns> logs -l job-name=cnpg-restore-test-manual -c restore-test -f
```

If it prints “latest completed backup already tested”, and you want to force re-testing that same backup:

```bash
kubectl -n <ns> delete configmap cnpg-restore-test-state
kubectl -n <ns> create job --from=cronjob/cnpg-restore-test cnpg-restore-test-manual
```

### What it validates

- Always: connectivity (`SELECT 1`).
- Optionally (configured per app): checks that an expected database name and role exist (for example the app’s bootstrap DB and owner role).

## Always-on disaster recovery (warm standby)

This repo can also run a warm standby cluster in each app namespace named `cnpg-disaster-recovery`.

It bootstraps from the same object-store backup+WAL path as production and continuously replays WAL.

Operationally:

- Restore drills answer “can we rebuild from backups?”
- Warm standby answers “how quickly can we come back up if prod is dead?”

## Alerting expectations

- Restore drill alerts (failure + staleness) are based on Kubernetes CronJob/Job metrics from kube-state-metrics.
- DR alerts are based on custom Postgres queries exported as Prometheus metrics from the DR cluster.

## Day-2 ops: quick confidence checks

After changes (CNPG upgrade, storage maintenance, object-store outage, etc.), these checks quickly answer “are we still recoverable?”.

### Backups exist and complete

```bash
kubectl -n <ns> get scheduledbackup
kubectl -n <ns> get backups.postgresql.cnpg.io -l cnpg.io/cluster=<cluster> --sort-by=.metadata.creationTimestamp
```

### Restore drill ran successfully

```bash
kubectl -n <ns> get cronjob cnpg-restore-test
kubectl -n <ns> get jobs --sort-by=.metadata.creationTimestamp | tail -n 20
kubectl -n <ns> get configmap cnpg-restore-test-state -o yaml
```

### Force a one-off drill

```bash
kubectl -n <ns> create job --from=cronjob/cnpg-restore-test cnpg-restore-test-manual
kubectl -n <ns> logs -l job-name=cnpg-restore-test-manual -c restore-test -f
```

### DR cluster sanity

```bash
kubectl -n <ns> get cluster cnpg-disaster-recovery
kubectl -n <ns> get pods -l cnpg.io/cluster=cnpg-disaster-recovery
```

If the synthetic check CronJob is enabled:

```bash
kubectl -n <ns> get cronjob cnpg-disaster-recovery-check
kubectl -n <ns> get jobs -l cronjob-name=cnpg-disaster-recovery-check --sort-by=.metadata.creationTimestamp | tail -n 20
```
```

Apply the restore Cluster:

```bash
kubectl apply -f restore-cluster.yaml
kubectl -n cnpg-restore get cluster/backstage-db-restore -o yaml
```

Watch pods and operator logs:

```bash
kubectl -n cnpg-restore get pods -w
kubectl -n cnpg-system logs -l app.kubernetes.io/name=cloudnative-pg-operator --tail=200
```

## PITR (Point-In-Time Recovery) test

1. Identify the WAL timeline and available WAL segments: CNPG will archive WAL to the object store when configured. You can inspect backup metadata in S3 or CNPG `Cluster` status to find available WAL ranges.

1. Create a Cluster specifying the target recovery time or WAL position. Example fragment:

```yaml
spec:
  bootstrap:
    recovery:
      source: clusterBackup
      recoveryTarget:
        targetTime: "2025-12-01T12:34:00Z"  # ISO8601 target time
```

1. Apply and monitor similar to the full restore.

## Verification steps

- Once the restored pod is running, connect to the database and verify expected rows exist.

```bash
kubectl -n cnpg-restore port-forward svc/backstage-db-restore-rw 5432:5432 &
psql "host=127.0.0.1 port=5432 user=backstage dbname=backstage password=<from_secret>" -c "SELECT count(*) FROM some_table;"
```

- Confirm WAL recovery mode and timelines in Postgres logs and CNPG `Cluster` status.

## Notes and cautions

- For homelab Ceph/MinIO with single-node storage, backups are not redundant; treat them accordingly.
- Always test restores in a non-production environment before relying on them for production.
- If RGW is using self-signed TLS, ensure CNPG pods trust the CA or use HTTP endpoint during tests.

## Troubleshooting

- `Command failed to fetch object` from S3: verify access/secret keys, `endpointURL`, bucket/path in `destinationPath`, and that the endpoint is reachable from inside the cluster.
- `WAL archive missing` errors during PITR: ensure WAL archiving is enabled and WAL segments were uploaded to S3.

