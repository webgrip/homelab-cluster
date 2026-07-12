---
name: victorialogs
description: Author and operate the VictoriaLogs logs backend — the VLSingle CR (vm-operator), Alloy loki.write ingest with _stream_fields, LogsQL queries and LogQL→LogsQL translation for Grafana panels (victoriametrics-logs-datasource), and the /select/logsql verification API.
when_to_use: Use when writing/editing a VLSingle CR, adding or repointing a log shipper, writing or translating a LogsQL query, a log panel shows "No data" after migration, debugging missing log streams or fields (_msg missing, attributes.* paths), or verifying log ingest. NOT incident triage (runbooks/victorialogs.md) nor metrics CRs (victoriametrics skill).
---

# VictoriaLogs — the logs backend

Logs backend = **VLSingle** via vm-operator (ADR-0041): `kubernetes/apps/observability/victorialogs/`.
Endpoint `vlsingle-victorialogs.observability.svc:9428`. Firefighting → `docs/techdocs/docs/runbooks/victorialogs.md`.

## CR shape

- Real example: `kubernetes/apps/observability/victorialogs/app/vlsingle.yaml`.
- **apiVersion `operator.victoriametrics.com/v1`** — VLSingle is v1; VMSingle's `v1beta1` and its
  `removePvcAfterDelete` field are rejected (flux-local passes the wrong apiVersion; kubeconform/apiserver catch it).
- `retentionPeriod: "30d"` + `extraArgs: {retention.maxDiskSpaceUsageBytes: "18GiB"}` = drop-oldest valve under the 20Gi PVC.
- vm-operator auto-creates the `VMServiceScrape` (`job="vlsingle-victorialogs"`) — don't author one.
- CRD present? MCP `view` can't get CRDs; probe instead: `resources_list apiVersion=operator.victoriametrics.com/v1 kind=VLSingle` — empty list = registered, "no matches" = missing.

## Ingest (shippers stay on loki.write)

VictoriaLogs ingests the **Loki push protocol**; a shipper cutover is a URL change:

```river
url = "http://vlsingle-victorialogs.observability.svc.cluster.local:9428/insert/loki/api/v1/push?_stream_fields=cluster,namespace,pod,container,job,node,instance"
```

- `_stream_fields` pins which labels form streams; fields absent on an entry are ignored (one list serves many pipelines). No tenant headers (defaults to 0:0).
- Alloy hot-reloads via its config-reloader sidecar (~30s, no restart); confirm with the sidecar's `Reload triggered` log line.

## The load-bearing semantic: JSON logs are shredded at ingest

VL parses JSON log bodies into first-class fields — **there is no `_msg`** for JSON-emitting apps
(flux, OTLP events, tetragon). Plain-text logs keep `_msg`.

- Text filters against a shredded stream match nothing **silently** — filter on fields, or rebuild a line: `| pack_json | filter _msg:~"(?i)(...)"`.
- OTLP `attributes.*` arrive pre-flattened (dotted names) → `| rename attributes.y as x`, not json-extraction.
- `| unpack_json from <field>` only for nested JSON-string fields (e.g. claude-code `attributes.tool_parameters`).
- Before writing any query against an unfamiliar stream, look at one real entry: `query=<sel> | limit 1` — never assume field paths (claude-code sessions are `attributes.session.id`, dotted).

## Verify (parse errors return HTTP 400, so `status:success` is meaningful)

```sh
curl -sk 'https://victorialogs.${SECRET_DOMAIN}/select/logsql/stats_query' --data-urlencode 'query=_time:15m | stats by (job) count()'
# also: /select/logsql/query (lines), /stats_query_range (start/end/step), /field_names, /hits; vmui at /select/vmui
```

Or the `victorialogs` MCP server (`.mcp.json`). PromQL side: `vl_rows_ingested_total`/`vl_bytes_ingested_total`
are **lazily registered** — absent (not 0) until first ingest, so `rate(...) == 0` alerts can't see the day-0 failure.

## Gotchas

- LogsQL phrase filters are **word-tokenized**, not substring — translate LogQL `|=` to regex `~"..."` unless token alignment is proven.
- Regex escapes are doubled in LogsQL strings: `extract_regexp "(?P<f>\\S+)"`, `~"i\\/o"` — a single backslash is an HTTP-400 parse error.
- Grafana time range is injected by the datasource plugin — no `_time:` in panel exprs, and LogQL `[$__range]`/`[$__interval]` windows disappear in translation.
- **VL ≥ v1.51.0 rejects bare filters after a pipe**: `foo | bar` is an error unless the segment starts with a known pipe name or `field:`; write `foo bar` or `foo | filter bar`. VL's version moves **invisibly on vm-operator chart bumps** (no image pin) — before one, sweep dashboard LogsQL: walk each GrafanaDashboard `spec.json` panels/targets **with datasource inheritance** (targets usually inherit the panel-level `datasource` — same-dict matching finds ~3 of 62 exprs), split exprs on top-level `|`, flag unknown first tokens. Swept clean 2026-07-12 (62 exprs).
- **Anchor query windows to *cluster* time, not your guess of now** — a `start`/`_time` even minutes in the future returns 0 results, which reads as "ingest broken". Get cluster-now from any fresh PromQL result's epoch timestamp first.

## Additional resources

- Full LogQL→LogsQL translation crib + Grafana plugin queryType mapping → [reference.md](reference.md)
- Decision + Loki grace-period/removal checklist → `docs/techdocs/docs/adr/adr-0041-victorialogs-logging-backend.md`
