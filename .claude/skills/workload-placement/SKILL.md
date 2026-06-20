---
name: workload-placement
description: Decide which node a workload runs on and pin it the DRY way — capability-label taxonomy (pool=worker), the worker-pool component, nodeAffinity/nodeSelector. Not control-plane-role or node names.
when_to_use: Use when adding/placing a workload, choosing nodeAffinity/nodeSelector, pinning apps to the worker pool, keeping infra unconstrained, wiring the worker-pool component, or debugging a pod stuck Pending / "didn't match node affinity" / a volume (e.g. CNPG, n8n) that won't schedule on a node you just added.
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
  nothing. Keep recovery-critical-path infra here (anything on the admission/secrets/storage-operator
  path, e.g. kyverno, external-secrets, cnpg-operator) so a both-worker outage is recoverable.
- **Apps** (stateless + stateful) → **hard-pin to `pool=worker`** → `Pending` if both workers down (apps
  aren't worth crushing the 12 GiB soyos for). User-facing apps + their CNPG DBs (e.g. the observability
  stack, authentik).
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

## ⚠️ When NOT to use the component — prefer native `nodeSelector` (learned 2026-06)

The component works for **stateless multi-Deployment** charts (keda, guac). It **fails** for two classes,
where you must instead set the chart's **native `nodeSelector`** in `values` (plain values apply cleanly;
postRenderers don't):

1. **Charts that expose `nodeSelector` per component** (harbor, the goharbor chart; kube-prometheus-stack;
   app-template `pod.nodeSelector`; CNPG `spec.affinity.nodeSelector`; raw Deploy/STS `template.spec.nodeSelector`).
   Just set `node.webgrip.io/pool: worker` there — simpler and reliable.
2. **Any HR whose pin *moves* a RWO Deployment** (dependency-track api-server, harbor registry/jobservice).
   Two failure modes both end in `remediateLastFailure` rolling the whole release back in a loop:
   - **Inline/component postRenderer** → helm-controller `failed to wait for object to sync in-cache after
     patching: context deadline exceeded` (the slow soyo API). Inline postRenderers are unreliable here.
   - **RWO RollingUpdate move** → Multi-Attach deadlock → release never goes Ready → rollback (it does NOT
     "self-heal" — the rollback aborts the move). The chart often **hardcodes `RollingUpdate`** so you
     can't set `Recreate` via values either (renders both → k8s rejects).
   Handling: pin only the components that move cleanly (stateless Deploys + StatefulSets — STS do an
   ordered recreate, no Multi-Attach); **leave RWO Deployments unpinned**, then move them via a one-off
   PVC recreate on the Immediate `longhorn` SC (works when the PVC data is throwaway/S3-backed). Verify a
   pin actually stuck: `kubectl get deploy <d> -o jsonpath='{.spec.template.spec.nodeSelector}'` AND check
   `kubectl get hr <app> -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}'` is not `RollbackSucceeded`.

## ⚠️ RWO + RollingUpdate deadlock when a pin *moves* a pod

Pinning a single-replica **Deployment** with a RWO Longhorn PVC that **relocates it to another node**
(e.g. soyo → worker) hangs: `RollingUpdate` with `maxUnavailable` rounding to 0 keeps the old pod up
holding the volume, so the new pod sits `ContainerCreating` with `Multi-Attach error ... Volume is
already used by pod(s) …`. Fix = **`strategy: Recreate`** (terminate-then-start) on that Deployment —
done for `dependency-track-api-server` via its postRenderer (commit after `70dff79`). StatefulSets and
CNPG are unaffected (ordered recreate). Apps **already on a worker** don't relocate, so they don't hit
this — it only bites `longhorn`-backed Deployments currently on a soyo. Set Recreate in the same place
you set the affinity (component apps: the chart's `controllers.<name>.strategy`, or an inline patch).

## ⚠️ Sequencing gotcha (stateful) — it's the SC binding mode, not "all PVs"

A stateful app is safe to hard-pin to `pool=worker` **iff its volume isn't node-locked to nodes that
exclude the worker you need**. That lock depends entirely on the StorageClass `volumeBindingMode`:

- **`longhorn` (`Immediate`)** → PV has **no** `nodeAffinity` → attaches anywhere, incl. later-added
  worker-1. **Pin now**, stateful or not (all CNPG DBs, dependency-track api-server, etc.).
- **`longhorn-general` (`WaitForFirstConsumer`)** → PV bakes in the storage nodes present at first bind
  and never refreshes → **permanently excludes worker-1**. Can still reach the older workers it lists
  (fringe), so it pins fine **once the fringe taint is retired**; to reach worker-1 it must be **migrated
  to the `longhorn` SC** (ADR-0029) — eviction can't rewrite the immutable PV `nodeAffinity`.

Check before pinning a stateful app: `kubectl get pv <pv> -o jsonpath='{.spec.nodeAffinity}'` (empty =
free). Symptom of pinning a locked volume too early: `Pending` / `didn't match PersistentVolume's node
affinity` (this is what stranded n8n — a `longhorn-general` volume). See
[ADR-0028](docs/techdocs/docs/adr/adr-0028-application-workload-placement.md) D2 and the
[longhorn](docs/techdocs/docs/runbooks/node-taxonomy-migration-status.md) skill.

## Soft affinity is non-deterministic — don't

A `preferred` (weight-100) nodeAffinity lost to image-locality scoring (an app stuck on a soyo with
worker capacity free). Use **`required`** (hard) for placement you actually want to hold.

## Why not taint the soyos?

A taint would shove *all* infra onto the workers (overloading them) and forces tolerations everywhere.
Apps opt *out* of soyos via the hard worker affinity; infra stays put. etcd protection is enforced at the
**Longhorn layer** (replicas off soyos — see the `longhorn` skill), not via k8s taints.

## Validate

`./scripts/run-flux-local-test.sh` after adding the component (confirms the post-render injected the
affinity). Before pinning a stateful app, check its PV `nodeAffinity` per the sequencing gotcha above.
