# Incident 2026-06-18 — Longhorn rolling-IM detonation (guaranteed-IM-CPU) + guac-db faulted

> **Closing addendum:** Resolved 2026-06-18 via staged drain — see [runbooks/longhorn-im-cpu-converge.md](../runbooks/longhorn-im-cpu-converge.md); the setting remains `"20"`. (Body below written mid-incident.)

**Severity:** SEV3 (one non-critical app down; recurring cluster-wide degraded waves; one volume `faulted` but Tier-4/recoverable from a logical dump).
**Duration:** 2026-06-18 ~02:19 UTC (first soyo IM roll) → **ONGOING as of ~07:49 UTC** — the driving setting is still `applied=false` and the IMs keep re-cycling (soyo-3 + soyo-1 have each re-rolled a 2nd time). Volumes *oscillate* degraded↔healthy between rolls.
**Data loss:** `guac-db` block replicas are **unrecoverable** (auto-salvage failed `no data exists`), BUT a clean **logical `pg_dump` from 02:40 UTC today exists in S3** — so no real data loss (the dump predates the fault and the DB is Tier-4/rebuildable anyway). No other volume lost.

## Summary

The hardening setting **`guaranteedInstanceManagerCPU: "20"`** — committed 2026-06-12 as a follow-on
fix to the [06-09 OOM cascade](2026-06-09-longhorn-oom-cascade.md) (instance-managers had been
silently running the 12% default through that incident's starvation waves) — **detonated lazily today**.
Longhorn **cannot apply this setting while a node has running engine instances** — confirmed in the
manager log: *"failed to apply guaranteed-instance-manager-cpu setting … when there are running engine
instances. It will be eventually applied."* So it sat `applied=false` for 6 days and the setting
controller retries continuously. Whenever a soyo node briefly has no running instances, Longhorn
**recreates that node's `instance-manager`** with the new 790m (=20% of 3950m) request — and **each IM
recreation kills every replica on that node.** With `concurrentReplicaRebuildPerNodeLimit: "1"`,
rebuilds can't keep pace, so a `degraded` wave follows each roll. Because it never reaches
`applied=true` (fringe + busy soyo nodes rarely hit a zero-engine window), this is **not a one-shot
event — it oscillates**: IMs re-cycle, volumes degrade, rebuilds heal, repeat. soyo-3 and soyo-1 have
each re-rolled a *second* time (06:16 / 05:16 UTC). `guac-db` was the casualty: it entered the day on
effectively **one** healthy replica (its soyo-2 replica had been unhealthy since 06-17 11:07), and the
02:19 soyo-3 IM roll killed the last good one → both replicas dead → `faulted`, with **no salvageable
data**.

This was **self-inflicted**: the (still-incomplete) application of a fix for the *previous* storm
became the *next*, recurring storm. Nothing external failed — no node reboot, no OOM, no disk fault.

## Impact

- `security/guac` down — `guac-db-1` stuck `Init:0/1` (faulted PVC won't mount) → `Kustomization/security/guac` not Ready (`dependsOn guac-db`).
- Cluster-wide Longhorn: peaked at **23/42 volumes `degraded`, 0 actively rebuilding**; transient mount/startup-probe flaps on `forgejo-db-1`, `grafana-db-1`, `n8n-db-1`, `dependency-track-api`, `searxng`, `loki-0`, `openbao-0` as their volumes re-attached. All self-recovered.
- `pvc-b49dc09c` (`guac-db`) → `faulted`.

## Timeline (UTC, approximate)

| Time | Event |
| --- | --- |
| 06-12 21:39 | Longhorn 1.11.2 Helm upgrade writes `guaranteedInstanceManagerCPU: "20"`. Setting goes `applied=false` (danger-zone: applies per-node on volume detach). |
| 06-12 → 06-18 | Setting sits `applied=false` for 6 days. fringe + soyo IMs still on the old 12% (954m / 474m). |
| 06-17 11:07 | guac-db's **soyo-2** replica last healthy — it was already unhealthy/un-rebuilt going into the incident (so guac-db was effectively on 1 replica). |
| 06-18 02:40:09 | **Nightly `guac-db-backup` job completes 1/1** → clean `pg_dump` lands in S3 (the volume was still serving at this point). This is the recovery source. |
| 06-18 02:19:54 | **soyo-3** IM recreated with 790m (20%) → soyo-3 replicas wiped. guac-db soyo-3 (last good) replica `failedAt` 02:20:01 → guac-db now has 0 live replicas. |
| 06-18 03:36:39 | **soyo-1** IM recreated (790m) → soyo-1 replicas wiped → degraded wave. |
| 06-18 03:45:54 | guac-db **soyo-2** replica retry-exhausted/`failedAt` → volume confirmed `faulted`. |
| 06-18 05:03:17 | **soyo-2** IM recreated (790m). FailedRebuilding events (replica connection timeouts) during the churn. |
| 06-18 ~05:05 | Incident noticed (session-start Flux health report flags `guac`/`guac-db`). |
| 06-18 05:16 / 06:16 | **soyo-1 and soyo-3 IMs re-roll a *second* time** (new pod IPs) — confirming the churn recurs, not a one-shot. |
| 06-18 05:36:51 | Longhorn **auto-salvage fires and fails**: *"All replicas are failed, auto-salvaging volume … Failed to auto salvage volume: no data exists."* guac-db block replicas are unrecoverable. |
| 06-18 ~07:49 | Setting still `applied=false`, controller still erroring every few seconds. Volumes momentarily 41 healthy / 1 faulted, **0 rebuilding** (a trough between rolls). **Incident ongoing.** |
| — pending | **fringe** IM still on 12% (954m) — has not rolled; another wave is queued for its next volume-detach window. |

## Root cause

```text
2026-06-12: guaranteedInstanceManagerCPU "12% default" → "20" (fix for 06-09 IM starvation)
  → Longhorn CANNOT apply this to a node's instance-manager while that node has running
    engine instances ("...It will be eventually applied") → setting stuck applied=false
  → setting controller retries forever; whenever a soyo node hits a momentary zero-engine
    window it RECREATES that node's instance-manager with the new 790m (=20% of 3950m) request
      → recreating an instance-manager kills EVERY replica on that node
      → concurrentReplicaRebuildPerNodeLimit=1 + replicaReplenishmentWaitInterval=120s
        → rebuilds can't keep pace → degraded wave per roll
      → never reaches applied=true (fringe/busy nodes rarely hit a zero-engine window)
        → OSCILLATES: re-roll → degrade → heal → re-roll (soyo-3 & soyo-1 rolled 2× already)
  → guac-db was already on 1 healthy replica (soyo-2 replica unhealthy since 06-17 11:07);
    the 02:19 soyo-3 roll killed the last good replica → FAULTED, no salvageable data
    (auto-salvage tried 05:36 → "no data exists")
```

Proof it was the 20% roll and not an external fault: IM pods show `restarts=0` but fresh, staggered
`startedAt` (no node reboot — node `Ready`-since + `bootID` unchanged); new soyo IMs request **790m
(=20% of 3950m)** while the not-yet-rolled **fringe** IM still requests the old **954m (=12% of 7950m)**.
That 12%/20% split is the per-node lazy apply caught mid-flight.

## Contributing factors

- **Destructive application model.** Any change to `guaranteed-*-cpu` / IM spec forces a rolling IM
  recreation, and recreation wipes that node's replicas. There is no in-place CPU-request update.
- **`concurrentReplicaRebuildPerNodeLimit: "1"`** (correct for RAM-tight nodes) means rebuilds are
  slow — so a multi-node roll easily outpaces healing, widening the degraded window.
- **`guac-db` was already on 1 healthy replica.** It had only 2 replicas (soyo-2 + soyo-3) and the
  soyo-2 one had been unhealthy since 06-17 11:07 — so a *single* node roll (soyo-3) was enough to
  fault it. A healthy 3-replica spread (1/soyo-node) would have survived a single-node-at-a-time roll.
- **The setting can never self-complete.** Because it only applies to a node with zero running engine
  instances, and the soyo nodes + tainted fringe rarely/never all hit that window, it stays
  `applied=false` indefinitely and keeps opportunistically re-cycling IMs — turning a one-time roll
  into an open-ended source of degraded waves.
- **Fire-and-forget commit.** The setting was committed like any other manifest; nobody staged or
  watched the per-node roll, so it detonated unattended 6 days later.
- **Lazy + invisible trigger.** `applied=false` for 6 days gave no obvious "pending destructive
  operation" signal; the detonation looked like an out-of-nowhere storm.

## Resolution

> ⚠️ As of last check the incident is **still active** — the setting is `applied=false` and IMs keep
> re-cycling. "Currently 41 healthy" is a *trough*, not a fix. The bleeding stops only when the setting
> reaches `applied=true` on every node (or is reverted).

1. **Stop the oscillation (root) — make the setting converge or back it out.** It will not self-heal:
   - **Drain to apply.** One node at a time, `kubectl cordon` + drain so *all* its volumes detach →
     Longhorn gets the zero-engine window and recreates that node's IM at 20% cleanly → wait for
     `degraded→healthy` → uncordon → next node, finishing with **fringe**. When all four match, the
     setting flips `applied=true` and the retry loop stops.
   - **Or revert** `guaranteedInstanceManagerCPU` to a value the cluster already runs (12%) if the
     20% benefit isn't worth the roll cost — note reverting is *also* a rolling re-apply, so still
     stage it. (See action item #7 — it may be unnecessary now that `longhorn-manager` is Guaranteed-QoS.)
2. **Recover `guac-db` — restore from the logical dump (salvage is NOT possible).** Auto-salvage already
   fired (05:36) and failed `no data exists`; both block replicas are unrecoverable. The clean source is
   the **02:40 UTC `pg_dump` in S3** (`s3://<guac-bucket>/_db-backups/guac-<date>.sql.gz`, job
   `guac-db-backup-29695840` Complete) — newer than any replica. Recreate the (faulted) PVC so CNPG
   re-`initdb`s, then load the dump; or, acceptable by design, just re-init and **re-ingest SBOMs**
   (GUAC is Tier-4, the lowest-stakes DB in the cluster).
3. **fringe** rolls last in step 1's drain sequence — do it deliberately, not on an incidental detach.

> All of the above are mutating/human-gated (GitOps-only guard hook fences the agent out of `kubectl`/Longhorn).

## Detection gap

The 06-09 incident added `LonghornManagerOOMKilled` / `LonghornManagerRestarting` — but those watch the
*manager* (control plane). This storm came from **instance-manager pod churn** (data plane) and a
**faulted volume**, neither of which has a dedicated alert. `LonghornVolumeDegraded` likely fired but
degraded-is-normal-noise; the signal that mattered — **`faulted > 0`** and **instance-manager
recreation rate** — was not alerted. Caught manually via the session-start Flux report again.

## Learnings & action items

| # | Action | Type | Status |
| --- | --- | --- | --- |
| 0 | **Converge or revert the setting NOW** — incident is live. Drain soyo-1/2/3 + fringe one at a time so the IM applies cleanly per node (→ `applied=true` stops the loop), or revert to 12%. | recovery (root) | ⏳ open (P0) — human-gated |
| 1 | **Never fire-and-forget `guaranteed-*-cpu` / IM-spec changes.** Stage them: cordon one node → let its IM recreate → wait `degraded→healthy` → next node. | process (root) | ✅ runbook written — [longhorn-im-cpu-converge](../runbooks/longhorn-im-cpu-converge.md) |
| 2 | Recover `guac-db` from the **02:40 S3 `pg_dump`** (salvage impossible — `no data exists`), else re-init + re-ingest SBOMs. | recovery | ⏳ open (P1) — human-gated |
| 3 | Controlled-roll **fringe** IM to 20% during a quiet window (don't let it detonate incidentally). | prevention | ⏳ open (P1) — human-gated |
| 4 | Ensure critical volumes carry **3 replicas, 1 per soyo node**, so a single-node roll can't fault them (`guac-db` had 2). Audit replica counts of all DB volumes. | prevention | ⏳ open (P2) |
| 5 | Alert on **`longhorn_volume_robustness == faulted` (faulted>0)** and on **instance-manager pod recreation rate** — the two root signals this storm produced. | detection | ⏳ open (P2) |
| 6 | During a *known* IM roll, temporarily raise `concurrentReplicaRebuildPerNodeLimit` 1→2 so rebuilds keep pace, then revert (watch RAM — the 06-09 OOM lesson). | mitigation | ⏳ open (P3) |
| 7 | Re-evaluate whether 20% is necessary now that `longhorn-manager` runs Guaranteed QoS (`5fb9390`). If a lower IM reservation suffices, the destructive roll shrinks. | prevention | ⏳ open (P3) |

## Reusable nuggets

- **Signature of this class of storm:** many volumes `degraded` + **0 actively rebuilding** + `instance-manager` pods with `restarts=0` but fresh/staggered `startedAt` (and **IP changing across checks** = re-cycling), while nodes stayed `Ready` (bootID unchanged). That = a **rolling IM recreation**, not a node/OOM fault. Confirm with the IM `cpu.request` split (old-% on un-rolled nodes vs new-% on rolled ones).
- **`guaranteed-instance-manager-cpu` (and any IM-spec change) is a rolling-replica-wipe, and it can't apply while a node has running engine instances** (`"...It will be eventually applied"`). On a cluster where nodes never all hit a zero-engine window, it stays `applied=false` and **re-cycles IMs indefinitely** → oscillating degraded waves. Treat every such change as a deliberate, drain-backed, node-by-node maintenance op; confirm it reaches `applied=true`.
- **`auto-salvage=true` does NOT mean a faulted volume is recoverable.** Here it fired and logged `Failed to auto salvage volume: no data exists` — when no replica has valid data (all `healthyAt` empty), salvage can't help. Recovery then requires a *logical* backup (pg_dump/S3), not a block-replica salvage. Check `replica.spec.healthyAt`/`lastHealthyAt` to know if salvage is even possible.
- **Tier-4 DBs (`guac-db`) are designed to be lost** — no WAL archiving, nightly `pg_dump` to S3 + rebuild from re-ingested data. Don't over-invest in salvaging them; restore-the-dump or re-init is the valid recovery.
- Durable guidance now lives in the `longhorn` skill and [longhorn-im-cpu-converge runbook](../runbooks/longhorn-im-cpu-converge.md) (the capacity-remediation runbook was retired 2026-07-02).
