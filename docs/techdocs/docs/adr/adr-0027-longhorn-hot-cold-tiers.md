# Longhorn hot/cold storage tiers (SSD/HDD), configured from node annotations

* Status: proposed
* Date: 2026-07-01

Technical Story: [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md)

## Context and Problem Statement

With Longhorn confined to the two workers ([ADR-0026](adr-0026-confine-longhorn-to-workers.md)),
fringe's 236 GiB SSD is the binding capacity constraint — hard anti-affinity means it holds a full
second copy of every hot volume — while fringe's 1 TB HDD sits unused. Longhorn node/disk
configuration is also not GitOps-managed at all (disks and tags would have to be clicked in the
UI), which is undeclared and is why the soyos still auto-create Longhorn disks.

The HDD is not spare hot capacity — Longhorn writes a volume's replicas **synchronously**, so a hot
volume split across SSD + HDD runs at HDD speed, and Postgres/WAL on a spinning disk reproduces the
fsync-stall failure class we are escaping. Its correct role is a **cold tier** for bulk, low-IOPS
data, which relieves the SSD bottleneck.

## Considered Options

* Storage tiers via Longhorn disk tags, driven from node annotations
* `nodes.longhorn.io` CRs committed to Git
* One tier (SSD only), ignore the HDD
* Put everything on the 1 TB HDD

## Decision Outcome

Chosen option: "Storage tiers via Longhorn disk tags, driven from node annotations", because the
annotation + `createDefaultDisk…` path is the supported declarative entrypoint — disk topology
lives in Git, not the UI — and a cold tier on the HDD relieves the SSD bottleneck without putting
hot data at HDD speed.

Define explicit storage tiers via Longhorn disk tags, and drive **all** Longhorn node/disk
configuration declaratively from Kubernetes node annotations set in Talos machine config (with
`createDefaultDiskLabeledNodes: true` in the Longhorn HelmRelease):

* `node.longhorn.io/default-disks-config` defines each node's disk path(s) + tag(s);
  `node.longhorn.io/default-node-tags` sets node tags — disk topology lives in Git, not the UI.
* Disk tags: `hot` (worker-1 SSD, fringe SSD) and `cold` (fringe HDD, `/var/lib/longhorn-hdd`,
  addressed by stable `by-id`/mount path, not `/dev/sdX`).
* The soyos get **no** disk config → no schedulable Longhorn disk → ADR-0026's end-state is
  config, not a manual eviction that can drift back.

The hot tier is the default `longhorn` class itself ([ADR-0029](adr-0029-storageclass-consolidation.md));
a volume's replicas never span tiers:

| StorageClass | `diskSelector` | replicas | use |
| --- | --- | --- | --- |
| `longhorn` (default) | `hot` | 2 | databases, app state — anything needing IOPS |
| `longhorn-cold` | `cold` | 1 | backups, archives, large low-IOPS/bulk volumes |

**Implementation state (2026-07-02): the mechanism is unbuilt.** The
[HelmRelease](../../../../kubernetes/apps/longhorn-system/longhorn/app/helmrelease.yaml) still sets
`createDefaultDiskLabeledNodes: false`, no node annotations exist, and the live disks carry no tags.
[`longhorn-cold`](../../../../kubernetes/apps/longhorn-system/longhorn/storageclass/cold.yaml) is
committed but **inert** — its `cold` disk doesn't exist: the fringe HDD still holds unwiped NTFS.
The wipe is deferred to the supervised dedicated-disk step gated by
[ADR-0037](adr-0037-storage-engine-gated-on-dedicated-disks.md).

### Positive Consequences

* The 1 TB HDD does useful work as a cold tier, relieving the real constraint (the SSD); disk/tag
  topology becomes declarative, reproducible on reinstall, and reviewable — closing the "tags set
  by hand in the UI" gap.
* Rollback: remove the annotations and set `createDefaultDiskLabeledNodes: false` — which is the
  still-current state.

### Negative Consequences

* More classes to keep straight; misfiling a hot volume onto `longhorn-cold` would be slow —
  mitigated by the default class being the hot tier, so cold is an explicit, reviewed choice.

## Pros and Cons of the Options

### Storage tiers via Longhorn disk tags, driven from node annotations

* Good, because the annotation + `createDefaultDisk…` path is the supported declarative
  entrypoint — disk/tag topology lives in Git, reproducible on reinstall and reviewable.
* Bad, because more classes to keep straight.

### `nodes.longhorn.io` CRs committed to Git

* Bad, because Longhorn's node CRs mix declared intent with live status and reconcile awkwardly
  via Flux.

### One tier (SSD only), ignore the HDD

* Bad, because it throws away the only relief valve for fringe's 236 GiB SSD and leaves the 1 TB
  disk idle.

### Put everything on the 1 TB HDD

* Bad, because HDD-speed Postgres/WAL is the fsync-stall failure class this RFC exists to remove.

## Links

* 2026-06-19 — proposed, as Phase C of the node-taxonomy RFC
* 2026-06-21 — the `gitops-critical` soyo disk + `longhorn-gitops` StorageClass retired unbuilt
  with the [ADR-0026](adr-0026-confine-longhorn-to-workers.md) update; the soyos get no Longhorn
  disk config at all
* 2026-07-01 — the fringe HDD wipe (the cold tier's prerequisite) deferred to the supervised disk
  step of [ADR-0037](adr-0037-storage-engine-gated-on-dedicated-disks.md); `longhorn-cold` remains
  inert and the annotation mechanism remains unbuilt
