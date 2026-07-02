# ADR-0026: Confine Longhorn storage to the worker nodes (protect etcd)

> Status: **Accepted** · Date: 2026-06-19 · Part of [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md) · Amended 2026-06-21 (see Status log)

## Context

The soyo control-planes are N150 / 12 GiB boxes with a **single 512 GB SSD shared by etcd, the OS,
and Longhorn replicas**. Every storage SEV this cluster has had — rebuild storms, instance-manager
OOM, the "guaranteed-IM-cpu delayed detonation" pattern, fsync stalls — traces to Longhorn
contending with etcd on that one disk. Tuning Longhorn has only ever moved the problem around; the
structural fix is to take Longhorn off the soyos so etcd has its disk and RAM back. Measured at
decision time (2026-06-19): 47 volumes, 541 GiB provisioned / 115 GiB actual, hard replica
anti-affinity; the workers (worker-1 SSD 891 GiB, fringe SSD 236 GiB) are the only nodes that
should hold replicas.

## Decision

**Longhorn replicas live only on worker-1 + fringe; the soyos hold zero replicas — no exceptions.**
Enforced at the **Longhorn layer** (the soyos get no schedulable Longhorn disk and are locked
`allowScheduling=false` — [ADR-0027](adr-0027-longhorn-hot-cold-tiers.md)'s node/disk mechanism),
not via Kubernetes taints. Two storage nodes + hard anti-affinity give a **2-replica ceiling**;
accepted and over-provisioned (115 GiB actual fits fringe's 236 GiB SSD).

The GitOps-critical workloads get no storage exception: **forgejo and openbao are worker-pinned
like any other app**, with DR via **external Garage S3** (Longhorn backup target for
`forgejo-data`/`gitea-mirror`, CNPG barman for `forgejo-db`, raft snapshots for openbao) and
forgejo's reconcile-resilience handled by the GitHub fallback source
([ADR-0015](adr-0015-external-bootstrap-fallback-source.md)).

The migration was **evictive, not a drain** (etcd quorum untouched): 3-replica volumes reduced to
2, soyos evicted one at a time (`allowScheduling=false` + `evictionRequested=true`), then locked
storage-free. Eviction also *opens* pre-worker-1 PV `nodeAffinity` — the prerequisite for stateful
worker-pinning ([incident 2026-06-19](../incidents/2026-06-19-node-taxonomy-migration-storage-churn.md)).

## Alternatives considered

- **Keep replicas on soyos, tune Longhorn harder** — every prior tuning round only relocated the
  contention; etcd sharing a disk with Longhorn is the defect.
- **k8s taints to keep Longhorn off the soyos** — replica placement is Longhorn's scheduler, not
  kube-scheduler; the clean lever is "no Longhorn disk on the node".
- **A 3rd storage node now (3 replicas everywhere)** — a hardware change; deferred, and the
  headline RFC follow-up.
- **A scoped soyo-replica exception for the GitOps root** — a 3-replica `longhorn-gitops` class
  keeping forgejo/openbao serveable through a both-worker outage. Initially adopted, dropped
  2026-06-21 before being built (see Status log).

## Consequences

- etcd gets its disk and RAM back on every soyo — removing the root cause of the recurring storage
  SEVs; the eviction also cleared the then-running 38-degraded rebuild storm.
- HA tolerates losing one of {worker-1, fringe}; losing both is a full storage outage, with
  restore-from-external-Garage-S3 as the DR path. A 3rd storage node or bigger fringe SSD restores
  a 3-replica ceiling.
- fringe's 236 GiB SSD is the binding constraint — depends on over-provisioning, cold-tiering
  ([ADR-0027](adr-0027-longhorn-hot-cold-tiers.md)), and a usage alert.
- Live caveats (checked 2026-07-02): one straggler replica remains on soyo-2 (eviction not fully
  converged), and the follow-up to restrict the Longhorn DaemonSets (`longhorn-manager`/CSI) to
  storage nodes is **not done** — `longhornManager` carries only a stale fringe-taint toleration,
  so the soyos still run Longhorn system pods.

## Status log

- 2026-06-19 — Accepted, with a scoped "gitops-critical" exception: one designated soyo was to keep
  a small tagged Longhorn disk + a 3-replica `longhorn-gitops` StorageClass for forgejo + openbao,
  so the GitOps root stayed serveable through a both-worker outage.
- 2026-06-21 — Exception dropped; the soyos stay 100% Longhorn-free. Garage S3 is external
  (off-cluster), so backups survive a both-worker outage, and
  [ADR-0015](adr-0015-external-bootstrap-fallback-source.md) decouples forgejo's
  reconcile-resilience from its storage. `longhorn-gitops` and the `gitops-critical` soyo disk
  retired unbuilt; forgejo/openbao worker-pinned.
