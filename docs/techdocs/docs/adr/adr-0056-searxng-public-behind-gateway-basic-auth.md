---
status: accepted
date: 2026-09-11
---

# SearXNG goes public behind gateway-level basic auth, not naked

Technical Story: owner request (2026-09-11) — "make it externally available", raised in the same
breath as a report that search had been failing with every engine suspended at once. Narrows the
internal-by-default posture of [ADR-0021](adr-0021-lan-only-exposure.md) for one app, and is the
first use of Envoy Gateway's `SecurityPolicy` in this estate, which
[RFC: Request authorization at the gateway](../rfc/rfc-request-authorization-envoy.md) proposed
but which nothing had yet exercised.

## Context and Problem Statement

SearXNG was reachable only from the LAN: one `HTTPRoute` on `envoy-internal`, carrying
`external-dns.alpha.kubernetes.io/exclude: "true"` so the public zone never learned the name. The
owner wants it usable away from home, without dialling the WireGuard VPN first — the same friction
[ADR-0054](adr-0054-forgejo-ssh-off-lan-cloudflare-tunnel.md) removed for git-over-SSH.

Publishing it is one `parentRefs` line. The problem is what that line does to the app.

SearXNG is a **metasearch proxy**: every user query becomes outbound queries to Google, DuckDuckGo,
Brave, Qwant and the rest, from this house's single IP address. Those engines rate-limit and
CAPTCHA per source IP. An instance anyone can reach is an instance anyone can drive, and public
SearXNG instances are found and scraped continuously — the software ships a bot-detection limiter
precisely because of it. This deployment runs with `server.limiter: false` and
`server.public_instance: false`, i.e. explicitly configured as a private instance with no bot
protection, because until now the LAN boundary was the protection.

So the naive version of this request defeats the request that came with it: the engine bans that
made search unusable are exactly what an unguarded public instance would earn permanently. The
protection has to move from the network boundary to the request, or it has to not be published.

SearXNG has no authentication of its own — there is no user model to enable. Whatever gates it has
to sit in front of it.

## Decision Drivers

* **The gate must not depend on anything that is itself LAN-only**, or it cannot work off-LAN.
* **Manifest-managed.** Dashboard-only configuration is outside review, diff and rollback, the same
  driver that shaped ADR-0054.
* **Fail closed.** A misconfigured or missing credential must not silently publish an open instance.
* **One hostname.** `base_url` is baked into the settings and used to build absolute links
  (the image proxy among them), so a second public hostname would serve broken pages.
* **Proportionate.** One user, one password. The gate should not cost more to operate than the
  thing it guards.

## Considered Options

* **Envoy Gateway `SecurityPolicy` with `basicAuth`**, credential from OpenBao via External Secrets
* **`SecurityPolicy` with `oidc`**, federated to Authentik
* **Cloudflare Access** in front of the tunnel
* **Publish it unauthenticated**
* **Decline to publish; keep it on the VPN**

## Decision Outcome

Chosen option: **Envoy Gateway `SecurityPolicy` with `basicAuth`**, because it is the only option
that authenticates off-LAN traffic without depending on a LAN-only component, lives entirely in
manifests, and fails closed.

The `HTTPRoute` now attaches to **both** gateways — `envoy-internal` and `envoy-external` — under
the single hostname `searxng.${SECRET_DOMAIN}`, and a `SecurityPolicy` targets **the route**, not a
gateway. Targeting the route is what makes the behaviour uniform: split-horizon DNS can hand a LAN
client either gateway's address, and both paths land on the same authenticated route either way.
The credential is an htpasswd entry read from OpenBao at `secret/searxng/basic-auth` by an
`ExternalSecret`; the namespace's `webgrip.io/exposure` label moves from `internal` to `external`,
and `searxng` joins the allowlist in `restrict-external-gateway-attachment`, the enforcing Kyverno
policy that would otherwise deny the attachment.

The Cloudflare Tunnel needs no change: its `*.${SECRET_DOMAIN}` rule already forwards any new
public hostname to `envoy-external`, and external-dns publishes the record once the `exclude`
annotation is gone.

### Consequences

* Good, because the public path is authenticated by a component already running and already in the
  request path, with no new deployment, no service mesh and no per-app middleware.
* Good, because it fails closed by construction: Envoy Gateway's translator returns a 500 direct
  response on the targeted route when the secret is missing or its `.htpasswd` key is empty, so a
  credential that never arrives yields an unusable route rather than an open one.
* Good, because it proves the `SecurityPolicy` datapath on a low-stakes route, which is step 2 of
  the request-authorization RFC's rollout, without adopting an authorization server.
* Good, because the engine-ban blast radius stays where it was — only the owner can drive outbound
  queries, which is what keeps the fix in the accompanying commit durable.
* Bad, because the LAN path now asks for a password too. That is the price of one hostname and one
  uniform rule; browsers remember it.
