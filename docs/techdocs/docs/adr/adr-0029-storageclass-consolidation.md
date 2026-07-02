# ADR-0029: Consolidate Longhorn StorageClasses to a minimal, intent-named set

> Status: **Proposed** · Date: 2026-06-19 · Part of [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md) · Amended 2026-06-21 (see Status log)

## Context

The cluster had **ten** Longhorn StorageClasses, only two carrying data: `longhorn` (the chart's
default, **3 replicas** — the CNPG databases + observability StatefulSets) and `longhorn-general`
(**2 replicas** — the app volumes). The two are functionally identical — no `diskSelector`,
`dataLocality: disabled` — differing *only* in replica count. That is split-brain: which name a
manifest happens to use decides its replica count. The 3-replica default is also wrong for this
cluster: with two storage nodes and hard anti-affinity
([ADR-0026](adr-0026-confine-longhorn-to-workers.md)), **2 is the ceiling anyway**. The remaining
classes (`longhorn-hot`, `-hdd`, `-cache`, `-static`, `-rwx`, `-snapshot`) had zero bound volumes.

## Decision

Collapse to a minimal, GitOps-owned, intent-named set at the 2-replica ceiling:

| Class | Replicas | Disk | Purpose |
| --- | --- | --- | --- |
| **`longhorn`** (default) | 2 | SSD | the one general-purpose class — this *is* the "hot" tier |
| `longhorn-cold` | 1 | HDD (`cold`) | bulk / low-IOPS — [ADR-0027](adr-0027-longhorn-hot-cold-tiers.md) |
| `longhorn-rwx` | 2 | SSD | ReadWriteMany (NFS) workloads |
| `longhorn-snapshot` | 1 | SSD | restore source |

**Retire:** `longhorn-general` (fold into `longhorn`), `longhorn-hot` (the default *is* SSD/hot),
`longhorn-hdd` (→ `longhorn-cold`), `longhorn-cache` (unused). `longhorn` becomes a GitOps-owned
2-replica class instead of the chart's 3-replica default.

**Staged execution** — the convergence touches the immutable `longhorn` SC, so it is deliberate:

- **Stage 1 (done 2026-06-19, safe, no data impact):** `defaultSettings.defaultReplicaCount: "2"`;
  the empty redundant classes deleted; existing 3-replica volumes were reduced to 2 at runtime.
- **Stage 2 (open):** converge the chart's `longhorn` SC to 2 replicas + the SSD `diskSelector` by
  **recreating** it — `numberOfReplicas` is an immutable StorageClass parameter, so it's
  delete+create. A StorageClass is metadata: bound PVCs are unaffected; only a sub-second
  new-provision gap, done in a window. Then retire `longhorn-general` by repointing its references
  to `longhorn` and letting volumes recreate onto it.

As of 2026-07-02 Stage 2 has not run: the chart-created `longhorn` SC still carries
`numberOfReplicas: 3` (acknowledged in the
[HelmRelease](../../../../kubernetes/apps/longhorn-system/longhorn/app/helmrelease.yaml) comment)
and `longhorn-general` is still referenced by ~18 manifests.

## Alternatives considered

- **Keep both `longhorn` and `longhorn-general`** — that *is* the split-brain to remove.
- **Rename `longhorn-general` → `longhorn-hot` as the keeper** — churn for no gain; forces
  migrating the app volumes off a good name; the conventional `longhorn` default is the natural
  keeper.
- **Force-replace the `longhorn` SC to 2 replicas immediately (`upgrade.force`)** — an
  immutable-resource force-replace on the Longhorn HelmRelease during an active rebuild is exactly
  the kind of storage change this cluster has been burned by; deferred to a window (Stage 2).

## Consequences

- One obvious default at 2 replicas, matching the storage ceiling; new volumes are consistent.
- Existing bound PVCs are unaffected at every step (PVCs cache their class; PVs reference the
  provisioner). `longhorn-general` lingers as deprecated until its references migrate.
- Until Stage 2 lands, the split-brain persists in reduced form: manifests naming `longhorn` still
  provision 3-replica volumes.
- Rollback: Stage 1 is a settings value; Stage 2's recreate is reversed by recreating the previous
  StorageClass definition.

## Status log

- 2026-06-19 — Proposed; Stage 1 executed in the same commit (6fa8b38c): `defaultReplicaCount: "2"`
  plus deletion of the redundant empty classes.
- 2026-06-21 — `longhorn-gitops` (the planned 3-replica forgejo/openbao exception) retired unbuilt
  with the [ADR-0026](adr-0026-confine-longhorn-to-workers.md) update; dropped from the target set.
- 2026-07-02 — Stage 2 still open: the chart `longhorn` SC remains 3-replica and `longhorn-general`
  is still referenced (~18 manifests).
