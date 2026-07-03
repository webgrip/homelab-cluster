# RFC: The observability pipeline beyond metrics — logs, traces, profiles, synthetics

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** ADR-0034 gave the metrics backend a record; the rest of the telemetry pipeline —
> Loki, Tempo, the two-Alloy collector topology, Beyla, Pyroscope, the synthetics fleet — has
> none. The composition is genuinely good and deserves ratifying; the open decisions hiding in it
> (retention tiers chosen app-by-app, single-replica everything, an unauthenticated Loki, a
> failing Kepler) deserve deciding.

## Why

The pipeline as built (verified in-tree 2026-07-02):

- **Logs**: `alloy-agent` (DaemonSet, host network) collects pod stdout, Kubernetes events, and
  **Talos kernel/service logs** via a syslog listener (:6514) → **Loki** in SingleBinary mode —
  1 replica, `auth_enabled: false`, 30d retention, chunks on Garage S3, 10Gi Longhorn scratch.
- **Traces**: `alloy-gateway` (Deployment, 1 replica) receives OTLP (:4317/:4318) + Grafana Faro
  (:12347) and fans out: traces → **Tempo** (S3, 14d, metrics-generator remote-writing service
  graphs into VMSingle), logs → Loki, metrics → VMSingle. **Beyla** (eBPF, opt-in via the
  `beyla.instrument: "true"` annotation, 10% sampling, metrics export disabled) feeds it.
- **Profiles**: Pyroscope — suspended; re-enable gated on the owner-run etcd defrag
  ([ADR-0037](../adr/adr-0037-reenable-pyroscope-worker-pool.md)).
- **Synthetics & meta**: blackbox-exporter `Probe`s (incl. Garage), k6-canaries every 30 min
  writing into VMSingle, Sloth-generated SLOs, kepler (power), twitch-exporter, OpenCost reading
  VMSingle.

None of this has a decision record — which is not just bookkeeping. The pattern that produced
ADR-0034's "scrape coverage is now our responsibility" lesson applies pipeline-wide: hand-built
composition means silent gaps are *ours*, and without records the load-bearing choices can't be
distinguished from accidents. Specific undecided choices found in the audit:

- **Retention/durability was never chosen as a policy**: 15d metrics / 30d logs / 14d traces are
  three per-app defaults, not a tiering decision; whether *any* of it must survive loss is the
  [backup & DR RFC](rfc-backup-dr.md)'s tier question (observability data is presumably
  acceptable-loss — decide it).
- **Every pipeline component is single-replica** (Loki, Tempo, alloy-gateway, VMSingle): an
  alloy-gateway restart drops in-flight OTLP; acceptable for a homelab, but currently accidental.
- **Loki has no auth** (`auth_enabled: false`) and its HTTPRoutes ride the LAN-only posture — the
  same exposure story as the [identity RFC](rfc-identity-sso.md).
- **Kepler is currently unable to roll out** (Helm upgrade timeout on the DaemonSet) — a
  privileged, tolerate-everything DaemonSet whose value (RAPL power metrics feeding the €3/W·yr
  heuristic) has never been weighed against its cost as a decision.
- **Beyla's opt-in convention** (annotation, 10% sampling, traces-only) is a house rule nothing
  documents.

## Proposal

1. **Backfill three retroactive ADRs**:
   (a) **Loki as the log backend** with the alloy-agent collection set — the Talos syslog
   ingestion is the distinctive, easy-to-lose piece; alternatives (VictoriaLogs — natural
   post-ADR-0034 candidate, Elastic) recorded;
   (b) **Tempo + OTLP via alloy-gateway as the tracing spine**, Beyla's opt-in annotation
   convention included;
   (c) **the two-Alloy topology** — per-node *agent* for node-bound sources vs central *gateway*
   for push protocols — as the pattern any new telemetry source must slot into.
2. **Decide the retention & durability tiers** (new ADR): one table — signal → retention →
   survives-what — aligned with the backup-DR tier map. Includes explicitly classifying
   observability data as acceptable-loss (or not, for e.g. security-relevant logs).
3. **Decide Kepler's fate** (new ADR): fix-and-keep (right-sized, with its metrics actually
   consumed by dashboards/OpenCost) or drop it — a privileged DaemonSet that can't reconcile is
   the worst of both. The current Flux-unready state forces the question now.
4. **Ratify the single-replica posture** (fold into 1a–1c consequences): named as the accepted
   trade, with the upgrade path (Loki simple-scalable, gateway HPA) noted for when it stops being
   acceptable.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Loki + alloy-agent as the logging pipeline (retroactive) |
| candidate | — | Tempo + OTLP/alloy-gateway + Beyla opt-in as the tracing pipeline (retroactive) |
| candidate | — | Agent/gateway Alloy topology as the collector pattern (retroactive) |
| candidate | — | Telemetry retention & durability tiers (new) |
| candidate | — | Kepler: fix or retire (new) |

## Out of scope

- The metrics backend — [ADR-0034](../adr/adr-0034-victoriametrics-metrics-backend.md).
- Alert rule shape/health — the [alerting-reliability RFC](rfc-observability-alerting-reliability.md).
- Alert **delivery** — the [alert-delivery RFC](rfc-alert-delivery.md).
- Pyroscope re-enablement — decided, gated, tracked in ADR-0037.

## References

- [observability doc](../general/observability.md) · [victoriametrics runbook](../runbooks/victoriametrics.md) ·
  the `victoriametrics` + `grafana-dashboard` skills
