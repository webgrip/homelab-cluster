# Standardize the Grafana threshold alert-rule shape + lint it

* Status: accepted
* Date: 2026-07-02

Technical Story: [RFC: Observability alerting reliability](../rfc/rfc-observability-alerting-reliability.md)

## Context and Problem Statement

Every threshold SLO rule (16 at the time) under
[`kubernetes/apps/observability/grafana/app/alerting/`](../../../../kubernetes/apps/observability/grafana/app/alerting/)
errored on every evaluation for ~3 weeks:

```text
[sse.parseError] failed to parse expression [threshold]:
no variable specified to reference for refId threshold
```

Each rule is a two-node server-side expression (SSE) chain: a Prometheus query node
(`refId: query`) feeding a threshold node. The threshold node carried its evaluator under
`conditions[]` but **omitted the top-level `expression:` key** that tells the SSE engine which
upstream refId to compare — so the threshold had no input. Two rules with
`execErrState: Alerting` produced false-positive pages; the rest went silently to Error.

This shipped because nothing validates SSE model internals: the Grafana operator CRD types
`rules[].data[].model` as a **preserve-unknown-fields object**, so kubeconform and
`flux-local build` render broken rules without complaint.

The correct value was confirmed **empirically** against the live Grafana (operator chart 5.23.0):
a throwaway rule created via the read-only-by-default Grafana MCP with `expression: query`
reported `health: ok`. The value is the **bare refId string** (`query`) — not `$query`, and not
the UI's default `A`-style naming.

## Considered Options

* Canonical `expression:` shape + a lint guard in CI
* kubeconform / CRD schema validation
* A PyYAML-based validator
* A Kyverno admission policy on the CR

## Decision Outcome

Chosen option: "Canonical `expression:` shape + a lint guard in CI", because the minimal
reversible fix is the one `expression:` line per rule, and nothing else validates SSE model
internals — the operator CRD types the model as a preserve-unknown-fields object, so kubeconform
and `flux-local build` render broken rules without complaint.

1. **Canonical shape.** A Grafana threshold rule's SSE node sets `type: threshold` **and**
   `expression: <input-refId>` (here `query`), alongside its `conditions[]` evaluator; the
   rule-level `condition:` points at the threshold node's refId. The legacy
   `conditions[].query.params: [query]` is left in place (harmless, consistent) — the minimal
   reversible fix is the one `expression:` line per rule.

2. **Lint guard.**
   [`scripts/validate_grafana_alert_expr.py`](../../../../scripts/validate_grafana_alert_expr.py)
   — stdlib-only, no YAML deps (the `validate_alert_annotations.py` house convention, so it runs
   in bare CI `python3`) — fails if any `GrafanaAlertRuleGroup` has an SSE node of `type` in
   {threshold, math, reduce} without a sibling `expression:`. Wired into
   [`.github/workflows/e2e.yaml`](../../../../.github/workflows/e2e.yaml) and
   [`scripts/run-flux-local-test.sh`](../../../../scripts/run-flux-local-test.sh).

### Positive Consequences

* The SLO rules evaluate again; validation was a rule-health re-query via the Grafana MCP, not
  just render success.
* A future rule repeating the omission fails the build with the rule uid and line number — a
  silent, weeks-long outage becomes a red CI check.

### Negative Consequences

* The lint is a text heuristic keyed on consistent indentation; it covers the
  threshold/math/reduce shapes this repo uses. A radically different hand-authored layout could
  evade it — acceptable for a shift-left guard aimed at the exact regression we hit.

## Pros and Cons of the Options

### Canonical `expression:` shape + a lint guard in CI

* Good, because the fix is minimal and reversible — one `expression:` line per rule.
* Good, because the validator is stdlib-only, no YAML deps, so it runs in bare CI `python3`.
* Bad, because the lint is a text heuristic keyed on consistent indentation — a radically
  different hand-authored layout could evade it.

### kubeconform / CRD schema validation

* Bad, because it cannot see inside the preserve-unknown-fields `model` blob; it passed the
  broken files for 3 weeks. Insufficient.

### A PyYAML-based validator

* Good, because more robust parsing.
* Bad, because PyYAML is absent from bare CI `python3` and the house convention is deliberately
  dependency-free.

### A Kyverno admission policy on the CR

* Bad, because server-side, post-commit, and parsing nested model arrays in a ClusterPolicy is
  heavy for a one-field invariant. Overkill, too late in the loop.

## Links

* 2026-06-21 — accepted; per-rule fix + lint guard shipped (217b512c)
* 2026-07-02 — unaffected by the [ADR-0038](adr-0038-victoriametrics-metrics-backend.md)
  metrics-backend swap: the rules evaluate in Grafana's SSE engine against the `prometheus`-uid
  datasource (now fronting VictoriaMetrics); the lint remains wired in CI
