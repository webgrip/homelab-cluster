# ADR-0025: Capability-based node taxonomy (labels), retiring the `fringe` taint/`nodegroup` scheme

> Status: **Proposed** · Date: 2026-06-19 · Part of [RFC: Node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md)

## Context

Node placement today is incoherent and keys off facts we don't want to depend on:

- A `dedicated=fringe:NoSchedule` **taint** on fringe, with ~11 apps (authentik, grafana, minecraft,
  drawio, backstage, guac, sparkyfitness-frontend, kube-prometheus-stack…) carrying matching
  tolerations + a `nodegroup=fringe` nodeSelector to be pinned there.
- A one-off `workload-tier=apps` label on worker-1, used by four apps' soft affinity.
- `nodegroup=soyo` on the control-planes.
- Implicit reliance on `node-role.kubernetes.io/control-plane` to mean "infra goes here."

The owner wants placement keyed on **what a node can do**, not its identity or current role (roles may
change), and wants the `fringe` taint/`nodegroup` complexity **gone**. There is no upstream standard
label for capability/pool tiers (only `node-role.kubernetes.io/*` for roles and cloud-vendor nodepool
labels), and Kubernetes reserves `kubernetes.io/`/`k8s.io/` prefixes and directs custom semantics to a
**domain-prefixed** label. See the [RFC](../rfc/rfc-node-taxonomy-and-storage-placement.md) for the
taint-vs-label reasoning.

## Decision

Adopt a **domain-prefixed capability taxonomy**, set via Talos `machine.nodeLabels`:

| Label | Values | On |
|---|---|---|
| `node.webgrip.io/pool` | `worker` \| `soyo` | all nodes |
| `node.webgrip.io/cpu` | `high` \| `standard` | `high` = fringe |
| `node.webgrip.io/ram` | `high` \| `standard` \| `low` | `high` = worker-1, `low` = soyos |
| `storage.webgrip.io/longhorn` | `"true"` | worker-1 + fringe |

Principles: **taints are for protection only** (never for capability); capability is expressed as
labels and consumed via `nodeAffinity` (attraction, opt-in); scheduling must not key off the
control-plane role. The soyos get **no app-exclusion taint** — apps are kept off them by a hard
affinity toward `pool=worker` ([ADR-0028](adr-0028-application-workload-placement.md)), leaving the
soyos open to the infra/system pods that belong there.

**Retire the `fringe` scheme:** remove the `dedicated=fringe:NoSchedule` taint and the
`nodegroup=soyo|fringe` labels; re-home the ~11 fringe-pinned apps onto `pool=worker` affinity
(dropping their `nodegroup` nodeSelector + fringe toleration). Keep `workload-tier=apps` only as a
transitional alias until those apps carry the new affinity, then delete it.

Longhorn node/disk **tags** are a separate concern, set by [ADR-0027](adr-0027-longhorn-hot-cold-tiers.md);
they are not k8s labels.

## Consequences

- Placement becomes self-describing and role-independent; a future node is onboarded by labelling its
  capabilities, and workloads it qualifies for follow automatically.
- The `fringe` taint and per-app tolerations disappear — fringe is "just a worker" (high-CPU + the HDD
  cold disk). Both workers become interchangeable hosts for apps, instead of fringe being a special
  hand-pinned island.
- Re-homing the ~11 fringe-pinned apps is a real chunk of work; done one app at a time, with the node
  taint removed **last** so nothing is briefly homeless (see RFC Phase D).
- Labels live in Talos machine config (GitOps); applying them is a no-reboot `apply-node`. A node with
  no `node.webgrip.io/*` labels is a misconfiguration a future guard could lint for.

## Alternatives considered

- **`node-role.kubernetes.io/{worker,storage}`** for the nice `kubectl get nodes` ROLES column.
  Rejected as the primary scheme: it re-introduces role-coupling the owner wants to avoid, and the
  `node-role.kubernetes.io/` prefix is conventionally cluster-managed. The domain-prefixed labels carry
  the scheduling semantics; a ROLES-column nicety can be added later without changing them.
- **Keep `nodegroup`/`workload-tier`.** Rejected: ad-hoc, not capability-shaped, and the `fringe`
  taint forces tolerations everywhere — exactly the complexity being removed.
- **Taint soyos to keep apps off.** Rejected: a taint blocks the infra that legitimately runs on the
  control-planes and would force tolerations on it; a hard worker-pool affinity achieves "apps off
  soyos" without that blast radius.
