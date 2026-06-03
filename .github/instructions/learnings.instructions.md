---
description: Accumulated learnings from past sessions — non-obvious pitfalls and constraints specific to this repository.
---

# Repository Learnings

## GrafanaDashboard folder resolution is namespace-scoped

`folderRef: <crd-name>` and `folder: "Title"` both look for `GrafanaFolder` CRDs in the **same namespace** as the `GrafanaDashboard`. `allowCrossNamespaceImport: true` does NOT help with folder lookup — it only makes the dashboard visible to a cross-namespace Grafana instance.

**Symptom:** `NoMatchingFolder` error on dashboards deployed to non-`observability` namespaces even though GrafanaFolder CRDs exist in `observability`.

**Fix:** All `GrafanaDashboard` files must live in `kubernetes/apps/observability/grafana/app/dashboards/`. Do NOT co-locate dashboards with their service in other namespaces. Use `folder: "Title"` (not `folderRef:` or `folderUID:`). Add entries to `observability/grafana/app/kustomization.yaml`.

## GUAC blob-store must be set explicitly when MinIO is disabled

When `minio.enabled: false` in the GUAC chart, the default `blob-addr` still points to the MinIO service (`s3://guac?endpoint=http://security-minio...`). The chart does NOT auto-update it.

**Symptom:** `cd/osv-certifier` CrashLoopBackOff with S3 connection errors to the disabled MinIO service.

**Fix:** Set `guac.blobAddr` explicitly in the HelmRelease values:
```yaml
guac:
  blobAddr: "s3://guac?endpoint=http://10.0.0.110:3900&region=garage&disableSSL=true&s3ForcePathStyle=true"
```

## Pre-commit hook may reformat YAML; re-stage before commit

`lefthook` runs `format-yaml` on staged files. If it modifies files, `git commit` exits non-zero with unstaged changes. Re-run `git add -A && git commit` to pick up the reformatted files.

## talosctl: soyo-3 must be addressed by IP, not hostname

`talosctl` cannot resolve `soyo-3` by hostname. Use the IP `10.0.0.22` directly for any `talosctl` operations targeting soyo-3.

## GPG signing is enabled; bypass for agent commits

The repo has `commit.gpgsign=true`. Use `git -c commit.gpgsign=false commit` when committing from the agent environment where GPG keys are not available.

## talosctl requires the clusterconfig talosconfig, not talos/talosconfig

`talos/talosconfig` is a stub file containing only `context: ""` — it has no endpoints. Always use `--talosconfig talos/clusterconfig/talosconfig` for all `talosctl` operations.

## The correct talosconfig for this cluster

```bash
mise exec -- talosctl --talosconfig talos/clusterconfig/talosconfig --nodes <IP> <command>
```

## soyo node extra disks are iSCSI LUNs, NOT local SSDs

The only local disk on each soyo control-plane node is `/dev/sda` (WUXIN G15 512GB SSD, rotational=0). All other disks (`sdb`, `sdc`, …) are iSCSI LUNs presented via Linux IET (vendor string `IET`, rotational=1, model `VIRTUAL-DISK`). They are network-attached HDDs. **Never configure etcd or any latency-sensitive workload on these disks.** The extra-disk appearance in `talosctl get discoveredvolumes` is misleading.

## etcd runs on sda4 (shared with all container I/O) — no isolation today

etcd's WAL and boltdb database live on `/dev/sda4` (Talos EPHEMERAL XFS, 510 GB), the same partition used by containerd images, overlay snapshots, kubelet, and Longhorn replica data. There is no I/O isolation. Write-heavy workloads scheduled on control-plane nodes directly contend with etcd fsync latency.

**Consequence:** etcd WAL fsync p99 can spike to 1–4 seconds under disk pressure, triggering leader elections (observed: 3337+ leader changes in a single day). Downstream effect: kube-controller-manager and kube-scheduler lose lease locks and restart repeatedly.

