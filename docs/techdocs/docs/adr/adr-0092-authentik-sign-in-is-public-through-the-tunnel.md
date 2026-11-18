---
status: accepted
date: 2026-11-18
---

# Authentik's sign-in is public through the tunnel, its admin interface stays on the LAN

Technical Story: owner decision (2026-11-18), "Heb liever dat die webgrip endpoint gewoon publiek te
bereiken is", after signing in to OpenBao, Kubernetes and wellhead from outside the LAN took a VPN to
the homelab next to Tailscale, and OpenVPN Connect on macOS kept Tailscale from reaching its relay.
Narrows [ADR-0021](adr-0021-lan-only-exposure.md) for Authentik and supersedes the Authentik half of
[ADR-0090](adr-0090-claude-reaches-unfold-mcp-through-the-tunnel-from-anthropic-addresses-only.md).

## Context and Problem Statement

Authentik answered on the LAN only. The tunnel served five paths and answered 404 for the rest: the
token endpoint and the `unfold-mcp` discovery for Claude, from Anthropic's addresses only (ADR-0090),
and the `unfold-kubernetes` discovery and keys for the Unfold cluster's API servers. Every sign-in
that opens a browser (`bao login -method=oidc`, kubelogin, wellhead, the Unfold workbench's Homelab
login) therefore needed the LAN or a VPN to it. Away from home that is a second VPN beside Tailscale,
and the two did not run together.

## Decision Drivers

* Signing in works from any network without a VPN.
* The administrator interface stays where it was.
* No second gate that expires or needs its own credential in front of every OIDC client.

## Considered Options

* **Publish Authentik through the tunnel, except `/if/admin/`**
* Reach Authentik over the Unfold tailnet: Headscale answers its name with the homelab gateway's
  address and people's devices may open the gateway's 443 (proposed and declined, unfold-cluster#231)
* Put Cloudflare Access in front of Authentik

## Decision Outcome

Chosen option: **publish Authentik through the tunnel, except `/if/admin/`**. The tunnel forwards
every Authentik path to `envoy-internal` and answers 404 for `/if/admin/`. The Anthropic-only route
on the token endpoint (`unfold-mcp-token-through-tunnel`) goes, because the token endpoint is now
public for every client.

### Consequences

* Good, because every browser sign-in works from anywhere, with no VPN and no tailnet.
* Good, because LAN clients are untouched: k8s-gateway keeps answering the LAN address.
* Bad, because Authentik's login, enrolment, recovery and API endpoints face the internet. The gates
  are Authentik's own: Google-only login with closed enrolment
  ([ADR-0057](adr-0057-google-only-login-closed-enrolment.md)) and a security key for admins
  ([ADR-0077](adr-0077-admins-prove-a-security-key-at-google-and-sessions-end-in-twelve-hours.md)).
  An admin session reaches the admin API from anywhere; only the admin interface's pages stay on
  the LAN.
* Bad, because a flaw in Authentik is now reachable from the internet, so its updates are urgent.

### Confirmation

* From outside the LAN, `https://authentik.webgrip.dev/application/o/authorize/?client_id=openbao`
  answers Authentik's flow (a 302 or 200), not 404, and `https://authentik.webgrip.dev/if/admin/`
  answers 404.
* `bao login -method=oidc` completes from a network outside the LAN, without a VPN.

## Pros and Cons of the Options

### Reach Authentik over the Unfold tailnet

* Good, because Authentik stays off the internet.
* Bad, because it ties every sign-in to the tailnet and a hand-kept gateway address, and the
  first join and every renewal of a device still need the LAN.

### Cloudflare Access in front of Authentik

* Good, because a second login gates the internet path.
* Bad, because command-line clients redeem codes at the token endpoint without a browser session,
  so the token endpoint would need an exception anyway, and an expiring Access session in front of
  the identity provider is a worse failure mode than the exposure it removes (the trade-off
  [ADR-0054](adr-0054-forgejo-ssh-off-lan-cloudflare-tunnel.md) made for Forgejo SSH).
