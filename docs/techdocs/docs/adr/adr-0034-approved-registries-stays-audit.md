# ADR-0034: `require-approved-registries` stays Audit

> Status: **Accepted** · Date: 2026-06-21 · Part of [RFC: Kyverno audit→enforce hardening](../rfc/rfc-kyverno-audit-enforce-hardening.md)

## Context

`require-approved-registries` (in
[`image-supply-chain-audit.yaml`](../../../../kubernetes/apps/kyverno/policies/app/image-supply-chain-audit.yaml))
requires every container image to come from `harbor.${SECRET_DOMAIN}/*`. It is the single largest
FAIL source (~103 findings at proposal time): essentially every upstream
`docker.io`/`ghcr.io`/`registry.k8s.io` image violates it. Flipping it to Enforce cluster-wide is a
guaranteed full-cluster admission outage, and even a *satisfiable* Enforce makes Harbor a
**pull-time single point of failure** — the same failure class as the CNPG↔Garage WAL SPOF that
has already caused SEVs here.

The mirroring prerequisite has since shipped: Harbor pull-through proxy projects cover the
upstream registries in use
([ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md)/[ADR-0017](adr-0017-registry-mirror-talos-spegel.md)).
What remains unbuilt is the admission-side path below. This decision is distinct from
`require-image-digest` (digest-pinning), which is achievable without a Harbor SPOF and is promoted
on its own track.

## Decision

`require-approved-registries` **stays Audit indefinitely** as a drift/visibility signal,
explicitly excluded from the enforce campaign. If it is ever enforced, only via a two-phase path —
the plan of record, never a flip:

1. Add a Kyverno **mutate** policy that rewrites known upstream prefixes to the Harbor proxy path
   at admission — images become compliant transparently, with no fleet-wide manifest edits.
2. Only after the mutate path is proven and Harbor availability is acceptable, scope the validate
   rule to Enforce via `validationFailureActionOverrides` in one low-risk namespace, watch, then
   expand.

## Alternatives considered

- **Enforce now and accept breakage** — a self-inflicted cluster outage. Rejected.
- **Hand-edit every manifest to Harbor proxy paths, then enforce** — a large ongoing maintenance
  burden, and still a pull-time Harbor SPOF at admission. Rejected.
- **Drop the rule entirely** — loses the signal of how far from registry-sovereign the cluster is;
  Audit keeps that signal at zero operational risk. Rejected.

## Consequences

- Registry-approval stays advisory; the cluster gains no hard Harbor pull-time dependency at
  admission.
- The FAILs persist in PolicyReports as intended drift signal; `slo-kyverno-fail-total`'s threshold
  and the campaign burn-down account for them.
- Enforcing later is contingent on the mutate-rewrite policy and proven Harbor availability, not on
  this campaign.

## Status log

- 2026-06-21 — Proposed; the policy runs with `validationFailureAction: Audit`.
- 2026-06-23 — The mirroring prerequisite shipped: Harbor pull-through proxy cache + Talos-layer
  mirror accepted (ADR-0016/0017); the mutate-rewrite admission path remains unbuilt.
- 2026-07-02 — Accepted (status corrected in ADR audit): in effect as decided — the rule still runs
  Audit.
