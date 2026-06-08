# Runbook: Longhorn capacity remediation (in progress)

Tracks the multi-step effort to relieve Longhorn storage pressure. Started
2026-06-08. **Resume point: after the first `snapshot-cleanup` RecurringJob run
(daily 03:00), measure reclaim, then execute the staged actions below.**

## Why

At the 2026-06-08 audit the binding constraint was **scheduling reservation, not
raw usage**: actual disk ~65% but reserved ~87%, with `soyo-1` effectively at its
over-provisioning ceiling (new PVCs / replica rebuilds could not land). Root
causes: snapshots accumulating with no cleanup job (~164 GiB single-copy /
~460 GiB on disk), ~315 GiB of reservation held by detached/abandoned volumes,
and CNPG DB volumes at 3 Longhorn replicas despite being single-instance with
WAL archived to Garage S3.

## Already done (committed to `main`, GitOps)

- `feat(longhorn): recurring snapshot-cleanup + filesystem-trim jobs` — daily
  `snapshot-cleanup` 03:00 + weekly `filesystem-trim`, group `default`
  (`kubernetes/apps/longhorn-system/longhorn/app/recurringjob.yaml`).
- `feat(longhorn): add 1TB HDD on fringe as a cold tier` — Talos mount +
  `longhorn-hdd` StorageClass. **Talos part is INERT until applied** (reboots
  fringe, reformats the disk). The HDD is **not empty** — it holds an old
  Windows install (EFI + MSR + recovery + ~930 GB `sdb4`); verify before apply.

## Baseline (2026-06-08, pre-reclaim)

| Node | Max | Used | Free | Reserved | Used% |
|---|---|---|---|---|---|
| soyo-1 | 474Gi | 318Gi | 156Gi | 426Gi | 67% |
| soyo-2 | 474Gi | 300Gi | 173Gi | 350Gi | 63% |
| soyo-3 | 474Gi | 230Gi | 243Gi | 301Gi | 48% |
| fringe | 236Gi | 171Gi | 64Gi | 205Gi | 72% |
| **Total** | **1659Gi** | **1021Gi** | **637Gi** | **1282Gi** | **61%** |

Snapshots: **31** (~164 GiB single-copy). Orphans: 0. Reserved cluster-wide: **77%**.

## Step 0 — Morning: measure the snapshot-cleanup reclaim

```bash
# Live capacity + reserved
kubectl get nodes.longhorn.io -n longhorn-system -o json | jq -r '
  (["NODE","max","used","free","reserved","used%"]|@tsv),
  (.items[]|.metadata.name as $n|(.status.diskStatus//{})|to_entries[]|
   [$n,"\((.value.storageMaximum/1073741824)|floor)Gi",
    "\(((.value.storageMaximum-.value.storageAvailable)/1073741824)|floor)Gi",
    "\((.value.storageAvailable/1073741824)|floor)Gi",
    "\((.value.storageScheduled/1073741824)|floor)Gi",
    "\(((.value.storageMaximum-.value.storageAvailable)/.value.storageMaximum*100)|floor)%"]|@tsv)' | column -t
# Snapshot count + single-copy total (compare vs 31 / 164Gi)
kubectl get snapshots.longhorn.io -n longhorn-system -o json | jq -r '
  [.items[].status.size//"0"|tonumber] as $s | "snapshots=\($s|length) singleCopy=\(($s|add)/1073741824|floor)Gi"'
# Confirm the job actually ran
kubectl get recurringjobs.longhorn.io -n longhorn-system
kubectl -n longhorn-system get jobs -l recurring-job.longhorn.io/name=snapshot-cleanup 2>/dev/null | tail -5
```

If snapshots barely dropped: the `default` group may not cover every volume —
check `kubectl get volumes.longhorn.io -n longhorn-system -o json | jq -r
'.items[] | select((.metadata.labels//{}) | keys | any(startswith("recurring-job"))) | .metadata.name'`
(those volumes opted out of `default` and need their own job/label).

## Step 1 — Tier-1 deletes (imperative, irreversible — verified 2026-06-08)

Frees ~205 GiB reservation; drops `soyo-1` off its ceiling.

```bash
# OnCall — decommissioned (0 git refs, no workloads). Disposable data.
kubectl delete pvc -n observability \
  data-oncall-postgresql-0 data-oncall-rabbitmq-0 \
  redis-data-oncall-redis-master-0 redis-data-oncall-redis-replicas-0
# Loki old write-path PVCs (Loki is now SingleBinary)
kubectl delete pvc -n observability data-loki-write-0 data-loki-write-1 data-loki-write-2
# Stray "test" volume (no PVC) + any orphan replica dirs
kubectl delete volumes.longhorn.io -n longhorn-system test
kubectl delete orphans.longhorn.io -n longhorn-system --all
```

