# Runbook: Authentik OIDC login failures

Use this when you see "Failed to get token from provider", "Login failed", or a generic
OAuth/OIDC error logging into an app via Authentik. **Authoring** a new provider (blueprints,
apply order, secret wiring) is the `authentik-oidc` skill — this page is triage only.

## Dependency chain

```text
Browser ──▶ App (Grafana/Backstage/Forgejo/Harbor/OpenBao) ──▶ Authentik OIDC (authorize/token/userinfo)
                 │                                                   │
           needs DNS to resolve                              needs to be reachable
           authentik.${SECRET_DOMAIN}                        from the app's pod
```

Failures rarely come from Authentik itself. They usually come from the **app's pod not being
able to reach Authentik**, or from **credential mismatches** between the app's OAuth config and
the Authentik provider.

## Fast triage

### 1) Check the app's logs

```bash
kubectl logs -n observability deployment/grafana-deployment --tail=500 | grep -iE 'oauth|authentik|token|login.*fail'
# same pattern for any other consumer (backstage, forgejo, harbor-core, …)
```

### 2) Match the error to the cause

| Log line contains | Root cause |
| --- | --- |
| `dial tcp: lookup authentik.<domain>: no such host` | **DNS**: pod cannot resolve Authentik. Go to [dns-split-dns](dns-split-dns.md). |
| `... on ...: server misbehaving` | **DNS**: CoreDNS can't forward to k8s-gateway. Go to [dns-split-dns](dns-split-dns.md). |
| `connection refused` to `authentik.<domain>:443` | **Envoy Gateway** not routing. Go to [envoy-gateway](envoy-gateway.md). |
| `invalid_client` or `client_id not found` | **Credential mismatch**: the app's `client_id` doesn't match the Authentik provider. Check both (below). |
| `invalid_grant` or `redirect_uri mismatch` | **Redirect URI**: must match the provider's `redirect_uris` **exactly**. |
| `token exchange failed` after successful authorization | **client_secret wrong**, or the app can't reach the token endpoint (DNS/network). |
| `failed to get userinfo` | Wrong `api_url`/`userinfo_url`, or insufficient scopes. |
| OpenBao OIDC login fails with a JWT/alg error | Provider fell back to **HS256** — pin an RS256 `signing_key` (see [ESO runbook gotchas](external-secrets.md#gotchas)). |

### 3) Verify DNS (most common cause)

```bash
kubectl exec -n <app-ns> deployment/<app-name> -- nslookup authentik.${SECRET_DOMAIN}
```

Expected: resolves to `10.0.0.27` (envoy-internal LB IP). NXDOMAIN → [dns-split-dns](dns-split-dns.md).

### 4) Verify Authentik provider credentials match

App side (example — Grafana):

```bash
kubectl get secret grafana-oauth -n observability -o jsonpath='{.data.GF_AUTH_GENERIC_OAUTH_CLIENT_ID}' | base64 -d && echo
```

Authentik side (via API, using the bootstrap token):

```bash
TOKEN=$(kubectl get secret authentik-secret -n authentik -o jsonpath='{.data.AUTHENTIK_BOOTSTRAP_TOKEN}' | base64 -d)
kubectl exec -n authentik deployment/authentik-server -- curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v3/providers/oauth2/?name=<provider-name>' | jq '.results[0].client_id'
```

These MUST match. If they don't: the client id/secret are **OpenBao-backed via ESO** (e.g.
`grafana-oauth` ← OpenBao `grafana/oauth`). Fix by writing the correct value to the OpenBao path
and force-syncing the ExternalSecret — the [secret-rotation runbook](secret-rotation.md) is the
exact procedure. Do not hand-edit the Kubernetes Secret; ESO owns it.

### 5) Verify redirect URI

The app's redirect URI must **exactly match** the Authentik provider (Admin → Applications →
(app) → Provider → Redirect URIs). Canonical values live in the provider blueprints
(`kubernetes/apps/authentik/app/blueprints/3x-oidc-<app>.yaml`); the two most-debugged:

| App | Redirect URI in Authentik |
| --- | --- |
| Grafana | `https://grafana.${SECRET_DOMAIN}/login/generic_oauth` |
| Backstage | `https://backstage.${SECRET_DOMAIN}/api/auth/oidc/handler/frame` |

### 6) Check Authentik itself

```bash
kubectl get pods -n authentik
kubectl logs -n authentik deployment/authentik-server --tail=100 | grep -i error
```

## Common fixes summary

| Problem | Fix |
| --- | --- |
| DNS NXDOMAIN | Add the `${SECRET_DOMAIN}` zone forward to CoreDNS → [dns-split-dns](dns-split-dns.md) |
| Wrong client_id/secret | Write the provider's value to the OpenBao path behind the app's ExternalSecret, force-sync → [secret-rotation](secret-rotation.md) |
| Redirect URI mismatch | Fix the provider blueprint's `redirect_uris` (commit) — `authentik-oidc` skill |
| Authentik not processing new blueprints | Restart worker (`kubectl rollout restart deployment/authentik-worker -n authentik` — human step, hook-blocked for agents), then check logs for `blueprints_discovery` / `apply_blueprint`. If tasks were enqueued but never started (Dramatiq queue stall), a second restart resolves it. |
| Token exchange fails after a DNS fix | Restart the app pod — it may cache the NXDOMAIN (`kubectl rollout restart deployment/<app> -n <ns>` — human step, hook-blocked for agents) |

> n8n has **no** OIDC: native SSO is Enterprise-license-gated and the old
> `N8N_USER_MANAGEMENT_AUTHENTICATION_*` config was a silent no-op — removed 2026-06-30.
