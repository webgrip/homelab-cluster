# Adding Self-hosted Applications

This repo is GitOps-first: **you add apps by adding manifests under `kubernetes/apps/**`, and Flux applies them**.

The platform gives you a few standard building blocks:

- **Ingress:** Gateway API via Envoy Gateway (`envoy-internal` and `envoy-external` in the `network` namespace)
- **DNS:**
  - Internal split DNS via `k8s-gateway` (answers `${SECRET_DOMAIN}` inside the LAN)
  - External DNS automation to Cloudflare via `cloudflare-dns` (ExternalDNS)
- **TLS:** cert-manager issues certs used by Envoy gateways
- **Authentication:** Authentik SSO with OIDC for apps that support it — see [Authentication (Authentik OIDC)](#authentication-authentik-oidc)
- **Secrets:** SOPS (Age) encrypted secrets decrypted in-cluster by Flux
- **Storage:** Longhorn (StorageClasses like `longhorn-general`, plus `longhorn` used by CNPG clusters)
- **Databases:** CloudNativePG operator (CNPG) for in-cluster Postgres

## Quick decision guide

Pick the simplest approach that fits:

1. **Most apps:** HelmRelease using `app-template` (bjw-s) + optional `HTTPRoute`
2. **Apps with bespoke manifests:** plain YAML + Kustomize (as in `invoiceninja`)
3. **Apps needing Postgres:** add a CNPG `Cluster` in the app namespace
4. **Apps needing Redis/Valkey:** add a small StatefulSet + Service in-namespace
5. **Apps supporting OIDC login:** add an Authentik blueprint + SOPS secret — see [Authentication (Authentik OIDC)](#authentication-authentik-oidc)

## Standard repo pattern

A typical app namespace looks like this:

```
kubernetes/apps/<namespace>/
├── namespace.yaml
├── kustomization.yaml                # Kustomize root for that namespace
├── <app>/
│   ├── ks.yaml                       # Flux Kustomization -> ./app
│   └── app/
│       ├── kustomization.yaml
│       ├── helmrelease.yaml           # or deployment.yaml, service.yaml, etc.
│       ├── httproute.yaml             # ingress via Envoy Gateway
│       ├── <app>-secrets.sops.yaml    # SOPS-encrypted secrets (db, API keys)
│       ├── <app>-oidc-secrets.template.yaml   # OIDC secret template (optional)
│       └── database/
│           └── cluster.yaml           # CNPG Postgres cluster (optional)
```

And if the app supports OIDC, a parallel entry goes in the Authentik blueprints directory:

```
kubernetes/apps/authentik/app/blueprints/
├── 30-oidc-grafana.yaml              # example of existing blueprint
└── <nn>-oidc-<app>.yaml              # add yours here
```

The Flux `Kustomization` usually includes:

- `postBuild.substituteFrom: cluster-secrets` so `${SECRET_DOMAIN}` is available
- `dependsOn` when the app needs a platform service (e.g. CNPG)

## Option A (recommended): app-template HelmRelease

Many apps in this repo use the bjw-s `app-template` chart from OCI. The pattern is:

- `OCIRepository` pointing to `oci://ghcr.io/bjw-s-labs/helm/app-template`
- `HelmRelease` that configures:
  - `controllers` (containers, env, resources)
  - `service` (ports)
  - `persistence` (PVC mounts)
  - `route` (Gateway API hostnames / parentRefs)

Examples in this repo:

- FreshRSS: `kubernetes/apps/freshrss/freshrss/app/helmrelease.yaml`
- SearXNG: `kubernetes/apps/searxng/searxng/app/helmrelease-app.yaml`
- SparkyFitness: `kubernetes/apps/sparkyfitness/sparkyfitness/app/helmrelease.yaml`

### Ingress (route) choices

- **Internal only:** parentRefs → `envoy-internal` / `sectionName: https`
- **Public:** parentRefs → `envoy-external` / `sectionName: https`

Example (internal):

```yaml
route:
  app:
    hostnames: ["myapp.${SECRET_DOMAIN}"]
    parentRefs:
      - name: envoy-internal
        namespace: network
        sectionName: https
    rules:
      - backendRefs:
          - identifier: app
            port: 8080
```

## Option B: Raw manifests + Kustomize

If an app doesn't fit a Helm chart cleanly, keep it as plain YAML under `.../app/` and include it via a `kustomization.yaml`.

Example: Invoice Ninja is assembled from Deployments/Services/ConfigMaps + PVCs under `kubernetes/apps/invoiceninja/invoiceninja/app/`.

## Databases (Postgres) via CNPG

If an app needs Postgres:

1. Ensure CNPG is installed (`kubernetes/apps/cnpg-system/cloudnative-pg`).
2. Add a `postgresql.cnpg.io/v1` `Cluster` resource in your app's namespace.
3. Reference the generated `*-app`/`*-rw` services from your application.

Examples of CNPG clusters in this repo:

- `kubernetes/apps/freshrss/freshrss/app/database/cluster.yaml`
- `kubernetes/apps/backstage/backstage/app/database/cluster.yaml`
- `kubernetes/apps/sparkyfitness/sparkyfitness/app/database/cluster.yaml`

Backups are optional and depend on having an S3-compatible endpoint configured; see [docs/techdocs/docs/cnpg-backups.md](cnpg-backups.md).

## Secrets (SOPS)

- Encrypt secrets with SOPS (Age). Commit only `*.sops.yaml`.
- The cluster-wide values (like `${SECRET_DOMAIN}`) come from `cluster-secrets`.

Important: do not commit any decrypted artifacts (for example `*.decrypted~*.yaml`).

### OIDC secret template

If the app supports OIDC (see next section), also create a **plaintext template** for the OIDC credentials file alongside your SOPS secrets:

```bash
cp <app>-oidc-secrets.template.yaml <app>-oidc-secrets.sops.yaml
# Fill in client_id and client_secret from Authentik, then:
sops -e -i <app>-oidc-secrets.sops.yaml
```

The template file (`*.template.yaml`) documents the required keys so the next person knows what to fill in — commit it as-is (no encryption). The encrypted copy (`*.sops.yaml`) is what goes in the Kustomize resources list.

## Authentication (Authentik OIDC)

For apps that support OIDC login, wire them to the cluster's Authentik instance.

### Prerequisites

- Authentik must be deployed and healthy (`kubectl get pods -n authentik`)
- The app's pod must be able to resolve `authentik.webgrip.dev` (DNS via CoreDNS → k8s-gateway). If not, see the [dns-split-dns runbook](runbooks/dns-split-dns.md).

### Step 1: Create an Authentik OIDC blueprint

Create `kubernetes/apps/authentik/app/blueprints/<nn>-oidc-<appname>.yaml`. Copy the pattern from any existing `3x-oidc-*.yaml`. The blueprint creates:

- An `oauth2provider` with `authorization_code` grant type
- An `application` linked to that provider
- `policybinding` entries for `homelab-users-only` and `homelab-mfa-required`

Key template variables in the `context` block:

| Variable | Purpose |
|---|---|
| `app_host` | Subdomain (e.g., `n8n`, `searxng`) |
| `redirect_path` | App's OAuth callback path (check the app's docs) |

### Step 2: Register in the Authentik kustomization

Add the new blueprint filename to the `configMapGenerator.files` list in `kubernetes/apps/authentik/app/kustomization.yaml`.

### Step 3: Configure the app for OIDC

Add OIDC environment variables to the app's ConfigMap/HelmRelease. Non-secret values (discovery URL, endpoints) go in ConfigMaps. Client credentials (`client_id`, `client_secret`) go in a **SOPS-encrypted Secret**.

App-side secret template pattern:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <appname>-oidc-secrets
  namespace: <app-namespace>
type: Opaque
stringData:
  <APP>_OIDC_CLIENT_ID: "<from-authentik>"
  <APP>_OIDC_CLIENT_SECRET: "<from-authentik>"
```

Wire it in the HelmRelease/Deployment via `secretRef` in `envFrom`.

### Step 4: Get credentials from Authentik

After Flux reconciles the blueprint (up to 10 min for Authentik to process it):

```bash
TOKEN=$(mise exec -- kubectl get secret authentik-secret -n authentik -o jsonpath='{.data.AUTHENTIK_BOOTSTRAP_TOKEN}' | base64 -d)
mise exec -- kubectl exec -n authentik deployment/authentik-server -- \
  curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v3/providers/oauth2/?name=<appname>-oidc' | jq '.results[0] | {client_id, client_secret}'
```

Fill these into the SOPS secret template, encrypt, and commit.

### Apps that don't support native OIDC

Some apps don't have native OIDC support. Known apps in this repo:

| App | Alternative |
|---|---|
| FreshRSS | Proxy provider or forward auth |
| Invoice Ninja | Proxy provider or forward auth (could add via `socialiteproviders/oidc` Laravel package with custom image build) |
| SearXNG | Proxy provider or forward auth — no OIDC env vars exist in the application |

For these, consider:

- **Proxy provider**: Place the app behind an Authentik outpost proxy with header-based auth
- **Forward auth**: Use a reverse proxy to check Authentik session before forwarding requests

This is more complex than native OIDC and requires additional infrastructure.

## Storage (Longhorn)

- Prefer Longhorn for PVC-backed apps.
- Use existing StorageClasses already defined under `kubernetes/apps/longhorn-system/longhorn/storageclass/`.

Rules of thumb:

- Use `longhorn-general` for typical RWO PVCs.
- Use `longhorn-rwx` only if you truly need RWX.

## Checklist for a new app PR

### Foundation

- [ ] New namespace folder exists under `kubernetes/apps/<namespace>/`.
- [ ] Namespace `kustomization.yaml` includes `../../components/sops`.
- [ ] App `ks.yaml` uses `substituteFrom: cluster-secrets`.
- [ ] Ingress is defined (either `HTTPRoute` or `route:` values) and points at the correct gateway (`envoy-internal` or `envoy-external`).
- [ ] PVCs specify the intended StorageClass.
- [ ] All secrets are SOPS-encrypted (`*.sops.yaml`) and referenced via `envFrom` / `secretKeyRef`.

### If the app supports OIDC

- [ ] **Authentik blueprint** created at `kubernetes/apps/authentik/app/blueprints/<nn>-oidc-<app>.yaml` (copy from existing `3x-oidc-*.yaml`).
- [ ] Blueprint **registered** in the `configMapGenerator.files` list in `kubernetes/apps/authentik/app/kustomization.yaml`.
- [ ] **OIDC env vars** (discovery URL, endpoint URLs) added to the app's ConfigMap or HelmRelease values.
- [ ] **OIDC secret template** created at `<app>/<app>-oidc-secrets.template.yaml` documenting the required keys.
- [ ] **OIDC secret ref** wired into the HelmRelease/Deployment via `envFrom` → `secretRef`.
- [ ] **DNS check:** `authentik.webgrip.dev` resolves from the app namespace (or the CoreDNS zone forward is in place — see [dns-split-dns runbook](runbooks/dns-split-dns.md)).

### If the app needs a database

- [ ] CNPG `Cluster` resource added under `<app>/app/database/cluster.yaml` (or a separate Flux Kustomization for database-heavy apps).
- [ ] Database credentials wired via the auto-generated `*-app` secret (not a SOPS secret).

## Observability checklist

For details, see [docs/techdocs/docs/observability.md](observability.md).

- Logs: app writes to stdout/stderr (structured logs preferred)
- Traces: set OTLP exporter to `alloy-gateway.observability.svc.cluster.local` (4317/4318)
- Metrics: expose `/metrics` and add a `ServiceMonitor`
- Alerts (optional): add `PrometheusRule` + route via Alertmanager
