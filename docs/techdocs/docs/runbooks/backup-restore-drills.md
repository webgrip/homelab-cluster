# Runbook: backup restore drills

A backup counts once a drill has restored it, found a fresh canary and recorded the result. This
runbook covers how each drill works, how to read its result, how to run one on demand, the
owner's quarterly escrow drill, and the local mutation tests. The program behind it is the
[backup and DR RFC](../rfc/rfc-backup-dr.md); the decision is
[ADR-0081](../adr/adr-0081-backups-land-on-a-capped-garage-are-proven-by-canary-drills-and-lock-elsewhere.md).

## How a result is recorded

Every drill ends the same way. On success, and only then, it deletes and re-creates a ConfigMap
named `restore-verified-<kind>-<name>` with the labels `backup.webgrip.io/restore-verified: "true"`,
`backup.webgrip.io/namespace`, `backup.webgrip.io/name` and `backup.webgrip.io/kind`.
kube-state-metrics exports its creation time, and the recording rules in
`kubernetes/apps/observability/victoria-metrics/app/rules/prometheusrule-platform-backups.yaml`
turn it into `backup:restore_last_success_timestamp_seconds{dataset, kind}`.

A failed drill leaves the previous ConfigMap alone, so the timestamp ages and
`BackupRestoreVerificationStale` fires after 8 days (2 days for a daily drill). The Job's own
failure shows in its logs; there is no separate "failed" metric, because a drill that cannot run at
all (image pull, quota, a missing Secret) must alert the same way as one that ran and failed.

## Reading the results

- Grafana dashboard **Backups** (uid `backups`): one row per dataset with tier, copies, last backup,
  last verified restore.
- PromQL, the age of every verified restore in days:

    ```promql
    (time() - backup:restore_last_success_timestamp_seconds) / 86400
    ```

- Datasets that should be drilled and never were:

    ```promql
    backup:dataset_copies{drill=~"weekly|daily"} unless on (dataset) backup:restore_last_success_timestamp_seconds
    ```

- In the cluster, every recorded result:

    ```sh
    mise exec -- kubectl get configmaps -A -l backup.webgrip.io/restore-verified=true \
      -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,VERIFIED:.metadata.creationTimestamp
    ```

## The drills

### CNPG canary restore

Component `kubernetes/components/cnpg-restore-test`, CronJob `cnpg-restore-test` in each database's
namespace, weekly in daytime UTC (schedule per database in its `backup/restore-test/cronjob-patch.yaml`).

1. Writes a nonce and the time into `backup_canary` in the source primary's `postgres` database,
   then `pg_switch_wal()`.
2. Waits until that WAL segment shows as archived in `pg_stat_archiver`. Timeout means WAL
   archiving is broken: stale, fail.
