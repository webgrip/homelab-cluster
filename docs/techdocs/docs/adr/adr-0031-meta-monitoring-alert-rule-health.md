# ADR-0031: Meta-monitoring of Grafana alert-rule health

> Status: **Accepted** · Date: 2026-06-21 · Part of [RFC: Observability alerting reliability](../rfc/rfc-observability-alerting-reliability.md)

## Context

The 16 SLO rules errored for ~3 weeks (see [ADR-0030](adr-0030-grafana-threshold-rule-shape.md))
and **nothing alerted on it** — there was no monitoring of the monitoring. Two layers were wrong:

1. **Grafana `/metrics` were never scraped.**
   [`ServiceMonitor/grafana`](../../../../kubernetes/apps/observability/grafana/app/servicemonitor.yaml)
   lacked the `release: kube-prometheus-stack` label that kube-prometheus-stack's
   `serviceMonitorSelector` requires, so Prometheus never loaded the ServiceMonitor at all.
   Separately, its `.spec.selector` matched `app.kubernetes.io/name: grafana`, a label the
   operator-created Service does not carry. Result: zero `grafana_alerting_*` series in
   Prometheus — only `grafana_operator_*` (a different target).

2. **No watcher rule existed.** Even once metrics flow, an evaluation-failure alert had to be
   added. Note the existing `slo-grafana-operator-recon-fail` watches *operator reconcile*
   failures (CR sync) — a different signal that does **not** catch per-rule evaluation errors,
   which is exactly what slipped through.

## Decision

1. **Fix the scrape.** Add `release: kube-prometheus-stack` to the ServiceMonitor's metadata
   labels and change `.spec.selector` to the labels the operator's Service actually carries
   (`app.kubernetes.io/managed-by: grafana-operator` + `grafana.internal/instance: grafana`); the
   endpoint `port: grafana` was already correct.

2. **Add a page-on-failure meta-rule.** `slo-grafana-alert-rule-eval-failing` in the
   `slo-observability` group, on
   `sum(increase(grafana_alerting_rule_evaluation_failures_total[10m])) > 0`, `for: 10m`, with
   **`noDataState: Alerting` and `execErrState: Alerting`** — a watcher that itself loses data or
   errors must page, not go silent. It uses the canonical `expression: query` shape from ADR-0030
   so it cannot reproduce the bug it watches for.

## Consequences

- The alerting layer now self-monitors: a future broken rule (any `sse.parseError`, bad
  datasource, etc.) pages within ~10 minutes instead of failing silently for weeks.
- One additional Prometheus scrape target (Grafana `/metrics`) and one always-on critical rule.
- Because the meta-rule pages on `NoData`, a Grafana/Prometheus scrape outage will also page —
  intended: "I can't tell if alerting works" is itself actionable.
- The `release:` label requirement is now load-bearing; the `[observability] ServiceMonitor
  missing release label` skill guard already enforces it on edit.

## Alternatives considered

- **Rely on `slo-grafana-operator-recon-fail`** — it catches operator CR-sync failures, not rule
  *evaluation* errors; the 3-week outage proves that gap. Rejected.
- **Blackbox/external uptime probe of Grafana** — confirms Grafana is up, says nothing about
  whether individual rules evaluate. Complementary at best. Rejected as the primary control.
- **Page only on `execErrState`, keep `noDataState: OK`** — would let a scrape outage silence the
  watcher, recreating the blind spot. Rejected in favour of page-on-NoData.
