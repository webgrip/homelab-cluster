# Runbook: node-taxonomy + Longhorn migration — status & how to resume

Live status and the exact remaining steps for the migration defined in
[RFC: node taxonomy & storage placement](../rfc/rfc-node-taxonomy-and-storage-placement.md) and
[ADR-0025](../adr/adr-0025-node-taxonomy.md)–[ADR-0029](../adr/adr-0029-storageclass-consolidation.md).
Goal: get Longhorn replicas **off the soyo control-planes** (protect etcd) and place workloads by a
**capability taxonomy** instead of the ad-hoc `nodegroup=fringe` / `workload-tier` scheme. Keep updating
this file as phases complete.

## Done (as of 2026-06-19)

- **Docs:** RFC + ADR-0025…0029 written and registered.
- **Phase B — taxonomy labels:** `node.webgrip.io/{pool,cpu,ram}` + `storage.webgrip.io/longhorn` applied
  to **all 5 nodes** (soyos applied with `MODE=no-reboot`; the old `nodegroup`/`workload-tier` labels +
  the `dedicated=fringe` taint are still present, retired later). The broken fringe HDD cold-tier disk
  config was removed (see the [incident](../incidents/2026-06-19-node-taxonomy-migration-storage-churn.md)).
- **StorageClass consolidation (ADR-0029):** retired the redundant `longhorn-hot` + broken `longhorn-hdd`;
  `defaultReplicaCount: 2`; added `longhorn-cold`/`longhorn-gitops` scaffolding (inert until disks tagged).
- **Placement mechanism:** `kubernetes/components/placement/worker-pool` built and **proven on n8n**
  (the component correctly injects the hard `pool=worker` affinity), then **un-pinned** — see the blocker
  below.
- **Storage:** the rebuild wedge was cleared and the cluster is back to baseline-healthy.

## The two blockers the n8n canary exposed (read before resuming)

1. **Existing Longhorn PVs exclude `worker-1`.** Volumes created before `worker-1` joined have a PV
   `nodeAffinity` listing only the older nodes, so a **stateful** pod pinned to `pool=worker` can attach
   only on `fringe`, never `worker-1`, until Longhorn places a replica on `worker-1` (eviction). →
   **eviction (Phase E) must precede stateful worker-pinning.**
2. **The fringe taint can't be removed via GitOps.** `register-with-taints` only applies at registration;
   editing Talos config won't drop the live taint, and `kubectl taint` is hook-blocked. Removal needs a
   **fringe re-register (reboot)** or a manual `kubectl taint nodes fringe-workstation dedicated=fringe:NoSchedule-`.

## Remaining steps (corrected order)

1. **Phase D1 — pin stateless apps now.** Apps with **no** PVC can hard-pin to `pool=worker` immediately
   (they reach `worker-1` or `fringe` freely). Add `components/placement/worker-pool` to each app's
   `app/kustomization.yaml` (one line). Candidates: drawio/plantuml, excalidraw, backstage,
   dependency-track frontend, the GUAC web/collectors, harbor web tier, grafana, etc. See the
   `workload-placement` skill and the [ADR-0028](../adr/adr-0028-application-workload-placement.md) tier table.
2. **Retire the fringe taint** — owner removes it manually, or do a controlled fringe re-register; then
   drop `register-with-taints` from `talos/patches/worker/fringe-dedicated.yaml`. After that, `fringe` is
   a normal worker and apps can use both workers.
3. **Phase E — evict Longhorn off the soyos** onto `worker-1`: set `allowScheduling=false` +
   `evictionRequested=true` per soyo, one at a time, wait for 0 replicas + healthy before the next. This also **opens the PV affinity** for `worker-1`, unblocking stateful
   pinning. Keep one designated soyo's `gitops-critical` disk for forgejo/openbao.
4. **Phase D2 — pin stateful apps + CNPG** to `pool=worker` (now that their volumes can reach
   `worker-1`). Same component; CNPG `Cluster`s get `spec.affinity.nodeSelector`.
5. **gitops-critical exception** — forgejo + openbao to `longhorn-gitops` (3 replicas incl. the designated
   soyo) and a worker-preferred / soyo-permitted affinity, so they survive a both-worker outage.
6. **Cleanup** — remove `nodegroup`/`workload-tier` labels once nothing references them; delete `echo` +
   the stale `default/envoy-*` duplicates; optionally exclude the Longhorn DaemonSets from the soyos.

## Guardrails

GitOps-first; **one reversible change per commit, spaced apart** (batched reconciles have collapsed
storage before); **evict, don't drain** soyos (etcd quorum stays intact); validate with
`./scripts/run-flux-local-test.sh` before each commit; watch Longhorn robustness between steps.
