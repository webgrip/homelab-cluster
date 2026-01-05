# CloudNativePG & Backups

This page documents how PostgreSQL is provided as a **platform service** via CloudNativePG (CNPG) and how backups are wired to **Ceph RGW** using a vendor‑neutral S3 setup.

- CNPG operator is installed cluster‑wide in the `cnpg-system` namespace via Helm + Flux.
- Backups use S3‑compatible object storage exposed by Ceph RGW on your Proxmox node `pve`.
- A reusable Kustomize component injects a `cnpg-backup-s3` Secret with **S3_*** keys (no AWS branding).

---

## CloudNativePG Operator

**Location in repo**

- Namespace and app:
  - `kubernetes/apps/cnpg-system/kustomization.yaml`
  - `kubernetes/apps/cnpg-system/namespace.yaml`
  - `kubernetes/apps/cnpg-system/cloudnative-pg/ks.yaml`
  - `kubernetes/apps/cnpg-system/cloudnative-pg/app/{kustomization,helmrepository,helmrelease}.yaml`

**Behavior**

- Operator is installed as a HelmRelease in namespace `cnpg-system`.
- `clusterWide: true` is set so CNPG `Cluster` resources in any namespace are managed by this single operator.
- Monitoring is enabled:
  - Prometheus `PodMonitor` for CNPG metrics.
  - A Grafana dashboard is published as a `ConfigMap` labeled `grafana_dashboard=1` so existing Grafana sidecars/operators can auto‑import it.

At this stage **no application is wired to CNPG**; it is a platform‑level capability ready to host PostgreSQL clusters when you choose to add them.

---

## Backup Credentials Component (`cnpg-backup-s3`)

Backups are configured via CNPG's `backup.barmanObjectStore` and a reusable Secret component.

**Location**

- `kubernetes/components/cnpg-backup/kustomization.yaml`
- `kubernetes/components/cnpg-backup/backup-credentials.sops.yaml`

**Secret schema**

The component defines a Secret named `cnpg-backup-s3` with **generic S3 field names**:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cnpg-backup-s3
stringData:
  S3_ACCESS_KEY_ID: CHANGE_ME_ACCESS_KEY
  S3_SECRET_ACCESS_KEY: CHANGE_ME_SECRET_KEY

  # Connection parameters for your S3-compatible endpoint
  S3_REGION: "local"                    # arbitrary label, kept consistent everywhere
  S3_ENDPOINT: "http://10.0.0.10:7480"  # Ceph RGW HTTP endpoint
  S3_BUCKET: "cnpg-backups"             # bucket dedicated to CNPG backups
  S3_PATH: "/homelab-cluster"          # optional per-cluster prefix
```

These keys are **not** AWS‑branded; they are plain S3‑style names that will be mapped explicitly into CNPG's `barmanObjectStore.s3Credentials`.

**How to fill and encrypt**

1. Replace `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` with the keys of your Ceph RGW user (see next section).
2. Ensure `S3_ENDPOINT` and `S3_BUCKET` match your RGW setup (e.g. `http://10.0.0.10:7480`, bucket `cnpg-backups`).
3. Optionally adjust `S3_REGION` and `S3_PATH` to taste.
4. Encrypt with SOPS so the secret is never committed in plaintext:

   ```bash
   cd /home/ryan/projects/webgrip/homelab-cluster
   sops -e -i kubernetes/components/cnpg-backup/backup-credentials.sops.yaml
   ```

**How to include in a namespace**

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

## Ceph RGW as S3 Backend

Backups are stored in a bucket on Ceph RGW running on Proxmox node `pve`.

### Ceph cluster characteristics

- Single‑node Ceph Squid cluster with:
  - 1 MON, 1 MGR, 1 OSD (~931 GiB SSD).
- Pools created for RGW (`.rgw.root`, `default.rgw.*`) have `size=1` and `min_size=1` to match the single OSD.
- Health warnings about lack of redundancy and too few OSDs were muted for this **lab** setup:
  - `POOL_NO_REDUNDANCY`
  - `TOO_FEW_OSDS`

> This configuration is **not redundant**: if the Ceph disk dies, backup data is lost. This is acceptable here because the goal is a homelab proof‑of‑concept.

### RGW endpoint

- RGW is exposed on `pve` at:

  - `http://10.0.0.10:7480`

From the Proxmox host you can sanity‑check RGW with:

```bash
curl -v http://10.0.0.10:7480/ | head -n 20
```

An XML error like `AccessDenied` is expected and confirms RGW is reachable.

### RGW S3 user

A dedicated S3 user is created for CNPG backups:

```bash
# Run on pve
radosgw-admin user create \
  --uid=cnpg-backup \
  --display-name="CNPG Backup User" \
  --max-buckets=10 > /root/cnpg-backup-user.json

# Inspect keys
jq '.keys[0]' /root/cnpg-backup-user.json
```

From the JSON output, copy:

- `access_key` → `S3_ACCESS_KEY_ID`
- `secret_key` → `S3_SECRET_ACCESS_KEY`

and place them into `backup-credentials.sops.yaml` before encrypting.

### RGW S3 bucket

Using `s3cmd` as a generic S3 client (no AWS involved), configured to talk to `10.0.0.10:7480`:

```bash
s3cmd ls                      # talk to Ceph, not AWS
s3cmd mb s3://cnpg-backups    # create bucket for CNPG backups

# quick upload test
echo "hello from ceph rgw" > /tmp/rgw-test.txt
s3cmd put /tmp/rgw-test.txt s3://cnpg-backups/rgw-test.txt
s3cmd ls s3://cnpg-backups
```

This verifies that the user + bucket + endpoint combination works end‑to‑end.

---

## How CNPG Will Use This (Example)

When you are ready to create a PostgreSQL cluster, you'll define a CNPG `Cluster` with `backup.barmanObjectStore` pointing at the RGW bucket and using the `cnpg-backup-s3` Secret.

Below is an **example fragment** (not currently applied in the repo) showing how to wire the secret into CNPG:

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
    barmanObjectStore:
      destinationPath: "s3://cnpg-backups/homelab-cluster/example-db"
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

    # you can further tune these according to CNPG docs
    wal:
      compression: gzip
    data:
      compression: gzip
```

Key points:

- The **only coupling** between CNPG and Ceph RGW is the S3 API (endpoint + credentials).
- All sensitive values live in `cnpg-backup-s3`, encrypted with SOPS and injected by the `cnpg-backup` component.
- No AWS‑specific names or services are used; everything is expressed in terms of generic S3 semantics.

When you later introduce real application databases, you can copy this pattern into their CNPG `Cluster` definitions and adjust only:

- `metadata.name` / `namespace`
- `destinationPath` (e.g. per‑cluster prefix)
- any performance/retention tuning under `backup.barmanObjectStore`.

---

## Automated DR verification (optional)

For teams that want ongoing validation of backups and restores, there is an optional `cnpg-dr` component in the repo that deploys a CronJob to run a lightweight DR check on a schedule.

- Location: `kubernetes/components/cnpg-dr`
- What it does: runs a small script from a `ConfigMap` that verifies the CNPG operator presence; it can be extended to run full create→backup→restore tests.
- RBAC: the component installs a `ClusterRole` with privileges to create/delete CNPG `Cluster` and `ScheduledBackup` CRs. Apply with caution — prefer running in a dedicated test cluster or restricted namespace.

Enable it by including `- ../../components/cnpg-dr` in a kustomization that is applied to the cluster (or apply manifests manually).