3. Checks the newest completed base backup is younger than 36 h: else stale, fail.
4. Creates `<db>-restore` (one instance, the source's image) from the ObjectStore, waits for Ready.
5. Asserts `SELECT 1`, the expected database and role, and that the canary row carries the nonce
   from step 1. A missing or different nonce is corrupt: fail.
6. Deletes the restore cluster and records `restore-verified-cnpg-<db>`.

Hibernated databases (n8n, sparkyfitness, backstage) keep the CronJob suspended. When one wakes,
un-suspend its drill in the same commit.

Logs: `mise exec -- kubectl -n <ns> logs job/<latest cnpg-restore-test job>`. A restore cluster left
behind after a crash: the next run deletes it first; by hand it needs the
`policy.webgrip.io/allow-stateful-delete` annotation the drill already sets.

### Longhorn volume restore

Namespace `backup`, app `kubernetes/apps/backup/restore-drills`, one CronJob per dataset
(forgejo-data Sat 10:00, vikunja Sat 14:00, invoiceninja-storage Sun 14:00 UTC).

1. Finds the newest `Completed` Longhorn Backup of the volume; older than 36 h is stale: fail.
2. Creates a temporary Longhorn Volume `restore-drill-<name>` from that backup's URL with one replica
   and waits for the restore to finish. A restore error is corrupt: fail.
3. Binds it through a static PV and PVC, mounts it read-only in a verifier pod.
4. The verifier checks every required path exists and, for datasets with a freshness limit, that the
   newest file is within the allowed hours of the backup time. This is the canary: it proves the
   restore holds recent writes without writing into production. invoiceninja-storage has no
   freshness limit while the app is scaled to 0.
5. Tears down the pod, PVC, PV and Volume, records `restore-verified-longhorn-<name>`.

Leftovers after a crash: `mise exec -- kubectl -n longhorn-system get volumes.longhorn.io | grep restore-drill`
and `mise exec -- kubectl get pv | grep restore-drill`. The next run removes them first.

### OpenBao snapshot drill

Namespace `security`, next to the snapshot job in `kubernetes/apps/security/openbao/bootstrap`,
weekly on Sunday 11:00 UTC.

1. The nightly `openbao-snapshot` job writes a nonce and the time to `secret/backup-canary/openbao`
   just before it takes the snapshot.
2. The drill downloads the newest `openbao-snapshots/*.snap` with the read-only `backup-verify` key.
   Older than 30 h is stale: fail.
3. It starts a scratch OpenBao inside its own pod (raft in an emptyDir, listener on localhost),
   initialises it, and restores the snapshot with `-force`. The scratch server now holds production's
   barrier and needs production's unseal key.
4. Unseals with the live key from `security/openbao-keys`, then runs `operator generate-root` with
   the same key to mint a root token for the scratch copy. That is the real recovery path: the
   production root token is revoked by design.
5. Reads `secret/backup-canary/openbao` and compares it with the expected window. Restore, unseal,
   generate-root or nonce failure is corrupt: fail. Records `restore-verified-openbao-openbao-raft`.
6. Compares the live unseal key's sha256 with the `sha256` key of the immutable ConfigMap
   `security/openbao-unseal-key-fingerprint`. The first drill finds no such ConfigMap, records the
   live key's fingerprint there and leaves the escrow dataset unverified for that run; every later
   drill compares against it. A match records `restore-verified-escrow-openbao-unseal-key`; a
   different key fails the drill, because the key changed without a new escrow. After a deliberate
   re-key and a new escrow, delete the ConfigMap and the next drill records the new key.

The scratch server and its token die with the pod. The drill never talks to production OpenBao
except through the snapshot it downloaded.

### Homelab etcd

Namespace `backup`, app `kubernetes/apps/backup/etcd`. `etcd-backup` runs talos-backup every 6 h
(`17 */6 * * *` UTC) and uploads an age-encrypted snapshot to bucket `homelab-etcd` with the
write-only key `homelab-etcd-writer`. Each snapshot is encrypted to two recipients, both listed in
OpenBao `secret/backup/homelab-etcd` property `AGE_X25519_PUBLIC_KEY` (comma-separated):

- the escrow recipient, whose identity (`AGE_ESCROW_IDENTITY`, same path) the owner copies into the
  password manager and onto paper, and which no workload reads;
- a drill recipient, whose identity (`AGE_DRILL_IDENTITY`, same path) the daily drill uses.

Both identities are generated once by the Job `homelab-etcd-age-keygen` in `backup`, inside its pod,
and written to OpenBao with `cas=0` under a policy that can create that path but never update it.
A later run, or a Flux re-creation of the Job, finds the path and does nothing. The bucket's 7-day
expiry is the CronJob `homelab-etcd-lifecycle` (08:05 UTC daily): it puts
`homelab-etcd-lifecycle.json` with the write-only key and reads it back with `backup-verify`.

`etcd-restore-drill` (07:40 UTC daily, image `infra-runner`) downloads the newest snapshot with the
read-only `backup-verify` key, refuses one older than 7 h, decrypts it with the drill identity,
runs `etcdutl snapshot restore`, starts a throwaway etcd on the result and checks that the
`kube-system`, `flux-system` and `backup` namespaces exist. Its canary is the ConfigMap
`backup/etcd-backup-canary`: every run writes a new `canary-<epoch>-<nonce>-end` token, and the next
run requires the restored snapshot to carry a token younger than 30 h. The very first run finds no
canary, seeds one and records nothing; from then on a missing canary is a failure. A pass records
`restore-verified-etcd-homelab-etcd` in `backup`.

The talos-backup pod needs Talos API access (`os:etcd:backup`, namespace `backup`), which is the
machine-config patch `talos/patches/controller/kubernetes-talos-api-access.yaml`, applied with
`just talos-apply-node <node> '' no-reboot` per control plane. Until it is on all three, the `etcd-backup-talos-access` Kustomization fails (its
`talos.dev/v1alpha1` ServiceAccount kind does not exist yet) and `HomelabEtcdBackupStale` /
`BackupDatasetNeverBackedUp` fire, as they should.

## Run a drill on demand

Creating a Job from a CronJob is an imperative write; it is the owner's call, and it is safe
because every drill only creates and deletes its own scratch objects.

```sh
mise exec -- kubectl -n forgejo create job --from=cronjob/cnpg-restore-test cnpg-restore-test-manual-$(date +%s)
mise exec -- kubectl -n backup get cronjobs
mise exec -- kubectl -n backup create job --from=cronjob/restore-drill-forgejo-data restore-drill-forgejo-data-manual-$(date +%s)
mise exec -- kubectl -n backup create job --from=cronjob/etcd-restore-drill etcd-restore-drill-manual-$(date +%s)
mise exec -- kubectl -n security create job --from=cronjob/openbao-restore-drill openbao-restore-drill-manual-$(date +%s)
```

Follow it with `mise exec -- kubectl -n <ns> logs -f job/<name>`. Run CNPG and Longhorn drills
between 09:00 and 17:00 UTC, away from the 02:00–04:00 backup window.

## Quarterly escrow drill

Proves the escrowed copies work. Run it on the workstation with the copies from the password
manager or the sealed paper, never with values read from the cluster. Nothing here writes to the
cluster or to garage-fsn1. Record the date in the escrow entry of the password manager.

### OpenBao: restore a snapshot with the escrowed unseal key

```sh
set -eu
W="$(mktemp -d)"; trap 'kill "$BAO_PID" 2>/dev/null; rm -rf "$W"' EXIT
export AWS_ACCESS_KEY_ID="$(bao kv get -field=S3_ACCESS_KEY_ID secret/s3/backup-verify-offsite)"
export AWS_SECRET_ACCESS_KEY="$(bao kv get -field=S3_SECRET_ACCESS_KEY secret/s3/backup-verify-offsite)"
S3='aws --region garage --endpoint-url https://s3-offsite.webgrip.dev'
SNAP="$($S3 s3 ls s3://cnpg-backups-bucket/openbao-snapshots/ | awk '{print $4}' | sort | tail -n1)"
$S3 s3 cp "s3://cnpg-backups-bucket/openbao-snapshots/$SNAP" "$W/restore.snap"
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

mkdir "$W/raft"
cat > "$W/config.hcl" <<EOF
storage "raft" { path = "$W/raft"  node_id = "drill" }
listener "tcp" { address = "127.0.0.1:18200"  tls_disable = true  disable_unauthed_generate_root_endpoints = false }
api_addr = "http://127.0.0.1:18200"
cluster_addr = "http://127.0.0.1:18201"
EOF
bao server -config="$W/config.hcl" >"$W/server.log" 2>&1 & BAO_PID=$!
export BAO_ADDR=http://127.0.0.1:18200; sleep 3

INIT="$(bao operator init -key-shares=1 -key-threshold=1 -format=json)"
bao operator unseal "$(printf '%s' "$INIT" | jq -r '.unseal_keys_b64[0]')" >/dev/null
BAO_TOKEN="$(printf '%s' "$INIT" | jq -r .root_token)" bao operator raft snapshot restore -force "$W/restore.snap"
unset INIT

read -rs ESCROWED_UNSEAL_KEY
bao operator unseal "$ESCROWED_UNSEAL_KEY" >/dev/null
bao status | grep -E '^Sealed'
OTP="$(bao operator generate-root -generate-otp)"
NONCE="$(bao operator generate-root -init -otp="$OTP" -format=json | jq -r .nonce)"
ENC="$(printf '%s' "$ESCROWED_UNSEAL_KEY" | bao operator generate-root -nonce="$NONCE" -format=json - | jq -r .encoded_token)"
unset ESCROWED_UNSEAL_KEY
BAO_TOKEN="$(bao operator generate-root -decode="$ENC" -otp="$OTP")" bao kv get secret/backup-canary/openbao
```

Pass: `Sealed false` and the canary prints a time from the night of the snapshot. The scratch
server, its data and its root token are removed on exit. The `bao` client is the mise-pinned one.
OpenBao 2.5 and later refuse `operator generate-root` without a token unless the listener sets
`disable_unauthed_generate_root_endpoints = false`; the scratch config above does, production
does not. Rehearsed locally on 2026-10-25 with `bao` 2.5.5: a forced restore leaves the server
sealed, the original key unseals it, generate-root mints a working root token, the canary reads
back.

Then check that the escrowed key is the one the drill fingerprinted:

```sh
read -rs ESCROWED_UNSEAL_KEY; printf '%s' "$ESCROWED_UNSEAL_KEY" | sha256sum | cut -d' ' -f1; unset ESCROWED_UNSEAL_KEY
mise exec -- kubectl -n security get configmap openbao-unseal-key-fingerprint -o jsonpath='{.data.sha256}{"\n"}'
```

The two lines must be equal.

### SOPS age key

```sh
read -rs AGE_KEY && SOPS_AGE_KEY="$AGE_KEY" mise exec -- sops -d talos/talsecret.sops.yaml >/dev/null && echo pass; unset AGE_KEY
```

### Homelab etcd snapshot with the escrowed identity

```sh
set -eu
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
export AWS_ACCESS_KEY_ID="$(bao kv get -field=S3_ACCESS_KEY_ID secret/s3/backup-verify-offsite)"
export AWS_SECRET_ACCESS_KEY="$(bao kv get -field=S3_SECRET_ACCESS_KEY secret/s3/backup-verify-offsite)"
S3='aws --region garage --endpoint-url https://s3-offsite.webgrip.dev'
OBJ="$($S3 s3 ls --recursive s3://homelab-etcd/ | awk '{print $4}' | sort | tail -n1)"
$S3 s3 cp "s3://homelab-etcd/$OBJ" "$W/etcd.snap.age"
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
read -rs AGE_IDENTITY && printf '%s\n' "$AGE_IDENTITY" > "$W/id" && unset AGE_IDENTITY
age -d -i "$W/id" -o "$W/etcd.snap" "$W/etcd.snap.age"
docker run --rm -v "$W:/w" gcr.io/etcd-development/etcd:v3.6.5 \
  sh -c 'etcdutl snapshot status /w/etcd.snap -w table && etcdutl snapshot restore /w/etcd.snap --data-dir /w/restored >/dev/null && echo restore-ok'
```

Pass: a revision and key count print, then `restore-ok`. The real recovery path for the cluster is
`talosctl bootstrap --recover-from`, drilled once per hardware cycle.

## Mutation tests (local)

Every drill's check has a local mutation test in `scripts/` that runs it three ways: good fixture
(must pass), corrupted fixture (must fail) and stale fixture (must fail). A test that only checks
failure cannot tell a working drill from a crashing one, so the pass case is required. List them
and run them from the repository root:

```sh
mise exec -- ./scripts/test-cnpg-restore-drill.sh
./scripts/test-openbao-restore-drill.sh
./scripts/test-etcd-restore-drill.sh
mise exec -- ./scripts/test-longhorn-restore-drill.sh
./scripts/test-homelab-etcd-age-keygen.sh
mise exec -- ./scripts/test-garage-offsite-reconcile.sh
mise exec -- ./scripts/test-longhorn-retired-backups.sh
```

The last three cover the provisioning around the drills: the etcd identity Job (generates once,
never overwrites, never prints a key), the Garage reconciler with the lifecycle job (converges,
repairs drift, never deletes, refuses an unhealthy cluster, duplicate key names or a mismatched
OpenBao entry) and the retired-backup listing (read-only by default, deletes superseded backups
only after two replacements, never an orphaned BackupVolume).

The alert rules are covered by `./scripts/test-vmalert-rules.sh`
(`scripts/vmalert-tests/platform-backups.test.yaml` and the fixed CNPG and Longhorn rules).

## Related

- [garage-offsite](garage-offsite.md): the landing copy, its quotas and permission model.
- [cnpg-backups](cnpg-backups.md): PITR, WAL pruning, the DR standby.
- [openbao-restore](openbao-restore.md): restoring production OpenBao itself.
- [etcd health](etcd-health.md): the manual `talosctl etcd snapshot` safety step.
