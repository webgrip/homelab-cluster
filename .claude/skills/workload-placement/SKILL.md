---
name: workload-placement
description: Decide which node a workload runs on and pin it the DRY way. Use when adding/placing a workload, choosing nodeAffinity/nodeSelector, pinning apps to the workers, keeping infra unconstrained, or wiring the worker-pool component. Capability-label taxonomy, not control-plane-role or node names.
---

# Workload placement

Placement is keyed off a **capability taxonomy** ([ADR-0025](docs/techdocs/docs/adr/adr-0025-node-taxonomy.md)),
not "is it control-plane" or hostnames. Set via Talos `machine.nodeLabels`:

| Label | Values | Meaning |
|---|---|---|
| `node.webgrip.io/pool` | `worker` \| `soyo` | pool membership |
| `node.webgrip.io/cpu` | `high`(fringe) \| `standard` | CPU class |
| `node.webgrip.io/ram` | `high`(worker-1) \| `low`(soyo) \| `standard` | RAM class |
| `storage.webgrip.io/longhorn` | `"true"` | a Longhorn storage node (workers) |

## The tier model ([ADR-0028](docs/techdocs/docs/adr/adr-0028-application-workload-placement.md))

Every workload resolves to one of these:

- **Control-plane** (apiserver/etcd/scheduler, coredns) → soyos. Leave as-is.
- **Node DaemonSets** (cilium, longhorn-manager/csi, node-exporter, alloy-agent, spegel) → all nodes. No decision.
- **Infra / operators** → **unconstrained** (run on soyos *and* workers — uses soyo RAM on purpose). Add
  nothing. Keep recovery-critical-path infra here (kyverno admission, external-secrets, openbao-unsealer,
  trust-manager, cnpg-operator, flux/cilium/cert-manager) so a both-worker outage is recoverable.
- **Apps** (stateless + stateful) → **hard-pin to `pool=worker`** → `Pending` if both workers down (apps
  aren't worth crushing the 12 GiB soyos for). This includes the observability stack, ARC runners, KEDA,
  authentik, harbor, the security *apps* (dependency-track, guac, trivy-server), all CNPG DBs.
- **gitops-critical** (forgejo, openbao) → worker-preferred + one designated soyo permitted, on
  `longhorn-gitops` (3 replicas) — survive a both-worker outage.

## How to pin — the DRY component

Don't write per-app affinity blocks. Add one line to the app's `app/kustomization.yaml`:

```yaml
components:
  - ../../../../components/placement/worker-pool
```

[`components/placement/worker-pool`](kubernetes/components/placement/worker-pool/kustomization.yaml)
injects the hard `pool=worker` affinity into HelmRelease-rendered Deployments/StatefulSets (post-render,
chart-agnostic), raw Deploy/StatefulSet, **and** CNPG `Cluster`s (`spec.affinity.nodeSelector`).

**Exception:** an HR that already defines its own `spec.postRenderers` (e.g. `dependency-track`) must NOT
use the component — its strategic-merge would replace that list; set the same affinity inline there.

## ⚠️ Sequencing gotcha (stateful)

**Existing Longhorn PVs exclude later-added nodes** — a stateful app pinned to `pool=worker` can't attach
its volume on a node that joined after the volume was created, until Longhorn places a replica there. So
**pin stateless apps now, but pin stateful apps only after the eviction** that moves a replica onto the
new worker ([ADR-0028](docs/techdocs/docs/adr/adr-0028-application-workload-placement.md) D2,
[longhorn](docs/techdocs/docs/runbooks/node-taxonomy-migration-status.md) skill). Symptom of pinning too
early: `Pending` with `didn't match PersistentVolume's node affinity`.

## Soft affinity is non-deterministic — don't

A `preferred` (weight-100) nodeAffinity lost to image-locality scoring (an app stuck on a soyo with
worker capacity free). Use **`required`** (hard) for placement you actually want to hold.

## Why not taint the soyos?

A taint would shove *all* infra onto the workers (overloading them) and forces tolerations everywhere.
Apps opt *out* of soyos via the hard worker affinity; infra stays put. etcd protection is enforced at the
**Longhorn layer** (replicas off soyos — see the `longhorn` skill), not via k8s taints.
