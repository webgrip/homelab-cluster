---
name: grafana-dashboard
description: Add or edit Grafana dashboards, datasources, folders, or alert rules. Use when working with Grafana resources — all managed as Grafana Operator CRDs, never ConfigMaps or HelmRelease values.
---

# Grafana resources (Operator-managed)

Everything is a `grafana.integreatly.org/v1beta1` CRD. Never use dashboard ConfigMaps (`grafana_dashboard: "1"` — the sidecar was removed) or HelmRelease values.

## Universal rules
- Every CRD needs:
  ```yaml
  spec:
    instanceSelector:
      matchLabels: { grafana.internal/instance: grafana }
  ```
- Resources **outside** the `observability` namespace also need `spec.allowCrossNamespaceImport: true`.
- The Grafana instance itself is `observability/grafana/app/grafana-instance.yaml` (there is no `helmrelease.yaml` — don't look for one).
- Datasources = `GrafanaDatasource` CRDs with `spec.datasource.editable: true` (not in the instance `spec.config`).
- The operator reconciles ~every 10m and **reverts UI edits** — all changes must be in Git. Inventory: `kubectl get grafanadashboards -A`.

## Add a dashboard
1. Create `kubernetes/apps/observability/grafana/app/dashboards/<name>.yaml`:
   ```yaml
   apiVersion: grafana.integreatly.org/v1beta1
   kind: GrafanaDashboard
   metadata: { name: <name> }
   spec:
     instanceSelector: { matchLabels: { grafana.internal/instance: grafana } }
     folder: "<Title>"        # by title — see Folders below
     json: |
       { "title": "...", "uid": "...", ... }
   ```
2. Add `- ./dashboards/<name>.yaml` to `observability/grafana/app/kustomization.yaml`.
3. **Do NOT co-locate dashboards with their service.** Folder resolution is **namespace-scoped**: `folder:`/`folderRef:` resolve only within the dashboard's own namespace. `allowCrossNamespaceImport` controls instance targeting, NOT folder lookup. Cross-namespace dashboards must use `folderUID` instead of `folder:`.

## Folders

Dashboards in `observability/` (the convention) just set `folder: "<Title>"` by name. Valid titles and scope: **Apps** (user workloads) · **Data** (DBs/queues) · **Kubernetes** (cluster health) · **Networking** (Cilium/Envoy) · **Observability** (Prom/Alertmanager/Loki/Tempo/Mimir) · **Platform** (Flux/cert-manager/Renovate/etcd) · **Security** (Kyverno/Falco/Tetragon/Trivy/Cosign) · **Storage** (Longhorn) · **Synthetics** (blackbox/k6) · **Claude Code** (Claude Code usage/cost telemetry). List live folders with `kubectl get grafanafolders -A`.

Only if you must place a dashboard in a *different* namespace (discouraged), reference it by `folderUID` instead of `folder:` — titles resolve only within the dashboard's own namespace. Get the UID from `kubectl get grafanafolder <name> -o jsonpath='{.spec.uid}'`.

## Query authoring & escaping (hard-won — these break things silently)

**Flux `envsubst` runs on every dashboard.** Single `$` is consumed as a variable.
- Double **every** Grafana macro/variable: `$$__rate_interval`, `$$__range`, `$$__range_s`, `$$__interval`, `$$myvar`, `$$__all`.
- **Never put a single `$` immediately before `{`, `{{`, or `(`.** envsubst tries to parse it as a variable name and **the entire `grafana` Kustomization fails postBuild → no dashboard updates apply at all** (not just the bad panel). This bit us via a literal `${{.attributes_cost_usd}}` in a Loki `line_format`. Don't put a literal `$` in titles / `line_format` / text panels — write `USD`.
- **Pre-commit gate:** `grep -rnP '(?<!\$)\$[{(]' dashboards/claude-code-*.yaml` must print nothing.
- The `grafana` ks also `dependsOn` `grafana-db`; if that CNPG DB is unhealthy the ks won't reconcile and **nothing** updates — check `kubectl get kustomization -n observability grafana`.

**LogQL (Loki):**
- Event fields are nested under `attributes.*`. For aggregation/`unwrap`/`quantile` use **explicit** extraction `| json field="attributes.field"`, then use `field`. **Never bare `| json` for aggregation** (cardinality explosion breaks quantile/unwrap). Bare `| json` is fine for display-only `logs` panels.
- `clamp_min` and most Prometheus functions are **invalid in LogQL** (query error). `vector(0)` **is** valid in Loki.

**Claude Code metrics (Prometheus, cumulative counters → `increase()`/`rate()`):**
- `claude_code_token_usage_tokens_total{type=input|output|cacheRead|cacheCreation, model, query_source, session_id, ...}`, `claude_code_cost_usage_USD_total` (same labels minus `type`), `claude_code_active_time_seconds_total{type=user|cli}`, `claude_code_session_count_total{start_type, session_id}`, `claude_code_{lines_of_code,commit,pull_request}_count_total`, `claude_code_code_edit_tool_decision_total{decision}`.
- **`session_id` is on every metric** → `sum(increase(claude_code_session_count_total))` is always ~0. Count sessions with `count(count by (session_id)(max_over_time(claude_code_session_count_total[$$__range])))`.
- Cost is an **estimate** (token × API list price); on a Pro/Max subscription it is notional, not real spend — label panels accordingly.

**Panel hygiene:**
- Multi-series panels (timeseries / bargauge / table): **do not** append `or vector(0)` — it creates a phantom `Value=0` series. Only `stat` panels use `or vector(0)`.
- Calendar **month-to-date**: set dashboard `time: {from: now/M, to: now}` → `$$__range` is MTD, days elapsed = `$$__range_s/86400`, full-month projection = `(<expr over $$__range>) * $$days_in_month * 86400 / $$__range_s`.

**Many near-identical series (e.g. an N-provider cost comparison):** generate the dashboard JSON from a small Python rate-table generator rather than hand-writing — far less error-prone, trivial to re-run when rates change. Table panel: two instant queries + a `merge` transform joins them by shared label into `Value #A` / `Value #B` columns; embed reference values (e.g. rates) directly in the series `label_replace` name to avoid extra columns.

**Validation gate before every commit:** JSON parses (`json.loads(yaml.safe_load(f)['spec']['json'])`) → the `envsubst` grep above is empty → `mise exec -- kustomize build kubernetes/apps/observability/grafana/app` → live smoke-test a couple of queries via the read-only Grafana MCP (`query_prometheus` / `query_loki_logs`).

## Don't
- Don't omit `editable: true` on datasources (operator may treat them read-only and reject updates).
- Don't edit dashboards in the Grafana UI expecting them to persist — they're reverted.
