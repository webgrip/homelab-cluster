# Authentik

Authentik is the identity broker, in the `authentik` namespace: Flux installs the
`goauthentik/authentik` chart, CloudNativePG owns its database, Envoy Gateway serves it at
`https://authentik.${SECRET_DOMAIN}` on the LAN. Every application signs people in through it,
and it signs people in through Google Workspace and nothing else
([ADR-0057](../adr/adr-0057-google-only-login-closed-enrolment.md)).

## What configures it

Nothing in Authentik is configured by hand or by blueprint any more, with one exception. The
[access plane](../runbooks/access-plane.md) reconciles it from
`kubernetes/apps/security/access-plane/`: the Google source, the login flow and brand, every
user, every group and its members, every OIDC provider and application, the group bindings
that gate each application, and the scope mappings
([ADR-0058](../adr/adr-0058-access-plane-one-module-one-model.md)).

| What | Comes from |
| --- | --- |
| Users and their group membership | `model/people.yaml`, through roles and grants |
| Groups | every group a capability projects onto in `model/capabilities.yaml` |
| Which groups open which application | `projects.authentik.applications` on the capability |
| OIDC providers and applications | `tofu/broker/applications.tf` |
| Google source, Google-only flow, brand | `tofu/broker/google.tf` |
| Client secrets | the vault, at the same path the application reads them from |
| The password flow `homelab-authentication` and its MFA stages | the one remaining blueprint, `app/blueprints/20-flows-mfa-auth.yaml` |

The blueprint is kept because that flow is the break-glass door: it is reachable at
`/if/flow/homelab-authentication/` for `akadmin` and linked from nowhere.
Since 2026-09-15 an expression policy on the flow's login stage admits `akadmin` and nobody else,
so a rostered person's leftover local password opens nothing; the Google door is their only one.

## Two login pages, on purpose

- `https://authentik.${SECRET_DOMAIN}/` shows one control, Sign in with Google. A person who is
  not in `people.yaml` is refused after Google succeeds; there is no enrolment.
- `https://authentik.${SECRET_DOMAIN}/if/flow/homelab-authentication/` still takes a username,
  a password and an authenticator. Only `akadmin` has those, and its password is in the vault
  at `secret/authentik/app`. Use it when Google or the access plane is broken.

MFA is Google's, enforced in the Workspace admin console. Authentik carries no MFA policy.

## GitOps layout

- Flux Kustomizations: `kubernetes/apps/authentik/ks.yaml`, `kubernetes/apps/authentik/database/ks.yaml`
- HelmRelease: `kubernetes/apps/authentik/app/helmrelease.yaml`
- CNPG cluster: `kubernetes/apps/authentik/app/database/cluster.yaml`
- Network policy: `kubernetes/apps/authentik/app/networkpolicy.yaml`, which admits the
  access-plane runner from `security` and lets Authentik reach Google on 443
- Dashboard and rules: `kubernetes/apps/observability/grafana/app/dashboards/security-authentik.yaml`,
  `kubernetes/apps/observability/victoria-metrics/app/rules/prometheusrule-security-authentik.yaml`
- Login canary: the `blackbox-authentik-login` probe and the `AuthentikLoginFlowBroken` alert

## Adding an OIDC application

1. Add the application to `oauth_applications` in `tofu/broker/applications.tf`: provider name,
   client id, where the client secret lives in the vault, redirect URIs, which scope mappings
   it needs. A public client has `client_secret = null`.
2. If the secret is generated, add an ExternalSecret and PushSecret pair next to
   `harbor-oidc-client.externalsecret.yaml` so the value lands in the vault once, and give the
   runner's policy (`openbao/bootstrap/access-plane.hcl`) read on that path.
3. Name the application in the `applications` list of the capability that should open it, in
   `model/capabilities.yaml`. That is the whole authorization; the gate bindings follow.
4. Configure the application against
   `https://authentik.${SECRET_DOMAIN}/application/o/<slug>/.well-known/openid-configuration`
   with the same vault path for its credentials.

DNS prerequisite: the application pod must resolve `authentik.${SECRET_DOMAIN}`; see the
[split-DNS runbook](../runbooks/dns-split-dns.md).

## Retrieving OIDC credentials

The module sets a provider's client secret from the vault, so the vault is the answer:

```sh
export BAO_ADDR="$(mise exec -- just bao-addr)"
mise exec -- bao login -method=oidc
mise exec -- bao kv get secret/<app>/oidc
```

The OpenBao client is the exception: Authentik generated its secret and the module reads it
from the provider resource into the OpenBao auth mount, so it exists in no vault path.

## Operations

```sh
mise exec -- flux get kustomizations -n authentik authentik-db authentik
mise exec -- flux get helmreleases -n authentik authentik
mise exec -- kubectl get pods -n authentik -l app.kubernetes.io/instance=authentik
mise exec -- kubectl get cluster -n authentik authentik-db
mise exec -- kubectl -n security get terraform access-broker
```

The media PVC is `authentik-media`; expand it and Longhorn grows the volume. Login failures:
[Authentik OIDC login runbook](../runbooks/authentik-oidc-login.md). A group or user changed
by hand in the admin UI is reverted on the next reconcile.
