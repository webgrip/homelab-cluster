# ADR-0034: `require-approved-registries` stays Audit

> Status: **Proposed** · Date: 2026-06-21 · Part of [RFC: Kyverno audit→enforce hardening](../rfc/rfc-kyverno-audit-enforce-hardening.md)

## Context

`require-approved-registries` (in `image-supply-chain-audit`) requires every container image to
come from `harbor.${SECRET_DOMAIN}/*`. It is the single largest source of FAILs (~103): today
essentially nothing but first-party webgrip images satisfies it — authentik, harbor's own jobs,
keda, forgejo, and every upstream `docker.io`/`ghcr.io`/`registry.k8s.io` image violates it.

Flipping it to Enforce cluster-wide is a guaranteed full-cluster admission outage. Making it
*satisfiable* requires mirroring every upstream through Harbor as a pull-through proxy, which turns
Harbor into a **pull-time single point of failure** — the same failure class as the
CNPG↔Garage WAL SPOF that has already caused SEVs here.

This is distinct from `require-image-digest` (digest-pinning, ~25 FAILs), which is achievable
without making Harbor a SPOF and is promoted on its own track (RFC wave 11).

## Decision

`require-approved-registries` **stays Audit indefinitely** as a drift/visibility signal. It is
explicitly excluded from the enforce campaign. If it is ever enforced, only via a two-phase path,
never a flip:

1. Configure Harbor pull-through proxy projects for the upstreams actually in use, and add a
   Kyverno **mutate** policy that rewrites known upstream prefixes to the Harbor proxy path at
   admission — making images compliant transparently instead of forcing every manifest edit.
2. Only after the mutate path is proven and Harbor availability is acceptable, scope
   `require-approved-registries` to Enforce via `validationFailureActionOverrides` in one low-risk
   namespace, watch, then expand.

Digest-pinning is decoupled and pursued separately.

## Consequences

- Registry-approval remains advisory; the cluster does not gain a hard Harbor pull-time dependency
  at admission.
- The ~103 FAILs persist in PolicyReports as intended drift signal; `slo-kyverno-fail-total`
  accounts for them (its threshold and the campaign's burn-down reflect this).
- Enforcing it later is contingent on the Harbor proxy-cache work
  ([RFC: Harbor proxy cache](../rfc/rfc-harbor-proxy-cache.md)), not on this campaign.

## Alternatives considered

- **Mirror everything now + enforce** — large ongoing maintenance burden (per-upstream proxy
  projects, credentials) and makes Harbor a pull-time SPOF. Rejected for now.
- **Enforce and accept breakage** — a self-inflicted cluster outage. Rejected.
- **Drop the rule entirely** — loses the drift signal that tells us how far from registry-sovereign
  we are. Rejected; Audit keeps the signal at zero operational risk.
