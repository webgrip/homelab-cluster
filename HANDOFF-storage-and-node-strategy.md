# Handoff — Longhorn storage migration + node placement strategy

**From:** cluster-health / Longhorn-remediation thread (2026-06-19)
**To:** the workload-scheduling thread (deciding how/where to schedule workloads)
**Purpose:** hand over (1) the live cluster facts we worked out today, (2) the proposed
storage migration, and (3) the open node-labeling/taint strategy question — so workload
placement can be designed on top of a known storage end-state.

Related in-tree doc: [`docs/techdocs/docs/rfc/rfc-layered-hardware-architecture.md`](docs/techdocs/docs/rfc/rfc-layered-hardware-architecture.md)
(the L0–L5 layered model; this handoff is the concrete L3/L4 placement layer for the **current**
5-node hardware, i.e. RFC "Phase 0 / evolve-in-place", not a new-hardware path).

---

## 1. Cluster as it physically is today (5 Talos nodes)

| Node | Role today | CPU | RAM | Disks | Notes |
|---|---|---|---|---|---|
| **soyo-1/2/3** | control-plane (etcd) | N150 (4c, low) | **12 GiB (tight)** | 1× 512 GB SATA SSD | RAM-tight; single shared disk (etcd+OS+Longhorn). Source of repeated storage SEVs. |
| **fringe-workstation** | worker | **i7-4770 (high CPU)** | 16 GiB | 256 GB SSD **+ 1 TB HDD** | Only node with an HDD → natural **cold/warm** storage tier. |
| **worker-1** | worker (NEW, added 2026-06-19) | i5-4670K | **24 GiB (high RAM)** | **960 GB SSD** | Big fast SSD, most RAM. **DO NOT SCHEDULE ON IT YET — owner's explicit hold.** |

Talos versions: soyos + fringe on v1.13.2; worker-1 on v1.13.3 (newer). All Ready.

**Hardware-capability read (drives labeling):**
- fringe = **CPU-heavy**, has the only **HDD** (cold storage).
- worker-1 = **RAM-heavy**, biggest **SSD** (hot storage).
- soyos = weak + RAM-tight → should be **infra/control-plane mostly**, kept out of heavy workloads.

---

## 2. Live findings from this thread (state + what we fixed)

**Started from a `/cluster-status` that flagged a Longhorn rebuild storm.** Investigated and acted:

