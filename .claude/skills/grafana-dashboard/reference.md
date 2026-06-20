# Grafana dashboard reference — queries, panels, tables, metric catalogs

Contents: [LogQL](#logql) · [Panel hygiene](#panel-hygiene) · [Multi-query tables](#multi-query-tables-merge--organize)
· [k8s capacity metrics](#k8s-capacity-metrics-verified-present) · [Claude Code metrics](#claude-code-metrics)

All hook-checked rules live in SKILL.md (shape, folderRef, Flux escaping). The below are NOT hook-checked.

## LogQL
- Fields nest under `attributes.*`. Aggregation/`unwrap`/`quantile` → explicit `| json field="attributes.x"` then use `x`; never bare `| json` for aggregation (cardinality blowup). Bare `| json` ok for display-only `logs` panels.
- `clamp_min`/most Prom funcs are invalid in LogQL; `vector(0)` is valid.

## Panel hygiene
- `or vector(0)` on `stat` panels only — on timeseries/table/bargauge it adds a phantom 0 series.
- `allValue: ".*"` (or omit) for `includeAll` vars; never `$$__all` (logic bug → No data).
- Variable queries must scope to a **real, existing** metric — `label_values(<metric>, <label>)`, never bare `label_values(<label>)` (scans every series, so e.g. `model` picks up node-exporter disk models → polluted dropdown). Verify the metric exists first via MCP — our kube-state-metrics has no `kube_namespace_labels`; use `kube_namespace_status_phase`.
- MTD: `time:{from:now/M,to:now}` → `$$__range`=MTD; projection `(<expr>)*$$days_in_month*86400/$$__range_s` (noisy early-month — label estimate + show MTD actual).

## Multi-query tables (`merge` + `organize`)
- N near-identical series / many instant queries → generate JSON from a small Python rate-table. Pattern: each metric a `format:"table",instant:true` target (refId A,B,…) → transform `merge` → `organize` `renameByName` the value cols (`Value #A`→friendly) + `indexByName` for order. Confirmed working in prod.
- Per-column units/colour = `fieldConfig.overrides` `byName` (the *renamed* display name). Default unit `short` SI-suffixes bytes as `Mil/Bil/K` — every byte/Bps/percent column needs an explicit override or it's unreadable.
- **`groupToNestedTable` (expandable rows) has two traps — prefer two flat tables for mixed-unit data:** (1) aggregated parent columns are renamed `X (sum)`, so add overrides for *both* `X` and `X (sum)`; sort by `X (sum)`. (2) **field overrides do NOT reach the nested subframe** — expanded rows fall back to the default unit (bytes → `Mil/Bil`, percentunit → `0.02`), and no single default fits CPU+bytes+%+Bps. No way to keep a metric in *both* parent (aggregated) and nested (raw) without querying it twice. Net: for a per-app cost breakdown use a flat ranked table (`Namespace`,`Workload`,abs+`% of cluster` via `… / scalar(sum(…))`) — overrides work, filterable/sortable — not nested.

## k8s capacity metrics (verified present)
`kube_node_status_allocatable`/`_capacity{resource,unit}`, `kube_pod_container_resource_requests`/`_limits{resource,unit,node}` (carry a **`node`** label → per-node req/lim with no join), `container_cpu_usage_seconds_total`/`container_memory_working_set_bytes` (carry **`node`** too), `kubelet_volume_stats_{used,capacity,available}_bytes{persistentvolumeclaim}`, `container_cpu_cfs_{throttled_,}periods_total`. Pod→workload rollup: `… * on(namespace,pod) group_left(workload,workload_type) namespace_workload_pod:kube_pod_owner:relabel` (rule value 1). No `kube_namespace_labels` here — namespace var = `label_values(kube_namespace_status_phase, namespace)`.

## Claude Code metrics
Prom counters → `increase()`/`rate()`:
`claude_code_token_usage_tokens_total{type=input|output|cacheRead|cacheCreation,model,query_source,session_id}`, `…cost_usage_USD_total` (same minus `type`), `…active_time_seconds_total{type=user|cli}`, `…session_count_total{start_type,session_id}`, `…{lines_of_code,commit,pull_request}_count_total`, `…code_edit_tool_decision_total{decision}`.
- `session_id` is on every metric → count sessions via `count(count by (session_id)(max_over_time(claude_code_session_count_total[$$__range])))`, not `sum(increase(...))`.
- Cost = tokens × list price (estimate; notional on Pro/Max — label it).
