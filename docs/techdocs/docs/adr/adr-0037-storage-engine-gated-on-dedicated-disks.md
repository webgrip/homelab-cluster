# ADR-0037: Storage engine stays Longhorn v1 until dedicated data disks exist; the v2/LINSTOR choice is gated

> Status: **Accepted** · Date: 2026-07-01 · Part of [RFC: Layered Hardware Architecture](../rfc/rfc-layered-hardware-architecture.md)

## Context

Longhorn v1 has detonated repeatedly, and every incident shares a shape — a userspace engine /
instance-manager competing for RAM on nodes that have none to spare (the
[2026-06-09 OOM cascade](../incidents/2026-06-09-longhorn-oom-cascade.md), the
[2026-06-18 IM-cpu rolling detonation](../incidents/2026-06-18-longhorn-im-cpu-rolling-detonation.md)).
The natural question: does moving to a next-gen engine — **Longhorn v2 (SPDK)** or **LINSTOR/Piraeus
(DRBD)**, the two that stay inside Kubernetes — retire that failure class? Both were evaluated against
this cluster in mid-2026. The finding is that **neither is a swap you make on the current hardware**,
for two reasons shared by both:

1. **Both need a clean, dedicated block device.** v1's filesystem data path (`/var/lib/longhorn`) does
   not carry over — v2 requires a raw *block-type* disk, and DRBD requires a raw device to auto-prepare
   into an LVM/ZFS pool. Today **neither storage node has one free**: fringe's 1 TB HDD is still unwiped
   NTFS (the inert cold-tier of [ADR-0027](adr-0027-longhorn-hot-cold-tiers.md)) and worker-1's 960 GB
   SSD is fully consumed by the OS + Longhorn. So both are blocked on exactly the **L3 boot/etcd-≠-data
   disk split** the RFC already calls for.
2. **Both add a permanent per-node reservation that lands on this cluster's weak spots** — the 12 GiB
   RAM-tight soyos and power cost (~€3/W·yr). Longhorn v2 locks **~2 GiB hugepages and busy-spins 1–2
   CPU cores per node 24/7**, even idle. LINSTOR is far lighter (in-kernel, no core-spin) but its
   out-of-tree DRBD module must be **rebuilt against every Talos kernel** — a per-upgrade tax v2 avoids.

Maturity compounds it: Longhorn v2 only reached **GA in 1.12.0 (2026-06-02)**, ~1 month before this
decision, with open Sev-1 (silent replica I/O-error, #13354) and P0 (post-reattach crash, #13314)
bugs; the cluster runs **1.11.2**, where v2 is still *Technical Preview*. LINSTOR's DRBD core is mature
(15+ yrs) but the Piraeus-on-Talos niche is small.

## Decision

**Keep Longhorn v1 (hardened) as the cluster's storage engine on the current hardware.** Do **not**
adopt Longhorn v2 or LINSTOR/Piraeus on today's nodes. **Gate any next-gen engine migration on the L3
dedicated-data-disk split**, and **defer the engine selection itself to Phase 2**, decided per the
chosen hardware path — this ADR sets the gate and records the evaluation, it does not pick the winner.

When dedicated disks exist, the choice is path-shaped:

| Engine | Best-fit path | Why |
|---|---|---|
| **Longhorn v2 (SPDK)** | Path A (hyperconverged all-NVMe) | No out-of-tree-kernel tax; reuses the Longhorn UI + S3 `BackupTarget` already wired to Garage; feature parity landed at 1.12.0. Cost: ~2 GiB locked hugepages + 1–2 spinning cores/node. |
| **LINSTOR / Piraeus (DRBD)** | A perf-per-watt-max node willing to pay the per-Talos-upgrade rebuild | Lowest steady-state overhead, near-native latency. Cost: CLI-first ops, DRBD split-brain recovery, DIY S3 backup, per-upgrade module rebuild. |
| **Rook-Ceph** / **ZFS-HA** | Path B / Path C | The distributed-dedicated and centralized-HA answers; out of scope on current hardware. |

## Consequences

- **The instance-manager-OOM class is not cured now.** It is *mitigated* by the QoS hardening already
  in the HelmRelease (Guaranteed `longhorn-manager`, `guaranteedInstanceManagerCPU: 20`,
  `replicaAutoBalance: disabled`) and remains the residual storage risk until Phase 2. That trade —
  accept a mitigated v1 over an immature/ill-fitting swap — is the point of this ADR.
- **StorageClasses keep `dataEngine: v1` explicit** (already set on all classes), so the field is
  future-proofed and a v2 class is a purely additive, per-StorageClass change when the time comes.
- **Adopting any next-gen engine later carries prerequisites**, none free: wipe fringe's 1 TB HDD (the
  deferred [ADR-0027](adr-0027-longhorn-hot-cold-tiers.md) step) and/or add a dedicated disk to
  worker-1; for DRBD, a **diskless tiebreaker** on a soyo control-plane node (untainted,
  `allowSchedulingOnControlPlanes: true`) to make 2-way quorum safe; and, if leaving Longhorn, a
  replacement for its native S3 `BackupTarget` (CNPG barman→Garage is storage-agnostic and unaffected).
- **The evaluation is now durable** — the "why not yet" won't be re-litigated each time the topic
  resurfaces; revisit only when the L3 disk gate opens.
- Adopting v2 or LINSTOR *before* dedicated disks exist would force file/loopback backing on the shared
  root filesystem — **reproducing the shared-disk contention this whole RFC exists to remove.**

## Alternatives considered

- **Adopt Longhorn v2 now** (per-StorageClass `dataEngine: v2`). Rejected: needs a raw block disk the
  storage nodes don't have, plus hugepages + `nvme-tcp`/`vfio_pci` Talos config and a chart bump to
  1.12.0; it *locks* RAM and *spins* cores on the RAM/power-tightest nodes; and 1.12.0 is 1-month-GA
  with open Sev-1/P0 data-integrity and crash bugs. Its loop/AIO file-backed path is test-grade (no
  TRIM). Right engine, wrong hardware, wrong month.
- **Adopt LINSTOR/Piraeus now.** Rejected: same no-free-disk blocker; the out-of-tree DRBD module
  couples to the exact Talos kernel (rebuild the Factory schematic on every upgrade); CLI-first ops +
  DRBD split-brain recovery are a real learning curve; loses Longhorn's native S3 backup. Genuinely
  lighter and lower-latency — revisit for a perf-per-watt-max node post-disks.
- **Adopt Rook-Ceph now.** Rejected: heaviest of all (BlueStore ~4–8 GiB RAM *per OSD*) on the
  RAM-tightest nodes; CephFS on Talos is an unblessed rough edge (the `ceph` kernel client is missing;
  only `rbd` is in-tree); 3-node minimum / 5 recommended. It is a Path B answer, not a current move.
- **Do nothing and don't record it.** Rejected: the comparison is expensive to redo, and without a
  written gate the "should we move to v2/LINSTOR?" question returns every few months.
