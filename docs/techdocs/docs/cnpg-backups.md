# CloudNativePG & Backups

This page documents how PostgreSQL is provided as a platform service via CloudNativePG (CNPG) and how this repo models S3-compatible backups.

- CNPG operator is installed cluster-wide in the `cnpg-system` namespace via Helm + Flux.
- Application databases are created as namespace-scoped CNPG `Cluster` resources (one cluster per app).
- Backup credentials (if/when enabled) are provided via a reusable Secret named `cnpg-backup-s3` (S3-compatible, not provider-specific).

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
