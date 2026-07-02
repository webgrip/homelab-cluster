# ADR-0028: Pin application workloads to the worker pool (hard)

> Status: **Accepted** · Date: 2026-06-19 · Part of [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md) · Amended 2026-06-21 (see Status log)

## Context

With the node taxonomy in place ([ADR-0025](adr-0025-node-taxonomy.md)) and Longhorn confined to
the workers ([ADR-0026](adr-0026-confine-longhorn-to-workers.md)), placement must be deliberate.
The soyos are 12 GiB control-plane nodes running etcd; overcommitting them is what caused the
OOM-cascade incidents. And a stateful pod that lands on a soyo makes that soyo run a Longhorn
engine (with remote replicas) even though it holds no local replica — re-introducing storage I/O on
the control plane. The owner's call: apps are **not** worth keeping up by spilling onto the soyos —
if the workers are gone, apps go `Pending` and wait. An earlier *soft* `workload-tier=apps`
preference proved non-deterministic (image-locality scoring kept apps on soyos with worker capacity
free).

## Decision

All **application** workloads — stateless and stateful, including all CNPG databases — get a
**hard** node affinity to the worker pool:

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - { key: node.webgrip.io/pool, operator: In, values: [worker] }
```

If both workers are unavailable the pod is `Pending`, never on a soyo. **Control-plane-critical
infra stays unconstrained** — coredns, cilium, the everywhere-DaemonSets, and everything on the
cluster-recovery critical path (kyverno admission, external-secrets, openbao-unsealer,
trust-manager, cnpg-operator, flux/cert-manager) — so a both-worker outage can still be *recovered*.

**Mechanism — DRY via a shared component.** One reusable kustomize component,
[`components/placement/worker-pool`](../../../../kubernetes/components/placement/worker-pool/kustomization.yaml),
post-render-injects the affinity into HelmRelease-rendered Deployments/StatefulSets, raw manifests,
and CNPG `Cluster`s; an app opts in with one line in its `app/kustomization.yaml`. Apps where the
post-render patch conflicts (own `postRenderers`) or deadlocks helm-controller on an RWO volume
move (freshrss, n8n, searxng) set the same pin via native `nodeSelector` inline. forgejo and
openbao are plain worker-pinned like every other app — the original gitops-critical soyo exception
was retired (see Status log).

### Placement reference (every workload resolves to one of these)

| Class | Examples | Runs on |
| --- | --- | --- |
| Control-plane | apiserver/etcd/scheduler/controller-manager, coredns | soyos |
| Node DaemonSet | cilium, longhorn-manager/csi, node-exporter, alloy-agent, spegel | all nodes |
| Infra / operators (incl. recovery critical-path) | flux, cert-manager, cnpg-operator, external-secrets, kyverno, longhorn csi-controllers, network gateways, observability operators | unconstrained (soyos + workers) |
| **Apps** (stateless + stateful) | forgejo, openbao, authentik, harbor, n8n, all CNPG DBs, the observability stack, runners, … | **worker pool (hard)** |

### Migration traps (learned 2026-06-19 — [incident](../incidents/2026-06-19-node-taxonomy-migration-storage-churn.md))

- The PV-exclusion blocker is **StorageClass-specific, keyed on `volumeBindingMode`** — not all
  volumes. `longhorn` (`Immediate`) PVs carry **no** `nodeAffinity` → those apps pin now, no
  eviction required. `longhorn-general` (`WaitForFirstConsumer`) PVs bake in the storage nodes
  present at first bind and never refresh — they **excluded `worker-1`** (what left n8n `Pending`);
  reaching a newer worker requires migrating the volume to an `Immediate` class
  ([ADR-0029](adr-0029-storageclass-consolidation.md)). **Eviction does not help** — it cannot
  rewrite the immutable PV `nodeAffinity`.
- A single-replica RWO **Deployment** that the pin relocates needs `strategy: Recreate`, else a
  Multi-Attach rollout deadlock.
- A `register-with-taints` taint (the old `dedicated=fringe`) applies only at node registration;
  removing it takes a re-registration (reboot) or a manual `kubectl taint … -`.

## Alternatives considered

- **Soft preference (`preferred…`) to the workers** — tried and rejected: non-deterministic (image
  locality kept apps on soyos with capacity free), and a soft rule lets a stateful pod start a soyo
  Longhorn engine, defeating ADR-0026.
- **Allow fallback to soyos under pressure** — rejected by the owner: a worker outage would dump
  app load onto the 12 GiB soyos, the OOM-cascade condition.
- **Taint the soyos instead of affinity on apps** — rejected ([ADR-0025](adr-0025-node-taxonomy.md)):
  a taint blocks the infra that must run on the control plane and forces tolerations onto it.

## Consequences

- Apps are deterministically on the workers and the soyos host no Longhorn engine — completing
  ADR-0026's etcd-protection goal.
- Losing both workers pauses the apps (`Pending`) rather than melting the soyos — the conscious
  trade; recovery infra keeps running unconstrained.
- Placement policy lives in one component + this ADR, not scattered per-manifest; retiring the
  fringe taint/nodeSelector scheme net-simplified the tree.
- Rollback: drop the component include (or the inline `nodeSelector`) per app; the scheduler
  reverts to free placement.

## Status log

- 2026-06-19 — Proposed with the RFC; the `worker-pool` component + placement model landed the same
  day (038c0717).
- 2026-06-19 — Sequencing refined after the n8n canary: roll out by `volumeBindingMode`, not
  statefulness; RWO `strategy: Recreate` trap recorded (28cf8f9e, 0498d512).
- 2026-06-20 — freshrss/n8n/searxng pinned via native `nodeSelector` where the post-render patch
  deadlocks on RWO moves (686271cb).
- 2026-06-21 — The gitops-critical exception (forgejo + openbao permitted on a designated soyo with
  `longhorn-gitops` replicas) retired with the ADR-0026 update; both are plain worker-pinned.
- 2026-07-02 — Accepted (status corrected in ADR audit; implemented and in effect since 2026-06-19).
