---
status: accepted
date: 2026-11-01
---

# Claude reaches Unfold's MCP endpoint through the tunnel, from Anthropic's addresses only

Technical Story: owner request (2026-11-01), "I want to expose it, I want to test it. But is it
secure?", to see Unfold's MCP Apps Work Item card in claude.ai. Narrows the internal-by-default
posture of [ADR-0021](adr-0021-lan-only-exposure.md) for five paths, the way
[ADR-0054](adr-0054-forgejo-ssh-off-lan-cloudflare-tunnel.md) and
[ADR-0056](adr-0056-searxng-public-behind-gateway-basic-auth.md) did for one app each.

## Context and Problem Statement

Unfold serves `unfold-mcp` at `https://unfold.${SECRET_DOMAIN}/mcp` as an OAuth 2.1 resource
server: every call needs an Authentik access token for that resource, with the `unfold:mcp` scope
and a group that maps to an Unfold role. Tokens live ten minutes. The action tools ask the person
to confirm before they change or spend anything.

claude.ai, Claude Desktop and the Claude mobile apps render MCP Apps, but they call a remote MCP
server from Anthropic's servers, not from the person's device. Three parties take part in a
connector sign-in:

| Step | Who sends it | What it reaches |
| --- | --- | --- |
| Discover the resource and its authorization server | Anthropic's servers | Unfold's protected resource metadata, Authentik's metadata for `unfold-mcp` |
| Sign in and consent | The person's browser | Authentik's authorize endpoint and login flow |
| Redeem the code, refresh the token | Anthropic's servers | Authentik's token endpoint |
| Call tools | Anthropic's servers | `/mcp` |

Today `unfold.${SECRET_DOMAIN}` has no public DNS record, and the tunnel answers 404 for every
Authentik path except the `unfold-kubernetes` discovery and keys. So the first, third and fourth
steps cannot happen. How does Claude reach these paths without putting Unfold or Authentik on the
internet?

## Decision Drivers

