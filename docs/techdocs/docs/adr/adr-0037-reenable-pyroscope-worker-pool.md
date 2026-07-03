# Re-enable Pyroscope, hard-pinned to the worker pool

* Status: accepted
* Date: 2026-07-02

## Context and Problem Statement

Pyroscope was suspended on 2026-06-03 after its sustained high-throughput profiling writes (a
20 GiB Longhorn volume) contended with etcd WAL fsync on the soyo control planes' shared Talos
EPHEMERAL partition: fsync p99 spiked to 1–4 s against a 1 s election threshold, 3337+ leader
changes on soyo-3, cascading control-plane restarts. The full root cause lives in the suspension
header of
[`kubernetes/apps/observability/pyroscope/ks.yaml`](../../../../kubernetes/apps/observability/pyroscope/ks.yaml).

The mitigation at the time — a **soft** affinity excluding only `soyo-3` — failed twice over:
"preferred" is ignored under scheduler pressure, and it excluded one hostname instead of all
control planes, so pyroscope landed on soyo-1, the then-leader. That is the anti-pattern
[ADR-0002](adr-0002-application-workload-placement.md) later codified against (never soft, never
hostnames). Since the suspension, the taxonomy + `worker-pool` component landed
([ADR-0001](adr-0001-node-taxonomy.md)/[ADR-0002](adr-0002-application-workload-placement.md)), a
second worker (`worker-1`) exists, and the etcd heartbeat/election tuning (500 ms / 5000 ms) is
applied.

## Considered Options

* Re-enable via the shared `worker-pool` component (hard worker-pool affinity)
* Native `nodeSelector`/inline hard affinity on the HelmRelease
* Keep it suspended indefinitely
* Pin to a single host (`fringe-workstation`)

## Decision Outcome

Chosen option: "Re-enable via the shared `worker-pool` component (hard worker-pool affinity)",
because a hard pin to the worker pool fully isolates pyroscope's I/O from etcd — it physically
cannot land on a soyo disk again — while the shared component centralizes the pinning logic
instead of duplicating it inline.

Re-enable pyroscope with placement enforced by
[`components/placement/worker-pool`](../../../../kubernetes/components/placement/worker-pool/kustomization.yaml):
a **hard** `node.webgrip.io/pool In [worker]` affinity post-render-injected into the rendered
StatefulSet (pyroscope has no pre-existing `postRenderers`, so the shared component applies
cleanly). The stale inline soft affinity is removed from the HelmRelease.

Re-enablement is **gated on an owner-run `talosctl etcd defrag`** (boltdb 436 MB → ~165 MB, one
member at a time, leader last — see the [etcd-health runbook](../runbooks/etcd-health.md))
**before** flipping `suspend: false`. This ADR ships the placement fix and keeps the Kustomization
suspended; the defrag + un-suspend is the operator's final step. **Acceptance:** pyroscope lands
on a worker (never `soyo-*`) and `etcd_disk_wal_fsync_duration_seconds` p99 stays < 500 ms with
leader changes ~0/h.

### Positive Consequences

* Pyroscope's I/O is fully isolated from etcd — it physically cannot land on a soyo disk again, so
  the 2026-06-03 failure class cannot recur from this workload.
* Rollback: re-set `suspend: true`; the volume is disposable profiling data.

### Negative Consequences

* Pyroscope goes `Pending` if both workers are down. Accepted per ADR-0002: observability, not on
  the recovery-critical path.
* A fresh 20 GiB Longhorn volume is provisioned on re-enable; land the un-suspend commit spaced
  away from other rollout-heavy commits (the batched-rollout storage-collapse failure mode).
* Does **not** close the long-term etcd durability gap (a dedicated local SSD per soyo for
  `/var/lib/etcd`); that remains a separate open item.

## Pros and Cons of the Options

### Re-enable via the shared `worker-pool` component (hard worker-pool affinity)

* Good, because pyroscope's I/O is fully isolated from etcd — the 2026-06-03 failure class cannot
  recur from this workload.
* Good, because pyroscope has no pre-existing `postRenderers`, so the shared component applies
  cleanly.
* Bad, because pyroscope goes `Pending` if both workers are down — accepted per ADR-0002.

### Native `nodeSelector`/inline hard affinity on the HelmRelease

* Bad, because it duplicates the pinning logic the `worker-pool` component centralizes, with no
  postRenderers conflict here.

### Keep it suspended indefinitely

* Bad, because it loses continuous profiling while worker placement already eliminates the etcd
  risk; the defrag is independent etcd hygiene.

### Pin to a single host (`fringe-workstation`)

The suspend-note's original suggestion.

* Bad, because it wastes the second worker and re-introduces a hostname dependency the taxonomy
  exists to avoid.

## Links

* 2026-06-21 — accepted; placement fix shipped with the Kustomization still suspended (51a8d323)
* 2026-07-02 — still suspended by design (`suspend: true` in ks.yaml): the sole remaining gate is
  the owner-run etcd defrag
* Supersedes the 2026-06-03 pyroscope suspension
* 2026-07-03 — renumbered from ADR-0032 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
