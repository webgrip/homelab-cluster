# ADR-0028: Pin application workloads to the worker pool (hard), with forgejo excepted

> Status: **Proposed** · Date: 2026-06-19 · Part of [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md)

## Context

Once Longhorn is confined to the workers ([ADR-0026](adr-0026-confine-longhorn-to-workers.md)) and the
taxonomy exists ([ADR-0025](adr-0025-node-taxonomy.md)), workload placement must be made deliberate.
Two facts drive it:

- The soyos are **12 GiB RAM** and run etcd; overcommitting them is precisely what caused the
  OOM-cascade incidents. Apps must not crush them.
- A **stateful** pod that lands on a soyo makes that soyo run a Longhorn engine (with remote replicas)
  even though it holds no local replica — re-introducing the storage I/O on the control plane we just
  evicted. So "soyos engine-free" requires stateful pods to stay off the soyos, not just replicas.

The owner's call: apps are **not** worth keeping up by spilling onto the soyos. If the workers are
gone, apps should go **`Pending`** and wait. The sole exception is **forgejo**, the GitOps root, which
gets a storage exception (ADR-0026) and must be schedulable on the designated soyo to use it. (Earlier
in this work apps used a *soft* `workload-tier=apps` preference; it proved non-deterministic — e.g.
image-locality scoring kept n8n on a soyo even with worker capacity free — which is another reason to
go hard.)

## Decision

All **application** workloads (stateful and stateless) get a **hard** node affinity to the worker pool:

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - { key: node.webgrip.io/pool, operator: In, values: [worker] }
```

Consequences of "hard": if both workers are unavailable the pod is **`Pending`**, never on a soyo.
Stateful apps are covered by the same rule (the worker pool is exactly the storage-node set,
`storage.webgrip.io/longhorn=true`), so the soyos host no Longhorn engine.

**Control-plane-critical infra stays unconstrained** — coredns, cilium, the operators and DaemonSets
that must run everywhere (including the soyos) get **no** worker-pool affinity. The split is "apps →
worker pool; platform that must tolerate the control plane → unconstrained."

**forgejo (exception):** its affinity *permits* the designated soyo and *prefers* the workers, matching
its 3-replica `longhorn-gitops` storage (ADR-0026), so it keeps serving git in a both-worker outage:

```yaml
# required: workers OR the designated soyo ; preferred: workers
requiredDuringScheduling…: [ pool In (worker) , kubernetes.io/hostname In (<designated-soyo>) ]
preferredDuringScheduling…: [ weight 100 → pool In (worker) ]
```

This replaces the four current `workload-tier=apps` **soft** affinities and the ~11 `nodegroup=fringe`
**hard pins**, converging every app onto one model. An alert fires if an app sits `Pending` for lack of
a worker (so the trade-off is visible). Roll out one app/namespace at a time; the fringe taint is
removed only after no app depends on it (RFC Phase D).

## Consequences

- Apps are deterministically on the workers, off the RAM-tight soyos, and the soyos are Longhorn-engine
  free — completing the etcd-protection goal of ADR-0026.
- Losing both workers pauses the apps (`Pending`) rather than melting the soyos — the conscious trade.
  forgejo is the exception, so GitOps reconciliation survives.
- Every app manifest gains the same affinity block; a shared kustomize component (à la
  `components/gateway-egress`) is the natural way to avoid drift and is a likely follow-up.
- Charts that don't expose `affinity` need a post-render patch (as already used for dependency-track) —
  a known, small cost per such chart.

## Alternatives considered

- **Soft preference (`preferred…`) to the workers.** Tried and rejected: non-deterministic — the
  scheduler's other scorers (notably image locality) kept apps on soyos with worker capacity free, and
  a soft rule lets stateful pods land on a soyo and start an engine, defeating ADR-0026.
- **Allow apps to fall back to soyos under pressure (no hard rule).** Rejected by the owner: a worker
  outage would dump app load onto the 12 GiB soyos — the OOM-cascade condition.
- **Taint the soyos instead of affinity on apps.** Rejected (see [ADR-0025](adr-0025-node-taxonomy.md)):
  a taint blocks the infra that must run on the control plane and forces tolerations on it.
