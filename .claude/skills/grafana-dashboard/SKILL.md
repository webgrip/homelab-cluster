---
name: grafana-dashboard
description: Add or edit Grafana dashboards, datasources, folders, or alert rules. Use when working with Grafana resources — all managed as Grafana Operator CRDs, never ConfigMaps or HelmRelease values.
---

# Grafana resources (Operator-managed)

All `grafana.integreatly.org/v1beta1` CRDs — never dashboard ConfigMaps or HelmRelease values. Operator reconciles ~10m and **reverts UI edits** (Git is truth). Instance: `observability/grafana/app/grafana-instance.yaml` (no helmrelease). Inventory: `kubectl get grafanadashboards,grafanafolders,grafanadatasources -A`.

**Shape** (enforced by `guard-skills.sh` — fix-up message if you miss one):
- Every CRD: `spec.instanceSelector.matchLabels: {grafana.internal/instance: grafana}`; add `allowCrossNamespaceImport: true` outside `observability`.
- Datasource = `GrafanaDatasource` with `spec.datasource.editable: true`.

## Add a dashboard
1. `observability/grafana/app/dashboards/<name>.yaml`: `kind: GrafanaDashboard`, `spec.folder: "<Title>"`, `spec.json: |`.
2. Register in `observability/grafana/app/kustomization.yaml`.
3. Keep dashboards in `observability` — `folder:` resolves only within the dashboard's own namespace. Cross-namespace → `folderUID` (`allowCrossNamespaceImport` is instance targeting, NOT folder lookup).

Folder titles: Apps · Data · Kubernetes · Networking · Observability · Platform · Security · Storage · Synthetics · Claude Code.

## Escaping (Flux envsubst) — enforced by `guard-skills.sh`
Double **every** Grafana token (`$$__range`, `$$__rate_interval`, `$$var`, `$$__all`). Single `$` before `{`/`(` fails the *whole* grafana Kustomization; single `$model`/`$__range` is silently blanked → No data. Double as you write to avoid fix loops. No literal `$` in titles/`line_format` — write `USD`.

## LogQL (not hook-checked)
- Fields nest under `attributes.*`. Aggregation/`unwrap`/`quantile` → explicit `| json field="attributes.x"` then use `x`; never bare `| json` for aggregation (cardinality blowup). Bare `| json` ok for display-only `logs` panels.
- `clamp_min`/most Prom funcs are invalid in LogQL; `vector(0)` is valid.

## Claude Code metrics (Prom counters → `increase()`/`rate()`)
`claude_code_token_usage_tokens_total{type=input|output|cacheRead|cacheCreation,model,query_source,session_id}`, `…cost_usage_USD_total` (same minus `type`), `…active_time_seconds_total{type=user|cli}`, `…session_count_total{start_type,session_id}`, `…{lines_of_code,commit,pull_request}_count_total`, `…code_edit_tool_decision_total{decision}`.
- `session_id` is on every metric → count sessions via `count(count by (session_id)(max_over_time(claude_code_session_count_total[$$__range])))`, not `sum(increase(...))`.
- Cost = tokens × list price (estimate; notional on Pro/Max — label it).

## Panel hygiene (not hook-checked)
- `or vector(0)` on `stat` panels only — on timeseries/table/bargauge it adds a phantom 0 series.
- `allValue: ".*"` (or omit) for `includeAll` vars; never `$$__all` (logic bug → No data).
- Filters that actually work: variable queries must scope to a **real, existing** metric — `label_values(<metric>, <label>)`, never bare `label_values(<label>)` (that scans every series, so e.g. `model` picks up node-exporter disk models → polluted dropdown). Verify the metric exists first via MCP — our kube-state-metrics has no `kube_namespace_labels`; use `kube_namespace_status_phase`.
- Datasource: hardcode `"uid": "prometheus"`/`"loki"` on panels and variable `datasource` fields. No `${datasource}` picker var — Flux blanks braced `${…}`, so it silently falls back to the *default* datasource (Loki panels then query Prometheus), and a one-option picker isn't a meaningful filter.
- MTD: `time:{from:now/M,to:now}` → `$$__range`=MTD; projection `(<expr>)*$$days_in_month*86400/$$__range_s` (noisy early-month — label estimate + show MTD actual).

## House style
- Don't graph everything: `stat` for single values, `table` for many-row comparison, `timeseries` only when over-time shape matters.
- Money: `currencyUSD`, `decimals: 2` (nl-NL). Pair counts with a derived rate. Log y-axis (`custom.scaleDistribution:{type:log,log:10}`) for series spanning magnitudes.
- N near-identical series → generate JSON from a small Python rate-table; table = instant queries + `merge` + `organize` rename.

## Validate
JSON parses → `mise exec -- kustomize build kubernetes/apps/observability/grafana/app` → smoke-test queries via the read-only Grafana MCP. MCP can't test var interpolation/table transforms — spot-check in UI after reconcile. The `grafana` ks `dependsOn` `grafana-db`; if that CNPG DB is down nothing updates.
