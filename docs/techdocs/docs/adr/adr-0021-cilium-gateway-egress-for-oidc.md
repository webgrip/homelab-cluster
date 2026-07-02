# ADR-0021: Identity-based egress to the gateway for server-side OIDC under default-deny

> Status: **Accepted** · Date: 2026-06-17 · Superseded in scope by [ADR-0039](adr-0039-default-deny-network-policies.md)

## Context

Harbor OIDC login returned `{"errors":[{"code":"UNKNOWN","message":"internal server error"}]}`.
The harbor-core log showed the real cause:

```text
[ERROR] [/pkg/oidc/helper.go:167]: Failed to get OAuth configuration, error: failed to
create OIDC provider, error: Get
"https://authentik.${SECRET_DOMAIN}/application/o/harbor/.well-known/openid-configuration":
dial tcp 10.0.0.27:443: i/o timeout
```

Harbor performs **server-side** OIDC discovery — the pod itself fetches
`.well-known/openid-configuration` from the Authentik issuer. That hostname resolves to
`10.0.0.27`, the **envoy-internal LAN VIP**, so the call hairpins back into the cluster through
the gateway. The namespace is zero-trust (default-deny plus an `<app>-allow-egress` policy of the
shape `ipBlock: 0.0.0.0/0 except <pod CIDR>`), which silently broke the hairpin: under Cilium,
egress to a Service/VIP is enforced **post-DNAT against the backend pod's identity and
targetPort**, not the VIP address/port — so CIDR rules can never match gateway traffic, and a first
patch that allowed `namespaceSelector: network` **with `port: 443`** still failed, because the real
post-DNAT port is Envoy's listener targetPort **10443**. (Full mechanics now live in
[ADR-0039](adr-0039-default-deny-network-policies.md), the canonical default-deny ADR.) The same
latent break existed in every zero-trust app with server-side OIDC — only a login attempt surfaces
it.

## Decision

1. **Shared component [`kubernetes/components/gateway-egress`](../../../../kubernetes/components/gateway-egress/networkpolicy.yaml):**
   a single `allow-gateway-egress` NetworkPolicy permitting egress to namespace `network` via a
   **`namespaceSelector` (identity) rule with no port filter**, modeled on `components/cnpg-netpol`.
   Identity-based and port-less is mandatory: a CIDR clause drops the post-DNAT traffic, and a port
   clause misses the `443→10443` translation (Envoy Gateway reassigns target ports on listener
   changes, so pinning one is fragile).
2. **Apply it per zero-trust app that makes server-side calls through the gateway** — currently
   harbor and backstage (n8n was in the original set; see Status log). The rule is not inlined into
   per-app policies — one source of truth.
3. **Shift-left guard [`scripts/check-gateway-egress.sh`](../../../../scripts/check-gateway-egress.sh)**
   in the flux-local CI workflow: the build fails if a zero-trust app references a server-side OIDC
   discovery URL but its kustomization does not include the component — converting a silent,
   login-only runtime failure into a build error.

## Consequences

- Harbor OIDC login works again; the other affected apps were fixed pre-emptively before any login
  attempt surfaced the break.
- The grant is opt-in, reviewable, least-privilege: the gateway can reach internal-only Services the
  public internet cannot, so it is gated per app rather than generated for every zero-trust
  namespace.
- **General rule for this cluster:** under Cilium, cross-namespace egress to a Service/VIP
  (gateway, kube-apiserver, any ClusterIP) must be expressed with **identity selectors**
  (`namespaceSelector` / `toEntities`), never `toCIDR`; CIDR egress clauses only govern real
  off-cluster IPs (e.g. Garage S3, the internet).

## Status log

- 2026-06-17 — Accepted; component + CI guard shipped, applied to harbor, backstage, n8n.
- 2026-06-30 — n8n's OIDC config removed (`d15b8e22` — it was a non-functional, Enterprise-gated
  half-config), shrinking the server-side-OIDC set to harbor + backstage; n8n redundantly keeps the
  component.
- 2026-07-02 — Superseded in scope by [ADR-0039](adr-0039-default-deny-network-policies.md), which
  now owns the cluster-wide default-deny + identity-egress model; the component and CI guard remain
  in force.
