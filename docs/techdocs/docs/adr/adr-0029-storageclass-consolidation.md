# ADR-0029: Consolidate Longhorn StorageClasses to a minimal, intent-named set

> Status: **Proposed** · Date: 2026-06-19 · Part of [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md)

## Context

The cluster had **ten** Longhorn StorageClasses, but only two carry data: `longhorn` (default,
**3 replicas**, 31 bound PVCs — the CNPG databases + observability StatefulSets) and `longhorn-general`
(**2 replicas**, 16 bound PVCs — the app volumes). They are **functionally identical** — both have no
`diskSelector` and `dataLocality: disabled` — and differ *only* in replica count.

This is split-brain. `longhorn-general` was created to be "the 2-replica app default," but the chart's
3-replica `longhorn` was never demoted, so workloads that name `longhorn` (34 manifest references) keep
landing on 3 replicas while apps that name `longhorn-general` (18 references) get 2. The 3-replica
default is also wrong for this cluster: with only two storage nodes and HARD anti-affinity
([ADR-0026](adr-0026-confine-longhorn-to-workers.md)), **2 is the ceiling anyway**. The
[Phase C work](adr-0027-longhorn-hot-cold-tiers.md) made it worse by adding a `longhorn-hot` class
that is redundant with `longhorn-general`. The remaining classes (`longhorn-hdd`, `-cache`, `-static`,
`-rwx`, `-snapshot`) have **zero** bound volumes.

**What the ecosystem does:** exactly one default StorageClass; define classes explicitly in Git rather
than relying on a chart's opinionated default; keep the set minimal and intent-named; add a tier only
when it expresses a *real* difference (replica count, disk medium, access mode). The chart-default
vs. hand-rolled-default overlap we have is the canonical anti-pattern.

## Decision

Collapse to a **minimal, GitOps-owned, intent-named set**, all at the 2-replica ceiling except the
scoped forgejo exception:

| Class | Replicas | Disk | Purpose |
|---|---|---|---|
| **`longhorn`** (default) | 2 | SSD | the one general-purpose class — this *is* the "hot" tier (no separate `longhorn-hot`) |
| `longhorn-cold` | 1 | HDD (`cold`) | bulk / low-IOPS (backups, archives) — [ADR-0027](adr-0027-longhorn-hot-cold-tiers.md) |
| `longhorn-gitops` | 3 | SSD + soyo (`gitops`) | forgejo exception only — [ADR-0026](adr-0026-confine-longhorn-to-workers.md) |
| `longhorn-rwx` | 2 | SSD | ReadWriteMany (NFS) workloads |
| `longhorn-snapshot` | 1 | SSD | restore source |

**Retire:** `longhorn-general` (fold into `longhorn`), `longhorn-hot` (redundant — the default *is*
SSD/hot), `longhorn-hdd` (→ `longhorn-cold`), `longhorn-cache` (unused). `longhorn` becomes a
**GitOps-owned 2-replica** class rather than the chart's 3-replica default.

**Staged execution** (the convergence touches the immutable `longhorn` SC, so it is deliberate, not a
quick toggle):

- **Stage 1 — now (safe, no data impact):** `defaultSettings.defaultReplicaCount: 2`; delete the empty
  redundant classes (`longhorn-hot`, `longhorn-hdd`); this ADR. Existing volumes are already at 2 (the
  3-replica ones were reduced at runtime on 2026-06-19).
- **Stage 2 — with the disk-tagging / soyo-eviction migration:** converge `longhorn` to 2 replicas +
  the SSD `diskSelector` by **recreating** the StorageClass (its `numberOfReplicas` parameter is
  immutable, so it's delete+create — a StorageClass is metadata, so bound PVCs are unaffected; only a
  sub-second new-provision gap, done in a window). Then retire `longhorn-general` by repointing its
  references to `longhorn` and letting volumes recreate onto it.

## Consequences

- One obvious default, 2 replicas, matching the storage ceiling — no more "did this land on 3 or 2?".
- The StorageClass set drops from 10 → 5 intent-named classes; new volumes are consistent.
- Existing bound PVCs are unaffected at every step (PVCs cache their class; PVs reference the
  provisioner). `longhorn-general` lingers as **deprecated** until its 16 refs migrate.
- The `longhorn` convergence is a deliberate recreate gated on a maintenance window, not done on
  still-healing storage — consciously sequenced with the migration, not rushed.

## Alternatives considered

- **Keep both `longhorn` and `longhorn-general`.** Rejected — that *is* the split-brain; two identical
  classes with different replica counts is the confusion to remove.
- **Rename `longhorn-general` → `longhorn-hot` as the keeper.** Rejected — churn for no gain and it
  would force migrating 16 app volumes off a perfectly good class name; the conventional `longhorn`
  default is the natural keeper.
- **Force-replace the `longhorn` SC to 2 replicas immediately** (`upgrade.force`). Rejected for now —
  an immutable-resource force-replace on a Longhorn HelmRelease during an active rebuild is exactly the
  kind of storage change this cluster has been burned by; deferred to a window (Stage 2).
