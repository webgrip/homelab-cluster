# ADR-0021: Identity-based egress to the gateway for server-side OIDC under default-deny

> Status: **Accepted** · Date: 2026-06-17 · Part of the [W7 zero-trust NetworkPolicy](index.md) work

## Context

Harbor OIDC login returned `{"errors":[{"code":"UNKNOWN","message":"internal server
error"}]}`. The harbor-core log showed the real cause:

```
[ERROR] [/pkg/oidc/helper.go:167]: Failed to get OAuth configuration, error: failed to
create OIDC provider, error: Get
"https://authentik.${SECRET_DOMAIN}/application/o/harbor/.well-known/openid-configuration":
dial tcp 10.0.0.27:443: i/o timeout
```

Harbor (like Backstage and n8n) performs **server-side** OIDC discovery — the *pod itself*
fetches `.well-known/openid-configuration` from the Authentik issuer. That hostname resolves
to `10.0.0.27`, the **envoy-internal LAN VIP**, so the call hairpins back into the cluster
through the gateway.

These namespaces are zero-trust: the `kyverno.io/default-network-policies: "true"` label makes
Kyverno generate a `default-deny` NetworkPolicy, and each app ships an `<app>-allow-egress`
policy of the shape `ipBlock: 0.0.0.0/0 except 10.42.0.0/16` (internet + LAN, minus the pod
CIDR). The intent was "allow the world, block direct cross-namespace pod IPs." It silently
broke the gateway hairpin.

**Why CIDR rules cannot express this under Cilium.** When a pod connects to a Kubernetes
Service ClusterIP or LoadBalancer VIP, Cilium translates the destination to a **backend pod**
*before* egress policy is enforced, and it enforces policy against that backend's **identity
and target port** — not the VIP address or port. So for `10.0.0.27:443`:

- the destination identity becomes an `envoy-internal` pod in namespace `network`
  (`10.42.x.x`) → matched by the `except 10.42.0.0/16` clause → **dropped**;
- the destination port becomes the Service's **targetPort `10443`** (Envoy Gateway's
  listener port), not `443`.

This is the same class of gotcha already documented in
[`components/cnpg-netpol`](../../../../kubernetes/components/cnpg-netpol/ciliumnetworkpolicy.yaml):
the kube-apiserver is matched by a reserved Cilium identity, so even `ipBlock: 0.0.0.0/0`
egress does not cover it. A first patch that added a `namespaceSelector: network` allow **with
`port: 443`** still failed — because the real post-DNAT port is `10443`.

The same latent break existed in **Backstage** and **n8n** (identical default-deny + egress
shape + server-side OIDC discovery to the public issuer); they had simply not had a login
attempt to surface it.

## Decision

1. **Shared component** [`kubernetes/components/gateway-egress`](../../../../kubernetes/components/gateway-egress/networkpolicy.yaml):
   a single `allow-gateway-egress` NetworkPolicy that permits egress to namespace `network`
   via a **`namespaceSelector` (identity) rule with no port filter**. Modeled on
   `components/cnpg-netpol`. Identity-based and port-less is mandatory: a CIDR clause drops it
   and a port clause misses the `443→10443` translation (and Envoy Gateway reassigns target
   ports on listener changes, so pinning a port is fragile).

2. **Apply it** to every zero-trust app that does server-side calls through a gateway:
   `harbor`, `backstage`, `n8n` (the default-deny ∩ server-side-OIDC set). The inline
   network-ns egress rule is **not** added to per-app policies — there is one source of truth.

3. **Shift-left guard** [`scripts/check-gateway-egress.sh`](../../../../scripts/check-gateway-egress.sh),
   wired into the `flux-local` CI workflow: it fails the build if an app in a zero-trust
   namespace references a server-side OIDC discovery URL (`well-known/openid-configuration` or
   `oidc_endpoint`) but its kustomization does not include `components/gateway-egress`. This
   converts a silent, login-only runtime failure (it passes `kubeconform` and `flux-local`
   render) into a build error.

## Consequences

- Harbor OIDC login works again; Backstage and n8n are fixed pre-emptively.
- Apps that legitimately need to reach internal-only services through the gateway opt in by
  adding the component — an explicit, reviewable, least-privilege grant (the gateway can reach
  internal-only Services that the public internet cannot, so this is gated per app rather than
  generated for every zero-trust namespace).
- **General rule for this cluster:** under Cilium, cross-namespace egress to a Service/VIP
  (gateway, kube-apiserver, any ClusterIP) must be expressed with **identity selectors**
  (`namespaceSelector` / `toEntities`), never `toCIDR`. The `0.0.0.0/0` and `10.43.0.0/16`
  CIDR egress clauses in the per-app policies are effective only for real off-cluster IPs
  (e.g. Garage S3 at `10.0.0.110`, internet) — they do not govern in-cluster Service traffic.
