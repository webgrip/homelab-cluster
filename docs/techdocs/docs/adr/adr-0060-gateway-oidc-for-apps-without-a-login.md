---
status: proposed
date: 2026-09-14
---

# Applications without a login of their own sit behind the broker at the gateway

Technical Story: [RFC: The access plane](../rfc/rfc-access-plane.md) D9. Closes the open
decision of the [Identity & SSO RFC](../rfc/rfc-identity-sso.md) and generalises
[ADR-0056](adr-0056-searxng-public-behind-gateway-basic-auth.md), which proved the
`SecurityPolicy` datapath with basic auth on one route.

## Context and Problem Statement

Six routes on `envoy-internal` had no authentication at all: Longhorn, which deletes volumes
and repoints the backup target; the Flux UI; VictoriaLogs, which holds every log line the
cluster emits; Prometheus; Alertmanager; and Policy Reporter. "You must be on the LAN" was the
whole control, and it erodes with every device that joins the network. None of these
applications can speak OIDC themselves.

## Decision Drivers

* One door for people, the same door as everywhere else.
* Authorization decided in one place, from the model, not per application.
* Nothing new in the request path; nothing that fails open.
* Longhorn is not a dashboard and must not share an audience with read-only ones.

## Considered Options

* **Envoy Gateway `SecurityPolicy` with `oidc`, one broker client per audience, authorization
  by Authentik group binding**
* Authentik proxy provider with an embedded outpost as forward-auth
* Per-application oauth2-proxy sidecars
* Accept LAN-only for a named list

## Decision Outcome

Chosen option: **`SecurityPolicy` OIDC, one client per audience, groups decide**, because
Envoy already serves every one of these routes, fails closed when its Secret is missing, and
needs no claim logic of its own: Authentik refuses to issue a token to anyone outside the
application's gate groups.

* Two broker clients, from the access-plane module: `longhorn`, opened by `storage-admin`
  (group `storage-admins`), and `cluster-dashboards`, opened by `dashboards-view` (group
  `cluster-dashboards`) with a redirect URI per dashboard host.
* Each client secret is generated once, pushed to the vault, and read into every namespace
  that carries a policy as a Secret with `client-id` and `client-secret` keys.
* One `SecurityPolicy` per HTTPRoute, landed only after its Secret is Ready.
* Longhorn keeps its own client and group because its UI destroys data; a person who may read
  dashboards may not touch storage.

### Consequences

* Good, because six unauthenticated surfaces become one capability each, reviewable in the
  model and visible in the access matrix.
* Good, because Envoy stays a pure login gate; the gate group is enforced by the broker before
  a token exists.
* Bad, because the gateway is now load-bearing for authorization: a deleted policy exposes the
  route again. The access matrix lists every route with what authenticates it, and `none` is a
  finding.
* Bad, because a missing or wrong Secret yields HTTP 500 on the route until it is fixed, by
  design.

### Confirmation

1. Each of the six hosts redirects an unauthenticated request to
   `https://authentik.${SECRET_DOMAIN}/application/o/authorize/`.
2. A signed-in person outside `cluster-dashboards` is refused by Authentik at the gate; a
   member is let through.
3. `kubectl get securitypolicy -A` shows every policy `Accepted`.
4. The access matrix lists the six routes as authenticated at the gateway.

## Pros and Cons of the Options

### `SecurityPolicy` OIDC, one client per audience

* Good, because the mechanism is already proven on this gateway (ADR-0056) and the objects are
  four short manifests per route.
* Bad, because each audience is a client and a Secret to keep.

### Authentik proxy outpost as forward-auth

* Good, because it is Authentik's own answer and needs no gateway feature.
* Bad, because it adds a component to the request path whose failure mode is a forward-auth
  outage, and Envoy already does the job.

### oauth2-proxy sidecars

* Bad, because it is one deployment per application, each with its own configuration and
  upgrade cadence, for the same result.

### Accept LAN-only for a named list

* Bad, because the list would include the storage UI and the log store, which is where the
  risk is.

## More Information

* [RFC: The access plane](../rfc/rfc-access-plane.md) · [ADR-0058](adr-0058-access-plane-one-module-one-model.md)
  · [ADR-0056](adr-0056-searxng-public-behind-gateway-basic-auth.md) ·
  [RFC: Request authorization at the gateway](../rfc/rfc-request-authorization-envoy.md)
* 2026-09-14 — proposed; the clients land first, the policies once their Secrets are Ready.
