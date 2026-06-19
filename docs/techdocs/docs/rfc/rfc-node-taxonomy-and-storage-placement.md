# RFC: Node taxonomy & storage placement (current 5-node cluster)

> Status: **Proposed** · Date: 2026-06-19 · Umbrella for [ADR-0025](../adr/adr-0025-node-taxonomy.md), [ADR-0026](../adr/adr-0026-confine-longhorn-to-workers.md), [ADR-0027](../adr/adr-0027-longhorn-hot-cold-tiers.md), [ADR-0028](../adr/adr-0028-application-workload-placement.md)

> **TL;DR.** Stop Longhorn from destabilising etcd by moving **all replicas off the soyo
> control-planes onto the two workers** (worker-1 + fringe), and replace today's ad-hoc placement
> (`is-it-control-plane?`, a one-off `workload-tier=apps` label, a `dedicated=fringe` taint) with a
> **capability-based node taxonomy**. Apps **hard-pin to the worker pool and go `Pending` if both
> workers fail** — they are not worth crushing the RAM-tight soyos for. **forgejo is the one
> deliberate exception** (the cluster's GitOps root): it keeps a storage replica on a designated soyo
> and may run there, so it survives a both-worker outage. fringe's 1 TB HDD becomes a **cold tier**
> for bulk data so its small SSD isn't the bottleneck.

This is the concrete **L3/L4 placement layer for the *current* 5-node hardware** — the "Phase 0 /
evolve-in-place" slice of [RFC: Layered Hardware Architecture](rfc-layered-hardware-architecture.md),
not a new-hardware path. It supersedes the storage-migration sketch in the handoff
(`HANDOFF-storage-and-node-strategy.md`).

## Why

Every storage SEV this cluster has had shares one shape: **Longhorn replicas live on the same single
512 GB SSD that the soyo control-planes use for etcd + OS.** The soyos are N150 / **12 GiB RAM**
boxes with one disk each; under Longhorn rebuild storms, instance-manager OOM, and the
"guaranteed-IM-cpu delayed detonation" pattern, the disk and RAM contention reaches etcd and the
control plane wobbles. The structural fix is not another Longhorn tuning band-aid — it is to **give
etcd its disk back** by removing Longhorn from the soyos entirely.

Placement of *workloads* is the second problem. Today it is keyed off "is this node a control-plane"
(which the owner wants to stop relying on — node roles may change), plus a single `workload-tier=apps`
label on worker-1 and a `dedicated=fringe:NoSchedule` taint that ~11 apps carry tolerations for. This
is incoherent and brittle. We want placement driven by **what a node can do** (capability), expressed
as labels, so workloads opt in.

## Concepts (the vocabulary this RFC commits to)

**Taint vs. label — they are opposites, used for opposite jobs.**

- A **taint** is *exclusion*: "keep workloads **off** this node unless they explicitly tolerate it."
  Taints are a blunt, protective instrument. Use them **only** to protect a node from work it must
  not run (e.g. the built-in `node-role.kubernetes.io/control-plane:NoSchedule` on dedicated CPs).
- A **label** + `nodeAffinity` is *attraction*: "this node **has** capability X; workloads that want X
  opt in." Use labels for everything descriptive — pool membership, CPU/RAM class, storage role.

The rule this cluster adopts: **never taint by capability.** "High-RAM" or "has-an-HDD" are *label*
facts; tainting them would force every pod everywhere to carry tolerations just to be scheduled. We
keep workloads off the soyos with a **hard nodeAffinity toward the worker pool**, not a soyo taint —
so the soyos stay open to the infra/system pods that legitimately run there, and apps simply have
nowhere to fall but `Pending` if the workers are gone.

**Longhorn tags are a separate namespace from Kubernetes labels.** Longhorn has its own node tags and
disk tags, consumed by StorageClass `nodeSelector`/`diskSelector`. They are *not* k8s labels and don't
participate in pod scheduling. We use them purely for storage tiering.

**Hot (SSD) vs. cold (HDD) is a tier, not just capacity.** fringe has a 256 GB SSD **and** a 1 TB HDD.
The instinct "1 TB is plenty of space" misreads the constraint: Longhorn writes every replica of a
volume **synchronously**, so a hot volume with one replica on SSD and one on HDD runs at **HDD speed**,
and Postgres/WAL on a 7200 rpm disk reproduces the exact fsync-stall failure class we are trying to
escape. So the HDD is **only** for *cold/bulk* data (backups, archives, large low-IOPS volumes). Used
that way it is the relief valve that keeps fringe's small 236 GiB **SSD** (the real bottleneck) from
filling.

## The cluster as it physically is

| Node | Role | CPU | RAM | Disks | Capability |
|---|---|---|---|---|---|
| soyo-1/2/3 | control-plane (etcd) | N150 (4c) | **12 GiB (tight)** | 1× 512 GB SATA SSD (shared w/ etcd) | infra; `ram: low` |
| fringe-workstation | worker | **i7-4770 (high)** | 16 GiB | 256 GB SSD + **1 TB HDD** | `cpu: high`; storage (hot **+ cold**) |
| worker-1 | worker | i5-4670K | **24 GiB (high)** | **960 GB SSD** | `ram: high`; storage (hot) |

Measured today: 47 Longhorn volumes · **541 GiB provisioned / 115 GiB actual** ·
`replica-soft-anti-affinity=false` (HARD anti-affinity → each replica of a volume on a distinct node).

## End-state design

**Node taxonomy** (k8s labels via Talos `machine.nodeLabels`; Longhorn tags via node annotations):

| Node | `node.webgrip.io/pool` | `cpu` | `ram` | `storage.webgrip.io/longhorn` | Longhorn disk tags |
|---|---|---|---|---|---|
| soyo-1/2/3 | `soyo` | standard | `low` | *(absent)* | none — **except** the one designated soyo keeps a small `gitops-critical` disk |
| fringe | `worker` | `high` | standard | `true` | `hot` (SSD) + `cold` (HDD) |
| worker-1 | `worker` | standard | `high` | `true` | `hot` (SSD) |

**Workload placement:**

- **Apps** (stateful + stateless) → **hard** nodeAffinity to `node.webgrip.io/pool=worker`. They never
  land on a soyo; if both workers are down they go `Pending` (alerted). This is the conscious trade:
  apps pause rather than crush the 12 GiB soyos.
- **Control-plane-critical infra** (coredns, cilium, operators, DaemonSets) → **unconstrained**; keeps
  running on soyos as it does today.
- **forgejo (the exception)** → affinity *permits* the designated soyo (prefers workers), matching its
  storage exception below, so the GitOps root survives a both-worker outage.

**Storage:**

- Longhorn replicas only on worker-1 + fringe; **soyos hold zero replicas** (etcd gets its disk back).
- 2 storage nodes + hard anti-affinity ⇒ a **2-replica ceiling**. The 11 current 3-replica volumes
  drop to 2. HA tolerates losing **one** of {worker-1, fringe}.
- **Hot/cold tiers:** `longhorn-hot` (default, SSD) and `longhorn-cold` (HDD `diskSelector`). Bulk
  volumes move to cold so fringe's 236 GiB SSD has headroom; over-provision (115 GiB actual fits) and
  alert on SSD usage.
- **forgejo exception:** `forgejo-data` + `forgejo-db` use a `longhorn-gitops` StorageClass = **3
  replicas** spanning both workers **and** a `gitops-critical`-tagged disk on one designated soyo.

## Decisions (ADRs under this RFC)

| Decision | ADR | Status |
|---|---|---|
| Capability node taxonomy (labels; retire the `fringe` taint/`nodegroup` scheme) | [ADR-0025](../adr/adr-0025-node-taxonomy.md) | Proposed |
| Confine Longhorn storage to the workers (protect etcd) + forgejo exception | [ADR-0026](../adr/adr-0026-confine-longhorn-to-workers.md) | Proposed |
| Longhorn hot/cold storage tiers (SSD/HDD) via node-annotation disk config | [ADR-0027](../adr/adr-0027-longhorn-hot-cold-tiers.md) | Proposed |
| Pin application workloads to the worker pool (hard; forgejo excepted) | [ADR-0028](../adr/adr-0028-application-workload-placement.md) | Proposed |

## Phased migration

One reversible change per commit, **spaced apart** (batched reconciles have caused storage collapse).

- **A — Docs.** This RFC + the four ADRs (flips to Accepted as each lands).
- **B — Taxonomy labels** (ADR-0025): add `node.webgrip.io/*` + `storage.webgrip.io/longhorn` +
  Longhorn disk-config annotations via Talos patches; apply per node (no reboot).
- **C — Hot/cold tiers** (ADR-0027): `createDefaultDiskLabeledNodes=true`; create
  `longhorn-hot`/`longhorn-cold`/`longhorn-gitops`; verify disks/tags; move bulk volumes to cold.
- **D — App pin + forgejo** (ADR-0028 / ADR-0026 exception): per app, swap `nodegroup=fringe`
  selectors → worker-pool affinity; convert the 4 `workload-tier=apps` soft affinities to hard; point
  forgejo's two volumes at `longhorn-gitops` and give forgejo its worker-preferred/soyo-permitted
  affinity. Remove the fringe taint from the node **last**.
- **E — Soyo eviction** (ADR-0026): open worker-1 in Longhorn + GC the orphan `slab` node; reduce
  3-replica volumes → 2; **evict soyos one at a time** (`allowScheduling=false` + `evictionRequested`,
  waiting for 0 replicas + all-healthy before the next); lock soyos storage-free and lower
  `guaranteedInstanceManagerCPU`.

## Risks & open questions

- **2-replica ceiling** loses the 3rd-copy redundancy on 11 volumes. Restored only by a **3rd storage
  node** or a **bigger fringe SSD** — a follow-up, gated on hardware.
- **fringe SSD (236 GiB)** is the binding capacity constraint; relies on over-provisioning + active
  cold-tiering. Needs a usage alert so it can't silently fill.
- **forgejo exception** puts scoped Longhorn I/O back on one soyo. Bounded to two volumes; revisit if a
  3rd storage node arrives (then forgejo joins the normal worker-only pool).
- **Eviction blast radius:** evict (not drain) soyos so etcd quorum is untouched; one node at a time.

## Verification

`mkdocs build --strict`; `./scripts/run-flux-local-test.sh` green throughout; `kubectl get
nodes.longhorn.io` shows fringe = 2 tagged disks and soyos = no schedulable disk (designated soyo =
`gitops-critical` only); after Phase D every app/CNPG pod is on a worker (forgejo may sit on the
designated soyo); replica spread reaches soyo = 0; a both-worker cordon drill leaves forgejo serving
git and Flux reconciling.
