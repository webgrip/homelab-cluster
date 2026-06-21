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
- **Phase D1 started:** sparkyfitness-server (`f10693a`) and dependency-track api-server+frontend
  (`70dff79`) hard-pinned to `pool=worker` — both `longhorn`-backed, so they moved/stayed on the worker
  pool with no eviction needed (proves the `Immediate`-binding path).

## The two blockers the n8n canary exposed (read before resuming)

1. **Only `WaitForFirstConsumer` volumes exclude `worker-1` — not all PVs** (corrected 06-19 after the n8n
   canary). The split is the StorageClass `volumeBindingMode`:
   - **`longhorn` = `Immediate`** → PV carries **no** `nodeAffinity` → attaches on any node incl.
     `worker-1`. So **`longhorn`-backed stateful apps pin to the worker pool now**, no eviction needed.
     This includes **all CNPG DBs**, `dependency-track-apiserver`, authentik-media, the observability
     TSDBs, etc. (Verified: DT api-server hard-pinned and rescheduled cleanly onto `worker-1` — commit
     `70dff79`; sparkyfitness-server already there — `f10693a`.)
   - **`longhorn-general` = `WaitForFirstConsumer`** → PV bakes in the storage nodes present at first bind
     and never refreshes → **permanently excludes `worker-1`**. n8n's 111-day-old `longhorn-general`
     volume listed soyo-2/soyo-3/fringe but not `worker-1`, so pinning it to `pool=worker` left it
     `Pending`. These can still reach `fringe` (once its taint is gone); to reach `worker-1` they must be
     **migrated to the `longhorn` SC** (ADR-0029) — **eviction does NOT help**, it can't rewrite the
     immutable PV `nodeAffinity`. The 16 `longhorn-general` PVCs: n8n, freshrss, searxng, invoiceninja
     (×2), minecraft, forgejo-data, gitea-mirror, openbao, harbor redis/trivy/jobservice, sparkyfitness
     backup/uploads, infisical-redis, searxng-valkey.
   - Check any volume: `kubectl get pv <pv> -o jsonpath='{.spec.nodeAffinity}'` (empty = free to move).
2. **The fringe taint can't be removed via GitOps.** `register-with-taints` only applies at registration;
   editing Talos config won't drop the live taint, and `kubectl taint` is hook-blocked. Removal needs a
   **fringe re-register (reboot)** or a manual `kubectl taint nodes fringe-workstation dedicated=fringe:NoSchedule-`.
   Retiring it lets the `longhorn-general` (WFFC) apps schedule on `fringe` without an SC migration.
3. **🚧 CAPACITY BLOCKS a full soyo eviction (found 2026-06-19).** Getting *all* Longhorn replicas off the
   soyos means each 2-replica volume keeps one copy on `fringe` and one on `worker-1` (hard anti-affinity,
   `replicaSoftAntiAffinity: false`). **The data is small — ~109 GiB actually used (one copy)** — but
   volumes are heavily over-provisioned: ~541 GiB *reserved* (every CNPG DB reserves 20–30 GiB for <0.5 GiB
   used). At Longhorn's default `storageOverProvisioningPercentage: 100`, `fringe`'s 236 GiB SSD can't
   *reserve* the 541 GiB second copy — even though the real 109 GiB would fit with room to spare. `worker-1`
   (891 GiB) holds a full copy fine.
   - **CHOSEN (2026-06-19): raise `storageOverProvisioningPercentage` 100 → 300** in the longhorn
     HelmRelease `defaultSettings` — lets the thin volumes reserve onto `fringe`'s SSD; real usage ~46% of
     236 GiB. **Watch `fringe` SSD free** (prometheus 50 GiB cap + WAL are the only growers; WAL capped by
     walStorage + Garage archive). Durable follow-ups: right-size the bloated volumes, or add the HDD.
   - **HDD role (ADR-0027, later):** cold/bulk **only** — Loki chunks, Harbor registry layers, staged
     backups, media, minecraft. **Never** Postgres data/WAL (too slow). Needs an NTFS wipe first (it wedged
     boot — see the [incident](../incidents/2026-06-19-node-taxonomy-migration-storage-churn.md)).
   With overprovisioning raised, evict soyos **one at a time** (worker-1 absorbs first, fringe takes the
   thin second copies) — never `evictionRequested` all three at once.

## Remaining steps (corrected order)

The D1/D2 split is no longer "stateless vs stateful" — it's **`longhorn`/Immediate (now) vs
`longhorn-general`/WFFC (after SC migration or fringe-taint retirement)**. Most stateful apps are on
`longhorn` and move now.

