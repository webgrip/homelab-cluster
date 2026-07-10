# Runbook: VictoriaLogs (logs backend)

Use this when log panels are empty, the `VictoriaLogsNoIngest` / `VictoriaLogsDown` alert fires,
or you're verifying the logs backend after a change. Design + rationale:
[ADR-0041](../adr/adr-0041-victorialogs-logging-backend.md).

## Facts (ports, names)

- **VLSingle** — single binary, query + ingest at `:9428`. Service
  `vlsingle-victorialogs.observability.svc.cluster.local:9428`; managed by vm-operator
  (CR `VLSingle/victorialogs`, apiVersion `operator.victoriametrics.com/v1` — **v1**, not
  VMSingle's v1beta1). Manifests: `kubernetes/apps/observability/victorialogs/`.
- **Ingest** is the **Loki push protocol**: `/insert/loki/api/v1/push?_stream_fields=…` — both
  Alloy shippers (`alloy-agent` DaemonSet: pod logs + k8s events + Talos syslog; `alloy-gateway`:
  OTLP/Faro) use `loki.write` pointed there.
- **Query language is LogsQL** (not LogQL). HTTP API: `/select/logsql/query` (log lines),
  `/select/logsql/stats_query` (instant), `/select/logsql/stats_query_range` (range),
  `/select/logsql/field_names`, `/select/logsql/hits`.
- **vmui**: `https://victorialogs.${SECRET_DOMAIN}/select/vmui` (LAN-only).
- Grafana datasource `uid: victorialogs` (plugin `victoriametrics-logs-datasource`); agent access
  via **mcp-victorialogs** (`https://mcp-victorialogs.${SECRET_DOMAIN}/mcp`, in `.mcp.json`).
- Storage: 20Gi Longhorn PVC, 30d retention, drop-oldest valve at 18GiB
  (`retention.maxDiskSpaceUsageBytes`). No S3.

## Fast triage — log panels empty / no fresh logs

```sh
# 1. Backend up?
kubectl get vlsingle -n observability
kubectl get pods -n observability | grep -E 'vlsingle|alloy'

# 2. Rows actually arriving? (via Grafana MCP / PromQL)
#    query_prometheus expr='sum(rate(vl_rows_ingested_total[5m]))'   # ~30-50 rows/s baseline

# 3. Any recent logs at all? (direct LogsQL)
curl -sk 'https://victorialogs.${SECRET_DOMAIN}/select/logsql/query' -d 'query=_time:5m | limit 5'

# 4. Which streams are flowing? (expect pod-log jobs + kubernetes/events + service_name streams)
curl -sk 'https://victorialogs.${SECRET_DOMAIN}/select/logsql/stats_query' \
  --data-urlencode 'query=_time:15m | stats by (job) count()'

# 5. Rows arriving but a specific pipeline missing → shipper side:
kubectl logs -n observability ds/alloy-agent | grep -iE 'error|fail'
kubectl logs -n observability deploy/alloy-gateway | grep -iE 'error|fail'
# The push URLs live in the two alloy HelmReleases; alloy hot-reloads config via its
# config-reloader sidecar (~30s after the ConfigMap changes) — no pod restart needed.
```

## Known conditions

- **`{job="talos/kernel"}` has no data** — pre-existing upstream breakage (since well before the
  VictoriaLogs migration): Talos sends `json_lines` to the alloy-agent syslog listener, which
  rejects the framing (`invalid or unsupported framing. first byte: '{'`). Fixing means changing
  the Talos `machine-logging` patch format or the alloy receiver — tracked separately; not a
  VictoriaLogs issue.
- **Tempo exporter errors in alloy-gateway logs** (`no children to pick from`) — expected while
  Tempo is suspended; unrelated to logs.
- **Disk almost full** — check for a runaway producer with
  `_time:1h | stats by (_stream) count() | sort by (count) desc | limit 10`; then grow the PVC
  (Longhorn expands online) or lower `retentionPeriod`. The 18GiB valve drops the oldest data
  before the PVC fills; `vl_storage_is_read_only` = 1 means the disk did fill.

## Grace period (until ~2026-08-07)

Loki remains deployed **read-only** for pre-2026-07-10 history (Grafana datasource `loki`,
Explore-only). Zero-ingest Loki alerts can be silenced in Alertmanager — do not edit the Loki
HelmRelease. Removal steps are listed in ADR-0041.
