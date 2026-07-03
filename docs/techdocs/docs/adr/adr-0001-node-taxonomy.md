# Capability-based node taxonomy (labels), retiring the `fringe` taint/`nodegroup` scheme

* Status: accepted
* Date: 2026-06-21

Technical Story: [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md)

## Context and Problem Statement

Node placement had grown incoherent, keyed off facts we don't want to depend on: a
`dedicated=fringe:NoSchedule` **taint** with ~11 apps carrying matching tolerations plus a
`nodegroup=fringe` nodeSelector; a one-off `workload-tier=apps` label on worker-1; `nodegroup=soyo`
on the control-planes; and implicit reliance on `node-role.kubernetes.io/control-plane` meaning
"infra goes here". The owner wants placement keyed on **what a node can do**, not its identity or
current role (roles may change), and the taint/`nodegroup` complexity gone. There is no upstream
standard label for capability tiers, and Kubernetes reserves the `kubernetes.io/`/`k8s.io/`
prefixes, directing custom semantics to **domain-prefixed** labels. Taint-vs-label reasoning:
[RFC](../rfc/rfc-node-taxonomy-and-storage-placement.md).

## Considered Options

* Domain-prefixed capability labels via Talos `machine.nodeLabels`
* `node-role.kubernetes.io/{worker,storage}`
* Keep `nodegroup`/`workload-tier`
* Taint the soyos to keep apps off

## Decision Outcome

Chosen option: "Domain-prefixed capability labels via Talos `machine.nodeLabels`", because
placement should key on **what a node can do** — not its identity or current role — and Kubernetes
reserves the `kubernetes.io/`/`k8s.io/` prefixes, directing custom semantics to domain-prefixed
labels.

Adopt a **domain-prefixed capability taxonomy**, set via Talos `machine.nodeLabels`:

| Label | Values | On |
| --- | --- | --- |
| `node.webgrip.io/pool` | `worker` \| `soyo` | all nodes |
| `node.webgrip.io/cpu` | `high` \| `standard` | `high` = fringe |
| `node.webgrip.io/ram` | `high` \| `standard` \| `low` | `high` = worker-1, `low` = soyos |
| `storage.webgrip.io/longhorn` | `"true"` | worker-1 + fringe |

Principles: **taints are for protection only** (never for capability); capability is expressed as
labels and consumed via `nodeAffinity` (attraction, opt-in); scheduling must not key off the
control-plane role. The soyos get **no app-exclusion taint** — apps are kept off them by a hard
affinity toward `pool=worker` ([ADR-0002](adr-0002-application-workload-placement.md)), leaving the
soyos open to the infra/system pods that belong there.

**Retire the `fringe` scheme:** remove the `dedicated=fringe:NoSchedule` taint and the
`nodegroup=soyo|fringe` labels; re-home the fringe-pinned apps onto `pool=worker` affinity; keep
`workload-tier=apps` only as a transitional alias, then delete it.

This is the umbrella for the placement family:
[ADR-0008](adr-0008-confine-longhorn-to-workers.md) confines Longhorn replicas to the workers,
[ADR-0009](adr-0009-longhorn-hot-cold-tiers.md) adds hot/cold storage tiers via Longhorn tags
(which are not k8s labels), [ADR-0002](adr-0002-application-workload-placement.md) pins application
workloads to the worker pool, and [ADR-0010](adr-0010-storageclass-consolidation.md) consolidates
the StorageClasses.

### Positive Consequences

* Placement is self-describing and role-independent: a new node is onboarded by labelling its
  capabilities, and workloads it qualifies for follow automatically.
* The `fringe` taint and per-app tolerations are gone — fringe is "just a worker" (high-CPU + the
  HDD cold disk); both workers are interchangeable hosts for apps.
* Labels live in Talos machine config (GitOps); applying them is a no-reboot `apply-node`. A node
  with no `node.webgrip.io/*` labels is a misconfiguration a future guard could lint for.

### Negative Consequences

* The Talos patch **filenames** still carry legacy names (`talos/patches/worker/fringe-dedicated.yaml`,
  `talos/patches/controller/nodegroup-soyo.yaml`); their contents are migrated — cosmetic naming
  debt only.

## Pros and Cons of the Options

### Domain-prefixed capability labels via Talos `machine.nodeLabels`

* Good, because placement becomes self-describing and role-independent — a new node is onboarded
  by labelling its capabilities, and workloads it qualifies for follow automatically.
* Good, because the `fringe` taint and per-app tolerations go away — both workers become
  interchangeable hosts for apps.

### `node-role.kubernetes.io/{worker,storage}`

* Bad, because it re-introduces the role-coupling being removed, and the prefix is conventionally
  cluster-managed; a ROLES-column nicety can be added later without changing the scheme.

### Keep `nodegroup`/`workload-tier`

* Bad, because ad hoc, not capability-shaped, and the `fringe` taint forces tolerations
  everywhere; exactly the complexity being removed.

### Taint the soyos to keep apps off

* Bad, because it blocks the infra that legitimately runs on control-planes and forces tolerations
  on it; hard worker-pool affinity achieves the same without that blast radius.

## Links

* 2026-06-19 — proposed; capability labels applied via Talos patches the same day, and the
  `dedicated=fringe:NoSchedule` taint + `nodegroup` labels retired
* 2026-06-21 — transitional `workload-tier` and straggler `nodegroup` labels retired; fully
  implemented (labels live on all 5 nodes, zero taints) — accepted
* 2026-07-03 — renumbered from ADR-0025 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
