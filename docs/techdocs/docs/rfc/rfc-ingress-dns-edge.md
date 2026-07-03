# RFC: Ingress, DNS & the exposure edge

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** How traffic enters this cluster — two Envoy gateways, a Cloudflare tunnel, split-horizon
> DNS, one wildcard certificate — is a coherent architecture that no decision record describes. This
> RFC backfills the edge as retroactive ADRs **and** closes the two real holes it found: the
> internal-by-default exposure posture is enforced by nothing (one wrong `parentRefs` line publishes
> an app to the internet), and the LAN half of split-DNS lives as undeclared manual OPNsense config.

## Why

The edge, as built (verified in-tree 2026-07-02):

- **Two Gateways** on one Envoy Gateway install (`network/envoy-gateway/app/envoy.yaml`):
  `envoy-internal` (`10.0.0.27`) and `envoy-external` (`10.0.0.28`), VIPs from Cilium LB-IPAM,
  both terminating TLS with the same wildcard secret; a shared `https-redirect` route; HTTP/3 and
  compression via Client/BackendTrafficPolicies; proxies on the worker pool, 2 replicas.
- **Public path**: `cloudflared` (2 replicas, QUIC, post-quantum) points `*.${SECRET_DOMAIN}` at
  the `envoy-external` in-cluster Service; a `DNSEndpoint` CNAMEs `external.${SECRET_DOMAIN}` to
  the tunnel. No inbound port-forward exists — Cloudflare is the only public entrance.
- **DNS is split-horizon**: external-dns publishes **only** `envoy-external` HTTPRoutes (plus
  explicit `DNSEndpoint`s) to Cloudflare; k8s-gateway serves the whole `${SECRET_DOMAIN}` zone at
  `10.0.0.26` for the LAN, wired via a CoreDNS stub zone in-cluster and **manual OPNsense
  rules** on the LAN ([dns-split-dns runbook](../runbooks/dns-split-dns.md)).
- **TLS**: one ClusterIssuer (`letsencrypt-production`, DNS01 via Cloudflare), one wildcard
  `Certificate`, consumed only by the two gateway listeners. No staging issuer.
- **The convention**: internal is the default (~25 internal routes vs ~9 external). ADR-0021
  applied it to Harbor; the general rule was never recorded, and nothing *enforces* it.

Nothing above is written down as a decision. Two concrete risks ride on that:

1. **Exposure is one YAML token away.** `parentRefs.name: envoy-external` on any HTTPRoute
   publishes the app publicly (external-dns creates the record automatically) — silently
   compliant with every existing policy. Several internal apps have no auth of their own
   ([identity RFC](rfc-identity-sso.md)), so the LAN boundary is their only protection.
2. **The LAN DNS half is out-of-band.** The OPNsense split-DNS rules are hand-configured; a
   router rebuild silently breaks every `*.${SECRET_DOMAIN}` LAN resolution with nothing in Git
   to say what "correct" was.

## Proposal

1. **Backfill three retroactive ADRs**: (a) the dual-gateway topology + internal-by-default
   exposure posture (generalizing ADR-0021); (b) public exposure exclusively via the Cloudflare
   tunnel (no port-forwards; the CF dependency accepted with eyes open — including the ~100 MB
   body cap ADR-0021 documented and the sovereignty tension with the forge-exit program);
   (c) split-horizon DNS via external-dns + k8s-gateway, including the OPNsense dependency.
2. **Enforce the exposure posture** (new decision): a Kyverno policy requiring an explicit opt-in
   label/annotation on any HTTPRoute whose `parentRefs` is `envoy-external` — Audit first, then
   Enforce via the [ADR-0032](../adr/adr-0032-kyverno-enforce-promotion-policy.md) wave process.
   Accidental publication becomes a build/admission failure instead of a silent DNS record.
3. **Declare the LAN DNS dependency**: document the exact OPNsense configuration in the runbook as
   the source of truth (or, if OPNsense config can be exported, commit the export alongside).
   Decide explicitly that router config stays out of GitOps — but stop it being undocumented.
4. **Decide the cert posture**: single prod wildcard is fine (DNS01 has no rate-limit pressure
   from renewal), but record it — including why no staging issuer and what the blast radius of a
   failed renewal is (both gateways at once).

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Dual Envoy gateways + internal-by-default exposure posture (retroactive) |
| candidate | — | Public ingress exclusively via Cloudflare tunnel (retroactive) |
| candidate | — | Split-horizon DNS: external-dns (public) + k8s-gateway (LAN) (retroactive) |
| candidate | — | Kyverno guard: explicit opt-in for `envoy-external` routes (new) |

## Out of scope

- East-west network policy — owned by [ADR-0006](../adr/adr-0006-default-deny-network-policies.md).
- Authentication on exposed apps — the [identity RFC](rfc-identity-sso.md).
- Gateway hardware/bandwidth (1 GbE flat LAN) — the [layered-hardware RFC](rfc-layered-hardware-architecture.md) L1.

## References

- [envoy-gateway runbook](../runbooks/envoy-gateway.md) · [dns-split-dns runbook](../runbooks/dns-split-dns.md) ·
  [cert-manager runbook](../runbooks/cert-manager.md)
- [ADR-0021](../adr/adr-0021-lan-only-exposure.md) — the Harbor-scoped instance of the posture
