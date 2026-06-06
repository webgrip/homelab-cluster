# Runbook: Authentik OIDC login failures

Use this when you see "Failed to get token from provider", "Login failed", or a generic OAuth/OIDC error when logging into any app via Authentik.

## Dependency chain

```
Browser ──▶ App (Grafana/n8n/SearXNG/etc.) ──▶ Authentik OIDC (authorize/token/userinfo)
                 │                                    │
           needs DNS to resolve               needs to be reachable
           authentik.webgrip.dev              from the app's pod
```

Failures rarely come from Authentik itself. They usually come from the **app's pod not being able to reach Authentik**, or from **credential mismatches** between the app's OAuth config and the Authentik provider.

## Fast triage

### 1) Check the app's logs

The error message tells you exactly where it breaks:

```bash
# Grafana
kubectl logs -n observability deployment/grafana-deployment --tail=500 | grep -iE 'oauth|authentik|token|login.*fail'

# n8n
kubectl logs -n n8n deployment/n8n --tail=500 | grep -iE 'oauth|authentik|oidc'

# SearXNG
kubectl logs -n searxng deployment/searxng --tail=500 | grep -iE 'oauth|authentik|oidc'
```

### 2) Match the error to the cause

| Log line contains | Root cause |
|---|---|
| `dial tcp: lookup authentik.webgrip.dev: no such host` | **DNS**: pod cannot resolve Authentik. Go to [dns-split-dns](dns-split-dns.md). |
| `dial tcp: lookup authentik.webgrip.dev on ...: server misbehaving` | **DNS**: CoreDNS can't forward to k8s-gateway. Go to [dns-split-dns](dns-split-dns.md). |
| `connection refused` to `authentik.webgrip.dev:443` | **Envoy Gateway** not routing. Go to [envoy-gateway](envoy-gateway.md). |
| `invalid_client` or `client_id not found` | **Credential mismatch**: the `client_id` in the app secret doesn't match the Authentik provider. Check both. |
| `invalid_grant` or `redirect_uri mismatch` | **Redirect URI**: the app's configured redirect URI doesn't match the Authentik provider's `redirect_uris`. |
| `token exchange failed` after successful authorization | **client_secret wrong** or the app can't reach the token endpoint (DNS/network). |
| `failed to get userinfo` | The app can reach Authentik but the `api_url`/`userinfo_url` is wrong, or the token has insufficient scopes. |

### 3) Verify DNS (most common cause)

From the app's pod:

```bash
kubectl exec -n <app-ns> deployment/<app-name> -- nslookup authentik.webgrip.dev
```

Expected: resolves to `10.0.0.27` (Envoy Gateway LB IP).
If NXDOMAIN: go to [dns-split-dns](dns-split-dns.md).

### 4) Verify Authentik provider credentials match

Get the app's current client_id from Kubernetes:

```bash
# Grafana
kubectl get secret grafana-oauth -n observability -o jsonpath='{.data.GF_AUTH_GENERIC_OAUTH_CLIENT_ID}' | base64 -d && echo

# n8n (after secrets are created)
kubectl get secret n8n-oidc-secrets -n n8n -o jsonpath='{.data.N8N_USER_MANAGEMENT_AUTHENTICATION_OIDC_CLIENT_ID}' | base64 -d && echo
```

Get the Authentik provider's client_id:

```bash
# Via API (requires bootstrap token)
TOKEN=$(kubectl get secret authentik-secret -n authentik -o jsonpath='{.data.AUTHENTIK_BOOTSTRAP_TOKEN}' | base64 -d)
kubectl exec -n authentik deployment/authentik-server -- curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v3/providers/oauth2/?name=<provider-name>' | jq '.results[0].client_id'
```

These MUST match. If they don't, either:

- Update the Kubernetes secret with the correct value from Authentik
- Or regenerate the client_secret in Authentik and update both sides

### 5) Verify redirect URI

The app's redirect URI must **exactly match** what's configured in the Authentik provider:

| App | Expected redirect URI in Authentik |
|---|---|
| Grafana | `https://grafana.webgrip.dev/login/generic_oauth` |
| n8n | `https://n8n.webgrip.dev/rest/oauth2-credential/callback` |
| SearXNG | `https://searxng.webgrip.dev/auth/oauth/callback` |
| Backstage | `https://backstage.webgrip.dev/api/auth/oidc/handler/frame` |

Check in Authentik: **Admin → Applications → (app) → Provider → Redirect URIs**

### 6) Check Authentik itself

If DNS and credentials are fine, verify Authentik is healthy:

```bash
kubectl get pods -n authentik
kubectl logs -n authentik deployment/authentik-server --tail=100 | grep -i error
```

## Common fixes summary

| Problem | Fix |
|---|---|
| DNS NXDOMAIN | Add `webgrip.dev` zone to CoreDNS → [dns-split-dns](dns-split-dns.md) |
| Wrong client_id/secret | Copy from Authentik provider, update SOPS secret, reconcile |
| Redirect URI mismatch | Update Authentik provider's `redirect_uris` to match the app |
| Authentik not processing new blueprints | Restart worker pod (`kubectl rollout restart deployment/authentik-worker -n authentik`), then check logs for `blueprints_discovery` and `apply_blueprint` tasks. If tasks were enqueued but never started (Dramatiq queue stall), a second restart resolves it. |
| Token exchange fails after DNS fix | Restart app pod to pick up new DNS resolution |

## After a DNS fix

Even after fixing CoreDNS, existing app pods may cache the NXDOMAIN result. Restart the app pod:

```bash
kubectl rollout restart deployment/<app-name> -n <namespace>
```
