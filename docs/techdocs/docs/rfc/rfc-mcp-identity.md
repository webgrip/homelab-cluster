# RFC: MCP endpoints carry the caller's identity

> Status: **Proposed** · Date: 2026-09-15 · Builds on [The access plane](rfc-access-plane.md) D9 and
> D10 · Closes the trigger D10 named: an in-cluster agent that reaches the Kubernetes API.

> **TL;DR.** Six MCP servers answer on the LAN to anyone who can reach the gateway, and the one
> that reads the cluster does so as its own service account. The fix is the door we already
> have: Claude Code signs in to the broker with a pre-registered client, Envoy verifies the
> broker's token on every MCP route, and the Kubernetes API is told to trust the broker as a
> second issuer so `k8s-mcp` can pass the caller's token through. A call from an agent then
> shows up in the audit log as `oidc:ryan@webgrip.nl`, with the agent's user agent, and the
> person's own RBAC decides what it may do. No dynamic client registration, no new component.

## Why

The access matrix lists these routes with no authentication at all:

| Route | Serves | Reads |
| --- | --- | --- |
| `k8s-mcp` | kubernetes-mcp-server | the cluster, as a service account bound to `view` |
| `mcp-grafana` | mcp-grafana | dashboards and PromQL |
| `mcp-victorialogs` | VictoriaLogs MCP | every log line |
| `opencost-mcp` | OpenCost MCP | cost data |
| `mcp-vikunja` | the board bridge | the roadmap, and it writes |
| `docs-mcp` | docs-mcp-server | scraped documentation |

"You are on the LAN" is the whole control, the same gap ADR-0060 closed for the dashboards.
Two of these matter more than the others: `mcp-victorialogs` reads the audit store the
break-glass alert depends on, and `k8s-mcp` reads the cluster under an identity that is not a
person, so nothing it does is attributable and the provenance rule cannot see it.

## What the ecosystem settled

