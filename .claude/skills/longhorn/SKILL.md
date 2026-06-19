---
name: longhorn
description: Operate Longhorn storage on the homelab — StorageClasses, replica/volume health, the rebuild-wedge fix, node eviction, capacity, and the gotchas that have caused storage SEVs. Use when touching kubernetes/apps/longhorn-system, StorageClasses, volumes/replicas/nodes.longhorn.io, diagnosing degraded/faulted volumes, or moving storage between nodes.
---

# Longhorn storage operations

Longhorn 1.11.x, Helm-managed at `kubernetes/apps/longhorn-system/longhorn/`. The soyo control-planes are
RAM-tight and share one SSD with etcd, so Longhorn churn there has repeatedly destabilised the cluster —
the strategic direction ([ADR-0026](docs/techdocs/docs/adr/adr-0026-confine-longhorn-to-workers.md))
is **replicas only on the workers (worker-1 + fringe); soyos hold zero**.

## StorageClasses (ADR-0029 consolidated set)

`kubernetes/apps/longhorn-system/longhorn/storageclass/`. The 2-replica ceiling is structural (2 storage
nodes + HARD anti-affinity).

| Class | Replicas | Disk | Use |
|---|---|---|---|
| `longhorn` | 2 (target) | SSD | default / general — the "hot" tier. **NOTE: the chart's `longhorn` SC still carries `numberOfReplicas: 3`** (immutable param; needs a recreate to converge — ADR-0029 Stage 2). |
| `longhorn-general` | 2 | SSD | app volumes (16 PVCs) — being folded into `longhorn` |
| `longhorn-cold` | 1 | HDD (`cold` tag) | bulk/low-IOPS (backups, archives). **Never** Postgres/WAL — HDD-speed sync writes. Inert until the fringe HDD is wiped + tagged. |
| `longhorn-gitops` | 3 | SSD + 1 soyo (`gitops` tag) | **only** forgejo + openbao (survive a both-worker outage). Inert until disks tagged. |
| `longhorn-rwx` | 2 | SSD (NFS) | ReadWriteMany |
| `longhorn-snapshot` | 1 | SSD | restore source |

`defaultReplicaCount: 2` in the HelmRelease. CNPG DBs use `longhorn` (reserved) — see the `cnpg-database` skill.

## Key defaultSettings (and why)

`replicaAutoBalance: disabled` (auto-balance caused a rebuild storm + OOM — 06-09) · `concurrentReplicaRebuildPerNodeLimit: "1"` (RAM-tight; rebuilds are serial/slow) · `guaranteedInstanceManagerCPU: "20"` (**danger-zone: changing it rolls every node's IM = a replica wipe; converge node-by-node** — see [longhorn-im-cpu-converge](docs/techdocs/docs/runbooks/longhorn-im-cpu-converge.md)) · `replicaDiskSoftAntiAffinity: false` (each replica on a distinct node). `longhorn-manager` is Guaranteed-QoS via a postRenderer (don't let it go BestEffort → OOM).

## ⚠️ Gotchas (these have caused SEVs)

- **Rebuild wedge:** many volumes `degraded` but **0 rebuilding** = zombie replicas (`running`,
  `healthyAt=""`, not in the engine `replicaModeMap`) holding the per-node slot. Fix:
  [longhorn-rebuild-wedge runbook](docs/techdocs/docs/runbooks/longhorn-rebuild-wedge.md).
- **Existing PVs exclude newly-added nodes.** A PV's `spec.nodeAffinity` is set at creation and **not
  refreshed** when a node joins — so existing stateful volumes can't attach on a new node until Longhorn
  places a **replica** there. **Evict/migrate replicas onto the new node before pinning stateful
  workloads to it** ([ADR-0028](docs/techdocs/docs/adr/adr-0028-application-workload-placement.md) D2).
- **Deleting a `nodes.longhorn.io` CR** is rejected while `allowScheduling=true` — patch it `false` first.
- **`faulted` ≠ recoverable.** `auto-salvage` can log `no data exists` when no replica has valid data;
  recovery is then a *logical* restore (pg_dump/S3), not a block salvage. Check `replica.spec.healthyAt`.
- **Storage-node reboots churn Longhorn** (detach/re-attach + IM restart → degraded waves + zombie
  replicas). Reboot replica-holding nodes deliberately, drained, expecting a wave.
- **Don't ship a Talos `machine.disks` entry over a disk that still has a filesystem** — Talos won't
  `mkfs` without `--force` and wedges boot (06-19). Wipe first.

## Eviction (move replicas off a node — ADR-0026 / Phase E)

One node at a time, **evict (don't drain)** so etcd quorum is untouched:

```bash
mise exec -- kubectl -n longhorn-system patch nodes.longhorn.io <node> --type=merge \
  -p '{"spec":{"allowScheduling":false,"evictionRequested":true}}'
# wait for 0 replicas on <node> AND all volumes healthy before the next node
```

## Read-only health

```bash
# robustness spread + active rebuilds (rebuilding==0 while degraded>0 = WEDGED)
mise exec -- kubectl get volumes.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '[.items[].status.robustness]|group_by(.)|map({(.[0]):length})|add'
mise exec -- kubectl get replicas.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '[.items[]|select(.status.currentState=="rebuilding")]|length'
# replica spread per node
mise exec -- kubectl get replicas.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '[.items[]|select(.status.currentState=="running")|.spec.nodeID]|group_by(.)|map({(.[0]):length})|add'
```

## Runbooks & incidents

- [longhorn-rebuild-wedge](docs/techdocs/docs/runbooks/longhorn-rebuild-wedge.md) · [longhorn-capacity-remediation](docs/techdocs/docs/runbooks/longhorn-capacity-remediation.md) · [longhorn-im-cpu-converge](docs/techdocs/docs/runbooks/longhorn-im-cpu-converge.md) · [longhorn](docs/techdocs/docs/runbooks/longhorn.md)
- Incidents: [06-09 OOM cascade](docs/techdocs/docs/incidents/2026-06-09-longhorn-oom-cascade.md) · [06-18 IM-cpu detonation](docs/techdocs/docs/incidents/2026-06-18-longhorn-im-cpu-rolling-detonation.md) · [06-19 reboot → wedge](docs/techdocs/docs/incidents/2026-06-19-node-taxonomy-migration-storage-churn.md)
- Migration status: [node-taxonomy-migration-status](docs/techdocs/docs/runbooks/node-taxonomy-migration-status.md)

> Imperative Longhorn mutations (`kubectl patch/delete` on volumes/replicas/nodes) are **human-gated** by
> the GitOps guard hook — diagnose read-only, hand the mutating step to a human (or run with explicit go).