- ✅ **Security GUAC certifiers fixed.** `osv-certifier` + `cd-certifier` were CrashLooping
  (~400 restarts) on `pq: relation "package_versions" does not exist`. Root cause: the
  `guac-db` CNPG cluster was **recreated ~24h ago** (during yesterday's storage churn) but
  `graphql-server` (which runs the GUAC ent migrations) predated it and never re-migrated the
  fresh DB. **Fix:** restarted `graphql-server` → it re-ran migrations → certifiers recovered.
  *(Reusable: after any guac-db recreate/restore, bounce graphql-server to re-migrate.)*

- 🟡 **`forgejo-codeberg` ExternalSecret** — `SecretSyncedError` (OpenBao `codeberg/pages`
  key absent). **By design fail-soft**: it's a *seed-once* Codeberg PAT; the consumer CronJob
  marks it `optional:true` and skips when absent. Not breaking anything. Clears when the owner
  seeds the PAT (scope `write:repository`) into OpenBao `codeberg/pages` key `token`.

- 🟡 **Longhorn rebuild storm — NOT fully resolved; superseded by the migration below.**
  38/47 volumes `degraded` (all still serving from ≥1 healthy replica — **no data loss, no
  faulted volumes**). Diagnosis (cluster-health subagent verified):
  - The three **soyo instance-managers were recreated ~6–8h ago** (during a cluster-wide reboot
    at ~03:00 + Talos churn).
  - **`guaranteedInstanceManagerCPU: "20"`** ([`kubernetes/apps/longhorn-system/longhorn/app/helmrelease.yaml:38`](kubernetes/apps/longhorn-system/longhorn/app/helmrelease.yaml#L38))
    can't apply while a node has running engines, so longhorn-manager re-cycles IMs — the
    documented "IM-cpu delayed detonation" pattern. (Has since **largely quieted** — 4/5 IMs now
    at 790m/20%; only fringe stale at 954m/12%.)
  - Rebuilds run **intermittently then wedge**: `concurrent-replica-rebuild-per-node-limit=1`,
    and the single slot on each soyo gets held by a freshly-created replica the engine never
    adopts (`inEngineMap=false`), blocking the queue. Deleting the orphan just rotates the slot.
  - **We chose NOT to band-aid it** (would just rebuild onto soyos or worker-1) and instead plan
    the real fix: move storage off the soyos entirely (Section 4).

---

## 3. Capacity facts (measured today) — the constraint that shapes everything

| Metric | Value |
|---|---|
| Volumes | **47** |
| Total **provisioned** | **541 GiB** |
| Total **actual data** | **115 GiB** |
| Replica counts | 35 vols @ 2 replicas · 11 @ 3 · 1 @ 1 |
| `replica-soft-anti-affinity` | **false** (HARD anti-affinity → each replica of a volume must be on a distinct node) |

Node Longhorn disks: soyo-1/2/3 = 474 GiB each · **fringe = 236 GiB** · worker-1 = 891 GiB.
Current replica spread: soyo-1=33, soyo-2=27, soyo-3=31, fringe=12, worker-1=0.

Orphan to GC: a Longhorn node **`slab`** (891 GiB, `KubernetesNodeGone`, 0 replicas) — almost
certainly **worker-1's previous identity** (same disk size); stale node CR, safe to remove.

**THE bottleneck = fringe (236 GiB).** With 2 storage nodes + hard anti-affinity, every volume
caps at **2 replicas** (one per storage node), so **fringe must hold a full copy of all data**:
- by *actual* (115 GiB) → fits in 236 GiB ✅
- by *provisioned* (541 GiB) → does **not** fit ❌ → migration depends on **thin/over-provisioning**
  (`storage-over-provisioning-percentage`) or a bigger fringe disk. **Open decision.**

---

## 4. Proposed storage migration (this thread's deliverable)

**End state:** Longhorn replicas live **only on worker-1 + fringe**; **soyos hold zero replicas**
(pure control-plane/etcd). This directly retires the "etcd shares a disk with Longhorn" root cause
(RFC L2/L3).

**Hard implications the scheduling thread must absorb:**
1. **2 storage nodes ⇒ 2-replica ceiling.** The 11 three-replica volumes drop to 2. HA tolerates
   losing **one** of {worker-1, fringe}, not both. (To get back to 3 replicas you need a 3rd
   storage node.)
2. **Engine-locality:** a Longhorn engine runs **where the consuming pod is attached**. If a
   stateful pod runs on a soyo, that soyo runs a Longhorn IM (engine + remote replicas) even with
   0 local replicas — so soyos aren't *truly* storage-free unless **stateful workloads are also
   pinned to worker-1 + fringe**. → **This is the key coupling to the scheduling design.** Decide:
   full disaggregation (pin stateful apps to storage nodes) vs replica-only eviction.
3. **fringe capacity** (Section 3) — over-provision or grow the disk before mass eviction.

**Phased (nothing runs until worker-1 is released by the owner):**
- **P0 (now, no mutation):** settle decisions D1–D3 below; consider lowering `guaranteedInstanceManagerCPU`
  in Git to kill the detonation pattern once soyos go storage-free.
- **P1:** open worker-1 (Longhorn `allowScheduling=true`, tag `storage`); GC orphan `slab` node.
- **P2:** reduce the 11×3-replica volumes → 2 (also relieves today's storm); tag volumes/nodes for placement.
- **P3:** evacuate soyos one at a time — per node set Longhorn `allowScheduling=false` +
  `evictionRequested=true`; wait for **0 replicas + volumes healthy** before the next. (Eviction,
  not drain — etcd quorum untouched.) This *also* resolves the current 38-degraded storm by
  rebuilding onto the big empty worker SSD.
- **P4:** lock soyos `allowScheduling=false` permanently; verify 0 replicas on soyos, every volume
  healthy @ 2 replicas across worker+fringe, detonation log silent.

---

## 5. The open question for YOUR thread — node labeling / taint strategy

Owner's framing (verbatim intent): *don't key scheduling off "is it control-plane" (that may
change); instead label by capability — soyos as "soyos", fringe+worker-1 as "workers"; fringe =
high-CPU, worker-1 = high-RAM; HDD/SSD for Longhorn; keep soyos mostly as infra.*

**Recommended principle (Kubernetes-idiomatic):**
- **Taints = exclusion** ("keep workloads OFF unless they tolerate"). Use sparingly for protection.
- **Labels + nodeAffinity = attraction** ("describe capability so workloads opt in"). Use for
  CPU/RAM/storage tiering. **Do NOT taint by capability** (high-CPU/high-RAM) — capability is a
  *label/affinity* concern; taints would force every pod to carry tolerations.
- **Longhorn disk/node tags are a SEPARATE namespace** from k8s labels — use them for HDD/SSD
  storage tiering via StorageClass `diskSelector`/`nodeSelector`.

**Concrete proposal to evaluate:**

*Taints (exclusion only):*
- soyos: keep `node-role.kubernetes.io/control-plane:NoSchedule` → only infra/tolerating pods land
  there. Matches "soyos mostly infra" without hard-coding role into app scheduling.
- worker-1: **temporary** `node.webgrip.io/hold=storage:NoSchedule` until owner releases it.

*Labels (attraction via nodeAffinity — capability, not role):*
- `node.webgrip.io/tier: worker|control-plane` (membership)
- `node.webgrip.io/cpu: high` (fringe) · `standard` (others)
- `node.webgrip.io/ram: high` (worker-1, 24Gi) · `standard` (fringe) · `low` (soyo, 12Gi)
- `storage.webgrip.io/longhorn: "true"` on worker-1 + fringe

*Longhorn tags (storage tiering — HDD/SSD):*
- Node tag `storage` on worker-1 + fringe; **disk tags** `ssd`/`hot` (worker-1 SSD, fringe SSD) and
  `hdd`/`cold` (fringe's 1 TB HDD). → StorageClasses: `longhorn-hot` (diskSelector `ssd`),
  `longhorn-cold` (diskSelector `hdd`) for bulk/backup-y volumes. fringe becomes **two** Longhorn
  disks (SSD + HDD) with different tags.

**Workload placement consequences to design (your thread):**
- **RAM-heavy** workloads (CNPG, big JVM, etc.) → prefer `ram: high` (worker-1).
- **CPU-heavy / bursty** → prefer `cpu: high` (fringe).
- **Stateful (PVC) workloads** → must land on `storage.webgrip.io/longhorn: "true"` nodes IF we go
  full-disaggregation (so engine + replicas co-locate off the soyos) — see §4 implication #2.
- **Infra/system** (operators, controllers, DaemonSets) → tolerate the soyo control-plane taint.
- Honor the soyo **12 GiB RAM** ceiling — the OOM-cascade incidents came from overcommitting them.

---

## 6. Decisions still open (need owner input before execution)

- **D1 — fringe capacity:** rely on Longhorn over-provisioning (115 GiB actual fits 236 GiB) vs
  give fringe a bigger disk. Gates the whole 2-storage-node design.
- **D2 — 2-replica ceiling:** accept losing 3-replica redundancy for the 11 vols (forced by 2
  storage nodes) — OK, or plan a 3rd storage node?
- **D3 — disaggregation depth:** pin stateful workloads to worker+fringe (soyos truly Longhorn-free)
  vs replica-only eviction (soyos may still run engines for pods scheduled there). **Most important
  coupling to the scheduling design.**
- **D4 — worker-1 release timing:** owner-gated; nothing in §4 P1+ runs until then.
- **D5 — labeling scheme sign-off:** §5 names — adopt as proposed or adjust.

---

## 7. Quick verification commands (read-only)

```bash
# Longhorn health snapshot
mise exec -- kubectl get volumes.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '[.items[].status.robustness]|group_by(.)|map({(.[0]):length})|add'
# Replica spread per node
mise exec -- kubectl get replicas.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '[.items[].spec.nodeID]|group_by(.)|map({(.[0]):length})|add'
# Node disks (total/avail/scheduled)
mise exec -- kubectl get nodes.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '.items[]|.metadata.name as $n|.status.diskStatus//{}|to_entries[]|"\($n)\t\((.value.storageMaximum//0)/1073741824|floor)/\((.value.storageAvailable//0)/1073741824|floor) GiB avail"'
# Current node labels/taints
mise exec -- kubectl get nodes -o json | mise exec -- jq -r '.items[]|"\(.metadata.name)\ttaints=\([.spec.taints[]?.key]|join(","))\tlabels=\([.metadata.labels|to_entries[]|select(.key|test("webgrip|role"))|"\(.key)=\(.value)"]|join(","))"'
```

**Constraints to never violate:** GitOps-first (no imperative `kubectl apply/delete/patch` for
durable changes — manifest edits reconciled by Flux); **do not schedule on worker-1 until the owner
says go**; one reversible change at a time (batched reconciles have caused storage collapse).
