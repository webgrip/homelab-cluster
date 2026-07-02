# Runbook: restore OpenBao from a Garage S3 raft snapshot

OpenBao is the cluster's secrets backend (ESO `ClusterSecretStore/openbao` → 66 ExternalSecrets,
2026-07-02). It's a **single-node raft** instance (`openbao-0`, 3Gi `longhorn` PVC) with a nightly raft
snapshot shipped to the **external Garage S3** (`openbao-snapshot` CronJob, `0 3 * * *`, last 14 retained
at `s3://cnpg-backups-bucket/openbao-snapshots/openbao-<ts>.snap`). Auto-unseal is handled by the
`openbao-unsealer` Deployment using the `openbao-keys` Secret (single `unseal-key`).

## ⚠️ Read first: a restore needs the unseal key, and it is NOT in S3

A raft snapshot is **encrypted**. Restoring it only helps if you can unseal the result, which requires the
**same `unseal-key`** that was active when the snapshot was taken. That key lives **only** in the K8s
Secret `security/openbao-keys` — it is **not** SOPS-tracked and **not** in S3. So:

- **Pod/PVC loss with the namespace intact** → `openbao-keys` survives → recoverable (below).
- **Full cluster rebuild / namespace wiped** → `openbao-keys` is gone → the auto-init CronJob generates a
  **new** key and a **fresh, empty** vault; an old S3 snapshot then **cannot be unsealed**. The S3
  snapshot is only useful if you *also* have that snapshot's `unseal-key`.

**Action item (do this once):** back the unseal key up off-cluster — e.g. add it to the SOPS floor or
export and store it in your password manager:
`mise exec -- kubectl get secret openbao-keys -n security -o jsonpath='{.data.unseal-key}' | base64 -d`
(treat it like a root credential). Without it, the nightly S3 snapshots are not a complete DR story.

## Which scenario are you in?

| Symptom | What's intact | Path |
|---|---|---|
| `openbao-0` restarted, sealed | PVC + `openbao-keys` | **None** — the unsealer auto-unseals within ~1 min. Just wait. |
| PVC wiped / data corrupt, pod runs | `openbao-keys` Secret | **Restore from snapshot** (below). |
| Both workers died, volume lost | `openbao-keys` Secret (namespace survived on the soyo etcd) | **Restore from snapshot** (below). |
| Full rebuild from bare Talos | only what you backed up | Need the snapshot **and** its `unseal-key` (see warning). Then restore. |

## Restore from a Garage snapshot (PVC lost, keys intact)

1. **Confirm the snapshot exists and pick the newest:**
   ```bash
   mise exec -- kubectl get cronjob openbao-snapshot -n security    # suspend should be false
   # list snapshots in Garage (run from any pod with aws-cli + the creds, or the Garage host):
   #   aws --endpoint-url http://10.0.0.110:3900 s3 ls s3://cnpg-backups-bucket/openbao-snapshots/
   ```
2. **Let openbao come up fresh-but-sealed** (if the PVC was wiped, the auto-init CronJob initialises a new
   empty vault). **Stop here before relying on that empty vault** — you're about to overwrite it.
3. **Get the snapshot onto `openbao-0`** (copy from Garage into the pod):
   ```bash
   mise exec -- kubectl exec -n security openbao-0 -- sh -c \
     'aws --endpoint-url "$S3_ENDPOINT" s3 cp s3://$S3_BUCKET/openbao-snapshots/openbao-<TS>.snap /tmp/restore.snap'
   # (S3_* env come from the cnpg-backup-s3 secret if present in the pod; else `kubectl cp` the file in.)
   ```
4. **Restore + unseal.** The restore must be done by an authenticated, *unsealed* openbao, OR with the
   `-force` flag against a sealed node that you then unseal with the snapshot's key:
   ```bash
   mise exec -- kubectl exec -n security openbao-0 -- sh -c \
     'export BAO_ADDR=http://127.0.0.1:8200; bao login <root-or-snapshot-token>; \
      bao operator raft snapshot restore /tmp/restore.snap'
   # openbao re-seals after restore → the openbao-unsealer unseals it with openbao-keys/unseal-key.
   ```
   If `openbao-keys` matches the snapshot, the unsealer takes over automatically. If not (mismatched key),
   unseal manually: `bao operator unseal <the-snapshots-unseal-key>`.
5. **Verify** a known secret reads back and ESO re-syncs:
   ```bash
   mise exec -- kubectl get pod openbao-0 -n security -o jsonpath='{.metadata.labels.openbao-sealed}'  # want false
   mise exec -- kubectl exec -n security openbao-0 -- bao kv get secret/s3/cnpg-backup   # a known path
   mise exec -- kubectl get externalsecrets -A | grep -v SecretSynced   # all should be SecretSynced
   ```

## After a both-worker outage specifically

Already-running pods keep their ESO-written K8s Secrets, so live workloads tolerate openbao being down for
a while; only **pod restarts** and **secret rotation** need openbao back. Recovery order: bring a worker
back (or let the volume re-attach) → `openbao-0` schedules on a worker → unsealer unseals from
`openbao-keys` → ESO resumes. A snapshot restore is only needed if the **raft data itself** was lost (both
Longhorn replicas gone). This is why [ADR-0026](../adr/adr-0026-confine-longhorn-to-workers.md) keeps
openbao's DR on external Garage S3 rather than a soyo replica.

## Related

- [CNPG backups & restore](cnpg-backups.md#restore-dr-drill) (the DB side — forgejo-db etc.).
- [external-secrets](external-secrets.md) (ESO + OpenBao backend).
- Snapshot CronJob + scripts: `kubernetes/apps/security/openbao/bootstrap/{snapshot-cronjob,snapshot.sh,upload.sh}`.
