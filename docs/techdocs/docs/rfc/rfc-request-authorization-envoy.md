# RFC: Request authorization at the gateway — one policy engine for admission *and* traffic

> Status: **Proposed** · Date: 2026-08-04 · Spawned by the [Kyverno estate audit](rfc-kyverno-audit-enforce-hardening.md#audit-2026-08-04)

> **TL;DR.** Admission control in this cluster is enforce-grade — 13 enforcing policies, gated
> waves, CI coverage. **Request** authorization is not governed at all: once a pod is admitted,
> anything that can reach its HTTPRoute can call it, and per-app auth is whatever each chart
> happens to ship. Envoy Gateway **v1.8.0 is already running with the `SecurityPolicy` CRD**,
> which exposes Envoy's native `extAuth` hook, and the Kyverno project ships an authorization
> server that answers it using **CEL policies** — the same engine, language and GitOps review path
> we already use for admission. Wiring these together closes the forward-auth hole named in the
> [identity RFC](rfc-identity-sso.md) without adding per-app middleware, a service mesh, or a
> second policy language.

## Why

Verified state, 2026-08-04:

- **Envoy Gateway v1.8.0**, two gateways — `envoy-internal` (10.0.0.27, LAN) and `envoy-external`
  (10.0.0.28, public) — fronting **40 HTTPRoutes**.
- **`securitypolicies.gateway.envoyproxy.io` CRD present.** That is the supported, first-party way
  to attach `extAuth` (gRPC or HTTP) to a Gateway or a single HTTPRoute. No mesh required.
- **Authentik** is the IdP and already issues OIDC tokens for the apps that speak OIDC.
- **`network-exposure-enforce`** governs HTTPRoute *shape* — HTTPS listeners, approved hostnames,
  which routes may attach to the external gateway. It governs **exposure**, and deliberately says
  nothing about **who may call what**.

Three gaps follow:

1. **Authorization is per-app and unauditable.** Each application enforces (or doesn't) its own
   authentication in its own configuration. There is no single place to ask "which identities can
   reach this route?", no review gate on the answer, and no report when it changes. The
   admission-side equivalent of this was solved years ago here; the traffic side never was.
2. **Non-OIDC apps have no story.** The identity RFC names this explicitly. Apps that cannot speak
   OIDC are currently either exposed without authentication or not exposed. A gateway-level authz
   filter is the standard answer — it authenticates *in front of* an app that cannot do it itself.
3. **Internal-vs-external is a network fact, not an identity fact.** Attaching to
   `envoy-internal` means "reachable from the LAN", which is a coarse and increasingly weak
   boundary for a cluster hosting a forge, a registry, a secret store and a CI system. Route-level
   authorization lets exposure and authorization be decided separately.

## Proposal

Deploy the **Kyverno Authz Server** as an `extAuth` backend for Envoy Gateway, and express
request-authorization as CEL `AuthorizationPolicy` objects reviewed through the same GitOps path
as admission policy.

1. **Stand it up observe-only** (new app under `kubernetes/apps/network/`, worker-pool placed).
   The authz server evaluates Envoy `CheckRequest` objects — method, path, headers, JWT claims —
   and returns allow/deny with optional header mutation. First deployment attaches to **nothing**;
   it exists to be reachable and monitored.
2. **Attach to one low-stakes internal route via `SecurityPolicy`**, with a policy that allows
   everything and logs the decision. This proves the datapath (Envoy → authz gRPC → decision) and
   establishes the latency and failure baseline before any request is ever denied.
3. **Decide the fail-open/fail-closed posture explicitly, and record it.** This is the decision
   that matters most and the easiest to get wrong. An `extAuth` backend on the **external**
   gateway that fails *closed* makes the authz server a public-availability SPOF; failing *open*
   makes it security theatre during an outage. The defensible split is likely
   **external → fail-closed, internal → fail-open**, but it must be a written decision with the
   blast radius stated, not a chart default. Note the direct precedent:
   [ADR-0033](../adr/adr-0033-approved-registries-stays-audit.md) kept `image-verify-harbor` in
   Audit for exactly this reason — `failurePolicy: Fail` would have made Harbor/OpenBao a SPOF.
4. **Migrate authorization app-by-app, never in bulk.** Start with an app that has *no* auth today
   and is internal-only. Each migration is one commit: `SecurityPolicy` + `AuthorizationPolicy` +
   a test. Apps that already do their own OIDC keep doing it until there is a reason to move them;
   double-enforcement is a debugging tax, not defence in depth.
5. **Break the circular dependency before it exists.** The authz server must never gate the path
   that serves its own dependencies — Authentik (token issuer), Harbor (its image), OpenBao. Carve
   those routes out from the start, the same way the verify policies carve out the components that
   produce verification.

## Risks

- **A new component in the synchronous request path.** Every gated request pays an extra hop.
  Baseline it in step 2, alert on the authz server's own latency and error rate, and treat the
  budget as a gate on widening the rollout.
- **CEL in the deny path at request rate.** Admission policy evaluates on writes; authz policy
  evaluates on *every request*. Policy complexity that is free at admission is not free here.
- **This overlaps with what Authentik forward-auth could do.** That alternative is real and
  cheaper to start: Authentik ships a forward-auth/proxy provider that Envoy can call. The
  argument for Kyverno Authz is engine consolidation and expressive policy under review; the
  argument for Authentik forward-auth is that it is already deployed. **This RFC should not be
  accepted without weighing them head to head** — see the decision table.
- **Project maturity.** `kyverno-authz` is a younger Kyverno sub-project than the admission
  controller. It is not carrying the cluster today, and step 1–2 are explicitly designed so that
  discovering it is unready costs one deleted directory.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Gateway-level request authorization is a platform concern, not per-app (new) |
| candidate | — | Kyverno Authz Server vs Authentik forward-auth as the `extAuth` backend (new) |
| candidate | — | `extAuth` failure posture per gateway — external fail-closed, internal fail-open (new) |

## Out of scope

- Admission-time policy — [audit→enforce RFC](rfc-kyverno-audit-enforce-hardening.md) and the
  [CEL migration](rfc-kyverno-cel-migration.md).
- Network-layer policy (L3/L4) — [ADR-0006](../adr/adr-0006-default-deny-network-policies.md);
  `extAuth` is L7 and complements it.
- A service mesh. The Kyverno authz server also fronts Istio; adopting a mesh here would be a far
  larger decision with its own RFC, and Envoy Gateway's `SecurityPolicy` makes it unnecessary for
  north-south traffic.
- Identity provider choice — Authentik is decided ([identity RFC](rfc-identity-sso.md)).

## References

- [kyverno/kyverno-authz](https://github.com/kyverno/kyverno-authz) — the authorization server
- [Kyverno Authz Server on Envoy Gateway](https://kyverno.github.io/kyverno-envoy-plugin/main/tutorials/envoy-gateway/)
  — the `SecurityPolicy` + `extAuth` wiring this proposes
- [CEL extensions for `CheckRequest`/`CheckResponse`](https://kyverno.github.io/kyverno-envoy-plugin/0.3.0/cel-extensions/)
- [RFC: Identity & SSO](rfc-identity-sso.md) — names the non-OIDC/forward-auth hole this closes ·
  [RFC: Ingress, DNS & edge](rfc-ingress-dns-edge.md) — the internal-by-default posture
