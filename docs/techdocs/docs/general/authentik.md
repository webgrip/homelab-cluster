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

MFA is Google's, enforced in the Workspace admin console. Two applications add a step of their own:
`unfold-headscale`, the Unfold tailnet's browser login, and `unfold-kubernetes`, the Unfold
Kubernetes API login (kubelogin, Headlamp). Both set `passkey_required` in `applications.tf`, which
gives them the authorization flow `webgrip-passkey-authorization` (`tofu/broker/passkey.tf`). That
flow accepts only a WebAuthn passkey or security key with user verification, every time it runs,
and refuses a person who has none. People enroll one under
**Settings → MFA Devices → Passkey or security key** (flow `webgrip-passkey-setup`). The flow runs
on every browser authorization, not on a refresh: kubelogin renews a Kubernetes token with its
refresh token (12 hours) without asking again. `tofu/broker/tests/passkey.tftest.hcl` checks the
flow and which applications get it, with mocked providers (`mise exec -- tofu test` in
`tofu/broker`).

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

## The one public path: the Unfold cluster's signing keys

Authentik answers on the LAN only, with one exception. The Unfold production cluster on Hetzner
signs people in to its Kubernetes API with the public client `unfold-kubernetes`, and its API
servers fetch that provider's discovery document and signing keys themselves. The Cloudflare
tunnel publishes `authentik.${SECRET_DOMAIN}` for exactly two paths,
`/application/o/unfold-kubernetes/.well-known/openid-configuration` and
`/application/o/unfold-kubernetes/jwks/`, and answers 404 to every other path on that name
before the request reaches the cluster. Both documents are public by design: they hold the
endpoints and the public half of the signing key. The login itself, the authorize and token
endpoints, stays on the LAN and the VPN: k8s-gateway answers the name with envoy-internal
there, and only off-LAN resolvers see the tunnel.

The Unfold cluster's operations consoles sign in here too, over the Unfold tailnet: Headlamp uses
the same public client `unfold-kubernetes` (redirect `https://headlamp.ops.unfoldhq.dev/oidc-callback`),
so its API calls carry the person's own token and Unfold's RBAC; Hubble UI and Policy Reporter sit
behind oauth2-proxy with the confidential client `unfold-consoles`, whose secret is generated here and
pushed to `authentik/unfold-consoles-oidc` and `unfold-main/ops-consoles/oidc`. Both read the
`unfold_kubernetes` scope, so only `unfold-admins` and `unfold-viewers` get in. Their token
exchanges reach Authentik through the Unfold gateway's 443 (unfold-cluster
`docs/runbooks/ops-consoles.md`).

| Piece | Where |
| --- | --- |
| Public record | `kubernetes/apps/network/cloudflare-tunnel/app/dnsendpoint.yaml` |
| Path allowlist | the `authentik.${SECRET_DOMAIN}` rules in the tunnel's `config.yaml`, above the wildcard |
| Client, scope `unfold_kubernetes` with claim `unfold_groups` | `tofu/broker/applications.tf` |
| Groups `unfold-admins` and `unfold-viewers` | capabilities `unfold-cluster-operate` and `unfold-cluster-view` |
| The cluster side | `webgrip/unfold-cluster`, `docs/runbooks/kubernetes-login.md` |

Check it as the internet sees it, through a public resolver:

```sh
curl -s --doh-url https://1.1.1.1/dns-query https://authentik.${SECRET_DOMAIN}/application/o/unfold-kubernetes/jwks/
curl -s -o /dev/null -w '%{http_code}\n' --doh-url https://1.1.1.1/dns-query https://authentik.${SECRET_DOMAIN}/application/o/authorize/
```

The first prints a key set; the second must print `404`.

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
