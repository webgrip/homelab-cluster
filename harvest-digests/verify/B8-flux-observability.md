## Flux / HelmRelease drift

### spegel is the only HR that perpetually shows DriftDetected — root cause + fix (not yet applied)
- **Type:** FACT · **Confidence:** HIGH (cause [VERIFIED]; fix still unapplied — repo confirms no per-HR ignore block in spegel yet)
- **What:** A global Flux patch sets `driftDetection.mode: warn` on EVERY HelmRelease (`kubernetes/flux/cluster/ks.yaml:~42`) — detect+log only, never remediate (avoids fighting Kyverno mutate webhooks). spegel is the only HR that drifts: its chart renders a DaemonSet omitting fields the API server then defaults — `spec.revisionHistoryLimit: 10`, `spec.updateStrategy.rollingUpdate.maxSurge: 0`, plus a third server-default — logged every reconcile, never converges. Benign noise on the FluxResourceDriftDetected alert.
- **Snippet (proposed per-HR fix):** `driftDetection: { mode: warn, ignore: [{ target: {kind: DaemonSet}, paths: [/spec/revisionHistoryLimit, /spec/updateStrategy] }] }`
- **Sources:** batch 4 (Talos upgrade digest)

---

## Grafana / observability / alerting

### Grafana threshold alert rules silently error without a top-level `expression:` — broke all 16 SLO rules for ~3 weeks
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] via throwaway MCP rule)
- **What:** A `GrafanaAlertRuleGroup` SSE chain (Prometheus query node + a `type: threshold` node) errors every evaluation (`[sse.parseError] failed to parse expression [threshold]: no variable specified to reference for refId threshold`) unless the threshold node's model includes `expression: <input-refId>` (the bare refId string, e.g. `query` — NOT `$query`, NOT `A`). The legacy `conditions[].query.params:[query]` is not sufficient. `kubeconform` and `flux-local build` do NOT catch it (the operator CRD is preserve-unknown-fields). Two rules with `execErrState: Alerting` produced false critical pages; the other 14 errored silently. Now guarded by `scripts/validate_grafana_alert_expr.py` (stdlib text linter) wired into `e2e.yaml` + `run-flux-local-test.sh` + ADR-0030.
- **Snippet:** `model: { refId: threshold, type: threshold, expression: query, datasource: {uid: "-100", type: __expr__} }`
- **Sources:** batch 2 (copy 8)

### Pre-flight a Grafana alert-rule shape with a throwaway MCP rule before mass-editing
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** Before editing many rules, `alerting_manage_rules` (op `create`) one throwaway rule, confirm `health != error`, delete it — validates exact SSE syntax against the live Grafana version without touching GitOps rules. After committing, verify via list `states:["error"]` (expect empty). Render-time validation (kubeconform/flux-local) cannot catch SSE model errors; live rule-health re-query is the only acceptance test.
- **Sources:** batch 2 (copy 8)

### PromQL anti-patterns: `count()` over a boolean gauge counts nodes; empty filtered set returns NoData not 0
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] — fixed across ~13 rules; flux-local passed)
- **What:** (1) `kube_node_status_condition{condition="MemoryPressure",status="true"}` emits one 0/1 series per node, so `count(...)` returns ~5 (node count) regardless of actual pressure → permanent false critical; use `sum(...)` (sums the 0/1 values). Same for any `kube_*_status_condition`/boolean gauge. (2) `count(up == 0)`, `count(flux_resource_info{ready="False"})`, etc. return an empty vector when healthy → the rule sits `health: nodata` (indistinguishable from a broken pipeline) instead of 0/Normal; append `or vector(0)` — EXCEPT rules whose `noDataState: Alerting` is intentional (a "metrics-stale" detector / "watch-the-watchers" meta-rule, where NoData must page).
- **Snippet:** `sum(kube_node_status_condition{condition="MemoryPressure",status="true"})`; `count(up == 0) or vector(0)`
- **Sources:** batch 2 (copy 8)

