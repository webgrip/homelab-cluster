## Talos node operations & upgrades

### `task talos:upgrade-node` built-in drain STALLS on single-replica-PDB workloads — force-drain first
- **Type:** GOTCHA + PROCEDURE · **Confidence:** HIGH ([VERIFIED]; all 5 nodes reached v1.13.4)
- **What:** `talosctl upgrade`'s internal cordon+drain cannot evict single-replica workloads with PDBs (`allowedDisruptions: 0`): kyverno-background/reports-controller on every node + ~7 single-instance CNPG DBs on worker-1. The drain hits a 5m global timeout, errors, and aborts — leaving the node cordoned, new image staged to the inactive partition, but NEVER rebooted (still old version) even though "upgrade completed" prints. Fix: `kubectl drain <name> --disable-eviction --force --ignore-daemonsets --delete-emptydir-data --timeout=600s` → `task talos:upgrade-node IP=<ip>` → `kubectl uncordon` → verify Server Tag. CNPG DBs (longhorn SC, Immediate, no PV node-lock) reschedule; etcd/kubelet are Talos static pods unaffected by kubectl drain so CP quorum is safe. A stalled upgrade is safe to Ctrl+C (`talosctl get machinestatus`: STAGE=running READY=true = stable, only the cordon to undo; a plain reboot won't switch partitions — re-run the upgrade after a clean force-drain).
- **Snippet:** `error draining node "soyo-1": [error when evicting pods/"kyverno-background-controller-..." ... global timeout reached: 5m0s]`
- **Sources:** batch 4 (Talos upgrade digest)

