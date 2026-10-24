---
name: victoriatraces
description: Author and operate the VictoriaTraces tracing backend — the VTSingle CR (vm-operator), Alloy otelcol OTLP/HTTP ingest, the spanmetrics/servicegraph connectors that replace Tempo's metrics-generator (traces_spanmetrics_* naming), the two Grafana datasources (jaeger-type /select/jaeger for dashboards; tempo-type /select/tempo with experimental TraceQL for Traces Drilldown), and ingest verification.
when_to_use: Use when writing/editing a VTSingle CR, repointing a trace shipper/exporter, writing or fixing a Grafana trace panel (Jaeger search for dashboards; TraceQL only on the tempo datasource), Traces Drilldown shows no data, a span-metrics alert/SLO or service-graph panel shows "No data", or verifying trace ingest. NOT log CRs (victorialogs skill) nor metrics CRs/scrapes (victoriametrics skill).
---

# VictoriaTraces — the traces backend

Traces backend = **VTSingle** via vm-operator (ADR-0042; replaced Tempo 2026-07-11):
`kubernetes/apps/observability/victoriatraces/`. Endpoint `vtsingle-victoriatraces.observability.svc:10428`.
Dashboard panels query the Jaeger JSON API; **TraceQL exists only via the experimental
Tempo API** (`/select/tempo`, VT ≥ v0.9.4, added 2026-07-12 for Grafana Traces Drilldown).

## CR shape

- Real example: `kubernetes/apps/observability/victoriatraces/app/vtsingle.yaml`.
- **apiVersion `operator.victoriametrics.com/v1`** (like VLSingle; VMSingle's v1beta1 is the outlier). No Helm chart, no image pin — the operator supplies both.
- `retentionPeriod: "14d"` + `extraArgs: {retention.maxDiskSpaceUsageBytes: "8GiB"}` = drop-oldest valve under the 10Gi PVC. Local PVC only; no object-storage backend exists.
- vm-operator auto-creates the `VMServiceScrape` (`job="vtsingle-victoriatraces"`) — don't author one.

## One port, three APIs

| Purpose | Path on `:10428` |
| --- | --- |
| OTLP/HTTP ingest | `/insert/opentelemetry` (exporter appends `/v1/traces`) |
| Jaeger query API | `/select/jaeger` (e.g. `/select/jaeger/api/services`) |
| Tempo query API (TraceQL, experimental, VT ≥ v0.9.4) | `/select/tempo` (e.g. `/select/tempo/api/search`, `/api/v2/search/tags`, `/api/echo`) — feeds Traces Drilldown incl. its TraceQL-metrics RED panels |
| Own metrics | `/metrics` — ingest rate is `vt_rows_ingested_total` / `vt_bytes_ingested_total` (**vt_**, not vl_) |

Alloy exporter (real config: `kubernetes/apps/observability/alloy-gateway/app/helmrelease.yaml`):

```river
otelcol.exporter.otlphttp "victoriatraces" {
  client { endpoint = "http://vtsingle-victoriatraces.observability.svc.cluster.local:10428/insert/opentelemetry" }
}
```

## Span metrics & service graphs come from Alloy, not the backend

VictoriaTraces has no metrics-generator. The alloy-gateway `otelcol.connector.spanmetrics` +
`otelcol.connector.servicegraph` consume the same trace stream and remote_write to VMSingle —
backend churn can't kill the alerts/SLO (Tempo's suspension silently did, for 3 weeks).

Naming vs the old Tempo metrics-generator (queries written pre-2026-07-11 may use the old names):

| Series | Now | Tempo era |
| --- | --- | --- |
| calls counter | `traces_spanmetrics_calls_total` | same |
| latency histogram | `traces_spanmetrics_duration_seconds_bucket` | `traces_spanmetrics_latency_bucket` |
| service label | `service_name` | `service` |
| service graph | `traces_service_graph_*` | same |

`span_kind`/`status_code` values unchanged (`SPAN_KIND_SERVER`, `STATUS_CODE_ERROR`). Extra dimensions
resolve from span attrs, then resource attrs; dots→underscores (`k8s.namespace.name` → `k8s_namespace_name`,
present only when the emitter sets that resource attribute).

⚠️ **An otelcol exporter pointing at a dead/removed backend is memory ballast, not just log noise.**
The default `sending_queue` (1000 batches, in-memory) sits permanently full and amplifies any
ingest surge into OOM territory — alloy-gateway's exporter kept targeting Tempo for 3 weeks after
Tempo was pruned and turned a telemetry spike into a 132-restart OOM loop that also killed the LOG
path. When repointing/retiring a backend, remove the exporter in the same change; if it must
temporarily stay, set `retry_on_failure { enabled = false }` + a small `sending_queue { queue_size }`.

## Grafana — two datasources, same backend

- **Dashboards**: uid `victoriatraces`, type **`jaeger`**, URL `...:10428/select/jaeger`
  (`kubernetes/apps/observability/grafana/app/datasources/victoriatraces.yaml`).
- **Traces Drilldown + TraceQL**: uid `victoriatraces-tempo`, type **`tempo`**, URL
  `...:10428/select/tempo` (`datasources/victoriatraces-tempo.yaml`, added 2026-07-12).
  Experimental upstream — panels/TraceQL may not match native Tempo. The Drilldown app
  only lists tempo-type datasources, which is why this second DS exists. Exemplar links
  (prometheus DS) and VL derived-field trace links point here, not at the jaeger DS.
- Trace panel target (dashboards) = Jaeger search, not TraceQL:
  `{"refId": "A", "datasource": {"type": "jaeger", "uid": "victoriatraces"}, "queryType": "search", "service": "<svc>", "limit": 30}`.
- jaeger-DS jsonData supports `tracesToLogsV2`/`tracesToMetrics`/`nodeGraph`; `serviceMap` and
  `tracesToProfiles` are tempo-type-only — the tempo DS carries `serviceMap` (→ uid `prometheus`,
  reading the Alloy servicegraph series); the `traces-service-graphs` dashboard also covers the map.

## Verify ingest (read-only, via the API-server service proxy — no HTTPRoute exists)

```sh
mise exec -- kubectl get --raw "/api/v1/namespaces/observability/services/vtsingle-victoriatraces:10428/proxy/select/jaeger/api/services"
# Tempo API (Traces Drilldown path) — `/api/echo` answers "echo", tags are scoped:
mise exec -- kubectl get --raw "/api/v1/namespaces/observability/services/vtsingle-victoriatraces:10428/proxy/select/tempo/api/v2/search/tags"
# span metrics landing in VMSingle (urlencode the query):
mise exec -- kubectl get --raw "/api/v1/namespaces/observability/services/vmsingle-vmsingle:8429/proxy/api/v1/query?query=sum(rate(traces_spanmetrics_calls_total%5B5m%5D))"
```

After any alloy-gateway config change, grep the **new pod's logs** for `level=error` — a broken
receiver/exporter keeps the pod Running/Ready (the Faro listener was silently dead this way).
Known-benign exclusion: exactly one `service=remotecfg ... err="noop client"` error per pod at
startup (unused Grafana Fleet Management; Alloy ≥ 1.17) — `grep level=error | grep -v remotecfg`.

## Additional resources

- Decision, trade-offs, removed-feature list → `docs/techdocs/docs/adr/adr-0042-victoriatraces-tracing-backend.md`
- Stack overview → `docs/techdocs/docs/general/observability.md`
