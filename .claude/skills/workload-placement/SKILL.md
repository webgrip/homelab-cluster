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
- **gitops-critical** (forgejo, openbao) → **also just hard-pinned to `pool=worker`** like any app.
  The old "one designated soyo replica" design was retired — soyos stay Longhorn-free;
  resilience to a both-worker outage comes from external-Garage-S3 backups + a GitHub fallback Flux
  source, not a soyo replica. See the `longhorn` skill (backups) and ADR-0026.

## How to pin — the DRY component

Don't write per-app affinity blocks. Add one line to the app's `app/kustomization.yaml`:

```yaml
components:
  - ../../../../components/placement/worker-pool
```

[`components/placement/worker-pool`](kubernetes/components/placement/worker-pool/kustomization.yaml)
injects the hard `pool=worker` affinity into HelmRelease-rendered Deployments/StatefulSets (post-render,
chart-agnostic), raw Deploy/StatefulSet, **and** CNPG `Cluster`s (`spec.affinity.nodeSelector`).

**Exception:** an HR that already defines its own `spec.postRenderers` must NOT use the component — its
strategic-merge would replace that list; set the affinity inline there instead.

## ⚠️ When NOT to use the component — prefer native `nodeSelector`

The component works for **stateless multi-Deployment** charts (keda, guac). It **fails** for two classes,
where you must instead set the chart's **native `nodeSelector`** in `values` (plain values apply cleanly;
postRenderers don't):

1. **Charts that expose `nodeSelector` per component** (harbor, the goharbor chart; kube-prometheus-stack;
   app-template `pod.nodeSelector`; CNPG `spec.affinity.nodeSelector`; raw Deploy/STS `template.spec.nodeSelector`).
   Just set `node.webgrip.io/pool: worker` there — simpler and reliable.
2. **Any HR whose pin *moves* a RWO Deployment** (harbor registry/jobservice) — two ways the whole release
   `remediateLastFailure`-rolls back in a loop:
   - **Inline/component postRenderer** → helm-controller `failed to wait for object to sync in-cache after
     patching: context deadline exceeded` (loaded soyo API). Use native `nodeSelector`, not a postRenderer.
   - **RWO RollingUpdate move** → Multi-Attach deadlock → never Ready → rollback. Fixes → the **RWO +
     RollingUpdate deadlock** section below.

## ⚠️ RWO + RollingUpdate deadlock when a pin *moves* a pod

Pinning a single-replica **Deployment** with a RWO Longhorn PVC that **relocates it to another node**
(soyo → worker) hangs: `RollingUpdate` (`maxUnavailable`→0) keeps the old pod holding the volume, so the
new pod sits `ContainerCreating` with `Multi-Attach error … Volume is already used by pod(s) …`; the HR
never goes Ready → `remediateLastFailure` rolls it back (it does NOT self-heal). StatefulSets + CNPG are
immune (ordered recreate); apps **already on a worker** don't relocate. Fixes, by preference:

1. **`strategy: Recreate`** when you control the strategy — set it where you set the affinity (component
   apps: the chart's `controllers.<name>.strategy`, or an inline patch).
2. **Convert to a StatefulSet** when the chart **hardcodes `RollingUpdate`** (renders both → k8s rejects,
   so Recreate-via-values is impossible) — `dependency-track` api-server did this (`deploymentType: StatefulSet`).
3. **Pin + break the deadlock by hand** (goharbor also hardcodes RollingUpdate): the upgrade leaves the
   new pod `Pending`, so delete the **old pod AND its old ReplicaSet** (`kubectl delete rs <old-rs>` — the
   Deployment won't recreate a superseded revision) to free the volume; the new pod attaches and the
   upgrade goes Ready. Do it while the control-plane is **idle** (the cache-sync rollback is driven by a
   *loaded* soyo API) and beat the HR timeout. **Proven on harbor registry+jobservice.**

Verify a move stuck: `kubectl get deploy <d> -o jsonpath='{.spec.template.spec.nodeSelector}'` and
`kubectl get hr <app> -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}'` == `UpgradeSucceeded`
(not `RollbackSucceeded`).

## Single-node-by-design apps (multiple pods, one RWO volume)

Some apps run several pods sharing **one RWO volume** (authentik: 2 server + 1 worker share `/data`
media) — they can't spread across nodes. RWX would let them, but **Kyverno `disallow-rwx-pvcs` blocks
RWX cluster-wide** (see `longhorn`). So pin them to a **single node via a capability label that resolves
to exactly one node** — never a hostname or a legacy label. authentik → `node.webgrip.io/cpu: high`
(fringe is the only high-CPU node), set as **both** `nodeSelector` and the hard `nodeAffinity`. The pods
stay co-located, the RWO volume attaches cleanly, and placement still goes through the taxonomy. Node-level
HA then requires moving the shared data off RWO first (e.g. authentik media → S3, roadmap #47) before
switching to `pool=worker`. Real example: `kubernetes/apps/authentik/app/helmrelease.yaml`.

## ⚠️ Sequencing gotcha (stateful) — legacy WFFC PVs only

A stateful app is safe to hard-pin to `pool=worker` **iff its PV isn't node-locked to nodes that exclude
the worker you need**. **All Longhorn SCs are now `Immediate`**, so any volume
bound since has **no** PV `nodeAffinity` → attaches anywhere, incl. worker-1 → **pin freely** (all CNPG
DBs, etc.). The trap is only **legacy WFFC-era PVs** (bound before the flip): they baked in the storage
nodes present at first bind and never refresh, so they can exclude worker-1 until recreated — eviction
can't rewrite an immutable PV `nodeAffinity`. Check before pinning: `kubectl get pv <pv>
-o jsonpath='{.spec.nodeAffinity}'` (empty = free). Symptom of pinning a still-locked legacy volume:
`Pending` / `didn't match PersistentVolume's node affinity` (this stranded n8n). See
[ADR-0028](docs/techdocs/docs/adr/adr-0028-application-workload-placement.md) D2 + the `longhorn` skill.

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
