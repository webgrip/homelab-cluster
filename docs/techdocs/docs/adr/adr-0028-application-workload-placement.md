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
worker pool; platform that must tolerate the control plane → unconstrained." Critically, the infra on
the **cluster-recovery critical path** (kyverno admission, external-secrets, openbao-unsealer,
trust-manager, cnpg-operator, flux/cilium/cert-manager) stays `unconstrained` so a both-worker outage
can still be *recovered* (admission control + secret delivery keep working on a soyo).

**gitops-critical exceptions:** **forgejo** (the Flux source) and **openbao** (the secrets backend)
keep a storage replica on one designated soyo (`longhorn-gitops`, 3 replicas — ADR-0026) **and** an
affinity that *permits* that soyo while *preferring* the workers, so both survive a both-worker outage:

```yaml
# required: workers OR the designated soyo ; preferred: workers
requiredDuringScheduling…: [ pool In (worker) , kubernetes.io/hostname In (<designated-soyo>) ]
preferredDuringScheduling…: [ weight 100 → pool In (worker) ]
```

### Placement reference (every workload resolves to one of these)

| Class | Examples | Runs on |
|---|---|---|
| Control-plane | apiserver/etcd/scheduler/controller-manager, coredns | soyos |
| Node DaemonSet | cilium, longhorn-manager/csi, node-exporter, alloy-agent, spegel | all nodes |
| Infra / operators (incl. recovery critical-path) | flux, cert-manager, cnpg-operator, external-secrets, kyverno, keda*, longhorn csi-controllers, network gateways, observability operators, mcp servers | unconstrained (soyos + workers) |
| **Apps** (stateless + stateful) | authentik, harbor, n8n, sparkyfitness, dependency-track, guac, grafana/prometheus/loki/alertmanager, all CNPG DBs, invoiceninja, freshrss, searxng, minecraft, drawio, excalidraw, backstage, trivy-server, **observability stack**, **ARC runners** | **worker pool (hard)** |
| **gitops-critical** | **forgejo (+forgejo-db), openbao** | **worker pool + 1 designated soyo** |

\* KEDA is part of the forgejo-runner autoscaling path → worker pool. `echo` and the stale `default/envoy-*`
duplicates are deleted, not placed.

This **retires the `fringe` scheme entirely** — every `nodegroup=fringe` nodeSelector + the
`dedicated=fringe:NoSchedule` taint are removed (ADR-0025); apps that were pinned to fringe move to the
worker pool. It also replaces the four `workload-tier=apps` soft affinities. An alert fires if an app
sits `Pending` for lack of a worker. Roll out one namespace at a time; the fringe taint is removed last.

> **Sequencing (learned the hard way — 2026-06-19).** Existing Longhorn PVs created before `worker-1`
> joined have a `nodeAffinity` that excludes it, so a **stateful** pod pinned to the worker pool can't
> attach on `worker-1` until a replica is placed there. Therefore **eviction ([ADR-0026](adr-0026-confine-longhorn-to-workers.md)
> Phase E) must precede stateful worker-pinning.** Phase D splits: **D1 = stateless apps now** (no PVC →
> reach any worker), **D2 = stateful apps after Phase E** opens the PV affinity. Also: the
> `dedicated=fringe` taint can only be removed by re-registering fringe (reboot) or manually
> (`kubectl taint … -`) — `register-with-taints` applies only at node registration.

### Mechanism — DRY via a shared component

Placement is applied through one reusable kustomize component,
[`components/placement/worker-pool`](../../../../kubernetes/components/placement/worker-pool/kustomization.yaml)
(house style, like `components/gateway-egress`). An app opts in with one line in its
`app/kustomization.yaml`. The component injects the hard `pool=worker` affinity into HelmRelease-rendered
Deployments/StatefulSets (via a post-render patch — chart-agnostic), raw Deploy/StatefulSet manifests,
and CNPG `Cluster`s (`spec.affinity.nodeSelector`). Apps that already define their own `postRenderers`
(dependency-track) set the same affinity inline instead; forgejo/openbao use the gitops-critical
placement, not this component.

## Consequences

- Apps are deterministically on the workers, off the RAM-tight soyos, and the soyos are Longhorn-engine
  free — completing the etcd-protection goal of ADR-0026.
- Losing both workers pauses the apps (`Pending`) rather than melting the soyos — the conscious trade.
  forgejo is the exception, so GitOps reconciliation survives.
- Placement policy lives in **one component + this ADR**, not scattered across ~40 manifests; an app is
  pinned by adding one line to its `app/kustomization.yaml`.
- The component is chart-agnostic (post-render patch), so charts that don't expose `affinity` are
  handled uniformly — no per-chart values archaeology, except the few with their own `postRenderers`.
- Retiring the fringe scheme removes a node taint + ~11 per-app tolerations/selectors, net-simplifying
  the tree.

## Alternatives considered

- **Soft preference (`preferred…`) to the workers.** Tried and rejected: non-deterministic — the
  scheduler's other scorers (notably image locality) kept apps on soyos with worker capacity free, and
  a soft rule lets stateful pods land on a soyo and start an engine, defeating ADR-0026.
- **Allow apps to fall back to soyos under pressure (no hard rule).** Rejected by the owner: a worker
  outage would dump app load onto the 12 GiB soyos — the OOM-cascade condition.
- **Taint the soyos instead of affinity on apps.** Rejected (see [ADR-0025](adr-0025-node-taxonomy.md)):
  a taint blocks the infra that must run on the control plane and forces tolerations on it.
