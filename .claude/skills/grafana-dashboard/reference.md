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
- `sum(A) + sum(B)` returns **empty** if either operand has zero series (e.g. a namespace with a Deployment but no StatefulSet) — Prom drops the whole vector. For a combined total give each metric its own target/series; don't `+` them. (`or vector(0)` on a timeseries adds a phantom 0 line, so that's not the fix either.)
- `histogram_quantile()` needs `le` buckets — confirm they exist via MCP. Some exporters ship only `_sum`/`_count` (e.g. Harbor `harbor_core_http_request_duration_seconds`, no `_bucket`); with no buckets show avg `rate(_sum)/rate(_count)`, not a fake p95.
- Verify panel metric **names** via MCP before authoring — don't copy from an old dashboard or upstream docs, they drift. (Harbor: real is `harbor_project_quota_usage_byte` not `harbor_quota_usage_byte`; totals are `harbor_statistics_*`.)

## Multi-query tables (`merge` + `organize`)
- N near-identical series / many instant queries → generate JSON from a small Python rate-table. Pattern: each metric a `format:"table",instant:true` target (refId A,B,…) → transform `merge` → `organize` `renameByName` the value cols (`Value #A`→friendly) + `indexByName` for order. Confirmed working in prod.
- Per-column units/colour = `fieldConfig.overrides` `byName` (the *renamed* display name). Default unit `short` SI-suffixes bytes as `Mil/Bil/K` — every byte/Bps/percent column needs an explicit override or it's unreadable.
- **`groupToNestedTable` (expandable rows) has two traps — prefer two flat tables for mixed-unit data:** (1) aggregated parent columns are renamed `X (sum)`, so add overrides for *both* `X` and `X (sum)`; sort by `X (sum)`. (2) **field overrides do NOT reach the nested subframe** — expanded rows fall back to the default unit (bytes → `Mil/Bil`, percentunit → `0.02`), and no single default fits CPU+bytes+%+Bps. No way to keep a metric in *both* parent (aggregated) and nested (raw) without querying it twice. Net: for a per-app cost breakdown use a flat ranked table (`Namespace`,`Workload`,abs+`% of cluster` via `… / scalar(sum(…))`) — overrides work, filterable/sortable — not nested.

## k8s capacity metrics (verified present)
`kube_node_status_allocatable`/`_capacity{resource,unit}`, `kube_pod_container_resource_requests`/`_limits{resource,unit,node}` (carry a **`node`** label → per-node req/lim with no join), `container_cpu_usage_seconds_total`/`container_memory_working_set_bytes` (carry **`node`** too), `kubelet_volume_stats_{used,capacity,available}_bytes{persistentvolumeclaim}`, `container_cpu_cfs_{throttled_,}periods_total`. Pod→workload rollup: `… * on(namespace,pod) group_left(workload,workload_type) namespace_workload_pod:kube_pod_owner:relabel` (rule value 1). No `kube_namespace_labels` here — namespace var = `label_values(kube_namespace_status_phase, namespace)`.

## App / per-namespace dashboards

One dashboard per app, every panel scoped to a single `namespace`. All apps share ONE baseline built
only from metrics present for any namespace, so generate the whole family from one Python script (titles/
queries/layout identical; only the namespace + an app-specific section differ). Folders: user-facing apps
→ `apps`; platform services (git, registry, CI) → `infrastructure`. Baseline sections + their source:

- **Health** (stat, `or vector(0)`): `kube_pod_status_phase{phase=...}`, `increase(kube_pod_container_status_restarts_total[1h])`, `increase(container_oom_events_total[24h])` (OOM kills), `kube_pod_container_status_waiting`.
- **CPU / Memory**: usage `rate(container_cpu_usage_seconds_total{image!=""}[…])` / `container_memory_working_set_bytes` vs `kube_pod_container_resource_{requests,limits}{resource="cpu"|"memory"}`; throttle `rate(container_cpu_cfs_throttled_periods_total)/rate(container_cpu_cfs_periods_total)`; mem-vs-limit % flags OOM risk.
- **Network**: `rate(container_network_{receive,transmit}_{bytes,errors,packets_dropped}_total[…])`.
- **Storage**: `kubelet_volume_stats_{used,capacity,available}_bytes`, inodes `kubelet_volume_stats_inodes{,_free}`.
- **Database** (CNPG, per-namespace, present when the app has a `Cluster`): `cnpg_collector_up`, `cnpg_pg_database_size_bytes`, `cnpg_backends_total`/`_waiting_total`, `rate(cnpg_pg_stat_database_{xact_commit,xact_rollback,blks_hit,blks_read,tup_*})`, `cnpg_pg_stat_archiver_{archived,failed}_count`, `cnpg_pg_replication_lag`.
- **App-specific** only where an exporter is scraped: `gitea_*` (Forgejo) + `go_*`/`process_*` on `job="forgejo-http"`, `harbor_*`/`harbor_statistics_*`, `gha_*` (ARC runners), `a2s_*` (Zomboid). No exporter (searxng, invoiceninja) → baseline only. Check `up{namespace=…}` and `kube_pod_container_info` first to see what's scraped / which DB engine (not every app is CNPG — invoiceninja=mariadb, searxng=valkey).

## Claude Code metrics
Prom counters → `increase()`/`rate()`:
`claude_code_token_usage_tokens_total{type=input|output|cacheRead|cacheCreation,model,query_source,session_id}`, `…cost_usage_USD_total` (same minus `type`), `…active_time_seconds_total{type=user|cli}`, `…session_count_total{start_type,session_id}`, `…{lines_of_code,commit,pull_request}_count_total`, `…code_edit_tool_decision_total{decision}`.
- `session_id` is on every metric → count sessions via `count(count by (session_id)(max_over_time(claude_code_session_count_total[$$__range])))`, not `sum(increase(...))`.
- Cost = tokens × list price (estimate; notional on Pro/Max — label it).