### Operator-managed Grafana ServiceMonitor needs the `release` label AND the operator's actual selector labels
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** For kube-prometheus-stack to scrape the grafana-operator-managed Grafana, the ServiceMonitor must (1) carry `metadata.labels.release: kube-prometheus-stack`, and (2) `spec.selector.matchLabels` must match the operator's actual Service labels: `app.kubernetes.io/managed-by: grafana-operator` + `grafana.internal/instance: grafana` (NOT `app.kubernetes.io/name: grafana`). Missing either → `grafana_alerting_*` never scraped → a "watch-the-watchers" rule sits NoData forever (the blind spot that hid the 3-week outage).
- **Sources:** batch 2 (copy 8)

### The cluster runs TWO independent alert engines with no unified view
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** (1) Grafana-managed SLO rules (`GrafanaAlertRuleGroup` CRDs under `grafana/app/alerting/{slo-platform,slo-security,slo-observability}.yaml`) — `grafana.${SECRET_DOMAIN}/alerting/list`. (2) Prometheus-native (kube-prometheus-stack + Sloth `PrometheusServiceLevel` + custom `PrometheusRule`) — `alertmanager.${SECRET_DOMAIN}` / `prometheus.${SECRET_DOMAIN}/alerts`. Some conditions were alerted by BOTH (DT critical/policy/risk rules); resolved by keeping the Grafana SLO rules and dropping the `PrometheusRule` dupes. No dashboard unifies both engines.
- **Snippet:** `ALERTS{alertstate="firing"}` (Prom) vs `alerting_manage_rules list states:["firing"]` (Grafana)
- **Sources:** batch 2 (copy 8)

### Trivy/Dependency-Track "supply-chain" numbers are whole-fleet third-party scans, NOT your images
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] — live `dt_portfolio_projects{state="total"}=159`)
- **What:** A `trivy-sbom-uploader` CronJob (Sundays 02:00) Trivy-scans all running cluster images and uploads CycloneDX SBOMs to DT, auto-populating 159 projects = every upstream third-party image (postgres, cilium, longhorn, grafana, alpine…); `trivy-operator` scans all running pod images registry-agnostically (no Harbor, no first-party SBOM). So "63 critical CVEs / 2332 policy fails / risk 5961" are about upstream images (fixed by version bumps/Renovate), NOT the user's build artifacts (only `ghcr.io/webgrip/github-runner` is genuinely first-party). Relatedly, `TrivyExposedSecretsDetected` matches `severity=~"Critical|High|Medium"` but carries `labels.severity: critical` — a Medium/High base-image finding pages as critical (the 2 firing were High in stock postgres/backup images, near-certain false positives). Verify the `ExposedSecretReport` CR before treating as a real leak.
- **Sources:** batch 2 (copy 8)

### Sloth burn-rate / synthetic alerts linger after recovery; disable alerts/SLOs in lock-step with their workload
- **Type:** FACT + DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** Multi-window burn-rate SLO alerts (Sloth `PrometheusServiceLevel`, fed by blackbox `probe_success`) keep firing after the endpoint recovers because the burned error budget is still in the long window — check `probe_success` current value before treating as a live outage. k6-operator/k6-canaries were suspended but `K6CanaryMetricsMissing` + `slo-synthetic-k6-canary` were left active and fired forever — comment them out too (with a note pointing back to the k6 suspension so re-enabling re-enables both); kept `slo-synthetic-availability` (independent of k6).
- **Sources:** batch 2 (copy 8)