### Two distinct Talos node operations with different drain behavior; use the recipes
- **Type:** FACT + PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** (1) **Config changes** → `task talos:apply-node-safe IP=<ip> HOSTNAME=<name>` (explicit `kubectl drain --timeout=120s` then apply). (2) **Version upgrades** → `task talos:upgrade-node IP=<ip>` (relies on Talos's OWN internal drain — do NOT pre-drain in the documented flow, do NOT hand-roll the `--image` string; the recipe looks up `talosImageURL`+`talosVersion`). Exception: a label-only no-reboot change uses `task talos:apply-node ... MODE=no-reboot`. Recipes in `.taskfiles/talos/Taskfile.yaml`: apply-node-safe, upgrade-node, upgrade-k8s, generate-config. Read hardware via read-only COSI: `get systeminformation/processors/memorymodules/disks` (`get disks` is mostly Longhorn iSCSI virtual disks — only `transport: sata` is physical; runtime `/dev/sdX` letters unstable; `meminfo` not a valid resource). `talhelper` must recognize the target version or genconfig warns — bump it (v3.1.11 added v1.13.4) as an adjacent pin.
- **Sources:** batch 4 (both Talos digests)

### Version pins live in two files; generated clusterconfig is gitignored
- **Type:** REFERENCE + FACT · **Confidence:** HIGH ([VERIFIED] against repo)
- **What:** `talos/talenv.yaml` holds `talosVersion` + `kubernetesVersion` (Renovate datasource comments); `.mise.toml` holds client tool pins. Current: **Talos v1.13.4** (kernel 6.18.34, etcd v2.6.12, Go 1.26.4), **Kubernetes v1.36.1** (newest stable — 1.37 doesn't exist), kubectl 1.36.1, talosctl 1.13.4, talhelper 3.1.11. `talos/clusterconfig/kubernetes-*.yaml` + `talosconfig` are NOT tracked (only `.gitignore`) — a version-bump commit is just `.mise.toml` + `talos/talenv.yaml`; per-node configs regenerated locally via `task talos:generate-config`, never committed. A node is added by an entry in `talos/talconfig.yaml` `nodes:` (hostname, ipAddress, installDisk, `controlPlane:`, MAC deviceSelector).
- **Sources:** batch 4 (both Talos digests)

### Node inventory & hardware (5 nodes)
- **Type:** REFERENCE + FACT · **Confidence:** HIGH ([VERIFIED]; cross-confirmed across batches)
- **What:** soyo-1 `10.0.0.20`, soyo-2 `.21`, soyo-3 `.22` = control-plane/etcd, `pool=soyo`, `allowScheduling=false` for Longhorn (ADR-0026); Intel N150 4C/4T, 12 GiB (4×3 GiB Samsung LPDDR5 soldered), 512 GB **SATA** SSD (earlier docs wrongly said NVMe); soyo-1 holds the VIP; address soyo-3 by IP (hostname flaky). fringe-workstation `.23` = worker, **only `cpu=high` node**, HP Z230 i7-4770 4C/8T, 16 GiB DDR3, 256 GB SSD + 1 TB HDD, Longhorn-schedulable. worker-1 `.24` (added 2026-06-19) = worker, high-RAM (Gigabyte Z87X-D3H, i5-4670K, 24 GiB DDR3 — most in cluster, 960 GB SSD, `installDisk: /dev/sda`), Longhorn-schedulable, **hosts the CNPG DB fleet**. All on Talos v1.13.4 / k8s v1.36.1. Capability label `node.webgrip.io/pool|cpu`. `secretDomain: webgrip.dev` lives in plaintext `talos/talenv.yaml` (owner confirmed not sensitive). Garage S3 external `10.0.0.110:3900`. Totals: 5 nodes, 24 vCPU / ~76 GiB.
- **Sources:** batches 4 (both Talos digests), 1 (copy 11, copy 16)

---

## etcd / control-plane HA & node placement

### etcd quorum / HA — corrects the "go to 1 control-plane" intuition
- **Type:** FACT + DECISION · **Confidence:** HIGH (quorum math textbook-correct; failover not exercised in-thread)
- **What:** etcd Raft needs majority (quorum = ⌊N/2⌋+1), tolerated failures = N−quorum (3→1, 5→2). Odd counts only. **3 CP nodes is the HA minimum; dropping to 1 is strictly less resilient** and there's no automated etcd backup yet (roadmap #52), so a single-CP disk loss is unrecoverable.
- **Conflict (resolved):** The intuition "3 soyos feel fragile → go to 1" is WRONG — the fragility is **correlated failure** (3 identical RAM-starved shared-disk boxes fail together) + etcd's fsync sensitivity when Longhorn saturates the shared SSD (→ leader-election flapping), not node count. Fix = isolate etcd, keep heavy workloads off CP nodes (now done — soyos app/Longhorn-free), add etcd backups; NOT fewer nodes. (Corroborated by memory `tenant-db-on-etcd-node-leader-change.md`.) "All storage on one node" trades correlated-failure for a SPOF; worker-1 is the second independent worker enabling cross-node Longhorn replicas.
- **Sources:** batch 4 (Talos hardware digest)

### Capability labels are the placement contract — and Cilium L2 CRDs consume node labels too
- **Type:** GOTCHA + DECISION · **Confidence:** HIGH ([VERIFIED] against repo)
- **What:** Placement uses capability labels (`node.webgrip.io/cpu`, `node.webgrip.io/pool`), never hostnames or legacy `nodegroup`/`workload-tier`. `kubernetes/apps/kube-system/cilium/app/networks.yaml` holds a `CiliumL2AnnouncementPolicy` whose `nodeSelector.matchLabels` was on `nodegroup: fringe` — a REAL dependency (dropping the label breaks LB-IP announcement); swapped to `pool: worker` before retiring legacy labels. So before retiring any node label, `grep -rn "nodegroup\|workload-tier" kubernetes/apps/` for ALL consumers including Cilium CRDs. gitops-critical apps (forgejo/openbao/gitea-mirror) are pinned to `pool=worker` like any app; DR is external-Garage-S3 backups + a GitHub fallback Flux GitRepository, NOT a soyo Longhorn replica (the `longhorn-gitops` SC was retired). Post-migration: 0 Longhorn replicas / 0 app pods on soyos (42 replicas each on fringe + worker-1); CP RAM 80–83% → 65–73% (residual = CP + BestEffort-DaemonSet overhead, structural to 12 GiB nodes).
- **Sources:** batch 4 (node-taxonomy migration digest)

### Pin a single-node RWO-shared app via a node-unique capability label (RWX is blocked)
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** When several pods share one RWO volume (can't spread) and RWX is blocked, pin to a single node using a capability label that resolves to exactly one node — never a hostname. authentik (2 server + 1 worker share `/data` media) → `node.webgrip.io/cpu: high` (fringe is the only high-CPU node), set as both nodeSelector and hard nodeAffinity. Node-level HA later requires moving the shared data off RWO first (media → S3).
- **Sources:** batch 4 (node-taxonomy migration digest)

---

## Workload placement & RWO/HelmRelease tactics

### Kyverno blocks all RWX PVCs cluster-wide
- **Type:** GOTCHA + FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** Any ReadWriteMany PVC is denied at admission by `storage-cnpg-governance/disallow-rwx-pvcs` (also `require-approved-pvc-storageclass`); there are zero RWX PVCs in the repo. A `longhorn-rwx` StorageClass exists (NFS share-manager) but is blocked cluster-wide. Denial is at dry-run/admission, so a Flux Kustomization referencing an RWX PVC goes `ReconciliationFailed` without disrupting the running app. Rules out RWX as the "share a volume across nodes for HA" solution and as a shared CI cache (NFS SPOF on RAM-tight nodes); shapes any "shared cache" design toward bake/hostPath/object-storage, RWX only behind a PolicyException.
- **Snippet:** `admission webhook "validate.kyverno.svc-fail" denied... disallow-rwx-pvcs: ReadWriteMany PVCs are not allowed...`
- **Sources:** batches 4 (node-taxonomy migration digest), 2 (copy 8), 1 (copy 13)

### Break a goharbor RWO RollingUpdate Multi-Attach deadlock by deleting the old ReplicaSet
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** The goharbor chart hardcodes RollingUpdate (renders both strategy blocks, so Recreate-via-values is impossible). Pinning a single-replica RWO Deployment to move nodes deadlocks: old pod holds the volume, new pinned pod sits ContainerCreating (Multi-Attach). Deleting just the old *pod* isn't enough (the RS recreates it). Fix: delete the old ReplicaSet — the Deployment won't recreate a superseded revision, the volume frees, HR goes UpgradeSucceeded. Must beat the HR timeout (20m for harbor).
- **Sources:** batch 4 (node-taxonomy migration digest)

### Convert a chart that hardcodes RollingUpdate to StatefulSet (dependency-track api-server); VCT storageClass is immutable
- **Type:** FACT + PROCEDURE · **Confidence:** HIGH (conversion [VERIFIED] against repo; immutability [ASSERTED] from K8s semantics)
- **What:** DT's api-server was converted to `apiServer.deploymentType: StatefulSet` (native nodeSelector, no postRenderer) — an ordered STS recreate frees the RWO volume, sidestepping the Multi-Attach deadlock. (Older skill docs claiming "DT uses `strategy: Recreate` via its postRenderer" were stale and corrected.) Note a StatefulSet's `volumeClaimTemplates.storageClassName` is immutable — repointing a chart-rendered STS PVC to a different SC is API-rejected and breaks the HR until STS+PVC are deleted/recreated (acceptable for DT only because `/data` is a rebuildable NVD/OSV cache; the encryption key lives in `dependency-track-secret`, not `/data`). CNPG `storageClass` changes are similarly disruptive — present the trade-off; don't unilaterally swap.
- **Sources:** batches 4 (node-taxonomy migration digest), 2 (copy 8)

### helm-controller cache-sync rollback is driven by a loaded control-plane API
- **Type:** GOTCHA · **Confidence:** LOW ([ASSERTED] — hypothesis, causation not proven)
- **What:** RWO-move/postRenderer HR upgrades had failed with `failed to wait for object to sync in-cache after patching: context deadline exceeded` → `remediateLastFailure` rolling the release back in a loop. After the soyo control-planes were emptied of apps (idle API), the same harbor move succeeded with no rollback. Hypothesis: the cache-sync timeout was caused by the slow/loaded soyo apiserver — operations previously "impossible via GitOps" may become safe once the control-plane is unloaded. **Needs verification** as a repeatable cause.
- **Snippet:** `kubectl get hr <app> -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}'` → want `UpgradeSucceeded`
- **Sources:** batch 4 (node-taxonomy migration digest)

---

## Longhorn storage

### All Longhorn StorageClasses are now `Immediate`; `longhorn-gitops` SC was deleted
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED] against repo)
- **What:** Every Longhorn SC is `volumeBindingMode: Immediate` now. WFFC was eliminated because with `dataLocality: disabled` volumes are network-attached, so WFFC's PV-node-locking is pure downside (it permanently excluded the later-added worker-1). The `longhorn-gitops` SC (soyo-replica DR design) was retired 2026-06-21; soyos stay 100% Longhorn-free. Legacy WFFC-era PVs keep their baked nodeAffinity until recreated. The storageclass Flux ks uses `force: true` so the immutable binding-mode change recreates the SC.
- **Snippet:** `kubectl get pv <pv> -o jsonpath='{.spec.nodeAffinity}'` (empty = free)
- **Sources:** batch 4 (node-taxonomy migration digest)

### The default longhorn SC still provisions 3 replicas on a 2-storage-node cluster (deliberate deferral)
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** The chart-created default `longhorn` SC carries `numberOfReplicas: 3` (immutable SC param, from `persistence.defaultClassReplicaCount`), but only 2 Longhorn-schedulable nodes exist with hard replica anti-affinity → a 3-replica volume can never be healthy (recurring "volume degraded", e.g. dependency-track-api-server). Existing volumes were reduced to 2 at runtime (not durable; any reprovision returns to 3). The chart's `defaultSettings.defaultReplicaCount: "2"` does NOT override an explicit SC param. Maintainers deliberately left it at 3 ("to avoid breaking the HR upgrade"); convergence to 2 is deferred (ADR-0029 Stage 2 / ADR-0027). Treat as a deliberate decision.
- **Sources:** batch 2 (copy 8)

### Longhorn 1.11 ignores `defaultSettings.backupTarget` — use a `BackupTarget` CR
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED]; target available=true)
- **What:** Setting `backupTarget`/`backupTargetCredentialSecret` in HelmRelease `defaultSettings` is silently ignored in Longhorn 1.11 (deprecated). The working mechanism is a `BackupTarget` CR named `default`. Creds from the `longhorn-backup-s3` ExternalSecret (OpenBao `s3/cnpg-backup` → AWS_*). A `gitops-backup` RecurringJob (cron `0 2 * * *`) backs up volumes labeled `recurring-job-group.longhorn.io/gitops-backup=enabled` (forgejo-data, gitea-mirror).
- **Snippet:** `kubectl get backuptarget default -n longhorn-system -o jsonpath='available={.status.available}'`
- **Sources:** batch 4 (node-taxonomy migration digest)

### Post-reboot Longhorn churn self-heals serially; detect rebuilds via JSON `rebuildStatus`, not table grep
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Rolling-rebooting all nodes left ~25 volumes degraded; they self-healed to ~0 over ~1–2h (expected — don't reboot another node until converged, each degraded volume is momentarily single-replica). Each volume wants 2 replicas (one per worker); after a worker reboot its replica shows `currentState=stopped, healthyAt=NEVER` and rebuilds from the other worker, throttled by `concurrent-replica-rebuild-per-node-limit=1` (serial by design) + `replica-auto-balance=disabled`. `kubectl get replicas.longhorn.io ... | grep -ci rebuild` always returns 0 — rebuild state isn't a table column, it's `.status.rebuildStatus` (JSON only); the "0 healthy replica" safety check must be computed from replica `healthyAt`/`failedAt`. `node-down-pod-deletion-policy=delete-both-statefulset-and-deployment-pod`.
- **Snippet:** `kubectl get replicas.longhorn.io -n longhorn-system -o json | jq -r '[.items[]|select(.status.rebuildStatus.state=="in_progress")]|length'`
- **Sources:** batch 4 (Talos upgrade digest)

---
