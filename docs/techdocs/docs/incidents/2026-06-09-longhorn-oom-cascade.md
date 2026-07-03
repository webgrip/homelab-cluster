# Incident 2026-06-09 — Longhorn OOM cascade + dependency-track-db outage

**Severity:** SEV2 (single app down ~18h; storage layer degraded cluster-wide, no data lost)
**Duration:** ~2026-06-08 late evening → 2026-06-09 ~05:05 UTC (DB recovery); volume healing tail after.
**Data loss:** none (no volume ever `faulted`; faulted=0 throughout).

## Summary

A routine Longhorn capacity cleanup the previous afternoon triggered a `replica-auto-balance`
rebuild storm. On RAM-tight nodes, the **BestEffort-QoS `longhorn-manager` was OOM-killed** during
the load spikes (rebuilds + the 03:00 all-volume snapshot-cleanup), causing the storage control
plane to flap. That cascaded into: (1) ~32 volumes stuck `degraded`, (2) one node's disk wedged in
a stale `Ready=False`, and (3) `dependency-track-db` crash-looping because its 10Gi WAL volume
filled and the PVC resize couldn't complete. Recovery was control-plane-first: stop the storm,
clear the stuck disk, expand the WAL, restart the DB, then heal volumes.

## Impact

- `dependency-track` (API + DB) down ~18h, 189 crash-loops on `dependency-track-db-1`.
- Cluster-wide Longhorn: 32/38 volumes `degraded` (still available — degraded ≠ down).
- Flux `security/dependency-track*` Kustomizations stuck not-ready.

## Timeline (UTC, approximate)

| Time | Event |
|---|---|
| 06-08 afternoon | Capacity cleanup (orphan/abandoned PVC + `test` volume deletes) → Longhorn `replica-auto-balance: best-effort` starts a rebuild/rebalance wave. |
| 06-08 ~11:00–12:00 | `longhorn-manager` OOM-killed (exit 137) on multiple nodes during the wave (BestEffort QoS → first OOM victim). |
| 06-08 late evening | `dependency-track-db` WAL volume (10Gi) fills (archiving fell behind during I/O stalls); Postgres begins crash-looping `no space left on device` migrating `pg_wal`. |
| 06-09 03:00 | `snapshot-cleanup` RecurringJob runs across **all 40 volumes** → `snapshotPurge` timeouts (03:09–03:31), more load. |
| 06-09 03:44–03:52 | `FailedRebuilding` cascade (replica connection-refused; engines flapping). |
| 06-09 ~03:48 | Incident noticed (session-start Flux health report). |
| 06-09 ~04:00–05:00 | Diagnosis: manager OOM root, 32 degraded, WAL-full deadlock, soyo-2 disk stuck `Ready=False`. |
| 06-09 ~05:05 | DB recovered `2/2`; rebuilds resumed at limit 1; healing (degraded 32→23→…). |

## Root cause

```
longhorn-manager runs BestEffort QoS (no memory request/limit)
  → on RAM-tight nodes (~11GB, 68–78% baseline) it is the kernel's first OOM target
  → load spike (auto-balance rebuilds + 03:00 all-volume snapshot purge) → OOM-killed (137)
  → storage control plane flaps:
      ├── replica-auto-balance keeps generating rebuilds that fail → 32 volumes stuck degraded
      ├── soyo-2 disk condition wedged Ready=False/NodeNotReady (stale, even after node recovered)
      └── csi-resizer flaps → dependency-track-db WAL PVC resize (10→30Gi) never completes
              → WAL stays full → Postgres can't start → CNPG can't reconcile the resize (deadlock)
```

Compounding: the git manifest already declared `walStorage: 30Gi`, but **CNPG does not auto-propagate
a `walStorage` size increase to the live PVC** — live stayed 10Gi. So the "fix" was already committed
yet never applied.

## Contributing factors

- **RAM-tight nodes** (soyo ~11GB) running at 66–87%; no headroom for Longhorn load spikes.
- **`replica-auto-balance: best-effort`** amplified a one-off cleanup into a sustained rebuild storm.
- **Synchronized recurring job:** `snapshot-cleanup` hit all 40 volumes at 03:00 — one big load spike.
- **fringe disk over-reserved** (the open capacity problem) blocked the WAL expansion on its replica,
  forcing a replica-count reduction mid-incident. Capacity debt had a direct availability cost.