### Bootstrap Jobs/CronJobs need explicit worker pinning; etcd fragmentation is double-alerted
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** `AppsTierWorkloadSpilledToControlPlane` excludes `.*-(runner|metrics-exporter|sbom-uploader|policy-bootstrap)-.*` but NOT provisioner/CronJob bootstrap pods — stateless forgejo bootstrap Jobs had no nodeSelector and scheduled onto a soyo (fired on `forgejo-ci-provisioner-*` + `forgejo-actions-secrets-*`). Fix = add `nodeSelector: { node.webgrip.io/pool: worker }` to their pod specs (ADR-0028; the `components/placement/worker-pool` component patches Deployments/StatefulSets/CNPG, NOT bare Jobs). Separately, etcd boltdb fragmentation is double-alerted (`EtcdDbHighFragmentationRatio` custom + stock `etcdDatabaseHighFragmentationRatio`) ×3 members — remediation is owner-run `talosctl etcd defrag` (one member at a time, leader last; gating prerequisite for re-enabling pyroscope).
- **Sources:** batch 2 (copy 8)

### Live alert/SLO read surfaces, dashboard UIDs, validators
- **Type:** REFERENCE · **Confidence:** HIGH ([VERIFIED])
- **What:** Aggregate views: `grafana.${SECRET_DOMAIN}/alerting/list`, `alertmanager.${SECRET_DOMAIN}`, `prometheus.${SECRET_DOMAIN}/alerts`. Dashboards (`/d/<uid>`): security-overview, security-trivy-sbom, dt-supply-chain-001, kyverno-violations, kyverno-policy-insights, platform-etcd, obs-stack-overview, talos-node-health. New validators: `scripts/validate_grafana_alert_expr.py`, `scripts/check-kyverno-test-coverage.sh`, both wired into `e2e.yaml` (mirror the dependency-free `scripts/validate_alert_annotations.py` pattern).
- **Sources:** batch 2 (copy 8)

---

## Observability — Forgejo/CI metrics & logs; MCP

### Forgejo exports NO Actions/CI metrics; runner logs are NOT in Loki
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED] — queried live)
- **What:** `/metrics` exposes only `gitea_*` count gauges (accesses, attachments, issues, repositories, releases, users, webhooks…) — no run-duration/job-timing/task-status. A CI build-duration/cache-hit dashboard is NOT possible from native metrics — it needs a custom Forgejo-Actions-API exporter. Loki here uses OTel-style labels (`service_name, service_namespace, deployment_environment, …`), not `namespace/pod/container`, so runner job logs don't appear in Loki — "where does the job time go" must come from Prometheus container metrics or the Forgejo UI, not LogQL.
- **Sources:** batches 1 (copy 13, copy 16)

### Query per-job resource peaks without a Prometheus series explosion; MCP UIDs
- **Type:** PROCEDURE + REFERENCE · **Confidence:** HIGH ([VERIFIED])
- **What:** Ephemeral pods create one series per pod, so a 7-day un-aggregated subquery over `forgejo-runner.*` overflows the MCP result — collapse with an outer aggregator (`quantile`/`max` over a `max_over_time(rate(...)[7d:3m])` subquery); a 3-min rate window smooths sub-minute bursts. Grafana MCP datasource UIDs are literally `prometheus` (default) + `loki`; `query_prometheus` requires `datasourceUid`. The in-cluster kubernetes MCP runs as `system:serviceaccount:observability:k8s-mcp-kubernetes-mcp-server` (view-scoped — listing nodes is forbidden; get node data via Prometheus `kube_node_status_allocatable`). When the grafana + kubernetes MCP servers (in-cluster, LAN-only) time out together (a brief LAN/ingress blip — ≠ cluster down), confirm via `kubectl get --raw '/readyz'` and read Prometheus alerts directly (`kubectl exec ... prometheus -- wget -qO- 'http://localhost:9090/api/v1/alerts'`; Grafana-managed SLO rule states are NOT in Prometheus and unavailable this way).
- **Snippet:** `quantile(0.95, max_over_time(rate(container_cpu_usage_seconds_total{namespace="forgejo",pod=~"forgejo-runner.*",container="runner"}[3m])[7d:3m]))`
- **Sources:** batches 1 (copy 16), 2 (copy 8)

---
