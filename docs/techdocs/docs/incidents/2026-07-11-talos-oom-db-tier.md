# Incident 2026-07-11 — Talos OOMController kills the entire CNPG DB tier; fix wedges 7 DBs Pending

**Severity:** SEV3 (all single-instance DBs restarted at once ~01:27; the *remediation* then caused a real ~15-min DB/SSO outage mid-morning)
**Duration:** trigger event 01:27 UTC (seconds); remediation outage ~07:00–07:15 UTC; fully green ~08:30 UTC.
**Data loss:** none.

## Summary

At 01:27 UTC, 16 containers across 10 namespaces on `fringe-workstation` — including **every CNPG
postgres pod on the node** — died with exit 137 within a 6-second window. The killer was not the
kernel OOM killer but **Talos v1.13's userspace OOM controller** (`runtime.OOMController`,
PSI-triggered, default-on), which kills the **largest BestEffort cgroups first**. All 12 CNPG
`Cluster`s set no `spec.resources`, so the whole DB tier sat permanently in the first-strike tier
on a node idling at ~86% memory with requests at ~90–98% of allocatable.

The remediation had its own incident: the first resources pass added `cpu: 100m`, and because the
worker pool is saturated on **opposite axes** (fringe memory-request-full, worker-1
CPU-request-full), the recreated DB pods fit **neither** node — 7 DBs (including authentik/SSO)
sat `Pending` ~15 minutes until a corrective commit dropped the CPU requests. A knock-on followed:
renovate job pods (1Gi request) no longer fit and needed right-sizing.

Forensics footnote: kernel-side evidence was unrecoverable because the node's dmesg was 100%
SELinux AVC spam — Talos's `auditd` had died silently on 2026-07-09 (upstream bug, see below),
flipping kernel audit output to printk. The `talosctl get oomactions` ledger provided the proof
instead.

## Impact

- 01:27 event: one brief restart of every DB on fringe (apps reconnected; authentik-server pods
  cycled). Counted as 22 "problem pods" by the morning health check.
- Remediation: 7 single-instance DBs down ~15 min (authentik, backstage, forgejo, freshrss, n8n,
  grafana, dependency-track); one authentik-server replica crash-looped and self-recovered.
- harbor-db + guac-db escaped to soyo-3 during pod recreation (missing affinity — latent gap).

## Root cause

```
all 12 CNPG Clusters set no spec.resources
  → every postgres pod is BestEffort QoS
  → Talos runtime.OOMController (PSI memory_full_avg10 threshold) selects
    largest BestEffort cgroups first on a chronically ~86%-full node
  → one reclaim stall kills the whole DB tier simultaneously
```

Remediation wedge: `cpu: 100m` requests + fringe memory-request-full (94–98%) + worker-1
CPU-request-full (89–98%) → `0/5 nodes available: 1 Insufficient cpu, 1 Insufficient memory,
3 didn't match affinity`.

## Key evidence

- `mise exec -- talosctl -n 10.0.0.23 get oomactions` — the kill ledger (entry 179 = this event);
  `node_vmstat_oom_kill` stayed **flat** → not the kernel.
- Identical `lastState.terminated` timestamps across namespaces → node event, not app bugs.
- `kubectl describe node <n> | grep -A6 "Allocated resources"` on both workers showed the axis
  inversion before the corrective commit.

## Fixes (commits, same day)

| Commit | Change |
|---|---|
| 2c9a3779 | `spec.resources` on all 12 CNPG clusters (memory 384Mi/768Mi; dependency-track 512Mi/1Gi) + de-BestEffort renovate-operator, ARC controller, flux-ui limit; trivy-operator → `ram=high` (worker-1) |
| 9fe39561 | **Drop the CPU requests** — memory request alone keeps Burstable QoS; CPU requests only gate scheduling |
| 6927cb47 | renovate job memory request 1Gi → 512Mi (no longer fit post-rebalance) |
| 2b0b03a9 | harbor-db + guac-db inline `spec.affinity.nodeSelector` (the two missing pins) |
| 859a5782 | cnpg-operator de-BestEffort'd (25m/128Mi req, 512Mi limit) + zero-risk soyo evacuation |

Net placement effect: 10 of 12 DBs rescheduled to worker-1 (17Gi free); fringe dropped 86%→70%
memory, requests 98%→93%.

## Lessons

1. **Group identical `Error/137` timestamps by `spec.nodeName` before per-app diagnosis**, then
   check `talosctl get oomactions`. (Now in the cluster-health agent + talos skill.)
2. **Every CNPG Cluster ships with `spec.resources`** — memory-only. (cnpg-database skill.)
3. **Check BOTH request axes on every eligible node before adding requests** — a request-full pool
   can be full on different axes per node. (workload-placement skill.)
4. **Adding requests to a full cluster displaces marginal schedulers** (renovate jobs) — sweep for
   new `Pending` pods after a requests rollout.
5. dmesg is not durable forensics on this cluster while the auditd wedge exists — use
   `oomactions` + VictoriaMetrics. auditd bug: `receiveEvents()` treats transient netlink errors
   as fatal (`errors.Is(err, EINTR) && errors.Is(err, EAGAIN)` — impossible condition, should be
   `||`); service still reports healthy; **reboot-only recovery**; upstream report drafted.

## Related

- [2026-06-09 — Longhorn OOM cascade](2026-06-09-longhorn-oom-cascade.md) — same BestEffort-first
  mechanism, kernel-side, different victim (longhorn-manager).
- [ADR-0002](../adr/adr-0002-application-workload-placement.md) — placement doctrine ratified the
  same day (soyos = recovery brain; zero-risk tier evacuated).
