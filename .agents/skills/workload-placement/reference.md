# Workload placement — deadlock deep-dives

Contents: [RWO + RollingUpdate move deadlock](#rwo--rollingupdate-move-deadlock)
· [Surge deadlock](#surge-deadlock-single-replica-pod-pinned-to-a-full-pool)
· [Single-node-by-design apps](#single-node-by-design-apps-multiple-pods-one-rwo-volume)

## RWO + RollingUpdate move deadlock

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

## Surge deadlock: single-replica pod pinned to a full pool

Even with no RWO move, a single-replica **Deployment** pinned to a small pool can wedge its own rollout:
default `RollingUpdate` (`maxSurge:1`/`maxUnavailable:0`) needs room for a **second** pod, but if every
eligible node is request-saturated the new pod sits `Pending` (`Insufficient cpu/memory`) and the old
can't be removed. Scheduling is on **requests**, so `kubectl top` can look fine. Fix: `maxSurge:0` +
`maxUnavailable:1` (terminate-then-recreate) where you set the strategy — e.g. VMAgent's
`spec.rollingUpdate` (2026-07-01, `pool=worker`). Fine for stateless/scraper pods (brief gap on rollout).

## Single-node-by-design apps (multiple pods, one RWO volume)

Some apps run several pods sharing **one RWO volume** (authentik: 2 server + 1 worker share `/data`
media) — they can't spread across nodes. RWX would let them, but **Kyverno `disallow-rwx-pvcs` blocks
RWX cluster-wide** (see `longhorn`). So pin them to a **single node via a capability label that resolves
to exactly one node** — never a hostname or a legacy label. authentik → `node.webgrip.io/cpu: high`
(fringe is the only high-CPU node), set as **both** `nodeSelector` and the hard `nodeAffinity`. The pods
stay co-located, the RWO volume attaches cleanly, and placement still goes through the taxonomy. Node-level
HA then requires moving the shared data off RWO first (e.g. authentik media → S3, roadmap #47) before
switching to `pool=worker`. Real example: `kubernetes/apps/authentik/app/helmrelease.yaml`.
