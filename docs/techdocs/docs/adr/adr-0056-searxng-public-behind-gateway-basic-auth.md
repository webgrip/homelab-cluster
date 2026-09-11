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
* **The LAN path must not regress.** It worked before this request and nothing about being
  reachable from outside should make being at home worse.
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

**Two routes, two hostnames, one backend.** `searxng.${SECRET_DOMAIN}` keeps its existing route on
`envoy-internal`, unauthenticated and excluded from public DNS, exactly as before. A second route,
`search.${SECRET_DOMAIN}`, attaches to `envoy-external`, and the `SecurityPolicy` targets **that
route only**. The credential is an htpasswd entry read from OpenBao at `secret/searxng/basic-auth`
by an `ExternalSecret`; the namespace's `webgrip.io/exposure` label moves from `internal` to
`external`, and `searxng` joins the allowlist in `restrict-external-gateway-attachment`, the
enforcing Kyverno policy that would otherwise deny the attachment.

Splitting the hostname is what keeps the two paths independent, and it is only safe because
searxng builds **relative** URLs: `image_proxify` calls `url_for('image_proxy')` with no
`_external`, and the only `_external=True` in the templates is the OpenSearch descriptor, which
affects "add to browser" and nothing else. A single hostname on both gateways was tried first and
reverted the same day — see the history below.

The Cloudflare Tunnel needs no change: its `*.${SECRET_DOMAIN}` rule already forwards any new
public hostname to `envoy-external`, and external-dns publishes `search.${SECRET_DOMAIN}` on its
own because it watches that gateway. The internal route keeps its `external-dns` exclusion, so the
old name stays off public DNS.

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
* Good, because the LAN path is untouched: same hostname, same absence of a password, and it stays
  up even while the public credential is missing.
* Bad, because basic auth carries no MFA, no session expiry and no group policy, unlike every other
  authenticated surface in this estate. It is a shared static credential over TLS.
* Bad, because the credential is a provided value: it must be written to OpenBao once by hand, and
  the **public** route answers 500 until it is. Rotation is one `bao kv put` plus the ESO refresh
  interval. Generating it instead was attempted and abandoned — Envoy Gateway accepts only unsalted
  `{SHA}` htpasswd entries, and this cluster's External Secrets build has no template function that
  turns `sha1sum`'s hex output back into the raw bytes the base64 needs.
* Bad, because the instance now answers to two names, and the OpenSearch "add to browser"
  descriptor always advertises the internal one.
* Bad, because one more name now resolves publicly, which is a standing invitation to credential
  stuffing. Cloudflare proxying keeps the origin address hidden, and the 401 is cheap to serve.

### Confirmation

Four checks, all against live state rather than manifests:

1. `dig search.${SECRET_DOMAIN} @1.1.1.1 +short` returns Cloudflare edge addresses, and
   `dig searxng.${SECRET_DOMAIN} @1.1.1.1 +short` returns nothing — only the gated name is public.
2. An unauthenticated request to `search.${SECRET_DOMAIN}` returns **401** with a
   `WWW-Authenticate: Basic` header; the same request with the credential returns **200**. A
   request to `searxng.${SECRET_DOMAIN}` from the LAN returns **200** with no credential.
3. `kubectl -n searxng get securitypolicy searxng-basic-auth` reports `Accepted=True`, and both
   `HTTPRoute`s report `Accepted`/`ResolvedRefs`.
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
* 2026-09-11 — accepted; `SecurityPolicy`, `ExternalSecret`, the second `HTTPRoute` and the Kyverno
  allowlist entry committed together.
* 2026-09-11 — **shape corrected the same day, before the record described anything durable.** The
  first implementation put one hostname on both gateways with the `SecurityPolicy` on that single
  route. Measured against the live cluster, that was wrong in a way reasoning had not caught:
  k8s-gateway answers LAN queries for the hostname with **both** gateway addresses (12 of 12
  queries returned 10.0.0.27 and 10.0.0.28), so route-level auth was the only way to make LAN
  behaviour deterministic — and it made LAN behaviour deterministically *authenticated*. Because
  the credential is a provided value that nobody had written yet, both gateways served **500** and
  LAN search went down. Fail-closed worked exactly as designed; the design was the problem. Two
  hostnames decouple the paths, which is only viable because searxng's URLs are relative. Kept
  from the first attempt: the fail-closed behaviour is now confirmed by observation, not by
  reading the translator source — a missing secret really does yield 500 on the targeted route.