- The MCP specification of 2026-07-28 deprecated Dynamic Client Registration in favour of
  Client ID Metadata Documents ([Zuplo's provider matrix](https://zuplo.com/learn/mcp/compatibility/identity-providers),
  [Stytch on DCR](https://stytch.com/blog/mcp-oauth-dynamic-client-registration/)). Authentik
  gained DCR in 2026.8 ([release notes](https://docs.goauthentik.io/releases/2026.8/)) and has no
  CIMD yet. Neither matters if the client is registered by hand.
- Claude Code takes a pre-registered client per server: `oauth.clientId` in `.mcp.json`, the
  secret in the keychain, PKCE on the authorization code flow
  ([reference](https://thepromptshelf.dev/blog/mcp-json-configuration-reference-2026/)).
- Envoy Gateway verifies a bearer JWT at the route with a `SecurityPolicy` `jwt` provider:
  issuer, audiences, a remote JWKS, claims copied to headers
  ([task](https://gateway.envoyproxy.io/docs/tasks/security/jwt-authentication/)). Version
  v1.8.3 runs here.
- kubernetes-mcp-server authenticates its HTTP clients with `require_oauth`,
  `oauth_audience`, `authorization_url` and `validate_token`, and presents the bearer it
  received to the Kubernetes API, optionally after an RFC 8693 exchange
  ([README](https://github.com/containers/kubernetes-mcp-server),
  [Keycloak guide](https://github.com/containers/kubernetes-mcp-server/blob/main/docs/KEYCLOAK_OIDC_SETUP.md)).
  The API server must therefore accept the broker's tokens.
- Kubernetes 1.36 takes a structured `AuthenticationConfiguration` with several JWT
  authenticators; on Talos it is `--authentication-config` plus a machine file, and it replaces
  the `oidc-*` flags ([multi-IdP walkthrough](https://a-cup-of.coffee/blog/apiserver-multi-idp/)).

## Decisions

| # | Question | Decision | Rejected |
| --- | --- | --- | --- |
| M1 | Who is the authorization server for MCP clients | The broker, with one confidential client `mcp` registered by the access-plane module, redirect URIs on the loopback ports Claude Code uses | Google directly (opaque access tokens, unusable at the gateway); DCR or CIMD (nothing to gain over a client in Git) |
| M2 | Where the token is verified | At Envoy, one `SecurityPolicy` `jwt` per MCP route, audience `mcp`, JWKS from the broker | In each server (six configurations, five of which cannot check a group) |
| M3 | Who may call | The gate on the `mcp` application: capability `mcp-use`, group `mcp-users`; `k8s-mcp` additionally gated on the person holding `k8s-read` or above, which the API server enforces anyway | A shared bearer token per server |
| M4 | How `k8s-mcp` reaches the API | Token pass-through; the API server trusts the broker as a second JWT authenticator with the same `oidc:` prefix on `email`, so the caller's own bindings apply | Impersonation by the server's service account (the server does not support it); token exchange (the broker is not an STS) |
| M5 | What the audit shows | `oidc:<email>` with the MCP server's user agent; the impersonation alert stays on its allow-list of none | A synthetic `agent:` identity (loses the human binding) |
| M6 | The Google door for `kubectl` | Unchanged; the structured configuration lists Google first and the broker second | Routing `kubectl` through the broker (ADR-0059 chose Google directly for the reasons it states) |

## Shape

1. **Model.** Capability `mcp-use` (risk medium: reads the cluster read-only, the logs, the
   board) projecting into Authentik group `mcp-users` and application `mcp`, held by
   `platform-engineer` and `developer`.
2. **Broker.** One `authentik_provider_oauth2` `mcp`, confidential, redirect URIs
   `http://localhost:<port>/callback` for the ports Claude Code is configured with, access
   token one hour, scopes `openid email profile groups`; its application gated on `mcp-users`.
   The client id and secret go to the vault at `authentik/mcp-oidc` and from there to every
   operator's keychain by `claude mcp add`, the way the kubelogin secret ships.
3. **Gateway.** A `SecurityPolicy` per MCP HTTPRoute: `jwt.providers[0]` with the broker's
   issuer `https://authentik.${SECRET_DOMAIN}/application/o/mcp/`, audience `mcp`, remote JWKS
   through a `Backend` to the broker, `claimToHeaders` copying `email` to `x-mcp-user` for the
   servers that log.
4. **API server.** `talos/patches/controller/cluster.yaml` moves the four `oidc-*` flags into an
   `AuthenticationConfiguration` file with two `jwt` entries: Google with `hd=webgrip.nl`
   required, and the broker with audience `mcp`; both map `email` to `oidc:<email>`. One Talos
   apply per control plane, the same routine as stage 4.
5. **`k8s-mcp`.** `require_oauth: true`, `oauth_audience: mcp`, `authorization_url` the
   broker's, `validate_token: false` because the API server validates; the `view` binding on
   its service account goes away, since the server no longer calls the API as itself.
6. **Clients.** `.mcp.json` gains `"oauth": {"clientId": "mcp"}` on each of the six servers; the
   first tool call opens the Google door once.

## Rollout

| Stage | Lands | Human step | Verified by |
| --- | --- | --- | --- |
| 1 | The capability, the client, the gate | none | the broker plans and applies; `mcp` appears in the matrix |
| 2 | `SecurityPolicy` on the five read-only MCP routes | `claude mcp add` with the client id and secret from the vault | an unauthenticated call to each route is 401; a signed-in Claude Code session lists tools |
| 3 | The structured authentication file in the Talos patch | one apply per control plane | `kubectl auth whoami` still returns the Google identity; a broker token for audience `mcp` is accepted by the API server |
| 4 | `k8s-mcp` on OAuth with pass-through; `SecurityPolicy` on its route; the `view` binding removed | none | an agent call appears in the audit as `oidc:ryan@webgrip.nl` with the server's user agent; `KubernetesImpersonationUsed` stays quiet |

## Confirmation

- Every MCP route in the access matrix reads "broker, at the gateway".
- A `curl` without a token to any MCP route is refused at the gateway.
- The audit dashboard's "Calls by person" row attributes agent calls to the person, with the
  MCP server's user agent, and the `k8s-mcp` service account disappears from "Calls by service
  account".
- `KubernetesBreakGlassCertificateUsed` and `KubernetesImpersonationUsed` stay quiet through the
  rollout.

## Out of scope

- Agents that run in the cluster without a person (the dark-factory builders). They keep their
  own identities until the D10 trigger fires for them, and that is a separate decision about
  budgets and blast radius, not about login.
- Per-tool authorization inside an MCP server; the gate is the person, the server's own
  read-only mode is the ceiling.

## References

- [RFC: The access plane](rfc-access-plane.md) · [ADR-0059](../adr/adr-0059-per-user-kubernetes-identity-via-google.md)
  · [ADR-0060](../adr/adr-0060-gateway-oidc-for-apps-without-a-login.md)
- [Authentik 2026.8 release notes](https://docs.goauthentik.io/releases/2026.8/) ·
  [Authentik DCR](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/dynamic-client-registration/)
- [Envoy Gateway JWT authentication](https://gateway.envoyproxy.io/docs/tasks/security/jwt-authentication/)
- [kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server)
- [Kubernetes API server with multiple identity providers](https://a-cup-of.coffee/blog/apiserver-multi-idp/)
