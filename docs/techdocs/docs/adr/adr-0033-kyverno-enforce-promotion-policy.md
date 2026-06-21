# ADR-0033: Gated Kyverno audit→enforce promotion + mandatory test coverage

> Status: **Proposed** · Date: 2026-06-21 · Part of [RFC: Kyverno audit→enforce hardening](../rfc/rfc-kyverno-audit-enforce-hardening.md)

## Context

11 Kyverno ClusterPolicies run in `Audit`; ~108–114 resources FAIL unenforced. Moving to
*enforce-not-observe* is the goal, but a careless flip blocks legitimate workloads at admission —
the cluster's standing discipline (the `kyverno-policy` skill) is to promote one at a time after a
clean PolicyReport. Two mechanics make this sharp:

- **Autogen duality** — each Pod policy emits a base `<rule>` finding and an `autogen-<rule>`
  finding; a waiver must cover both or admission still blocks (the most common self-inflicted
  outage).
- **No per-rule action** on a ClusterPolicy. The levers are: whole-policy
  `validationFailureAction: Enforce`, `validationFailureActionOverrides` (per-namespace), or
  splitting a policy into `-enforce` (clean rules) + `-audit` (not-yet-clean rules). Per-rule
  `failureAction: Audit` keeps individual rules observe-only inside an Enforce policy.

A latent gap made this riskier: `scripts/lib/kyverno-tests.sh` hardcoded a policy allowlist that
omitted six policies, so they could be promoted to Enforce with **zero** CLI test coverage while CI
stayed green.

## Decision

1. **Promote in gated waves, one policy/rule-group per commit.** Per-wave gate: clean PolicyReport
   for the promoted rules (base **and** autogen = 0 unwaived) for ≥1 reconcile cycle → CLI/chainsaw
   test added → `mise exec -- just kyverno-test` + `run-flux-local-test.sh` green → flip → watch one
   admission cycle. Space waves apart (batched-rollout storage-collapse memory). The 14-wave order
   and prerequisites are in the RFC.

2. **Standardize the mechanism** on policy-split + `validationFailureActionOverrides`, never a
   hand-rolled per-rule action. `workload-hardening` starts namespace-scoped via overrides and
   expands; `image-supply-chain`, `rbac-least-privilege`, `workload-advanced-hardening`,
   `secrets-observability-ops`, `image-verify` are split (clean rules enforce now, the rest stay
   Audit pending remediation).

3. **Make test coverage load-bearing.** `scripts/lib/kyverno-tests.sh` now discovers every policy +
   exception by kind (no allowlist). `scripts/check-kyverno-test-coverage.sh` (wired into
   `e2e.yaml`) fails CI if an enforcing policy isn't exercised by a CLI test with a `fail` case
   (pass-case advisory for now). Pre-existing untested `storage-cnpg-governance` is baselined as
   debt to burn down (roadmap #83), not a place to add new policies.

## Consequences

- Promotion is slower but each step is reversible and proven; the CI gate physically blocks an
  Enforce flip that lacks a test.
- Remediation campaigns become explicit prerequisites: probe sweep, image digest-pinning,
  PrometheusRule label sweep, wildcard-Role narrowing — each gates its wave.
- The test harness now stays in lock-step with the policies on disk; a new policy can't hide from
  the test runner.
- `storage-cnpg-governance` carries a visible coverage-debt marker until a CLI test is written.

## Alternatives considered

- **Big-bang flip of all audit policies to Enforce** — guaranteed multi-namespace admission outage
  (e.g. `require-approved-registries` alone blocks nearly the whole fleet). Rejected.
- **Keep everything in Audit** — no enforcement value; the backlog only grows. Rejected.
- **Per-promotion ADRs (10+)** — noise; most promotions are routine applications of this one
  decision. Reserved ADRs for the genuinely contentious call ([ADR-0034](adr-0034-approved-registries-stays-audit.md)).
- **A stricter gate requiring both pass and fail cases immediately** — would retroactively fail four
  existing enforce policies whose suites predate pass-cases. Deferred to a future tightening;
  pass-case is advisory now.
