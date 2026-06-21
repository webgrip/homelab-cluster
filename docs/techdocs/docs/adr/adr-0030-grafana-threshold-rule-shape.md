# ADR-0030: Standardize the Grafana threshold alert-rule shape + lint it

> Status: **Accepted** · Date: 2026-06-21 · Part of [RFC: Observability alerting reliability](../rfc/rfc-observability-alerting-reliability.md)

## Context

All 16 `GrafanaAlertRuleGroup` SLO rules (under
[`kubernetes/apps/observability/grafana/app/alerting/`](../../../../kubernetes/apps/observability/grafana/app/alerting/))
errored on every evaluation for ~3 weeks:

```
[sse.parseError] failed to parse expression [threshold]:
no variable specified to reference for refId threshold
```

Each rule is a two-node server-side expression (SSE) chain: a Prometheus query node
(`refId: query`) feeding a threshold node (`refId: threshold`, `type: threshold`). The threshold
node carried its evaluator under `conditions[]` but **omitted the top-level `expression:` key**
that tells the SSE engine which upstream refId to compare. Without it the threshold has no input
and the rule cannot evaluate. Two rules with `execErrState: Alerting` produced false-positive
pages; the rest went silently to an Error state.

This shipped because nothing validates SSE model internals: the Grafana operator CRD types
`rules[].data[].model` as a preserve-unknown-fields object, so kubeconform and `flux-local build`
render the broken rules without complaint.

The correct value was confirmed empirically against the live Grafana (operator chart 5.23.0) by
creating a throwaway rule via the read-only-by-default Grafana MCP with `expression: query`,
observing `health: ok`, then deleting it. The value is the **bare refId string** (`query`), not
`$query` and not the UI's default `A`-style naming.

## Decision

1. **Canonical shape.** A Grafana threshold rule's SSE node sets `type: threshold` **and**
   `expression: <input-refId>` (here `query`), alongside its `conditions[]` evaluator. The
   `condition:` at rule level points at the threshold node's refId. The legacy
   `conditions[].query.params: [query]` is left in place (harmless, consistent) — the minimal
   reversible fix is adding the one `expression:` line per rule.

2. **Lint guard.**
   [`scripts/validate_grafana_alert_expr.py`](../../../../scripts/validate_grafana_alert_expr.py)
   — a stdlib-only text validator (matching `validate_alert_annotations.py`, no YAML deps so it
   runs in bare CI `python3`) — fails if any `kind: GrafanaAlertRuleGroup` has an SSE node of
   `type` in {threshold, math, reduce} without a sibling `expression:`. Wired into
   [`.github/workflows/e2e.yaml`](../../../../.github/workflows/e2e.yaml) and
   [`scripts/run-flux-local-test.sh`](../../../../scripts/run-flux-local-test.sh) (the documented
   pre-commit gate).

## Consequences

- All 16 rules evaluate again; the SLO/SLA layer is functional. Validation is a rule-health
  re-query via the Grafana MCP, not just render success.
- A future rule that repeats the omission fails the build with the rule uid and line number,
  before it can ship — converting a silent, weeks-long outage into a red CI check.
- The lint is a text heuristic keyed on consistent indentation; it covers the threshold/math/
  reduce SSE shapes this repo uses. A radically different hand-authored model layout could evade
  it — acceptable for a shift-left guard whose job is catching the exact regression we hit.

## Alternatives considered

- **kubeconform / CRD schema validation** — cannot see inside the preserve-unknown-fields `model`
  blob; it passed the broken files for 3 weeks. Rejected as insufficient.
- **A PyYAML-based validator** — more robust parsing, but PyYAML is absent from the bare CI
  `python3` and the house convention (`validate_alert_annotations.py`) is deliberately
  dependency-free. Rejected to avoid a CI install step and stay consistent.
- **A Kyverno admission policy on the CR** — validates server-side, post-commit, and parsing
  nested model arrays in a ClusterPolicy is heavy for a one-field invariant. Rejected as overkill
  and too late in the loop.
