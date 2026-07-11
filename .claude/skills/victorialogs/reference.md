# LogQL → LogsQL translation reference

Empirically validated 2026-07-10 against the live backend (66 dashboard targets). Use with the
`victoriametrics-logs-datasource` Grafana plugin, datasource uid `victorialogs`.

## Contents
- Plugin queryType mapping
- Expression translation table
- Panel-level changes
- Claude Code event fields

## Plugin queryType mapping

Target `queryType` must be one of the plugin's enum strings (from plugin source `src/types.ts`):

| Panel shape (LogQL) | queryType | Backend endpoint |
| --- | --- | --- |
| logs panel (raw lines) | `instant` | `/select/logsql/query` |
| stat/bargauge/piechart/table aggregating over `[$__range]` | `stats` | `/select/logsql/stats_query` |
| timeseries aggregating over `[$__interval]` | `statsRange` | `/select/logsql/stats_query_range` (plugin supplies step) |
| log-count timeline | `hits` | `/select/logsql/hits` |

Remove old `"queryType": "range"` and `"instant": true/false` target props. Keep `legendFormat`
(`{{label}}` works when the `stats by` field has that name — `rename` to short names first).

## Expression translation table

| LogQL | LogsQL |
| --- | --- |
| `{ns="x", container=~"y.*"}` | identical — stream filters incl. regex work when labels are stream fields |
| `\|= "text"` | `~"text"` (regex = substring semantics). Bare phrase `"text"` ONLY if token-aligned — phrase filters are word-tokenized |
| `\|~ "(?i)(err\|warn)"` | `~"(?i)(err\|warn)"` |
| `!= "x"` / `!~ "re"` | `-"x"` / `-~"re"` |
| `\| json a="attributes.b"` | `\| rename attributes.b as a` (OTLP attrs pre-flattened; see SKILL.md shredding note) |
| post-json `\| success="false"` | `\| filter success:="false"` (`:=` exact match; after rename) |
| `\| repo != ""` | `\| filter -repo:""` |
| `sum by (x) (count_over_time({sel}...[$__interval]))` | `{sel} ... \| stats by (x) count()` (statsRange) |
| `sum(count_over_time({sel}...[$__range]))` | `{sel} ... \| stats count()` (stats) |
| `topk(15, sum by (x) (count_over_time(...)))` | `... \| stats by (x) count() hits \| sort by (hits) desc \| limit 15` |
| `quantile_over_time(0.9, ... \| unwrap d [...]) by (x)` | `... \| stats by (x) quantile(0.9, d)` — numeric strings parse; non-numeric rows skipped silently |
| ratio of two counts | one query: `\| stats count() total, count() if (cond) ok \| math ok / total as ratio \| fields ratio` |
| `\| regexp \`repo is (?P<repo>\S+)\`` | `\| extract_regexp "repo is (?P<repo>\\S+)"` (double the backslash) |
| `\| line_format "{{.a}} · {{.b}}"` | `\| format "<a> · <b>" as _msg` |
| `or vector(0)` | no equivalent — delete it, set panel `fieldConfig.defaults.noValue: "0"` |

## Panel-level changes

- Datasource: `{"type": "loki", "uid": "loki"}` → `{"type": "victoriametrics-logs-datasource", "uid": "victorialogs"}` (usually at panel level).
- Flux escaping unchanged: Grafana template vars stay `$$var`; translated exprs should contain no `$$__range`/`$$__interval` (windows dropped).
- Editing GrafanaDashboard CRs: edit the raw `spec.json` text — never YAML-round-trip the file (reformats everything). Integrity check after editing:
  `python3 -c "import yaml,json,sys; d=[x for x in yaml.safe_load_all(open(sys.argv[1])) if x][0]; json.loads(d['spec']['json'])" <file>`
- Verify every translated expr against the live API (SKILL.md "Verify") — empty result is acceptable only when that event type plausibly hasn't occurred in the window.

## Claude Code event fields (OTLP via alloy-gateway)

Pre-flattened dotted paths: `attributes.tool_name`, `attributes.duration_ms`, `attributes.model`,
`attributes.success` (string `"true"`/`"false"`), **`attributes.session.id`** (the old
`attributes_session_id` LogQL filters never matched). Nested JSON-string fields needing
`| unpack_json from ...`: `attributes.tool_parameters`, `attributes.tool_input`.
Error-event fields (confirmed 2026-07-11 against real pre-migration events): `api_error` carries
`attributes.status_code` + `attributes.attempt` (JSON **numbers** → numeral-string field values,
e.g. `"429"`), `attributes.model`, `attributes.duration_ms`, and the message in `attributes.error`;
`attributes.error_name` exists on `internal_error` events only.
