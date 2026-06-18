# Runbook — Converge a Longhorn `guaranteed-instance-manager-cpu` (IM-spec) change

**When to use:** after changing `guaranteedInstanceManagerCPU` (or any setting that forces an
instance-manager respec), the setting is stuck `applied=false` and instance-managers keep re-cycling,
causing **oscillating degraded waves**. See incident
[2026-06-18](../incidents/2026-06-18-longhorn-im-cpu-rolling-detonation.md) and memory
`longhorn-guaranteed-im-cpu-delayed-detonation`.

**Why it happens:** Longhorn *cannot* apply the new CPU request to a node's instance-manager while that
node has **running engine instances** (`"...It will be eventually applied"`). On a cluster where the
nodes rarely all hit a zero-engine window at once, the setting never reaches `applied=true`; the
controller retries forever and opportunistically recreates IMs (each recreation wipes that node's
replicas). The only way to stop it is to **give each node a clean zero-engine window, one at a time**,
so the setting applies and converges — or to revert the value (also a staged roll).

> **GitOps-only / human-gated.** The guard hook fences the agent out of `kubectl`/Longhorn mutations.
> Run these as the operator. Keep them staged — never roll two nodes before the first has fully healed.

---

## 0. Pre-flight — confirm the diagnosis & that it's safe to roll

```bash
# Setting still pending?  -> false means not converged
mise exec -- kubectl get settings.longhorn.io guaranteed-instance-manager-cpu -n longhorn-system \
  -o jsonpath='{.value}  applied={.status.applied}{"\n"}'

# IMs mid-roll? cpu.request split (790m=20% rolled vs 954m=12% not-yet) + changing IP across checks
mise exec -- kubectl get pods -n longhorn-system -o wide | grep instance-manager
for p in $(mise exec -- kubectl get pods -n longhorn-system -o name | grep instance-manager); do
  mise exec -- kubectl get $p -n longhorn-system \
    -o jsonpath='{.spec.nodeName} cpu={.spec.containers[0].resources.requests.cpu}{"\n"}'; done
```

**Gate — every *in-use* volume must have ≥2 healthy replicas before you start** (a staged single-node
roll then only ever drops a volume to 1, which heals). Audit:

```bash
mise exec -- kubectl get replicas.longhorn.io -n longhorn-system -o json \
 | mise exec -- jq -r '.items|group_by(.spec.volumeName)[]
     |{v:.[0].spec.volumeName,h:([.[]|select(.spec.healthyAt!="" and .spec.failedAt=="")]|length)}
     |select(.h<2)|"\(.h)\t\(.v)"'
```

Any volume with <2 healthy that is **attached/in-use** must be healed or recovered FIRST (see §1).
Detached/orphaned/suspended single-replica volumes (e.g. an Infisical orphan, a suspended Pyroscope)
have nothing to fault — note them but they don't block the roll.

---

## 1. Heal/recover exposed volumes first

- **`guac-db` (faulted, Tier-4)** — block replicas are unrecoverable (`auto-salvage` → `no data
  exists`). Restore from the nightly logical dump in S3 (newer than any replica). See §3.
- **Orphaned PVCs** (no workload, not in git — e.g. `data-infisical-redis-0`): just delete to reclaim
  space; they're not part of the roll.
- **Single-replica-by-config volumes** that are currently *detached/suspended* (e.g. Pyroscope): leave
  them; only resume/attach them **after** the converge, or bump their replica count to 2 first.

---

## 2. Converge — staged drain, one node at a time

Goal: give each node a window with **no running Longhorn engine instances** so the setting applies,
then move on. Do soyo workers/control-plane first, **fringe last**.

For each node `$N` in `soyo-1, soyo-2, soyo-3, fringe-workstation`:

```bash
# a) cordon + drain so all pods (and thus Longhorn volumes) leave the node
mise exec -- kubectl cordon $N
mise exec -- kubectl drain $N --ignore-daemonsets --delete-emptydir-data --timeout=15m
#    (control-plane nodes: drain evicts workloads only; etcd/kubelet stay. Watch RAM on the
#     remaining nodes — these are RAM-tight; the 06-09 incident was an OOM cascade. If memory
#     spikes dangerously, abort: uncordon and reschedule for a quieter window.)

# b) confirm THIS node's instance-manager has no running instances, then that it re-applied 20%
mise exec -- kubectl get pods -n longhorn-system -o wide | grep "instance-manager.* $N "
#    expect the IM to recreate; verify its cpu.request is now 790m (=20% of a 3950m soyo node)

# c) uncordon and WAIT FOR FULL HEAL before the next node
mise exec -- kubectl uncordon $N
#    wait until 0 volumes degraded / 0 rebuilding:
mise exec -- kubectl get volumes.longhorn.io -n longhorn-system --no-headers | awk '{print $4}' | sort | uniq -c
mise exec -- kubectl get replicas.longhorn.io -n longhorn-system --no-headers | grep -c -i rebuild
```

> `concurrentReplicaRebuildPerNodeLimit: "1"` makes heal slow — that's fine, it's the safety margin.
> Do **not** start the next node until degraded=0 and rebuilding=0.

---

## 3. Recover guac-db from the logical dump

guac-db is a **single-instance, Tier-4 CNPG** cluster (no WAL archiving) with a nightly logical backup:
CronJob `guac-db-backup` → `s3://<guac-bucket>/_db-backups/guac-<date>.sql.gz` (Garage S3). The faulted
volume has no salvageable data, so recover from the dump (or just re-init + re-ingest SBOMs — acceptable
by design). Cross-check exact CNPG mechanics with [cnpg-restore-playbook](../cnpg-restore-playbook.md).

1. Remove the faulted PVC + instance so CNPG re-bootstraps a fresh empty DB:
   `kubectl delete pvc guac-db-1 -n security` and let the operator recreate `guac-db-1` (initdb).
2. Once `guac-db-1` is `1/1` with an empty `guac` DB, load the latest dump:
   download `guac-<date>.sql.gz` from S3 → `gunzip -c guac-<date>.sql.gz | psql` into the `guac` DB
   (via a one-shot pod with the guac credentials, or `kubectl exec` into the primary).
3. **Or** skip the restore entirely: leave the DB empty and let GUAC re-ingest SBOMs — the graph
   rebuilds. Lowest-effort, acceptable for this Tier-4 DB.

---

## 4. Post-checks

```bash
mise exec -- kubectl get settings.longhorn.io guaranteed-instance-manager-cpu -n longhorn-system \
  -o jsonpath='applied={.status.applied}{"\n"}'              # MUST be true now → loop stopped
mise exec -- kubectl get volumes.longhorn.io -n longhorn-system --no-headers | awk '{print $4}' | sort | uniq -c   # faulted=0
mise exec -- flux get ks -A --status-selector ready=false    # security/guac back to Ready
```

`applied=true` is the success signal: the setting controller stops erroring and the IM re-cycling ends.

## Alternative — revert instead of converge

If the 20% reservation isn't worth the roll (it may be redundant now that `longhorn-manager` runs
Guaranteed QoS, `5fb9390`), set `guaranteedInstanceManagerCPU` back to `12` in
`kubernetes/apps/longhorn-system/longhorn/app/helmrelease.yaml` and commit. **This is still a staged
rolling re-apply** — follow §2 to converge it; reverting does not skip the drain.
