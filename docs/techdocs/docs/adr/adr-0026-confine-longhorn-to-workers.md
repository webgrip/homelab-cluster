# ADR-0026: Confine Longhorn storage to the worker nodes (protect etcd), with a scoped forgejo exception

> Status: **Proposed** · Date: 2026-06-19 · Part of [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md)

## Context

The soyo control-planes are N150 / 12 GiB boxes with a **single 512 GB SSD shared by etcd, the OS, and
Longhorn replicas**. Every storage SEV this cluster has had — rebuild storms, instance-manager OOM, the
"guaranteed-IM-cpu delayed detonation" pattern, fsync stalls — traces to Longhorn contending with etcd
on that one disk. Tuning Longhorn has only ever moved the problem around; the structural fix is to
**take Longhorn off the soyos** so etcd has its disk and RAM back.

Measured: 47 volumes, 541 GiB provisioned / 115 GiB actual, `replica-soft-anti-affinity=false` (HARD
anti-affinity). The two workers (worker-1 SSD 891 GiB, fringe SSD 236 GiB) are the only nodes that
should hold replicas. An orphan Longhorn node `slab` (worker-1's previous identity, 0 replicas) needs
GC.

One workload complicates a clean "soyos = zero Longhorn": **forgejo is the cluster's GitOps root** —
Flux reconciles by cloning its git repos, which (with its CNPG DB) live on Longhorn, not S3 (only bulk
attachments are on Garage S3). With storage confined to the two workers, forgejo cannot run during a
**both-worker** outage. The owner accepts a scoped exception so the GitOps root stays serveable.

## Decision

**Longhorn replicas live only on worker-1 + fringe; the soyos hold zero replicas.** Enforced at the
**Longhorn layer** (the soyos get no schedulable Longhorn disk — see
[ADR-0027](adr-0027-longhorn-hot-cold-tiers.md)'s node-annotation mechanism), not via Kubernetes
taints. Two storage nodes + hard anti-affinity ⇒ a **2-replica ceiling**; the 11 current 3-replica
volumes drop to 2. Accept it now and over-provision (115 GiB actual fits fringe's 236 GiB SSD).

**gitops-critical exception:** one designated soyo keeps a small Longhorn disk tagged `gitops-critical`.
A dedicated `longhorn-gitops` StorageClass (numberOfReplicas **3**, disks tagged `gitops`) is used
**only** by the two GitOps/bootstrap-critical workloads — **forgejo** (`forgejo-data` + `forgejo-db`,
the Flux source) and **openbao** (the secrets backend) — so each of those volumes gets a replica on
both workers **and** on the designated soyo. Their pods are allowed to run on that soyo
([ADR-0028](adr-0028-application-workload-placement.md)), so forgejo keeps serving git and openbao keeps
serving secrets even if both workers fail.

Migration is phased and evictive (not a drain — etcd quorum is untouched): open worker-1, GC `slab`,
reduce 3-replica volumes → 2, then evict soyos **one at a time** (`allowScheduling=false` +
`evictionRequested=true`, waiting for 0 replicas + all volumes healthy before the next), and finally
lock the soyos storage-free and lower `guaranteedInstanceManagerCPU` (the detonation trigger) now that
no soyo runs instance-managers under load.

## Consequences

- etcd gets its disk and RAM back on every soyo (the designated one retains only forgejo's scoped I/O)
  — this removes the root cause of the recurring storage SEVs.
- HA tolerates losing **one** of {worker-1, fringe}; losing both is a full storage outage (forgejo
  excepted). A 3rd storage node or a bigger fringe SSD (RFC follow-up) restores a 3-replica ceiling.
- The eviction **also resolves the current 38-degraded rebuild storm** by rebuilding onto worker-1's
  large empty SSD instead of wedging on the soyos' single rebuild slot.
- **Eviction is a prerequisite for stateful worker-pinning, not just a cleanup.** Existing Longhorn PVs
  created before `worker-1` joined have a `nodeAffinity` that excludes it ([incident 2026-06-19](../incidents/2026-06-19-node-taxonomy-migration-storage-churn.md));
  placing a replica on `worker-1` (what eviction does) is what *opens* the PV affinity so a stateful pod
  can attach there. So **Phase E precedes stateful pinning** ([ADR-0028](adr-0028-application-workload-placement.md) D2).
- The forgejo exception puts bounded Longhorn I/O back on one soyo; revisit (fold forgejo into the
  worker-only pool) when a 3rd storage node arrives.
- fringe's 236 GiB SSD is the binding constraint; depends on over-provisioning + active cold-tiering
  ([ADR-0027](adr-0027-longhorn-hot-cold-tiers.md)) and a usage alert.
- **Follow-up — make the soyos fully storage-free.** Once replicas + stateful pods are off the soyos,
  the Longhorn DaemonSets (`longhorn-manager`, `longhorn-csi-plugin`, `engine-image`) still run there by
  default. Restrict them to the storage nodes (`storage.webgrip.io/longhorn=true` via the chart's
  `longhornManager`/`longhornDriver` nodeSelector) so the soyos run *no* Longhorn components at all —
  except on the one designated `gitops-critical` soyo, which must keep them for the forgejo/openbao
  replicas.

## Alternatives considered

- **Keep replicas on soyos, tune Longhorn harder** (anti-affinity, rebuild limits, IM CPU). Rejected:
  every prior tuning round has only relocated the contention; etcd sharing a disk with Longhorn is the
  defect.
- **No forgejo exception (forgejo hard-pinned like everything else).** Rejected by the owner: a
  both-worker outage would stop GitOps reconciliation entirely. The exception is scoped to two volumes
  and one soyo — a deliberate, bounded dent in the etcd-protection goal for the GitOps root.
- **Three replicas everywhere via a 3rd storage node now.** Deferred: it's a hardware change; the
  2-replica ceiling is acceptable interim and is called out as the headline follow-up in the RFC.
- **k8s taints to keep Longhorn off soyos.** Rejected: replica placement is Longhorn's scheduler, not
  the kube-scheduler; the clean lever is "no Longhorn disk on the node," driven from node annotations.