* Bad, because basic auth carries no MFA, no session expiry and no group policy, unlike every other
  authenticated surface in this estate. It is a shared static credential over TLS.
* Bad, because the credential is a provided value: it must be written to OpenBao once by hand, and
  the route answers 500 until it is. Rotation is one `bao kv put` plus the ESO refresh interval.
* Bad, because one more name now resolves publicly, which is a standing invitation to credential
  stuffing. Cloudflare proxying keeps the origin address hidden, and the 401 is cheap to serve.

### Confirmation

Four checks, all against live state rather than manifests:

1. `dig searxng.${SECRET_DOMAIN} @1.1.1.1 +short` returns Cloudflare edge addresses — the name is
   published.
2. An unauthenticated request to the public hostname returns **401** with a
   `WWW-Authenticate: Basic` header; the same request with the credential returns **200**.
3. `kubectl -n searxng get securitypolicy searxng-basic-auth` reports `Accepted=True`, and the
   `HTTPRoute` reports `Accepted`/`ResolvedRefs` on **both** parents.
4. The Kyverno gate still bites: `kyverno apply` on the enforcing policy admits
   `searxng/searxng` and rejects the identical route in an unlisted namespace. Run as a
   three-way mutation test on 2026-09-11 — the pre-change policy rejected both, the post-change
   policy rejects only the unlisted one.

## Pros and Cons of the Options

### Envoy Gateway `SecurityPolicy` with `basicAuth`

* Good, because it needs no component that is not already serving the request.
* Good, because it fails closed, and the failure is visible (500, not silent admission).
* Good, because the whole gate is four short manifests under review.
* Bad, because the credential is static, shared and unrotated unless someone rotates it.
* Bad, because Envoy Gateway supports only SHA-hashed htpasswd entries, so the hash cannot be
  produced by an ESO generator and the value has to be provided.

### `SecurityPolicy` with `oidc` federated to Authentik

* Good, because it would reuse the estate's IdP, its MFA policy and its group bindings.
* Good, because it is the shape the request-authorization RFC ultimately wants.
* Bad, and decisive: **Authentik is itself LAN-only** — its `HTTPRoute` is on `envoy-internal`. The
  OIDC redirect happens in the user's browser, so an off-LAN browser cannot reach the authorize
  endpoint and the login cannot complete. Making this work means publishing the identity provider,
  which is a materially larger decision than publishing a search box and deserves its own record.

### Cloudflare Access

* Good, because it authenticates at the edge, before traffic enters the tunnel.
* Bad, because the application is configured in Cloudflare's dashboard or API, not in this repo —
  outside review, diff and rollback.
* Bad, because its Authentik federation ([blueprint 39](../../../../kubernetes/apps/authentik/app/blueprints/39-oidc-cloudflare-access.yaml))
  needs Cloudflare's edge to reach Authentik's OIDC endpoints, which are LAN-only, so it inherits
  the blocker above.
* Bad, because ADR-0054 already weighed and declined an Access application on this tunnel for the
  adjacent case.

### Publish it unauthenticated

* Good, because it is one line and no credential to manage.
* Bad, and disqualifying: it hands anyone who finds the host the ability to spend this house's
  search-engine reputation, which is the exact failure the accompanying fix was written to undo.
* Bad, because the instance runs `limiter: false` and `public_instance: false` — it has no bot
  protection to fall back on.

### Decline to publish; keep it on the VPN

* Good, because it changes nothing and risks nothing.
* Bad, because it does not do what was asked, and the VPN friction is real — the same friction
  already judged worth removing for git-over-SSH.

## More Information

* Sibling commit: the searxng correctness fixes (image unfrozen from 2025.12.9 after the Renovate
  versioning rule silently stopped matching, `outgoing.source_ips` removed after it was found
  binding half of all outbound sockets to an IPv6 wildcard the pod has no route for, and
  suspension timers returned to upstream defaults).
* Related: [ADR-0021](adr-0021-lan-only-exposure.md) (internal-by-default) ·
  [ADR-0054](adr-0054-forgejo-ssh-off-lan-cloudflare-tunnel.md) (the other off-LAN carve-out, and
  the precedent for declining Cloudflare Access) ·
  [ADR-0006](adr-0006-default-deny-network-policies.md) (L3/L4 policy, which `SecurityPolicy`
  complements at L7) ·
  [RFC: Request authorization at the gateway](../rfc/rfc-request-authorization-envoy.md) ·
  [RFC: Ingress, DNS & edge](../rfc/rfc-ingress-dns-edge.md) (names "exposure is one YAML token
  away" as the risk this record deliberately accepts, once, with a gate).
* 2026-09-11 — accepted; `SecurityPolicy`, `ExternalSecret`, dual-gateway `HTTPRoute` and the
  Kyverno allowlist entry committed together.
