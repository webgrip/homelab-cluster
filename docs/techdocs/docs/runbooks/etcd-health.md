# Runbook: etcd Health

This runbook covers diagnosing etcd instability and the operational procedures for keeping it healthy on this cluster (Talos, embedded etcd, three soyo control-plane nodes).

## Cluster-specific context

- etcd runs as an embedded static container inside Talos on soyo-1/2/3.
- **All three nodes run etcd on `/dev/sda4`** — the Talos EPHEMERAL XFS partition — which is shared with containerd images, overlay layers, kubelet state, and Longhorn replica data. There is no disk I/O isolation between etcd and workload containers.
- The extra disks on each soyo node (`sdb`, `sdc`, …) are **iSCSI LUNs over the network** (vendor: IET, rotational=1). They are NOT suitable for etcd.
- The only local SSD is `sda` (WUXIN G15 512GB).
- `talosctl` requires `--talosconfig talos/clusterconfig/talosconfig` and `--nodes <IP>`. soyo-3 must be addressed by IP `10.0.0.22`, not hostname.

## Quick status checks

```bash
# Who is the etcd leader right now?
mise exec -- talosctl --talosconfig talos/clusterconfig/talosconfig \
  --nodes 10.0.0.20 etcd status

# All three members at once (run from any CP node)
# MEMBER column = member ID; LEADER column = which member ID is currently leader
# If MEMBER == LEADER on a row, that NODE is the leader.

# Fragmentation ratio (>1.5 = run defrag soon; >2.0 = run defrag now)
mise exec -- kubectl -n observability exec \
  $(mise exec -- kubectl -n observability get pod -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}') \
  -c prometheus -- wget -qO- \
  --post-data 'query=etcd_mvcc_db_total_size_in_bytes / etcd_mvcc_db_total_size_in_use_in_bytes' \
  'http://127.0.0.1:9090/api/v1/query' | jq -r '.data.result[]? | [.metric.instance, .value[1]] | @tsv'

# Leader change rate (healthy = near 0/hour; >10/hour = investigate)
mise exec -- kubectl -n observability exec ... -- wget -qO- \
  --post-data 'query=rate(etcd_server_leader_changes_seen_total[1h]) * 3600' \
  'http://127.0.0.1:9090/api/v1/query' | jq -r '.data.result[]? | [.metric.instance, .value[1]] | @tsv'

# WAL fsync p99 (must stay well below 500ms; >1s = leader changes imminent)
mise exec -- kubectl -n observability exec ... -- wget -qO- \
  --post-data 'query=histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m]))' \
  'http://127.0.0.1:9090/api/v1/query' | jq -r '.data.result[]? | [.metric.instance, .value[1]] | @tsv'
```

## Defragmentation

**Run after any sustained fragmentation ratio >1.5, or if `EtcdDbHighFragmentationRatio` alert fires.**

etcd's boltdb backend accumulates free pages over time (key churn, compaction). It never shrinks on its own. Defrag rewrites the database file, reclaiming the wasted space and reducing backend commit latency.

> ⚠️ Defrag one member at a time. Never run concurrently — it temporarily makes that member unavailable.

```bash
TC="--talosconfig talos/clusterconfig/talosconfig"

# 1. Take a snapshot first (safety net)
mise exec -- talosctl $TC --nodes 10.0.0.20 etcd snapshot /tmp/etcd-backup-$(date +%Y%m%d-%H%M).db

# 2. Defrag the non-leader members first
mise exec -- talosctl $TC --nodes 10.0.0.21 etcd defrag
# Wait ~30s for it to complete and rejoin

mise exec -- talosctl $TC --nodes 10.0.0.22 etcd defrag
# Wait ~30s

# 3. Defrag the leader last
mise exec -- talosctl $TC --nodes 10.0.0.20 etcd defrag

# 4. Verify — all three DB sizes should now match "in use" size
mise exec -- talosctl $TC --nodes 10.0.0.20 etcd status
```

Expected result: DB size shrinks from ~430–450 MB to ~165 MB per member. Backend commit latency and leader change rate should drop significantly within minutes.

## Applying Talos config changes (e.g. etcd tuning)

When changes are made to `talos/patches/` (such as the etcd heartbeat/election-timeout tuning), they must be regenerated and applied to the cluster.

> ⚠️ **`--mode=auto` almost always triggers a reboot on these nodes.** Even etcd-only config changes cause a reboot if the running config differs in feature flags or other fields from what talhelper generates. A reboot with Longhorn-mounted pods causes SIGKILL races that can leave orphaned application locks in databases (see *Known issues* below). Always use the safe task.

**Preferred method — safe rolling apply with drain:**

```bash
# Applies one node at a time: drains workloads, applies config, waits for Ready, uncordons
task talos:apply-node-safe IP=10.0.0.20 HOSTNAME=soyo-1
task talos:apply-node-safe IP=10.0.0.21 HOSTNAME=soyo-2
task talos:apply-node-safe IP=10.0.0.22 HOSTNAME=soyo-3
```

**Manual method (if task runner unavailable):**

```bash
# 1. Regenerate all node configs from talconfig + patches
mise exec -- talhelper genconfig
TC="--talosconfig talos/clusterconfig/talosconfig"

# 2. For each node: drain → apply → wait → uncordon
mise exec -- kubectl drain soyo-1 --ignore-daemonsets --delete-emptydir-data --timeout=120s
mise exec -- talosctl $TC --nodes 10.0.0.20 apply-config \
  --file talos/clusterconfig/kubernetes-soyo-1.yaml --mode=auto
mise exec -- kubectl wait node/soyo-1 --for=condition=Ready --timeout=300s
mise exec -- kubectl uncordon soyo-1
# Repeat for soyo-2 (10.0.0.21) and soyo-3 (10.0.0.22)
```

