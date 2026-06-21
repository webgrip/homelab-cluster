# ADR-0032: Re-enable Pyroscope, hard-pinned to the worker pool

> Status: **Accepted** · Date: 2026-06-21 · Supersedes the 2026-06-03 pyroscope suspension · Related: [ADR-0025](adr-0025-node-taxonomy.md), [ADR-0026](adr-0026-confine-longhorn-to-workers.md), [ADR-0028](adr-0028-application-workload-placement.md)

## Context

Pyroscope was suspended on 2026-06-03
([`kubernetes/apps/observability/pyroscope/ks.yaml`](../../../../kubernetes/apps/observability/pyroscope/ks.yaml))
after its sustained high-throughput profiling writes — on a 20 GiB Longhorn volume — contended
with etcd WAL fsync on the soyo control-planes' shared `/dev/sda4` (Talos EPHEMERAL) partition.
The damage was severe: etcd WAL fsync p99 spiked to 1–4 s (election threshold 1 s), 3337+ leader
changes on soyo-3, and cascading control-plane restarts and context-deadline errors.

The mitigation at the time was a **soft** `preferredDuringSchedulingIgnoredDuringExecution`
affinity excluding only `soyo-3`. It failed twice over: "preferred" is ignored under scheduler
pressure, and it excluded one hostname instead of all control-planes — so pyroscope landed on
soyo-1, the then-leader. This is precisely the anti-pattern [ADR-0028](adr-0028-application-workload-placement.md)
later codified against (never soft, never hostnames).

Since the suspension the ground has shifted: the capability node taxonomy + `worker-pool`
component landed ([ADR-0025](adr-0025-node-taxonomy.md)/[ADR-0028](adr-0028-application-workload-placement.md)),
a second worker (`worker-1`) was added, and the etcd heartbeat/election tuning (500 ms / 5000 ms)
is applied. Pyroscope is a single-binary StatefulSet with no pre-existing `spec.postRenderers`, so
it is eligible for the shared placement component.

## Decision

Re-enable pyroscope with placement enforced by
[`components/placement/worker-pool`](../../../../kubernetes/components/placement/worker-pool/kustomization.yaml):
a **hard** `requiredDuringSchedulingIgnoredDuringExecution` `node.webgrip.io/pool In [worker]`
affinity, post-render-injected into the rendered StatefulSet. The stale inline soft affinity is
removed from the HelmRelease. `pool=worker` resolves to both `fringe-workstation` and `worker-1`
— strictly better than the suspend-note's outdated "fringe-only / control-plane DoesNotExist".

Re-enablement is **gated on an owner-run `talosctl etcd defrag`** (boltdb 436 MB → ~165 MB, one
member at a time, leader last; see the etcd-health runbook) **before** flipping `suspend: false`.
This ADR ships the placement fix and keeps the Kustomization suspended; the defrag + un-suspend is
the operator's final step. Acceptance: pyroscope lands on a worker (never `soyo-*`) and
`etcd_disk_wal_fsync_duration_seconds` p99 stays < 500 ms with leader changes ~0/h.

## Consequences

- Pyroscope's I/O is fully isolated from etcd — it physically cannot land on a soyo disk again,
  so the 2026-06-03 failure class cannot recur from this workload.
- Pyroscope goes `Pending` if both workers are down. Accepted per ADR-0028: it is observability,
  not on the recovery-critical path, and not worth crushing the 12 GiB soyos for.
- A fresh 20 GiB Longhorn volume is provisioned on re-enable; land the un-suspend commit spaced
  away from other rollout-heavy commits (the batched-rollout storage-collapse failure mode).
- This ADR does **not** close the long-term etcd durability gap (a dedicated local SSD per soyo
  for `/var/lib/etcd`); that remains a separate open item.

## Alternatives considered

- **Native `nodeSelector`/inline hard affinity on the HelmRelease** — works, but duplicates the
  pinning logic the `worker-pool` component centralizes; the component is the DRY default and
  pyroscope has no postRenderers conflict. Rejected.
- **Keep it suspended indefinitely** (the other planning option) — loses continuous profiling and
  the etcd risk is already eliminated by worker placement; the defrag is independent etcd hygiene.
  Rejected in favour of re-enabling.
- **Pin to a single host (`fringe-workstation`)** — the original suspend-note's suggestion; wastes
  the second worker and re-introduces a hostname dependency the taxonomy exists to avoid. Rejected.
