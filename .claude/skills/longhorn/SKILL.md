---
name: longhorn
description: Operate Longhorn storage on the homelab — StorageClasses, replica/volume health, the rebuild-wedge fix, node eviction, capacity, and the gotchas that have caused storage SEVs.
when_to_use: Use when touching kubernetes/apps/longhorn-system, choosing/deciding a StorageClass for a new volume, working with StorageClasses/volumes/replicas/nodes.longhorn.io, diagnosing degraded/faulted volumes, or moving storage between nodes.
allowed-tools: Bash(mise exec -- kubectl get volumes.longhorn.io*), Bash(mise exec -- kubectl get replicas.longhorn.io*), Bash(mise exec -- kubectl get nodes.longhorn.io*)
---

# Longhorn storage operations

Longhorn 1.11.x, Helm-managed at `kubernetes/apps/longhorn-system/longhorn/`. The soyo control-planes are
RAM-tight and share one SSD with etcd, so Longhorn churn there has repeatedly destabilised the cluster —
the strategic direction ([ADR-0026](docs/techdocs/docs/adr/adr-0026-confine-longhorn-to-workers.md))
is **replicas only on the workers (worker-1 + fringe); soyos hold zero**.

## StorageClasses (ADR-0029 consolidated set — canonical)

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

`replicaAutoBalance: disabled` (auto-balance caused a rebuild storm + OOM — [2026-06-09 incident](docs/techdocs/docs/incidents/2026-06-09-longhorn-oom-cascade.md)) ·
`concurrentReplicaRebuildPerNodeLimit: "1"` (RAM-tight; rebuilds are serial/slow) ·
`guaranteedInstanceManagerCPU: "20"` (**danger-zone: changing it rolls every node's IM = a replica wipe; converge node-by-node** —
[2026-06-18 incident](docs/techdocs/docs/incidents/2026-06-18-longhorn-im-cpu-rolling-detonation.md) + [runbook](docs/techdocs/docs/runbooks/longhorn-im-cpu-converge.md)) ·
`replicaDiskSoftAntiAffinity: false` (each replica on a distinct node). `longhorn-manager` is Guaranteed-QoS
via a postRenderer (don't let it go BestEffort → OOM).

## ⚠️ Gotchas (these have caused SEVs)

- **Rebuild wedge:** many volumes `degraded` but **0 rebuilding** = zombie replicas (`running`,
  `healthyAt=""`, not in the engine `replicaModeMap`) holding the per-node slot. Fix:
  [longhorn-rebuild-wedge runbook](docs/techdocs/docs/runbooks/longhorn-rebuild-wedge.md).
- **WFFC bakes a node-restrictive PV `nodeAffinity`; with `dataLocality` off it's pure downside.** WFFC
  (`WaitForFirstConsumer`) records the storage nodes present at first bind into the PV `nodeAffinity` and
  never refreshes it → permanently excludes nodes added later (this is the whole worker-1-exclusion saga).
  With `dataLocality: disabled` Longhorn volumes are **network-attached**, so WFFC's topology binding has
  **no benefit** — it's just harm. **The general/cold/snapshot/cache SCs were flipped to `Immediate`
  2026-06-20** (the storageclass Flux ks has `force: true` so the immutable binding-mode change recreates
  the SC; bound PVs unaffected). `gitops` stays WFFC (it uses `dataLocality: best-effort`). New volumes
  attach anywhere; **existing** WFFC-era PVs keep their baked affinity until recreated (migrate to the now-
  Immediate SC). Check per volume: `kubectl get pv <pv> -o jsonpath='{.spec.nodeAffinity}'` (empty = free).
- **Deleting a `nodes.longhorn.io` CR** is rejected while `allowScheduling=true` — patch it `false` first.
- **`faulted` ≠ recoverable.** `auto-salvage` can log `no data exists` when no replica has valid data;
  recovery is then a *logical* restore (pg_dump/S3), not a block salvage. Check `replica.spec.healthyAt`.
- **RWO + `RollingUpdate` = Multi-Attach deadlock when a single-replica Deployment moves nodes.** Fix =
  **`strategy: Recreate`** (StatefulSets/CNPG immune). Full explanation → the `workload-placement` skill.
- **Storage-node reboots churn Longhorn** (detach/re-attach + IM restart → degraded waves + zombie
  replicas). Reboot replica-holding nodes deliberately, drained, expecting a wave. Spacing rollout-heavy
  commits apart matters too (storage starvation → instance-manager probe timeouts → faulted volumes).
- **Don't ship a Talos `machine.disks` entry over a disk that still has a filesystem** — Talos won't
  `mkfs` without `--force` and wedges boot (06-19). Wipe first.

## Eviction (move replicas off a node — ADR-0026 / Phase E)

One node at a time, **evict (don't drain)** so etcd quorum is untouched:

```bash
mise exec -- kubectl -n longhorn-system patch nodes.longhorn.io <node> --type=merge \
  -p '{"spec":{"allowScheduling":false,"evictionRequested":true}}'
# wait for 0 replicas on <node> AND all volumes healthy before the next node
```

## Additional resources

- Read-only health one-liners, runbook index, incident log → [reference.md](reference.md)

> Imperative Longhorn mutations (`kubectl patch/delete` on volumes/replicas/nodes) are **human-gated** by
> the GitOps guard hook: diagnose read-only, hand the mutating step to a human (or run with explicit go).