## Known issues after node reboots

### Stranded Error pods (self-heal: NO — manual delete required)

After a Talos reboot, pods evicted mid-operation get stuck in `Error` state with 0 restart count. The ReplicaSet controller will not replace them unless the pod is deleted.

```bash
# Find all stuck Error pods
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded | grep Error

# Delete them (controller reschedules immediately)
kubectl delete pod -n <namespace> <pod-name>
```

Common namespaces after CP node reboots: `longhorn-system` (csi-attacher, csi-provisioner, csi-resizer, csi-snapshotter, longhorn-ui), `kube-system` (cilium-operator), `security` (policy-reporter).

### Grafana `server_lock` orphaned lock (after Longhorn SIGKILL on reboot)

If Grafana's PostgreSQL pod is SIGKILL'd mid-migration, a stale row in `server_lock` prevents Grafana from starting.

**Symptom:** `grafana-deployment` CrashLoopBackOff with error: `there is already a lock for this actionName: oss-ac-basic-role-seeder`

**Fix:**
```bash
kubectl exec -n observability grafana-db-1 -c postgres -- \
  psql -U postgres -d grafana -c \
  "DELETE FROM server_lock WHERE operation_uid LIKE '%seeder%';"
kubectl delete pod -n observability -l app=grafana
```

**Prevention:** Use `task talos:apply-node-safe` to drain the node first — Longhorn unmounts cleanly and PostgreSQL shuts down gracefully before the reboot.

## Diagnosing disk I/O contention

If WAL fsync p99 is elevated but etcd fragmentation looks healthy, the cause is likely disk I/O contention from a workload on the same node:

```bash
# Check IO utilisation per disk per node-exporter node
# High values on sda (the only local SSD) on a CP node = disk contention
mise exec -- kubectl -n observability exec <prometheus-pod> -c prometheus -- wget -qO- \
  --post-data "query=rate(node_disk_io_time_seconds_total{job='node-exporter',instance=~'10.0.0.2[012]:9100',device='sda'}[5m])" \
  'http://127.0.0.1:9090/api/v1/query' | jq -r '.data.result[]? | [.metric.instance, .value[1]] | @tsv'

# Check average write latency per disk
# >20ms on sda of a CP node while etcd spikes = a workload is saturating the disk
mise exec -- kubectl -n observability exec <prometheus-pod> -c prometheus -- wget -qO- \
  --post-data "query=rate(node_disk_write_time_seconds_total{job='node-exporter',device='sda'}[5m]) / rate(node_disk_writes_completed_total{job='node-exporter',device='sda'}[5m])" \
  'http://127.0.0.1:9090/api/v1/query' | jq -r '.data.result[]? | [.metric.instance, (.value[1] | tonumber * 1000 | floor | tostring + "ms")] | @tsv'

# Check which pods are on a given CP node
mise exec -- kubectl get pods -A -o wide --field-selector spec.nodeName=soyo-1 | grep -v Completed
```

**Key constraint:** Never schedule write-heavy workloads on control-plane nodes. The only local disk is shared with etcd. This includes: Pyroscope, Loki (if using local storage), any database with high write throughput.

## Known root cause history

### 2026-06-03 — Sustained etcd instability (3337+ leader changes)

**Root causes (in order of impact):**

1. **boltdb never defragmented** — 436 MB allocated, 163 MB in use (37% utilisation). Each backend commit flushed 2.6× more dirty pages than necessary, elevating fsync latency.
2. **Pyroscope co-located with etcd leader on soyo-1** — Pyroscope's 20 GB profiling volume (Longhorn-backed, on sda4) generated sustained bulk writes on the same disk as etcd's WAL. The HelmRelease had only a soft scheduling hint to avoid soyo-3, which the scheduler ignored.
3. **Default heartbeat/election timeouts too tight** — 100ms heartbeat + 1000ms election timeout. A single 200ms fsync spike caused a missed heartbeat; followers would trigger an election after 1s. Raised to 500ms / 5000ms.

**Actions taken:**
- Pyroscope suspended in Flux and HelmRelease deleted (pod + service removed, PVC preserved).
- `talos/patches/controller/cluster.yaml`: etcd `heartbeat-interval: 500`, `election-timeout: 5000`.
- Config applied to all 3 nodes via `task talos:apply-node` (each node rebooted). Confirmed via `talosctl get machineconfig`.
- etcd DB utilization increased from ~37% to ~91% after the reboots triggered compaction.
- **Still required:** `talosctl etcd defrag` (one member at a time) — reclaims fragmented boltdb pages.

**Side effect of rolling reboot:**
- All 3 nodes rebooted; stranded Error pods in longhorn-system, kube-system, security cleaned up manually.
- `grafana-db-1` was SIGKILL'd mid-operation on soyo-2 reboot → `server_lock` orphaned → Grafana CrashLoopBackOff. Fixed by deleting the stale lock row and restarting the pod.
- **Mitigation added:** `task talos:apply-node-safe` (drain → apply → wait → uncordon) added to `.taskfiles/talos/Taskfile.yaml` to prevent this in future.

**Structural limitation:** The extra disks on soyo nodes are iSCSI LUNs (vendor: IET, rotational HDD). They are NOT suitable for etcd. The only viable long-term fix is a second physical local SSD per soyo node, configured via `machine.disks` in Talos to mount at `/var/lib/etcd` before etcd starts.
