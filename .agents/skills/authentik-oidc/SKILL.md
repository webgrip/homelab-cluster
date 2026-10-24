---
name: authentik-oidc
description: Add SSO / OIDC login for an app via Authentik — an entry in the access-plane module plus a capability projection in the model, client secrets via ESO+OpenBao, exact redirect-URI matching, gateway OIDC for apps without a login.
when_to_use: Use when wiring an app to Authentik SSO, adding an OIDC client, putting a route behind the gateway's OIDC SecurityPolicy, or debugging an OIDC login failure or redirect-URI mismatch.
---

# Authentik OIDC onboarding

Authentik is reconciled by the access plane (ADR-0058): providers, applications, groups and
gate bindings are OpenTofu in `kubernetes/apps/security/access-plane/tofu/broker/`, driven by
the model in `kubernetes/apps/security/access-plane/model/`. Blueprints are gone except the
break-glass flow. Never create a provider in the admin UI; the next reconcile reverts it.

## Add an app with its own OIDC login
1. **Client secret — ESO+OpenBao, never SOPS.** Generate it in-cluster: an `ExternalSecret`
   in `kubernetes/apps/authentik/app/<app>-oidc-client.externalsecret.yaml` with
   `generatorRef` password-generator (`refreshInterval: "0"`, `deletionPolicy: Retain`),
   rewrite `password` → `client_secret`, and a `PushSecret` (store `openbao-push`) to
   `secret/<app>/oidc`. Register both in `authentik/app/kustomization.yaml`. Pattern:
   `harbor-oidc-client.{externalsecret,pushsecret}.yaml`.
2. **Provider + application** — one entry in `oauth_applications` in
   `tofu/broker/applications.tf`: `provider_name`, `client_id` (a literal slug, or the vault
   value when the app also reads its id from the vault), `client_secret` from
   `data.vault_kv_secret_v2.oidc_client[...]` (add the path to `data.tf`), `redirects` with the
   exact callback, `extra_scopes` (`groups` when the app maps groups to roles). Public client:
   `client_secret = null`, `client_type = "public"`. New entry: `adopt = false`.
3. **Runner policy** — `kubernetes/apps/security/openbao/bootstrap/access-plane.hcl` must read
   the vault path (`secret/data/+/oidc` covers `secret/<app>/oidc`).
4. **Authorization** — name the application in `projects.authentik.applications` of the
   capability that opens it, in `model/capabilities.yaml`. The module renders one group
   binding per projecting group, engine mode `any`. No binding means nobody gets in.
5. **App side** — discovery at
   `https://authentik.$${SECRET_DOMAIN}/application/o/<slug>/.well-known/openid-configuration`;
   an `ExternalSecret` (store `openbao`) reads `secret/<app>/oidc` for its credentials.
6. **Redirect URI** must match byte for byte; four callback shapes exist
   (`/oauth2/callback`, `/c/oidc/callback`, `/login/generic_oauth`, `/auth/openid/<key>`).

## Put an app without a login behind the gateway (ADR-0060)
1. Add a redirect URI `https://<host>.$${SECRET_DOMAIN}/oauth2/callback` to the right audience
   client (`cluster-dashboards` for read-only dashboards; a dedicated client for anything
   destructive) in `applications.tf`.
2. In the app namespace, an `ExternalSecret` templating `client-id` and `client-secret` from
   the client's vault path (`kubernetes/apps/observability/victoria-metrics/app/oidc.externalsecret.yaml`).
3. After that Secret is `Ready`, a `SecurityPolicy` with `oidc` targeting the HTTPRoute
   (`kubernetes/apps/longhorn-system/longhorn/app/securitypolicy-oidc.yaml`). Envoy fails
   closed (HTTP 500) while the Secret is missing, so order matters.
4. Authorization is the gate on the audience client, from the model, as above.

## Rotation
Delete the `<app>-oidc-client` Secret in `authentik`: it regenerates and re-pushes; the module
sets the provider on the next reconcile and the app's ExternalSecret refreshes.

## Debugging login failures (in order)
1. **Access plane** — `kubectl -n security get terraform access-broker`; a failed plan means
   Authentik does not have what Git says.
2. **Pod DNS** — can the app pod resolve `authentik.$${SECRET_DOMAIN}`? (split DNS,
   k8s-gateway `10.0.0.26`); restart pods after a DNS fix.
3. **Credentials** — app Secret and the vault path agree; the module reads the same path.
4. **Redirect URI** — compare the `redirect_uri` query parameter in the browser with the entry.
5. **Gate** — the person holds a capability whose projection names the application.

Refs: `docs/techdocs/docs/general/authentik.md`, `docs/techdocs/docs/runbooks/authentik-oidc-login.md`,
`docs/techdocs/docs/runbooks/access-model.md`.