**Mitigations in place (as of 2026-06-03):**
- `etcd heartbeat-interval: 500ms`, `election-timeout: 5000ms` (in `talos/patches/controller/cluster.yaml`) — reduces election sensitivity to transient disk spikes.
- Pyroscope suspended — it was the primary write-heavy offender when co-located with the etcd leader.

**Remaining action:** Run `talosctl etcd defrag` on each member (one at a time). See `docs/techdocs/docs/runbooks/etcd-health.md`.

**Long-term fix:** Add a second physical local SSD per soyo node and configure it via `machine.disks` in Talos to mount at `/var/lib/etcd` before etcd starts.

## Do not schedule write-heavy workloads on control-plane nodes

Pyroscope, Loki (local storage mode), databases with high write throughput, and similar workloads must not run on soyo-1/2/3. Use a hard `requiredDuringSchedulingIgnoredDuringExecution` nodeAffinity with `node-role.kubernetes.io/control-plane DoesNotExist`, not a soft preference. Soft preferences are ignored under resource pressure and do not guarantee placement on the worker node.

## task talos:apply-node can trigger a reboot even for etcd config changes

`talhelper gencommand apply` with `--mode=auto` lets Talos decide whether to reboot. Even "simple" etcd config changes (heartbeat-interval, election-timeout) will trigger a reboot if the running config differs in _any other way_ — for example, if feature flags like `rbac`, `stableHostname`, or `apidCheckExtKeyUsage` are absent from the generated config vs what's running. Talos sees these as requiring a restart.

**Consequence:** Every `apply-node` on this cluster currently triggers a full reboot, meaning Longhorn-mounted pods are SIGKILL'd mid-operation.

**Always use `task talos:apply-node-safe IP=<ip> HOSTNAME=<name>`** which drains the node first, applies, waits for Ready, then uncordons. This ensures clean Longhorn unmount before the reboot.

## Talos reboot with Longhorn volumes causes orphaned application locks

When a node reboots with Longhorn-backed pods still running (e.g. due to SIGKILL during shutdown), the CSI plugin terminates before kubelet can unmount volumes. Applications that hold database advisory locks (like Grafana's `server_lock` table) may leave stale rows, causing the app to refuse to start after the reboot.

**Symptom:** Grafana pod CrashLoopBackOff with `there is already a lock for this actionName: oss-ac-basic-role-seeder`.

**Fix:**
```bash
kubectl exec -n observability grafana-db-1 -c postgres -- \
  psql -U postgres -d grafana -c "DELETE FROM server_lock WHERE operation_uid LIKE '%seeder%';"
kubectl delete pod -n observability -l app=grafana
```

**Prevention:** Always drain before applying Talos config. Use `task talos:apply-node-safe`.

## After node reboots, stranded Error pods must be manually deleted

After a Talos node reboot, ReplicaSet/Deployment pods that were evicted mid-operation can get stuck in `Error` state with 0 restarts (the controller won't replace them because they're not in `Pending`). They do not self-heal.

**Fix:** `kubectl delete pod -n <namespace> <pod-name>` — the controller will reschedule immediately.

**Common namespaces to check:** `longhorn-system` (csi-attacher, csi-provisioner, csi-resizer, csi-snapshotter, longhorn-ui), `kube-system` (cilium-operator), `security` (policy-reporter).

## etcd DB utilization increases after reboots (compaction triggered)

After applying the etcd timing patch (which caused all 3 nodes to reboot), etcd DB utilization jumped from ~37% to ~91% of allocated space. This is because Talos's etcd restart triggers a compaction cycle. Defrag is still beneficial to reclaim the allocated-but-fragmented boltdb pages.

Run defrag one member at a time after any cluster-wide rolling restart:
```bash
TC="--talosconfig talos/clusterconfig/talosconfig"
mise exec -- talosctl $TC --nodes 10.0.0.21 etcd defrag
mise exec -- talosctl $TC --nodes 10.0.0.22 etcd defrag
mise exec -- talosctl $TC --nodes 10.0.0.20 etcd defrag  # current leader last
```
