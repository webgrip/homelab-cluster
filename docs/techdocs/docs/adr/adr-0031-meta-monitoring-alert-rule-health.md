# Meta-monitoring of Grafana alert-rule health

* Status: accepted
* Date: 2026-07-01

Technical Story: [RFC: Observability alerting reliability](../rfc/rfc-observability-alerting-reliability.md)

## Context and Problem Statement

The SLO rules errored for ~3 weeks ([ADR-0030](adr-0030-grafana-threshold-rule-shape.md)) and
**nothing alerted on it** — there was no monitoring of the monitoring. Two layers were wrong:
Grafana's `/metrics` were never scraped, so zero `grafana_alerting_*` series reached the metrics
backend (the
[ServiceMonitor](../../../../kubernetes/apps/observability/grafana/app/servicemonitor.yaml) wasn't
selected by the then-current Prometheus, and its `.spec.selector` matched a label the
operator-created Service doesn't carry); and no watcher rule existed — the existing
`slo-grafana-operator-recon-fail` watches operator *reconcile* failures (CR sync), a different
signal that does not catch per-rule *evaluation* errors, which is exactly what slipped through.

## Considered Options

* Scrape Grafana's `/metrics` + a page-on-failure meta-rule
* Rely on `slo-grafana-operator-recon-fail`
* Blackbox/external uptime probe of Grafana
* Page only on `execErrState`, keep `noDataState: OK`

## Decision Outcome

Chosen option: "Scrape Grafana's `/metrics` + a page-on-failure meta-rule", because both broken
layers need a fix — zero `grafana_alerting_*` series reached the metrics backend and no watcher
rule existed — and a watcher that itself loses data or errors must page, not go silent.

1. **Scrape Grafana's `/metrics`.** The ServiceMonitor's `.spec.selector` matches the labels the
   operator's Service actually carries (`app.kubernetes.io/managed-by: grafana-operator` +
   `grafana.internal/instance: grafana`), endpoint `port: grafana`. Under the
   [ADR-0038](adr-0038-victoriametrics-metrics-backend.md) VictoriaMetrics backend, the vm-operator
   converts the ServiceMonitor to a `VMServiceScrape` and VMAgent selects it via
   `selectAllByDefault: true` — there is no selector-label gate to forget (the file's
   `release: kube-prometheus-stack` label is vestigial). The residual failure mode is a wrong
   Service-label or port match, which yields zero targets silently.

2. **A page-on-failure meta-rule.** `slo-grafana-alert-rule-eval-failing` in the
   `slo-observability` group, on
   `sum(increase(grafana_alerting_rule_evaluation_failures_total[10m])) > 0`, `for: 10m`, with
   **`noDataState: Alerting` and `execErrState: Alerting`** — a watcher that itself loses data or
   errors must page, not go silent. It uses the canonical `expression: query` shape from ADR-0030,
   so it cannot reproduce the bug it watches for.

### Positive Consequences

* The alerting layer self-monitors: a future broken rule (any `sse.parseError`, bad datasource,
  etc.) pages within ~10 minutes instead of failing silently for weeks.
* Because the meta-rule pages on `NoData`, a Grafana or metrics-backend scrape outage also pages —
  intended: "I can't tell if alerting works" is itself actionable.

### Negative Consequences

* One additional scrape target and one always-on critical rule.

## Pros and Cons of the Options

### Scrape Grafana's `/metrics` + a page-on-failure meta-rule

* Good, because the meta-rule uses the canonical `expression: query` shape from ADR-0030, so it
  cannot reproduce the bug it watches for.
* Bad, because one additional scrape target and one always-on critical rule.

### Rely on `slo-grafana-operator-recon-fail`

* Bad, because it catches operator CR-sync failures, not rule evaluation errors; the 3-week
  outage proves that gap.

### Blackbox/external uptime probe of Grafana

* Good, because it confirms Grafana is up.
* Bad, because it says nothing about whether individual rules evaluate — complementary at best,
  rejected as the primary control.

### Page only on `execErrState`, keep `noDataState: OK`

* Bad, because a scrape outage would silence the watcher, recreating the blind spot; rejected in
  favour of page-on-NoData.

## Links

* 2026-06-21 — accepted; scrape fixed + meta-rule shipped (217b512c). The original fix also added
  the `release: kube-prometheus-stack` label that kube-prometheus-stack's `serviceMonitorSelector`
  required at the time
* 2026-07-01 — metrics backend swapped to VictoriaMetrics
  ([ADR-0038](adr-0038-victoriametrics-metrics-backend.md)): the ServiceMonitor is now
  operator-converted and selected by `selectAllByDefault`, so the `release:` label no longer gates
  selection. The decision itself (meta-rule, page-on-NoData) is unchanged
