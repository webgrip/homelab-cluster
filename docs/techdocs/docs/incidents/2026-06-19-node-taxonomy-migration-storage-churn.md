# Incident 2026-06-19 — config-drift reboot → broken-HDD boot wedge → Longhorn rebuild wedge

**Severity:** SEV3 (self-inflicted during a planned migration; one worker `NotReady` ~5 min; cluster-wide Longhorn degraded/faulted churn; **no data loss**; fully recovered).
**Duration:** ≈13:11 UTC (fringe reboots mid-apply) → ≈14:00 UTC (Longhorn back to baseline-healthy). A later, separate ~8 min `n8n` outage (≈14:4x UTC) came from the placement canary, not this storm — see *Reusable nuggets*.
**Data loss:** none. 5 volumes went transiently `faulted` (all `detached`/idle) and recovered; no replica with valid data was lost.

## Summary

During **Phase B** of the node-taxonomy migration (adding `node.webgrip.io/*` capability labels to every
node, [ADR-0025](../adr/adr-0025-node-taxonomy.md)), a **label-only** Talos `apply-node` to
`fringe-workstation` unexpectedly **rebooted** it. `worker-1` (freshly added that day) had taken the same
label change with **no reboot**, but `fringe` had a stale stored `install.image` (an old `v1.12.4`
pointer; running OS was `v1.13.2`), so `--mode=auto` chose to reboot to reconcile the drift. On reboot,
Talos got **stuck in a boot loop** trying to `mkfs.xfs` fringe's 1 TB HDD — the long-committed "cold
tier" `machine.disks` entry, which **had never actually worked** because the disk still held an NTFS
filesystem and Talos refuses to format over it without `--force`. `block.VolumeManagerController` looped
`failed`, the kubelet never started, and fringe sat `NotReady` for ~5 minutes.