- **CNPG `walStorage` resize is silent-no-op** on an existing cluster — a latent trap.

## Resolution

1. **Stop the storm:** committed `replica-auto-balance: disabled` (`058ca9d`); live-set
   `concurrent-replica-rebuild-per-node-limit=0` to pause rebuilds so the manager could stabilize.
2. **Unblock the WAL expand:** dropped the WAL volume 3→2 replicas and removed the **fringe** replica
   (fringe had ~7Gi scheduling headroom; soyo-2/soyo-3 had room).
3. **Clear the stuck disk:** restarted `longhorn-manager` on soyo-2 → disk `Ready=True` → the pending
   PVC resize auto-completed to 30Gi.
4. **Recover the DB:** `delete pod dependency-track-db-1` → started clean, drained WAL backlog to S3,
   went `2/2`, cluster phase healthy.
5. **Heal:** re-set rebuild limit to 1 (auto-balance still off → gentle replenishment). degraded fell.

## Detection gap

Symptom alerts exist and likely fired (`LonghornVolumeDegraded`, `LonghornNodeNotReady`,
`PVCVolumeAlmostFull`, `CNPGWALArchivingFailed`) but the incident was caught manually. There is **no
alert on the root signal** — `longhorn-manager` OOMKills / restart rate. `CNPGWALArchivingFailed`
also did **not** catch this: archiving reported healthy while the WAL still filled (resize stuck).

## Learnings & action items

| # | Action | Type | Status |
|---|---|---|---|
| 1 | Give `longhorn-manager` **Guaranteed QoS** so it's not the first OOM target. | prevention (root) | ✅ done — `5fb9390` (postRenderer, both DS containers req==lim; applies on Flux reconcile) |
| 2 | Finish **CNPG 3→2 replicas + add the HDD** — less rebuild memory + reservation headroom. Capacity work *is* stability work. | prevention | ✅ done 2026-06-12 (remediation runbook since retired; history in [ADR-0008](../adr/adr-0008-confine-longhorn-to-workers.md)/[0029](../adr/adr-0010-storageclass-consolidation.md) status logs) |
| 3 | Keep **`replica-auto-balance: disabled`**; rebalance manually after deliberate changes. | prevention | ✅ done — `058ca9d` |
| 4 | De-spike `snapshot-cleanup` so it isn't a synchronized 03:00 load event. | prevention | ✅ already gentle — RecurringJob runs `concurrency=1` (sequential); auto-balance was the real spike. No change needed. |
| 5 | Document that **CNPG `walStorage` resize needs a manual PVC expand** (git size alone won't apply). Add to the CNPG runbook. | docs | ⏳ open (P2) |
| 6 | Alert on **`longhorn-manager` OOMKills / restart rate** (ObservabilityOOMKills only covers `namespace=observability`). | detection | ✅ done — `498267e` (`LonghornManagerOOMKilled` + `LonghornManagerRestarting`) |
| 7 | Capture the **stuck-disk fix** as a reusable runbook step (below). | docs | ✅ done |
| 8 | **GitOps-only guard hook fences the agent out of `kubectl`** — recovery needed a human at the keyboard for every mutation. Decide: vetted break-glass allowlist vs. accept the tradeoff. | process | P3 |

## Reusable nuggets

- **Stuck Longhorn disk** (`disk Ready=False, reason=NodeNotReady`) while the **k8s node and Longhorn
  node are `Ready`** = stale disk-monitor state. Fix: `kubectl -n longhorn-system delete pod
  longhorn-manager-<pod-on-that-node>` (control-plane only; does **not** disrupt volume I/O, which the
  separate `instance-manager` serves). Disk returns to `Ready` in ~60s.
- **Longhorn rebuild storm:** set `concurrent-replica-rebuild-per-node-limit=0` to pause and let the
  managers stabilize, then back to `1` with `replica-auto-balance: disabled` for calm replenishment.
- **CNPG WAL-full deadlock:** expand the WAL PVC directly (`kubectl patch pvc …-wal … storage: NGi`),
  then `delete pod <cluster>-1`. If the expand is webhook-denied for disk scheduling, reduce that
  volume's replica count / move the replica off the over-reserved disk first.
- `faulted=0` is the line that matters during a degraded storm — degraded volumes are still serving.