1. **Phase D1 — pin everything backed by `longhorn` (Immediate) now.** Stateless apps **and**
   `longhorn`-backed stateful apps can hard-pin to `pool=worker` immediately. Add
   `components/placement/worker-pool` to each app's `app/kustomization.yaml` (one line), **one app per
   commit, spaced** (batched reconciles have collapsed storage). Done so far: sparkyfitness-server
   (`f10693a`), dependency-track api-server+frontend (`70dff79`). Remaining candidates: stateless web
   tiers (drawio/plantuml, excalidraw, backstage, GUAC web/collectors, harbor core/portal, grafana) +
   `longhorn`-backed ones (the CNPG DBs, trivy-server, loki, the kube-prometheus TSDBs, authentik). Skip
   any app whose volume is `longhorn-general` (see step 3). Verify each: `kubectl get pv <pv> -o
   jsonpath='{.spec.nodeAffinity}'` empty before pinning.
2. **Retire the fringe taint** — owner removes it manually, or do a controlled fringe re-register; then
   drop `register-with-taints` from `talos/patches/worker/fringe-dedicated.yaml`. After that, `fringe` is
   a normal worker **and the `longhorn-general` (WFFC) apps can schedule on `fringe`** even before their
   volumes migrate — so this unblocks most of step 3's apps for the worker pool immediately.
3. **Phase D2 — the `longhorn-general` (WFFC) apps.** Their PVs exclude `worker-1`. Two paths: (a) after
   the fringe taint is gone they pin to `pool=worker` and land on `fringe`; (b) to actually use `worker-1`
   capacity, **migrate the volume to the `longhorn` SC** (ADR-0029 consolidation — clone/restore into a
   new `longhorn` PVC, or back up→restore). Eviction does **not** fix these (immutable PV `nodeAffinity`).
4. **Phase E — evict Longhorn replicas off the soyos** onto the workers (protects etcd — the original
   goal): `allowScheduling=false` + `evictionRequested=true` per soyo, one at a time, waiting for both
   0 replicas and healthy volumes before the next. This is about **replica placement**, independent of
   the PV-pinning above. **Done 2026-06-21: soyos hold 0 replicas.**
5. **gitops-critical — RESOLVED WITHOUT a soyo replica (2026-06-21).** The original plan (forgejo+openbao
   on `longhorn-gitops`, 3 replicas incl. a designated soyo) is **dropped** — see the
   [ADR-0026](../adr/adr-0026-confine-longhorn-to-workers.md) update. Garage S3 is external (survives a
   both-worker outage) and forgejo's future-Flux-source resilience is the GitHub fallback
   ([ADR-0015](../adr/adr-0015-external-bootstrap-fallback-source.md)), so forgejo-db/openbao/gitea-mirror
   are pinned to the **workers** like any app; DR is external Garage S3 backups (Longhorn backup target +
   CNPG barman + openbao raft snapshots). `longhorn-gitops` SC deleted. **Soyos stay 100% Longhorn-free.**
6. **Cleanup** — remove `nodegroup`/`workload-tier` labels once nothing references them; delete `echo` +
   the stale `default/envoy-*` duplicates; optionally exclude the Longhorn DaemonSets from the soyos.

## DR hardening (replaces the soyo replica — 2026-06-21)

With the soyos kept Longhorn-free, forgejo/openbao survive a both-worker outage via **external Garage S3**
backups (Garage is off-cluster at 10.0.0.110), not a live replica:

- **forgejo-db** → CNPG barman to Garage (daily, confirmed: 5+ backups present). Restore drill left
  *suspended* (load + the mechanism is the proven shared CNPG component) — run on demand via the
  [cnpg-restore-playbook](cnpg-restore-playbook.md).
- **openbao** → nightly raft snapshot to Garage (confirmed running). Restore + the **unseal-key backup
  gap** → [openbao-restore](openbao-restore.md).
- **forgejo-data + gitea-mirror** → a **Longhorn backup target** (Garage S3, `default` BackupTarget CR,
  `AVAILABLE=true`) + the `gitops-backup` RecurringJob (daily, retain 7). **Owner one-time opt-in** (the
  Volume CR label is hook-gated):
  ```bash
  mise exec -- kubectl label volumes.longhorn.io \
    $(mise exec -- kubectl get pvc forgejo-data -n forgejo -o jsonpath='{.spec.volumeName}') \
    $(mise exec -- kubectl get pvc gitea-mirror -n forgejo -o jsonpath='{.spec.volumeName}') \
    -n longhorn-system recurring-job-group.longhorn.io/gitops-backup=enabled
  ```

## Guardrails

GitOps-first; **one reversible change per commit, spaced apart** (batched reconciles have collapsed
storage before); **evict, don't drain** soyos (etcd quorum stays intact); validate with
`./scripts/run-flux-local-test.sh` before each commit; watch Longhorn robustness between steps.