Removing the broken HDD disk config restored fringe in ~20 s. But fringe is a Longhorn storage node, and
the reboot's instance-manager restart **left two "zombie" replicas** (`running`, `healthyAt=""`, absent
from their engine's `replicaModeMap`) holding the single per-node rebuild slot on `worker-1` and
`soyo-2`. With `concurrentReplicaRebuildPerNodeLimit: "1"`, that **wedged the whole rebuild queue** — 25
volumes `degraded` with **0 actively rebuilding**. The `cluster-health` subagent diagnosed it; deleting
the two zombie replica CRs (after verifying each volume's surviving RW copy) freed the slots, and the
queue drained. We also GC'd the orphan `slab` Longhorn node and reduced 9 still-`degraded` 3-replica
volumes to 2, taking the cluster from 25→3 degraded.

Self-inflicted: a routine label change detonated a 6-day-old latent config defect (the unformattable
HDD) and exposed that `apply-node` is not "always a reboot".

## Impact

- `fringe-workstation` **NotReady ~5 min** (boot wedged on the HDD format loop); the ~11 apps hard-pinned
  to fringe (`nodegroup=fringe`) were unschedulable until it recovered.
- Cluster-wide Longhorn: peaked at **26 `degraded` / 5 `faulted` / 0 rebuilding**; ~33 fringe pods
  `ContainerCreating` while volumes re-attached. The 5 faulted were all `detached`/idle and recovered.
- Rebuild queue **wedged** (0 rebuilding despite 25 degraded) until the two zombie replicas were deleted.

## Timeline (UTC, approximate)

| Time | Event |
| --- | --- |
| ≈13:08 | Phase B: `worker-1` (10.0.0.24) gets `node.webgrip.io/*` labels via `apply-node` — **applied without a reboot** (fresh node, no config drift). |
| ≈13:11 | Same label change to **fringe** (10.0.0.23) → `apply-node` shows an `install.image` diff (`v1.12.4` → `v1.13.3`) and **reboots** the node under `--mode=auto`. |
| ≈13:12 | fringe stuck `STAGE=booting`. `dmesg`: `block.VolumeManagerController … error formatting XFS: mkfs.xfs: /dev/sdb1 appears to contain an existing filesystem (ntfs). Use the -f option to force overwrite.` — looping every ~30 s; kubelet PKI write fails on read-only fs. |
| ≈13:16 | Remove the HDD `disks:` + `extraMounts` from `talos/patches/worker/fringe-dedicated.yaml`; re-apply. fringe boots to `running` / Ready in ~20 s (still `v1.13.2` — no reinstall happened). |
| ≈13:18 | Longhorn fallout from the reboot: **26 degraded / 5 faulted**, ~33 fringe pods `ContainerCreating`. The 5 faulted (all `detached`) recover within ~2 min → 0 faulted. |
| ≈13:40 | Rebuild queue found **wedged**: 25 degraded, **0 rebuilding**. `cluster-health` subagent root-causes two zombie replicas (`pvc-e1cae8df-…-r-498d81fd` on worker-1, `pvc-5b05c78c-…-r-3e450748` on soyo-2) holding the per-node rebuild slot. |
| ≈13:45 | Delete the worker-1 zombie (verified its RW copy `r-8327c7a1` survives on soyo-1) → slot frees; healthy 17→19. |
| ≈13:48 | Delete the soyo-2 zombie (verified RW copy `r-beb73378` on fringe) → healthy →20. |
| ≈13:50 | GC the orphan `nodes.longhorn.io/slab` (worker-1's prior identity, 0 replicas) — rejected while `allowScheduling=true`; patch `false` first, then delete. |
| ≈13:55 | Reduce the 9 still-`degraded` 3-replica volumes → 2 (cancels queued rebuilds; matches the 2-replica ceiling). |
| ≈14:00 | Baseline-healthy: **3 degraded / 39 healthy / 0 faulted**, single-replica volumes 18→3, rebuilds flowing. |

## Root cause

```text
Phase B label change (no-op intent) applied with --mode=auto to fringe
  → fringe's STORED install.image was stale (v1.12.4 vs running v1.13.2)
    → --mode=auto decides a reboot is needed to reconcile the drift
      (worker-1, a fresh node, had no drift → applied live, no reboot)
  → on reboot, Talos tries to mkfs.xfs the 1 TB HDD per the committed
    machine.disks "cold tier" entry — but the disk still holds NTFS
      → Talos refuses to format without --force → block.VolumeManagerController
        loops "failed" forever → kubelet never starts → fringe NotReady ~5 min
  → fringe is a Longhorn storage node; its instance-manager restart on reboot
    leaves 2 replicas "running" but healthyAt="" and not in replicaModeMap
      → each holds its node's single rebuild slot (limit=1)
        → rebuild queue wedged: 25 degraded, 0 rebuilding
```

Proof it was config drift and not a "normal" apply: `worker-1` took the identical label change with
`Applied configuration without a reboot`, while fringe's apply printed an `install.image` diff and
rebooted. After recovery, fringe still ran `v1.13.2` (kubectl OS-IMAGE + server `Tag`), confirming the
reboot was a config re-apply, **not** a reinstall/downgrade — the `v1.12.4` was only the stale stored
pointer, now corrected to `v1.13.3`.

## Contributing factors

- **`apply-node` is not "always a reboot".** The talos skill said it always reboots and to use
  `apply-node-safe` (drain-wrapped). Reality: a label/annotation-only change applies **live** unless the
  node has reboot-requiring config drift. The blanket warning hid the safer `MODE=no-reboot` path that
  the soyos later used cleanly.
- **A latent, never-validated disk config.** The HDD "cold tier" `machine.disks` entry had been committed
  for ages but had **never succeeded** (NTFS never wiped); nothing failed visibly until a reboot forced
  the format attempt. Config that has never reconciled is a hidden landmine.
- **Storage-node reboots churn Longhorn.** Rebooting a node that holds replicas detaches/re-attaches its
  volumes and restarts its instance-manager — the exact churn that seeds zombie replicas and degraded
  waves on a RAM-tight, `rebuild-limit=1` cluster.
- **The migration started on an already-degraded baseline.** The cluster was mid-rebuild from prior
  incidents; the reboot's churn landed on top of that, amplifying the wedge.

## Detection gap

Same blind spot as [06-18](2026-06-18-longhorn-im-cpu-rolling-detonation.md): no alert on **`faulted > 0`**
and no alert on the **wedge signature** (degraded > 0 with **rebuilding == 0** for a sustained window).
Both states were caught manually mid-migration, not paged. A "rebuild queue stalled" alert
(`count(degraded) > 0 and count(rebuilding) == 0 for 15m`) would have flagged the wedge directly.

## Resolution

1. **Recover fringe — drop the broken HDD config.** Removed the `machine.disks` + `extraMounts` cold-tier
   entry from `talos/patches/worker/fringe-dedicated.yaml`; re-applied → fringe booted in ~20 s. The cold
   tier is re-introduced properly under [ADR-0027](../adr/adr-0027-longhorn-hot-cold-tiers.md) **with an
   explicit disk wipe first**.
2. **Un-wedge Longhorn — delete the zombie replicas.** See the
   [longhorn-rebuild-wedge runbook](../runbooks/longhorn-rebuild-wedge.md): verify a surviving RW replica
   in the engine's `replicaModeMap`, then `kubectl delete` the zombie replica CR; the per-node slot frees
   and Longhorn rebuilds normally. (Imperative Longhorn-CR deletes are human-gated; done with explicit
   owner go.)
3. **GC the orphan `slab` node** — patch `allowScheduling=false` (Longhorn refuses the delete otherwise),
   then `kubectl delete nodes.longhorn.io slab`.
4. **Relieve the storm — reduce over-replication.** Patched the 9 degraded 3-replica volumes to
   `numberOfReplicas: 2` (the [ADR-0026](../adr/adr-0026-confine-longhorn-to-workers.md) ceiling),
   cancelling their queued rebuilds.
5. **Finish Phase B safely — `MODE=no-reboot` on the soyos.** The remaining label applies used
   `task talos:apply-node IP=<ip> MODE=no-reboot` → labels applied live, install-image drift staged, **no
   etcd-node reboot**, zero storage impact.

## Learnings & action items

| # | Action | Type | Status |
| --- | --- | --- | --- |
| 1 | **`MODE=no-reboot` for label/annotation-only Talos applies**, especially on etcd nodes — applies live, stages drift, never reboots (and refuses if a change genuinely needs one). | process (root) | ✅ done this session; talos skill corrected |
| 2 | **Never ship a `machine.disks` entry over a disk that still holds a filesystem** — Talos won't `mkfs` without `--force` and wedges boot. Wipe the disk first; validate the mount actually came up before committing. | prevention (root) | ✅ broken config removed; ADR-0027 adds an explicit wipe step |
| 3 | **Zombie-replica rebuild-wedge runbook** — fingerprint (degraded>0, rebuilding==0) + the verified-delete SOP. | recovery | ✅ [runbook written](../runbooks/longhorn-rebuild-wedge.md) |
| 4 | Alert on **`faulted > 0`** and on **rebuild-queue stalled** (`degraded>0 and rebuilding==0 for 15m`). | detection | ⏳ open (P2) — same gap as 06-18 |
| 5 | Treat **storage-node reboots as deliberate, drained ops** — don't reboot a replica-holding node incidentally; expect a degraded wave. | process | ⏳ open (P2) |
| 6 | Re-introduce the fringe HDD **cold tier** with an explicit wipe (ADR-0027), then validate before relying on `longhorn-cold`. | prevention | ⏳ open (P3) |

## Reusable nuggets

- **`apply-node` reboots only on reboot-requiring config drift.** A fresh node with config matching
  `talenv` applies label/annotation changes live; a node with a stale stored `install.image` reboots
  under `--mode=auto`. Use **`MODE=no-reboot`** to apply live and stage the drift — the safe default for
  etcd nodes. `apply-node-safe` (drain-wrapped) is for changes that genuinely reboot.
- **A Talos boot stuck in `STAGE=booting` with `block.VolumeManagerController … mkfs … existing
  filesystem` in `dmesg`** = a `machine.disks` entry pointed at a disk that still has data. Talos won't
  force-format. Remove the disk config (or wipe the disk) to boot.
- **Rebuild-wedge signature:** many volumes `degraded` + **0 rebuilding** + replica CRs `running` with
  empty `healthyAt` that are **absent from their engine's `replicaModeMap`** = leaked rebuild slots.
  Deleting the zombie replica (after confirming a sibling RW copy) frees the slot. See the
  [runbook](../runbooks/longhorn-rebuild-wedge.md).
- **Longhorn won't delete a node CR while `allowScheduling=true`** — patch it `false` first.
- **Existing Longhorn PVs exclude later-added nodes.** A separate finding the same day: `n8n`'s
  111-day-old PV `nodeAffinity` listed soyos+fringe but **not** `worker-1` (joined that day). A stateful
  pod hard-pinned to a pool containing only `worker-1` went `Pending` — the volume can't attach there
  until Longhorn places a replica on it (eviction). So **eviction must precede stateful worker-pinning**
  (see [ADR-0026](../adr/adr-0026-confine-longhorn-to-workers.md) / the migration status runbook).
