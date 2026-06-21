# RFC: Observability alerting reliability

> Status: **Accepted** · Date: 2026-06-21 · Umbrella for [ADR-0030](../adr/adr-0030-grafana-threshold-rule-shape.md), [ADR-0031](../adr/adr-0031-meta-monitoring-alert-rule-health.md)

> **TL;DR.** The cluster's primary alerting layer — the 16 Grafana SLO alert rules — **silently
> errored on every evaluation for ~3 weeks** (2026-05-30 → 2026-06-21) and nobody noticed,
> because (a) each rule's server-side-expression (SSE) `threshold` node was missing the
> `expression:` field, and (b) Grafana's own `/metrics` were never scraped, so there was no
> signal that the watchers were down. This RFC makes alerting reliability a first-class concern:
> standardize + lint the rule shape, monitor the alerting system itself, and adopt a rule-health
> re-query as the acceptance test for any alert-rule change.

## Why

A routine cluster review on 2026-06-21 found two SLO alerts "firing" (cert-expiry-3d,
dt-exporter-stale). Both were **false positives** — direct Prometheus queries showed 0 certs
expiring and a fresh DT exporter. The rules were not evaluating their data at all. Every one of
the 16 `GrafanaAlertRuleGroup` rules reported `health: error` with:

```
[sse.parseError] failed to parse expression [threshold]:
no variable specified to reference for refId threshold
```

The `threshold` SSE node carried `type: threshold` + `conditions[].query.params: [query]` but
**no top-level `expression:`** pointing at the input query refId. Grafana's SSE engine had no
input to feed the threshold comparator, so it errored. Two rules had `execErrState: Alerting`
(→ false-positive page); the other fourteen had `execErrState: Error` and went silently to an
Error state that nothing surfaced. `activeAt` traced the breakage to 2026-05-30.

This passed every gate. kubeconform and the Grafana operator CRD treat `rules[].data[].model`
as a preserve-unknown-fields blob — they cannot validate model internals, so the broken files
rendered and reconciled cleanly for three weeks.

The deeper failure is the **silence**. There was no monitoring of the monitoring. The root cause
of *that*: the `ServiceMonitor/grafana` was never selected by Prometheus — it lacked the
`release: kube-prometheus-stack` label kube-prometheus-stack's `serviceMonitorSelector` requires,
*and* its `.spec.selector` did not match the operator-created Service labels. So no
`grafana_alerting_*` metric ever reached Prometheus; even a "watch the watchers" rule would have
sat in `NoData` forever.

Verified during triage: **every underlying metric the 16 rules query exists and returns data**
(`certmanager_certificate_expiration_timestamp_seconds`, `flux_resource_info` = 190 series, `up`,
`kube_node_status_condition`, `policy_report_result` = 4336 series / 108 fails, `dt_portfolio_*` +
`dt_exporter_last_scrape_timestamp`). So the fix is purely the rule shape — no exporters or
datasources are missing.

## Proposal

Three moves, realized by the two ADRs below.

1. **Fix + standardize the rule shape (ADR-0030).** Add `expression: query` to all 16 threshold
   models (the bare input refId, confirmed against the live Grafana via a throwaway rule). Then
   prevent recurrence with a dependency-free lint
   ([`scripts/validate_grafana_alert_expr.py`](../../../../scripts/validate_grafana_alert_expr.py))
   that fails CI if any `type: {threshold,math,reduce}` SSE node lacks a sibling `expression:`.
   Wired into `e2e.yaml` and `run-flux-local-test.sh`.

2. **Monitor the alerting system itself (ADR-0031).** Fix the `ServiceMonitor/grafana` so
   Prometheus scrapes Grafana `/metrics`, then add a meta-rule
   `slo-grafana-alert-rule-eval-failing` on `grafana_alerting_rule_evaluation_failures_total`
   with `noDataState`/`execErrState: Alerting` — a blind watcher must page, never go quiet.

3. **Acceptance test = rule-health re-query.** Any change to alert rules is validated by
   re-querying rule health through the read-only Grafana MCP (`alerting_manage_rules list
   states:["error"]` must be empty; a rule whose data exceeds threshold must transition to
   firing). Render-time validation (kubeconform/flux-local) is necessary but insufficient — it
   is exactly what missed this bug.

## Decisions

| ADR | Status | Decision |
|-----|--------|----------|
| [ADR-0030](../adr/adr-0030-grafana-threshold-rule-shape.md) | Accepted | Canonical Grafana threshold-rule shape (`expression: <refId>`) + a dependency-free lint guard in CI and flux-local. |
| [ADR-0031](../adr/adr-0031-meta-monitoring-alert-rule-health.md) | Accepted | Fix the Grafana ServiceMonitor scrape + add a page-on-failure meta-rule for alert-rule evaluation health. |

## Out of scope

- The Sloth burn-rate SLOs (`PrometheusServiceLevel`) are a separate, working system and are
  unaffected. Per-app Sloth SLOs remain a roadmap item.
- Alert *routing*/contact-point coverage (who gets paged) is not changed here.
