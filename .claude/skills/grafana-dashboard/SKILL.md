---
name: grafana-dashboard
description: Add or edit Grafana dashboards, datasources, folders, or alert rules — all Grafana Operator CRDs (folderRef binding, PromQL/LogsQL panels, Flux envsubst escaping), never ConfigMaps or HelmRelease values.
when_to_use: Use when creating/editing a GrafanaDashboard/GrafanaFolder/GrafanaDatasource or alert rule, writing panel PromQL/LogsQL, debugging a "No data" panel, or fixing duplicated folders.
---

# Grafana resources (Operator-managed)

All `grafana.integreatly.org/v1beta1` CRDs — never dashboard ConfigMaps or HelmRelease values. Operator reconciles ~10m and **reverts UI edits** (Git is truth). Instance: `observability/grafana/app/grafana-instance.yaml` — plugins install via its `GF_INSTALL_PLUGINS` env (grafana.com download at pod start; `Recreate` strategy ⇒ brief outage per change). The Grafana version is pinned via the instance CR's `spec.version` (renovate-annotated); the orphaned chart HelmRelease + its HelmRepository were deleted 2026-07-12 (never applied; confused Renovate). Datasources = the `GrafanaDatasource` CRs only. Inventory: `kubectl get grafanadashboards,grafanafolders,grafanadatasources -A`.

**Shape** (enforced by `guard-skills.sh` — fix-up message if you miss one):
- Every CRD: `spec.instanceSelector.matchLabels: {grafana.internal/instance: grafana}`; add `allowCrossNamespaceImport: true` outside `observability`.
- Datasource = `GrafanaDatasource` with `spec.datasource.editable: true`.

## Add a dashboard
1. `observability/grafana/app/dashboards/<name>.yaml`: `kind: GrafanaDashboard`, `spec.folderRef: <folder-crd-name>` (the GrafanaFolder `metadata.name`), `spec.json: |`.
2. Register in `observability/grafana/app/kustomization.yaml`.
3. Keep dashboards in `observability` — folder lookup resolves only within the dashboard's own namespace (`allowCrossNamespaceImport` is instance targeting, NOT folder lookup).

**Bind folders by `folderRef`, never `spec.folder: "<Title>"`.** A title string makes the operator create+own a *second* folder separate from the GrafanaFolder CRD of the same title → two identical folders, each resurrected on reconcile (UI deletes never stick). `folderRef: <crd-name>` ties the dashboard to the CRD-owned folder. (Fixed 2026-06-20 across the Claude Code dashboards.)

Folder CRD names (use as `folderRef`) = the files in `kubernetes/apps/observability/grafana/app/folders/` (e.g. `apps`, `infrastructure`, `executive` — the leadership KPI scorecard + drill-downs).

## Escaping (Flux envsubst) — enforced by `guard-skills.sh`
Double **every** Grafana token (`$$__range`, `$$__rate_interval`, `$$var`, `$$__all`). Single `$` before `{`/`(` fails the *whole* grafana Kustomization; single `$model`/`$__range` is silently blanked → No data. Double as you write to avoid fix loops. No literal `$` in titles/`line_format` — write `USD`. The guard also fires on **pre-existing** single-`$` tokens anywhere in a file you edit — escape the legacy ones too (safe: `postBuild.substituteFrom` renders `$$`→`$`).

## House style
- Don't graph everything: `stat` for single values, `table` for many-row comparison, `timeseries` only when over-time shape matters.
- Money: `currencyUSD`, `decimals: 2` (nl-NL). Pair counts with a derived rate. Log y-axis (`custom.scaleDistribution:{type:log,log:10}`) for series spanning magnitudes.
- Datasource: hardcode `"uid": "prometheus"`/`"victorialogs"` on panels + variable `datasource` fields — never a `${datasource}` picker (Flux blanks braced `${…}` → silent fallback to the default datasource). Log panels are LogsQL (`victoriametrics-logs-datasource`) — query language + queryType mapping → the `victorialogs` skill.
- Trace panels: Jaeger `search` targets against uid `victoriatraces` — dashboards don't use TraceQL. (TraceQL exists only on the tempo-type DS uid `victoriatraces-tempo`, which serves the Traces Drilldown app; experimental, don't build dashboard panels on it.) Target shape + naming deltas → the `victoriatraces` skill.

## Additional resources
- Panel hygiene, multi-query tables (`merge`+`organize`), the verified k8s-capacity metric catalog, and the Claude Code metric catalog → [reference.md](reference.md); log-query (LogsQL) rules → the `victorialogs` skill

## Validate
JSON parses → `mise exec -- kustomize build kubernetes/apps/observability/grafana/app` → smoke-test queries via the read-only Grafana MCP (`query_prometheus` needs `datasourceUid: prometheus` **and** `startTime`/`endTime` like `now-5m`/`now` even for an instant query). MCP can't test var interpolation/table transforms — spot-check in UI after reconcile. Applied-freshness = `status.observedGeneration == metadata.generation` + `status.lastResync` (the `DashboardSynchronized` condition timestamp does NOT move on content re-apply). The `grafana` ks `dependsOn` `grafana-db`; if that CNPG DB is down nothing updates.
