# CNPG Restore & PITR Playbook

This short playbook shows how to restore a CloudNativePG backup stored in S3-compatible storage (Ceph RGW / MinIO) and how to perform a PITR (point-in-time recovery) test.

Prerequisites
- CNPG operator installed and healthy in `cnpg-system`.
- S3 backup Secret `cnpg-backup-s3` present in the same namespace as the Cluster (or referenced appropriately).
- A backup exists in your S3 bucket (verify with `s3cmd ls` or the RGW console).

Restore full backup to a new temporary cluster
1. Prepare a temporary namespace (optional):

```bash
kubectl create ns cnpg-restore || true
```

2. Create a Cluster CR that uses `restoreFrom` (example below). Adjust storage size/class and Cluster name.

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
  restore:
    from:
      backup:
        # S3 path (adjust to match where backups are stored)
        name: "s3://cnpg-backups/backstage/backstage-db/"
        # Optional: specific backup id or timestamp
  backup:
    barmanObjectStore:
      destinationPath: "s3://cnpg-backups/backstage/backstage-db"
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
        endpointURL:
          name: cnpg-backup-s3
          key: S3_ENDPOINT
      s3Compatible:
        forcePathStyle: true
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

PITR (Point-In-Time Recovery) test
1. Identify the WAL timeline and available WAL segments: CNPG will archive WAL to the object store when configured. You can inspect backup metadata in S3 or CNPG `Cluster` status to find available WAL ranges.

2. Create a Cluster specifying the target recovery time or WAL position. Example fragment:

```yaml
spec:
  restore:
    from:
      backup:
        name: "s3://cnpg-backups/backstage/backstage-db/"
    recoveryTarget:
      targetTime: "2025-12-01T12:34:00Z"  # ISO8601 target time
```

3. Apply and monitor similar to the full restore.

Verification steps
- Once the restored pod is running, connect to the database and verify expected rows exist.

```bash
kubectl -n cnpg-restore port-forward svc/backstage-db-restore 5432:5432 &
psql "host=127.0.0.1 port=5432 user=backstage dbname=backstage password=<from_secret>" -c "SELECT count(*) FROM some_table;"
```

- Confirm WAL recovery mode and timelines in Postgres logs and CNPG `Cluster` status.

Notes and cautions
- For homelab Ceph/MinIO with single-node storage, backups are not redundant; treat them accordingly.
- Always test restores in a non-production environment before relying on them for production.
- If RGW is using self-signed TLS, ensure CNPG pods trust the CA or use HTTP endpoint during tests.

Troubleshooting
- `Command failed to fetch object` from S3: verify `cnpg-backup-s3` Secret `S3_ENDPOINT`, access/secret keys, bucket, and `forcePathStyle` setting.
- `WAL archive missing` errors during PITR: ensure WAL archiving is enabled and WAL segments were uploaded to S3.