* Anthropic's servers are the only callers that need the new paths, and Anthropic publishes the
  addresses they call from: `160.79.104.0/21`
  ([IP addresses](https://platform.claude.com/docs/en/api/ip-addresses)).
* Nothing on the LAN may change: the same hostnames keep answering the same way at home and over
  the VPN.
* Authentik's login stays LAN-only. Publishing the identity provider is a larger decision than
  this one, as ADR-0056 recorded.
* The resource URL stays `https://unfold.${SECRET_DOMAIN}/mcp`, so clients on the LAN and claude.ai
  use one URL and one token audience.
* Manifest-managed and reversible.

## Considered Options

* **Tunnel path rules plus tunnel-only routes that admit Anthropic's addresses only**
* Tunnel path rules alone, relying on Unfold's and Authentik's own checks
* Attach Unfold to `envoy-external` with a path-limited route
* Cloudflare Access or a WAF rule in front of the tunnel
* Keep it LAN-only and test with VS Code instead

## Decision Outcome

Chosen option: **tunnel path rules plus tunnel-only routes that admit Anthropic's addresses
only**, because it opens exactly the paths Claude's servers call, only to those servers, and
leaves every LAN request on the route it takes today.

1. The Cloudflare Tunnel forwards `unfold.${SECRET_DOMAIN}` paths `/mcp`,
   `/.well-known/oauth-protected-resource` and `/.well-known/oauth-protected-resource/mcp` to
   `envoy-internal`, and answers 404 for every other Unfold path.
2. It forwards Authentik's token endpoint `/application/o/token/` and the two `unfold-mcp`
   metadata documents to `envoy-internal`, above the existing Authentik 404 rule.
3. A `DNSEndpoint` publishes `unfold.${SECRET_DOMAIN}` as a proxied CNAME to the tunnel.
   k8s-gateway stays authoritative on the LAN, so LAN and VPN resolvers keep the internal address.
4. Two HTTPRoutes on `envoy-internal`, `ploeg/unfold-mcp-through-tunnel` and
   `authentik/unfold-mcp-token-through-tunnel`, match those exact paths only when the request
   carries `cf-connecting-ip`, which Cloudflare sets on every request it forwards. Exact path
   matches outrank the apps' existing `/` prefix routes, so tunnel traffic lands on them, and LAN
   traffic, which has no such header, keeps its existing route.
5. A `SecurityPolicy` on each of the two routes denies by default and allows `160.79.104.0/21`.
   Envoy takes the client address from `X-Forwarded-For` with one trusted hop, the gateways'
   shared `ClientTrafficPolicy`, so it sees the caller's real address on tunnel traffic, as the
   access logs already show for `envoy-external`.
6. The `unfold-mcp` Authentik application also accepts the redirect
   `https://claude.ai/api/mcp/auth_callback`.

### Consequences

* Good, because a request from anywhere but Anthropic's servers gets 403 from Envoy before it
  reaches Unfold or Authentik, and any path outside the five gets 404 from the tunnel.
* Good, because the login stays LAN-only: nobody off-LAN can sign in, and enrolment is closed
  ([ADR-0057](adr-0057-google-only-login-closed-enrolment.md)), so a token still needs a person
  who signs in with Google at home or over the VPN.
* Good, because the LAN path is untouched: no hostname, route or DNS answer changes for LAN
  clients.
* Bad, because the allowlist trusts every Anthropic customer's traffic. Any claude.ai user can make
  Claude call `/mcp` or the token endpoint; they still need a valid token or a code, which only a
  LAN sign-in produces.
* Bad, because claude.ai keeps the person's refresh token on Anthropic's side, and Work Item
  titles, questions, pull request links and spend pass through Anthropic and Cloudflare.
* Bad, because a claude.ai sign-in started by someone else and approved by the owner would give
  that person's connector the owner's Unfold access. The owner approves only a sign-in they
  started themselves.
* Bad, because a public `unfold.${SECRET_DOMAIN}` record means an off-LAN browser that opens Unfold
  now gets the tunnel's 404 instead of a name that does not resolve.
* Bad, because the allowlist follows Anthropic's published list by hand. When Anthropic changes it,
  claude.ai calls get 403 until this policy changes.

### Confirmation

1. `dig unfold.${SECRET_DOMAIN} @1.1.1.1 +short` returns Cloudflare addresses, and from the LAN
   `dig unfold.${SECRET_DOMAIN} +short` still returns `10.0.0.27`.
2. From a non-Anthropic address through Cloudflare (`curl --resolve` to a Cloudflare edge
   address), `/mcp` and `/application/o/token/` answer 403, `/` on Unfold answers 404, and from
   the LAN `/mcp` still answers 401 with a `WWW-Authenticate` challenge.
3. `kubectl get securitypolicy -n ploeg unfold-mcp-through-tunnel` and
   `-n authentik unfold-mcp-token-through-tunnel` report `Accepted=True`.
4. Adding `https://unfold.${SECRET_DOMAIN}/mcp` as a custom connector in claude.ai with client ID
   `unfold-mcp`, signing in from the LAN, and asking what waits shows the Work Item card.

## Pros and Cons of the Options

### Tunnel path rules plus tunnel-only routes from Anthropic's addresses

* Good, because it narrows by path at the tunnel and by caller at the gateway.
* Good, because it needs no change to Unfold, Authentik's login or the Kyverno gateway allowlist.
* Bad, because it is three moving parts, tunnel rules, routes and policies, to keep in step.

### Tunnel path rules alone

* Good, because it is two edits.
* Bad, because the token endpoint serves every Authentik client, so the whole internet could try
  client secrets and refresh tokens against it.

### `envoy-external` with a path-limited route

* Bad, because k8s-gateway answers a hostname with both gateways' addresses once it has a route on
  each, and LAN browsers would get 404 from `envoy-external` for half their Unfold requests, the
  failure ADR-0056 measured.
* Bad, because the `ploeg` namespace would join the Kyverno allowlist for `envoy-external`.

### Cloudflare Access or a WAF rule

* Bad, because it is configured in Cloudflare's dashboard, outside review and rollback, and
  ADR-0054 declined Access on this tunnel.

### Keep it LAN-only and test with VS Code

* Good, because nothing changes.
* Bad, because it does not show the card in Claude, which is what was asked.

## More Information

* Unfold's MCP over HTTPS and the MCP Apps card are described in Unfold's guides *Serve Unfold's
  MCP tools over HTTPS* and *Ask Unfold and Ploeg from an AI client*.
* Related: [ADR-0021](adr-0021-lan-only-exposure.md),
  [ADR-0054](adr-0054-forgejo-ssh-off-lan-cloudflare-tunnel.md),
  [ADR-0056](adr-0056-searxng-public-behind-gateway-basic-auth.md),
  [ADR-0057](adr-0057-google-only-login-closed-enrolment.md),
  [ADR-0058](adr-0058-access-plane-one-module-one-model.md).
