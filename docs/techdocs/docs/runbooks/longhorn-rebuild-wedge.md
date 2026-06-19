# Runbook: Longhorn rebuild-wedge (zombie replicas hold the rebuild slot)

Use when Longhorn shows **many `degraded` volumes but nothing is actually rebuilding** — the rebuild
queue is wedged. Root cause is usually one or more **"zombie" replicas**: a replica stuck `running` that
never finished rebuilding (`healthyAt=""`) and is **not in its engine's `replicaModeMap`**. With
`concurrentReplicaRebuildPerNodeLimit: "1"` it permanently occupies that node's single rebuild slot, so
every other rebuild queued for that node stalls. Seen 2026-06-19 (a storage-node reboot seeded two of
them) — see the [incident](../incidents/2026-06-19-node-taxonomy-migration-storage-churn.md).

## 1. Confirm the wedge (fingerprint)

```bash
# robustness spread — expect some "degraded"
mise exec -- kubectl get volumes.longhorn.io -n longhorn-system -o json \
  | mise exec -- jq -r '[.items[].status.robustness]|group_by(.)|map({(.[0]):length})|add'

# replicas actually rebuilding — if this is 0 while degraded > 0, the queue is WEDGED
mise exec -- kubectl get replicas.longhorn.io -n longhorn-system -o json \
  | mise exec -- jq -r '[.items[]|select(.status.currentState=="rebuilding")]|length'
```

`degraded > 0` **and** `rebuilding == 0` (sustained) = wedged.

## 2. Find the zombie replicas

Zombies are `running`, have an **empty `healthyAt`**, and (the giveaway) are **absent from their
volume's engine `replicaModeMap`** (the engine only lists the replicas it's actually serving/syncing):

```bash
# candidates: running replicas with no healthyAt, grouped by node
mise exec -- kubectl get replicas.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '
  .items[] | select(.status.currentState=="running" and (.spec.healthyAt // "")=="")
  | "\(.spec.nodeID)\t\(.spec.volumeName)\t\(.metadata.name)"'
```

The longhorn-manager log on the blocked node names the held slot explicitly:

```bash
mise exec -- kubectl -n longhorn-system logs ds/longhorn-manager --tail=200 \
  | mise exec -- rg 'rebuildings for .* are in progress on this node, which reaches .* concurrent limit'
```

## 3. VERIFY a surviving copy before deleting (critical)

For each zombie's volume, confirm a **different** replica is `RW` in the engine — deleting the zombie
must not remove the volume's only good copy:

```bash
V=<volume-name>   # e.g. pvc-e1cae8df-...
# which replica is RW (the real, serving copy)?
mise exec -- kubectl -n longhorn-system get engines.longhorn.io -o json \
  | mise exec -- jq -r --arg v "$V" '.items[]|select(.spec.volumeName==$v)|.status.replicaModeMap // {}|to_entries[]|"\(.key) = \(.value)"'
# all replicas of the volume + their node/state/healthyAt
mise exec -- kubectl -n longhorn-system get replicas.longhorn.io -o json \
  | mise exec -- jq -r --arg v "$V" '.items[]|select(.spec.volumeName==$v)|"\(.metadata.name) node=\(.spec.nodeID) state=\(.status.currentState) healthyAt=\(.spec.healthyAt // "")"'
```

Proceed only if a **different** replica shows `RW` with a real `healthyAt`. The zombie is the one that is
`running`/`healthyAt=""`/not in the `RW` map.

## 4. Delete the zombie replica CR

```bash
mise exec -- kubectl -n longhorn-system delete replicas.longhorn.io <zombie-replica-name>
```

Longhorn frees the node's rebuild slot, recreates the replica, and rebuilds it normally. **Do one node's
zombie at a time** and watch a rebuild progress (`WO` appears in a `replicaModeMap`, then `degraded`
count drops) before deleting the next — so only one rebuild runs at a time.

> ⚠️ Imperative Longhorn-CR deletes are **human-gated** (the GitOps guard hook fences the agent out of
> mutating `kubectl`). Run these yourself, or with explicit owner go.

## 5. Verify recovery

```bash
mise exec -- kubectl get volumes.longhorn.io -n longhorn-system -o json \
  | mise exec -- jq -r '[.items[].status.robustness]|group_by(.)|map({(.[0]):length})|add'
```

`degraded` should fall and `healthy` rise as the freed slots churn through the backlog (serial, slow with
`rebuild-limit=1` — give it time).

## Related cleanups often needed alongside

- **Orphan Longhorn node** (e.g. a renamed/replaced node): Longhorn refuses to delete the node CR while
  `allowScheduling=true` — patch it first:
  ```bash
  mise exec -- kubectl -n longhorn-system patch nodes.longhorn.io <name> --type=merge -p '{"spec":{"allowScheduling":false}}'
  mise exec -- kubectl -n longhorn-system delete nodes.longhorn.io <name>
  ```
- **Over-replicated volumes** (3 replicas on a 2-storage-node design — [ADR-0026](../adr/adr-0026-confine-longhorn-to-workers.md)):
  reducing them relieves the storm by cancelling queued rebuilds:
  ```bash
  mise exec -- kubectl -n longhorn-system patch volumes.longhorn.io <vol> --type=merge -p '{"spec":{"numberOfReplicas":2}}'
  ```

## See also

- [Incident 2026-06-19 — config-drift reboot → rebuild wedge](../incidents/2026-06-19-node-taxonomy-migration-storage-churn.md)
- [longhorn-capacity-remediation](longhorn-capacity-remediation.md) · [longhorn-im-cpu-converge](longhorn-im-cpu-converge.md) · [longhorn](longhorn.md)
