# Authenticating Prometheus & Alertmanager (Envoy Gateway OIDC)

> Status: **DESIGN / ready-to-apply, NOT yet wired** (roadmap #23 / #24).
> This is the one P0 item that cannot be landed as a single offline commit: it
> needs an Authentik client credential and live OIDC-flow testing, and a
> misconfigured `SecurityPolicy` can lock you out of Prometheus. Apply it
> deliberately, with the cluster in front of you.

## Why

`prometheus.${SECRET_DOMAIN}` and `alertmanager.${SECRET_DOMAIN}` attach to
`envoy-internal` (LAN-only) but have **no authentication** — anyone on the LAN
reaches them. Grafana already has its own login; these two do not. Unlike apps
with a login UI, Prometheus/Alertmanager are plain HTTP, so auth must be enforced
at the gateway via an Envoy Gateway **`SecurityPolicy`** (OIDC), not app-level OIDC.

There is currently **no `SecurityPolicy` precedent** in this repo — this is the
first one. Roll it out behind one host first, verify, then extend (the #24
auth-matrix sweep covers Longhorn, Policy Reporter, OpenBao UI, Backstage).

## Pieces required

1. **Authentik OIDC provider + application** — a blueprint modeled on
   `kubernetes/apps/authentik/app/blueprints/30-oidc-grafana.yaml`, e.g.
   `40-oidc-observability.yaml`, with:
   - `client_type: confidential`
   - redirect URI `https://prometheus.${SECRET_DOMAIN}/oauth2/callback`
     (and an Alertmanager entry, or a wildcard app per host)
   - a group restriction (e.g. `homelab-admins`) so only admins pass.
   - Register the filename in `authentik/app/kustomization.yaml`
     (`configMapGenerator`).

2. **Client secret** — generate via the OpenBao password-generator and store at
   `secret/observability/oidc` so both sides read the same value (no plaintext in
   git):
   - Authentik side: set `client_id` + `client_secret` on the provider via the
     blueprint (sourced from the secret), instead of letting Authentik
     auto-generate, so the value is GitOps-owned.
   - Envoy side: an `ExternalSecret` in `network` (or `observability`) projecting
     `clientID` / `clientSecret` keys for the `SecurityPolicy` to reference.

3. **Envoy Gateway `SecurityPolicy`** (one per host, or a `targetRefs` list)
   attaching to the HTTPRoutes `prometheus` and `alertmanager`:

   ```yaml
   apiVersion: gateway.envoyproxy.io/v1alpha1
   kind: SecurityPolicy
   metadata:
     name: observability-oidc
     namespace: observability
   spec:
     targetRefs:
       - group: gateway.networking.k8s.io
         kind: HTTPRoute
         name: prometheus
       - group: gateway.networking.k8s.io
         kind: HTTPRoute
         name: alertmanager
     oidc:
       provider:
         issuer: "https://authentik.${SECRET_DOMAIN}/application/o/observability/"
       clientID: "<from ExternalSecret>"
       clientSecret:
         name: observability-oidc        # Secret in the same namespace
       redirectURL: "https://prometheus.${SECRET_DOMAIN}/oauth2/callback"
       logoutPath: "/logout"
   ```

   > `SecurityPolicy` must live in the same namespace as the target HTTPRoute, and
   > Envoy Gateway must be allowed to reference the client-secret Secret.

## Apply procedure (with the cluster in front of you)

1. Land the Authentik blueprint first; wait for it to reconcile (~10m) and
   confirm the provider/application exist in the Authentik admin UI.
2. Populate `secret/observability/oidc` in OpenBao; confirm the `ExternalSecret`
   goes Ready and the Envoy-side Secret materialises.
3. Apply the `SecurityPolicy` for **Prometheus only** first.
4. From a browser, hit `https://prometheus.${SECRET_DOMAIN}` → expect an Authentik
   redirect → login → back to Prometheus. From an unauthenticated client, expect
   401/redirect.
5. Only then extend the policy to Alertmanager, and proceed with the #24 sweep.

## Rollback

Delete/Revert the `SecurityPolicy` (the HTTPRoutes revert to open immediately on
reconcile). The blueprint and secret are inert without the policy.

## Gotchas

- Pod DNS / split-DNS: the gateway must resolve the Authentik issuer host
  (see [dns-split-dns.md](dns-split-dns.md)).
- Redirect URI must match the Authentik provider **exactly**.
- Don't ship the `SecurityPolicy` before the client secret exists, or the OIDC
  filter fails closed and the route is unreachable.
