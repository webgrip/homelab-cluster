# ADR-0027: Longhorn hot/cold storage tiers (SSD/HDD), configured from node annotations

> Status: **Proposed** (the `gitops-critical` soyo disk is **dropped**) · Date: 2026-06-19 · Part of [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md)
>
> **Update (2026-06-21):** the `gitops-critical` disk on a designated soyo and the `longhorn-gitops`
> StorageClass are **retired** — see the [ADR-0026](adr-0026-confine-longhorn-to-workers.md) update. The
> soyos get **no** Longhorn disk config at all. The `hot` (worker SSD) and `cold` (fringe HDD) tiers in
> this ADR still stand; only the gitops row is dropped.

## Context

With Longhorn confined to the two workers ([ADR-0026](adr-0026-confine-longhorn-to-workers.md)),
fringe's **236 GiB SSD** becomes the binding capacity constraint: under hard anti-affinity it must hold
a full second copy of every hot volume. fringe also has a **1 TB HDD** that is currently unused by
Longhorn — the `longhorn-hdd` StorageClass exists with `diskSelector: hdd`, but **no disk is tagged
`hdd`**, so it matches nothing. More broadly, Longhorn node/disk configuration in this cluster is **not
GitOps-managed** today (no `nodes.longhorn.io` manifests; disks/tags would have to be clicked in the
UI), which is both undeclared and the reason the soyos still auto-create Longhorn disks.

The HDD is not spare hot capacity: Longhorn writes a volume's replicas **synchronously**, so a hot
volume split across SSD + HDD runs at HDD speed, and Postgres/WAL on a spinning disk reproduces the
fsync-stall failure class we are escaping. The HDD's correct role is a **cold tier** for bulk,
low-IOPS data — which, used that way, relieves the SSD bottleneck.

## Decision

Define explicit **storage tiers** via Longhorn disk tags, and drive **all** Longhorn node/disk
configuration declaratively from **Kubernetes node annotations** set in Talos machine config (with
`createDefaultDiskLabeledNodes: true` in the Longhorn HelmRelease):

- `node.longhorn.io/default-disks-config` annotation defines each node's disk path(s) + tag(s);
  `node.longhorn.io/default-node-tags` sets node tags. Set via Talos `machine.nodeLabels`/annotations,
  so disk topology is in Git, not the UI.
- **Disk tags:** `hot` (worker-1 SSD, fringe SSD), `cold` (fringe HDD `/var/lib/longhorn-hdd`),
  `gitops-critical` (the small disk on one designated soyo, for forgejo only — see ADR-0026).
- **soyos get no default disk config** (other than the one `gitops-critical` disk) → no schedulable
  Longhorn disk → the GitOps-clean enforcement of ADR-0026.

StorageClasses (the "hot" tier is the **default `longhorn` class itself** — there is no separate
`longhorn-hot`; see [ADR-0029](adr-0029-storageclass-consolidation.md)):

| StorageClass | `diskSelector` | replicas | use |
|---|---|---|---|
| `longhorn` (default) | `hot` | 2 | databases, app state — anything needing IOPS (the hot/SSD tier) |
| `longhorn-cold` | `cold` | 1 | backups, archives, large low-IOPS/bulk volumes |
| `longhorn-gitops` | `gitops` | 3 | **only** `forgejo-data` + `forgejo-db` (ADR-0026) |

**A volume's replicas never span tiers** (a hot SC selects only `hot` disks). Migrate identified
bulk/cold volumes off the SSD onto `longhorn-cold` to keep fringe's 236 GiB SSD within over-provisioned
headroom, and add a Longhorn-SSD usage alert.

## Consequences

- The 1 TB HDD finally does useful work, as a cold tier — relieving the real constraint (the 236 GiB
  SSD) instead of pretending to be hot capacity.
- Longhorn disk/tag topology is **declarative in Git** (via node annotations), reproducible on
  reinstall, and reviewable — closing the "tags set by hand in the UI" gap.
- The same mechanism enforces "no Longhorn disk on soyos," so ADR-0026's end-state is config, not a
  manual eviction that could drift back.
- More StorageClasses to keep straight; misfiling a hot volume onto `longhorn-cold` would be slow.
  Mitigated by `longhorn-hot` being the default and an explicit, reviewed choice for cold.
- Talos disk-letter instability is sidestepped: the HDD is addressed by stable `by-id`/mount path (as
  the existing fringe patch already does), and tags ride node annotations, not `/dev/sdX`.

## Alternatives considered

- **`nodes.longhorn.io` CRs committed to Git.** Workable but Longhorn's node CRs mix declared intent
  with live status and are awkward to reconcile via Flux; the node-annotation + `createDefaultDisk…`
  path is the supported declarative entrypoint.
- **One tier (SSD only), ignore the HDD.** Rejected: it throws away the only relief valve for fringe's
  236 GiB SSD and leaves the 1 TB disk idle.
- **Put everything on the 1 TB HDD (fits 541 GiB provisioned).** Rejected: HDD-speed Postgres/WAL is
  the fsync-stall failure class this whole RFC exists to remove.