**Do NOT delete:** `*/cnpg-disaster-recovery-1` (active DR, referenced in git),
`observability/data-pyroscope-0` (in git, scaled down).

## Step 2 — CNPG 3→2 replicas (imperative, reversible)

Frees a full 3rd copy (~90 GiB actual + reservation). All CNPG clusters are
single-instance + WAL→Garage, so 2 is safe. **Never go below 2** (no Longhorn
backup target yet — see Step 4).

```bash
for pvc in authentik-db-1 authentik-db-1-wal backstage-db-1 backstage-db-1-wal \
           dependency-track-db-1 dependency-track-db-1-wal grafana-db-1 grafana-db-1-wal \
           guac-db-1 guac-db-1-wal n8n-db-1 n8n-db-1-wal sparkyfitness-db-1 sparkyfitness-db-1-wal \
           freshrss-db-1 freshrss-db-1-wal forgejo-db-1 forgejo-db-1-wal; do
  v=$(kubectl get pvc -A -o json | jq -r --arg p "$pvc" '.items[]|select(.metadata.name==$p)|.spec.volumeName')
  [ -n "$v" ] && [ "$v" != "null" ] && kubectl -n longhorn-system patch volumes.longhorn.io "$v" --type=merge -p '{"spec":{"numberOfReplicas":2}}'
done
```

## Step 3 — Bring the 1TB HDD online as a cold tier (+~930 GiB raw)

1. **VERIFY `sdb4` is junk.** The disk holds an old Windows layout. Confirm you
   want it wiped — apply reformats the whole disk.
2. Apply the (already-committed) Talos config — reboots fringe:
   ```bash
   task talos:generate-config
   task talos:apply-node-safe IP=10.0.0.23 HOSTNAME=fringe-workstation
   ```
3. Register the disk + tag tiers (Longhorn Node CRs are runtime, not git):
   ```bash
   kubectl -n longhorn-system patch nodes.longhorn.io fringe-workstation --type=merge \
     -p '{"spec":{"disks":{"hdd-bulk":{"path":"/var/lib/longhorn-hdd","allowScheduling":true,"storageReserved":0,"tags":["hdd"]}}}}'
   for n in soyo-1 soyo-2 soyo-3; do
     kubectl -n longhorn-system patch nodes.longhorn.io $n --type=merge \
       -p '{"spec":{"disks":{"default-disk":{"tags":["ssd"]}}}}'
   done
   kubectl -n longhorn-system patch nodes.longhorn.io fringe-workstation --type=merge \
     -p '{"spec":{"disks":{"default-disk-080400000000":{"tags":["ssd"]}}}}'
   ```
4. **After** the SSD tags exist, optionally commit `diskSelector: ssd` onto the
   git-managed SSD classes (general/rwx/cache) so default volumes can't drift
   onto the HDD. Order matters — tags must exist first or new volumes go
   unschedulable. (`longhorn-hdd` already pins to `hdd`.)

Use `longhorn-hdd` only for large, latency-tolerant data (logs, archives, backup
staging). Never DBs/WAL/write-hot volumes (HDD random IOPS).

## Step 4 — Longhorn backup target on Garage S3 (foundation, not yet done)

Backup target is empty → Longhorn can only snapshot locally, no off-cluster DR
for non-DB volumes, and no safe way to offload+delete cold volumes. Wiring it
(Secret `cnpg-backup-s3`-style creds + backup-target setting; Garage already at
`10.0.0.110:3900`) unlocks restore-after-disk-loss and lets replica counts drop
safely. Non-secret parts can be committed; credentials need a human.

## GitOps boundary (why parts are imperative)

Declarative/in-git: RecurringJobs, StorageClasses, Talos machine config.
Imperative/runtime-only: orphaned-PVC deletes (apps already gone from git;
StatefulSet/Helm PVCs are retained by design), Longhorn `Node` disk
registration/tags, and per-`Volume` replica changes (Longhorn CRs live in the
cluster, not git). New volumes follow the StorageClass; existing ones must be
patched.

## Optional GitOps follow-ups

- Fix `orphanResourceAutoDeletion` in the longhorn HelmRelease (the `1.11`
  setting name differs from the HR's `orphanAutoDeletion: true`, which is why
  orphans lingered before auto-clearing).
- Drive HDD disk registration from Talos `nodeLabels` +
  `node.longhorn.io/default-disks-config` annotation (more GitOps, but flipping
  `createDefaultDiskLabeledNodes` has cluster-wide blast radius).
