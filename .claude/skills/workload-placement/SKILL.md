---
name: workload-placement
description: Decide which node a workload runs on and pin it the DRY way — capability-label taxonomy (pool=worker), the worker-pool component, nodeAffinity/nodeSelector. Not control-plane-role or node names.
when_to_use: Use when adding/placing a workload, choosing nodeAffinity/nodeSelector, pinning apps to the worker pool, keeping infra unconstrained, wiring the worker-pool component, or debugging a pod stuck Pending / "didn't match node affinity" / a volume (e.g. CNPG, n8n) that won't schedule on a node you just added.
---

# Workload placement

Placement is keyed off a **capability taxonomy** ([ADR-0001](docs/techdocs/docs/adr/adr-0001-node-taxonomy.md)),
not "is it control-plane" or hostnames. Set via Talos `machine.nodeLabels`:

| Label | Values | Meaning |
|---|---|---|
| `node.webgrip.io/pool` | `worker` \| `soyo` | pool membership |
| `node.webgrip.io/cpu` | `high`(fringe) \| `standard` | CPU class |
| `node.webgrip.io/ram` | `high`(worker-1) \| `low`(soyo) \| `standard` | RAM class |
| `storage.webgrip.io/longhorn` | `"true"` | a Longhorn storage node (workers) |

⚠️ **Node labels feed more than the scheduler — `grep` the whole repo (incl. Cilium CRDs) before
retiring/renaming one.** `CiliumL2AnnouncementPolicy.spec.nodeSelector` selects LB-IP-announcing nodes by
node label too; dropping one silently breaks L2 ARP announcement (an LB VIP goes dark), no scheduling error.

## The tier model ([ADR-0002](docs/techdocs/docs/adr/adr-0002-application-workload-placement.md)) — every workload resolves to one

- **Control-plane** (apiserver/etcd/scheduler, coredns) → soyos. Leave as-is.
- **Node DaemonSets** (cilium, longhorn-manager/csi, node-exporter, alloy-agent, spegel) → all nodes. No decision.
- **Infra / operators** → **unconstrained** (run on soyos *and* workers — uses soyo RAM on purpose). Add
  nothing. Keep recovery-critical-path infra here (admission/secrets/storage-operator path, e.g. kyverno,
  external-secrets, cnpg-operator) so a both-worker outage is recoverable.
- **Apps** (stateless + stateful) → **hard-pin to `pool=worker`** → `Pending` if both workers down (apps
  aren't worth crushing the 12 GiB soyos for). User-facing apps + their CNPG DBs.
- **gitops-critical** (forgejo, openbao) → **also just hard-pinned to `pool=worker`** like any app; resilience
  to a both-worker outage comes from external-Garage-S3 backups + a GitHub fallback Flux source, not a soyo
  replica (ADR-0008, `longhorn` skill).

## How to pin — the DRY component

Don't write per-app affinity blocks. Add one line to the app's `app/kustomization.yaml`:
`components: [../../../../components/placement/worker-pool]`.
[`components/placement/worker-pool`](kubernetes/components/placement/worker-pool/kustomization.yaml)
injects the hard `pool=worker` affinity into HelmRelease-rendered Deployments/StatefulSets (post-render,
chart-agnostic), raw Deploy/StatefulSet, **and** CNPG `Cluster`s (`spec.affinity.nodeSelector`).

**Exception:** an HR that already defines its own `spec.postRenderers` must NOT use the component — its
strategic-merge would replace that list; set the affinity inline there instead.

## When NOT to use the component — prefer native `nodeSelector`

The component works for **stateless multi-Deployment** charts (keda, guac). Set the chart's **native
`nodeSelector`** in `values` instead (plain values apply cleanly; postRenderers don't) for:

1. **Charts that expose `nodeSelector` per component** (harbor/goharbor; app-template `pod.nodeSelector`;
   CNPG `spec.affinity.nodeSelector`; raw Deploy/STS `template.spec.nodeSelector`) — just set
   `node.webgrip.io/pool: worker` there.
2. **Any HR whose pin *moves* a RWO Deployment** (harbor registry/jobservice) — a postRenderer pin fails
   (helm-controller `failed to wait for object to sync in-cache` on a loaded soyo API) and the move itself
   deadlocks → RWO class below.

## Three deadlock classes — symptom here, mechanism + fixes in [reference.md](reference.md)

- **RWO + RollingUpdate move:** a pin relocates a single-replica Deployment holding a RWO PVC → new pod stuck
  `ContainerCreating` `Multi-Attach error`, HR rolls back and never self-heals → reference.md.
- **Surge deadlock:** single-replica Deployment pinned to a request-saturated pool → new pod `Pending`
  `Insufficient cpu/memory` while the old can't be removed (`kubectl top` looks fine) → reference.md.
- **Single-node-by-design (several pods, one RWO volume — authentik):** co-locate on ONE node via a
  capability label that resolves to exactly one node (RWX is Kyverno-blocked) → reference.md.

## Sequencing gotcha (stateful) — legacy WFFC PVs only

A stateful app is safe to hard-pin to `pool=worker` **iff its PV isn't node-locked away from the target
worker**. **All Longhorn SCs are now `Immediate`** → volumes bound since have **no** PV `nodeAffinity` →
**pin freely** (all CNPG DBs, etc.). The trap is only **legacy WFFC-era PVs**: they baked in the storage
nodes present at first bind and never refresh — eviction can't rewrite an immutable PV `nodeAffinity`.
Check before pinning: `kubectl get pv <pv> -o jsonpath='{.spec.nodeAffinity}'` (empty = free). Symptom of
pinning a still-locked one: `Pending` / `didn't match PersistentVolume's node affinity` (stranded n8n).
ADR-0002 D2 + the `longhorn` skill.

## Gotchas

- **Soft affinity is non-deterministic:** a `preferred` (weight-100) nodeAffinity lost to image-locality
  scoring (an app stuck on a soyo with worker capacity free). Use **`required`** for placement you want to hold.
- **Don't taint the soyos:** a taint shoves *all* infra onto the workers and forces tolerations everywhere;
  apps opt *out* via the hard worker affinity. etcd protection is enforced at the **Longhorn layer**
  (replicas off soyos — `longhorn` skill), not via k8s taints.
- **Validate:** `./scripts/run-flux-local-test.sh` after adding the component (confirms the post-render
  injected the affinity); before pinning a stateful app, check its PV `nodeAffinity` (sequencing gotcha).
