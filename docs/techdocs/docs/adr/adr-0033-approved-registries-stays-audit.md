# `require-approved-registries` stays Audit

* Status: accepted
* Date: 2026-07-02

Technical Story: [RFC: Kyverno audit→enforce hardening](../rfc/rfc-kyverno-audit-enforce-hardening.md)

## Context and Problem Statement

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
([ADR-0023](adr-0023-harbor-pull-through-proxy-cache.md)/[ADR-0024](adr-0024-registry-mirror-talos-spegel.md)).
What remains unbuilt is the admission-side path below. This decision is distinct from
`require-image-digest` (digest-pinning), which is achievable without a Harbor SPOF and is promoted
on its own track.

## Considered Options

* Stay Audit indefinitely; enforce (if ever) only via a two-phase mutate-then-scope path
* Enforce now and accept breakage
* Hand-edit every manifest to Harbor proxy paths, then enforce
* Drop the rule entirely

## Decision Outcome

Chosen option: "Stay Audit indefinitely; enforce (if ever) only via a two-phase mutate-then-scope
path", because flipping to Enforce cluster-wide is a guaranteed full-cluster admission outage,
even a *satisfiable* Enforce makes Harbor a pull-time single point of failure, and Audit keeps the
drift signal at zero operational risk.

`require-approved-registries` **stays Audit indefinitely** as a drift/visibility signal,
explicitly excluded from the enforce campaign. If it is ever enforced, only via a two-phase path —
the plan of record, never a flip:

1. Add a Kyverno **mutate** policy that rewrites known upstream prefixes to the Harbor proxy path
   at admission — images become compliant transparently, with no fleet-wide manifest edits.
2. Only after the mutate path is proven and Harbor availability is acceptable, scope the validate
   rule to Enforce via `validationFailureActionOverrides` in one low-risk namespace, watch, then
   expand.

### Positive Consequences

* Registry-approval stays advisory; the cluster gains no hard Harbor pull-time dependency at
  admission.

### Negative Consequences

* The FAILs persist in PolicyReports as intended drift signal; `slo-kyverno-fail-total`'s threshold
  and the campaign burn-down account for them.
* Enforcing later is contingent on the mutate-rewrite policy and proven Harbor availability, not on
  this campaign.

## Pros and Cons of the Options

### Stay Audit indefinitely; enforce (if ever) only via a two-phase mutate-then-scope path

* Good, because the cluster gains no hard Harbor pull-time dependency at admission.
* Good, because Audit keeps the registry-sovereignty drift signal at zero operational risk.
* Bad, because the FAILs persist in PolicyReports; `slo-kyverno-fail-total`'s threshold and the
  campaign burn-down account for them.

### Enforce now and accept breakage

* Bad, because a self-inflicted cluster outage.

### Hand-edit every manifest to Harbor proxy paths, then enforce

* Bad, because a large ongoing maintenance burden, and still a pull-time Harbor SPOF at admission.

### Drop the rule entirely

* Bad, because it loses the signal of how far from registry-sovereign the cluster is; Audit keeps
  that signal at zero operational risk.

## Links

* 2026-06-21 — proposed; the policy runs with `validationFailureAction: Audit`
* 2026-06-23 — the mirroring prerequisite shipped: Harbor pull-through proxy cache + Talos-layer
  mirror accepted (ADR-0023/0017); the mutate-rewrite admission path remains unbuilt
* 2026-07-02 — accepted (status corrected in ADR audit): in effect as decided — the rule still runs
  Audit
* 2026-07-03 — renumbered from ADR-0034 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
