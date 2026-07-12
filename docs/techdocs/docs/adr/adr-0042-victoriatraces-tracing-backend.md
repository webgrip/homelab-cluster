# VictoriaTraces replaces Tempo as the tracing backend

* Status: accepted
* Date: 2026-07-12

Technical Story: [rfc-observability-pipeline](../rfc/rfc-observability-pipeline.md) — the same
consolidation line as ADR-0034 (metrics) and ADR-0041 (logs), extended to traces; also resolves
roadmap item #68's "decide the commented-out telemetry" for Tempo.

## Context and Problem Statement

Metrics run on VictoriaMetrics ([ADR-0034](adr-0034-victoriametrics-metrics-backend.md)) and logs
on VictoriaLogs ([ADR-0041](adr-0041-victorialogs-logging-backend.md)), but tracing was a zombie:
Tempo had been **suspended since 2026-06-19** (commented out of the observability kustomization to
free ~1Gi on the overcommitted fringe node). Traces sent to the Alloy gateway were exported to a
dead endpoint and dropped, the Grafana `tempo` datasource showed no data, and — less obviously —
Tempo's **metrics-generator** was the producer of the `traces_spanmetrics_*` and
`traces_service_graph_*` series that the app-traffic alerts and the apps-availability SLO consume,
so those had been silently no-data for three weeks. Restore Tempo (1–3Gi, Garage S3 on the
critical path), or complete the Victoria consolidation?

## Decision Drivers

* Tracing was effectively down; the choice was "which backend to bring up", not a live migration —
  no grace period or history concerns (the S3 bucket held only stale pre-June data).
* One operator: vm-operator (chart 0.65.1 / operator v0.72.0) already serves the `VTSingle` CRD;
  the deployment pattern is a copy of the proven VLSingle one.
* Resource pressure was the reason Tempo was suspended; VictoriaTraces runs the VictoriaLogs
  engine and fits in a fraction of Tempo's 1–3Gi.
* Remove Garage S3 from the tracing path (Tempo stored blocks in the `tempo` bucket).
* Cost: VictoriaTraces has no TraceQL (query via the Jaeger-compatible API) and no
  metrics-generator — span metrics and service graphs must be produced elsewhere.

## Considered Options

* VictoriaTraces (VTSingle via vm-operator) + Alloy spanmetrics/servicegraph connectors
* Re-enable Tempo as it was
* Leave tracing off and delete the trace pipeline

## Decision Outcome

Chosen option: "VictoriaTraces + Alloy connectors", because it restores tracing at a fraction of
the footprint that got Tempo suspended, completes the one-operator Victoria stack, takes Garage
off the tracing path, and the metrics-generator gap has a clean OTel-native answer: generate span
metrics and service graphs in the Alloy gateway, where the trace stream already flows.

Load-bearing specifics:

* `kubernetes/apps/observability/victoriatraces/` — `VTSingle` (apiVersion
  `operator.victoriametrics.com/v1`, like VLSingle), `retentionPeriod: 14d` matching Tempo's 336h,
  10Gi Longhorn PVC with safety valve `retention.maxDiskSpaceUsageBytes: 8GiB`, worker-pool
  placement. Endpoint `vtsingle-victoriatraces.observability.svc:10428` — OTLP/HTTP ingest under
  `/insert/opentelemetry`, Jaeger query API under `/select/jaeger`. The operator auto-creates the
  `VMServiceScrape` (job `vtsingle-victoriatraces`).
* `alloy-gateway`: the `otelcol.exporter.otlp "tempo"` (gRPC) exporter became
  `otelcol.exporter.otlphttp "victoriatraces"`; new `otelcol.connector.spanmetrics` (namespace
  `traces.spanmetrics`, seconds histogram, `exclude_dimensions: [span.name]`, same dimension set
  Tempo used) and `otelcol.connector.servicegraph` feed the existing prometheus-exporter →
  VMSingle remote_write chain. Memory limit 384Mi → 512Mi for connector state.
