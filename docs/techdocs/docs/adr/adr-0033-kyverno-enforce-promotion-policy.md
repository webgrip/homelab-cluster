# ADR-0033: Gated Kyverno audit→enforce promotion + mandatory test coverage

> Status: **Accepted** · Date: 2026-06-21 · Part of [RFC: Kyverno audit→enforce hardening](../rfc/rfc-kyverno-audit-enforce-hardening.md)

## Context

Most Kyverno ClusterPolicies ran in `Audit` with a large unenforced FAIL backlog (~110 findings at
proposal time). Moving to *enforce-not-observe* is the goal, but a careless flip blocks legitimate
workloads at admission. Two mechanics make this sharp:

- **Autogen duality** — each Pod policy emits a base `<rule>` finding **and** an `autogen-<rule>`
  finding; a waiver must cover both or admission still blocks (the most common self-inflicted
  outage).
- **No per-rule action on a ClusterPolicy.** The levers are: whole-policy
  `validationFailureAction: Enforce`; `validationFailureActionOverrides` (per-namespace); splitting
  a policy into `-enforce` (clean rules) + `-audit` (not-yet-clean rules); or per-rule
  `failureAction: Audit` to keep individual rules observe-only inside an Enforce policy.

A latent gap made this riskier: `scripts/lib/kyverno-tests.sh` hardcoded a policy allowlist that
omitted six policies — they could reach Enforce with **zero** CLI test coverage while CI stayed
green.

## Decision

1. **Promote in gated waves, one policy/rule-group per commit.** Per-wave gate: clean PolicyReport
   for the promoted rules (base **and** autogen = 0 unwaived) for ≥1 reconcile cycle → CLI/chainsaw
   test added → `mise exec -- just kyverno-test` + `run-flux-local-test.sh` green → flip → watch
   one admission cycle. Space waves apart. The wave order and prerequisites live in the RFC.

2. **Standardize the mechanism** on the policy split + `validationFailureActionOverrides`, never a
   hand-rolled per-rule action. The `-enforce`/`-audit` file split is live under
   [`kubernetes/apps/kyverno/policies/app/`](../../../../kubernetes/apps/kyverno/policies/app).

3. **Make test coverage load-bearing.** `scripts/lib/kyverno-tests.sh` discovers every policy +
   exception by kind (no allowlist);
   [`scripts/check-kyverno-test-coverage.sh`](../../../../scripts/check-kyverno-test-coverage.sh)
   (wired into `e2e.yaml`) fails CI if an enforcing policy isn't exercised by a CLI test with a
   `fail` case (pass-case advisory for now). The pre-existing untested `storage-cnpg-governance` is
   baselined as debt to burn down, not a place to add new policies.

## Alternatives considered

- **Big-bang flip of all audit policies to Enforce** — guaranteed multi-namespace admission outage
  (`require-approved-registries` alone would block most of the fleet). Rejected.
- **Keep everything in Audit** — no enforcement value; the backlog only grows. Rejected.
- **Per-promotion ADRs (10+)** — noise; most promotions are routine applications of this decision.
  Reserved for the genuinely contentious call
  ([ADR-0034](adr-0034-approved-registries-stays-audit.md)).
- **Require both pass and fail cases immediately** — would retroactively fail four existing enforce
  suites that predate pass-cases. Deferred to a future tightening.

## Consequences

- Promotion is slower but each step is reversible and proven; the CI gate physically blocks an
  Enforce flip that lacks a test.
- Remediation campaigns (probe sweep, digest-pinning, label sweeps, Role narrowing) become explicit
  wave prerequisites.
- The test harness stays in lock-step with the policies on disk; a new policy can't hide from the
  runner. `storage-cnpg-governance` carries a visible coverage-debt marker until its test exists.

## Status log

- 2026-06-21 — Proposed; the mechanism shipped in the same commit (701b6691): discovery-based test
  lib, `check-kyverno-test-coverage.sh` gate in `e2e.yaml`, first `-enforce`/`-audit` splits.
- 2026-07-02 — Accepted (status corrected in ADR audit): the gate is live in CI and the split is
  the operating mechanism; promotion waves are ongoing — most policies still run Audit.