* **Metric-name deltas** (the only query-visible change): the latency histogram is
  `traces_spanmetrics_duration_seconds_bucket` (was `traces_spanmetrics_latency_bucket`) and the
  service label is `service_name` (was `service`); `traces_spanmetrics_calls_total` and the
  `traces_service_graph_*` family are name-compatible. Updated consumers:
  `prometheusrule-app-traffic.yaml`, `slo-app-availability.yaml` (description only — calls_total
  queries unchanged), the relocated service-graphs dashboard (uid `tempo-service-graphs` →
  `traces-service-graphs`), and the Grafana trace-to-metrics config.
* Grafana: new `GrafanaDatasource` uid `victoriatraces`, **type `jaeger`** pointed at
  `/select/jaeger` (no TraceQL; trace panels use Jaeger `search` queries). `tracesToLogsV2` points
  at `victorialogs` (skipping the loki hop ADR-0041 planned to repoint at Loki removal);
  `serviceMap`/`tracesToProfiles` dropped (Tempo-only features; the service-graphs dashboard
  covers the map). Exemplar destinations and TraceID derived-fields repointed from `tempo`.
* Removal in the same change (no grace period — nothing to keep queryable):
  `kubernetes/apps/observability/tempo/` deleted, kustomization entry replaced, the
  `grafana-charts-tempo` Kyverno HelmRepository exception dropped. Out-of-repo cleanup: the Garage
  `tempo` bucket (stale since 2026-06-19). The `observability-s3` component's last consumer is now
  Loki, so it leaves with the ADR-0041 removal commit.

### Positive Consequences

* Tracing works again — it had been dropped on the floor since 2026-06-19 — and the span-metrics
  alerts/SLO get their data back.
* One CRD-driven stack for metrics + logs + traces; Garage S3 fully off the observability
  critical path (after the pending Loki removal).
* ~256Mi requests / 1Gi limit vs Tempo's 1Gi/3Gi; no S3 storage growth.
* Span-metrics generation now lives in the collector layer (Alloy), independent of which trace
  store is behind it.

### Negative Consequences

* No TraceQL: trace search is Jaeger-API-shaped (service/operation/tags), weaker for ad-hoc
  span-attribute queries; the Grafana MCP's Tempo tools go dead.
* Metric rename means span-latency history (pre-2026-06-19) doesn't line up with the new series
  name; service-graph edge history keeps its names.
* VictoriaTraces is the youngest Victoria product; less battle-tested than Tempo.
* Local-PVC-only storage: trace durability rides on Longhorn replication (same trade as
  VictoriaLogs, and traces are the most ephemeral signal).

## Pros and Cons of the Options

### Re-enable Tempo as it was

* Good, because TraceQL, serviceMap and traces-to-profiles are first-class in Grafana.
* Bad, because its 1–3Gi footprint is what got it suspended, and it keeps Garage S3 + a separate
  Helm stack on the tracing path.

### Leave tracing off

* Good, because zero resource cost.
* Bad, because the span-metrics alerts/SLO stay dead and the instrumented pipeline (Faro, OTLP
  apps, Claude Code telemetry) already emits traces that cost nothing extra to store at this
  volume.

## Links

* Refines [ADR-0034](adr-0034-victoriametrics-metrics-backend.md) and
  [ADR-0041](adr-0041-victorialogs-logging-backend.md) — completes the VictoriaMetrics
  consolidation for the third signal
* [rfc-observability-pipeline](../rfc/rfc-observability-pipeline.md) — pipeline inventory
* 2026-06-19 — Tempo suspended to relieve fringe-node memory pressure (context, not this ADR)
* 2026-07-11 — accepted; VTSingle deployed, alloy-gateway rewired, Tempo removed (this change)
* 2026-07-12 — the accepted "no TraceQL" trade-off is partially restored: VT v0.9.4 (via
  vm-operator 0.66.2, 832d9e1f) ships an experimental **Tempo query API + TraceQL** at
  `/select/tempo`; a second tempo-type Grafana datasource (`victoriatraces-tempo`) now serves
  the Traces Drilldown app and serviceMap. Dashboards stay on the Jaeger datasource. Note:
  Grafana **Logs Drilldown** remains impossible against VictoriaLogs (loki-type-only upstream;
  [victorialogs-datasource#424](https://github.com/VictoriaMetrics/victorialogs-datasource/issues/424))
  — the `victorialogs-explorer` dashboard is the fallback.
