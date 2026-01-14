# Adding Self-hosted Applications

This repo is GitOps-first: **you add apps by adding manifests under `kubernetes/apps/**`, and Flux applies them**.

The platform gives you a few standard building blocks:

- **Ingress:** Gateway API via Envoy Gateway (`envoy-internal` and `envoy-external` in the `network` namespace)
- **DNS:**
  - Internal split DNS via `k8s-gateway` (answers `${SECRET_DOMAIN}` inside the LAN)
  - External DNS automation to Cloudflare via `cloudflare-dns` (ExternalDNS)
- **TLS:** cert-manager issues certs used by Envoy gateways
- **Secrets:** SOPS (Age) encrypted secrets decrypted in-cluster by Flux
- **Storage:** Longhorn (StorageClasses like `longhorn-general`, plus `longhorn` used by CNPG clusters)
- **Databases:** CloudNativePG operator (CNPG) for in-cluster Postgres

## Quick decision guide

Pick the simplest approach that fits:

1. **Most apps:** HelmRelease using `app-template` (bjw-s) + optional `HTTPRoute`
2. **Apps with bespoke manifests:** plain YAML + Kustomize (as in `invoiceninja`)
3. **Apps needing Postgres:** add a CNPG `Cluster` in the app namespace
4. **Apps needing Redis/Valkey:** add a small StatefulSet + Service in-namespace

## Standard repo pattern

A typical app namespace looks like this:

- `kubernetes/apps/<namespace>/namespace.yaml`
- `kubernetes/apps/<namespace>/kustomization.yaml` (Kustomize root for that namespace)
- `kubernetes/apps/<namespace>/<app>/ks.yaml` (Flux Kustomization pointing at `.../<app>/app`)
- `kubernetes/apps/<namespace>/<app>/app/*` (actual Kubernetes resources)

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

## Storage (Longhorn)

- Prefer Longhorn for PVC-backed apps.
- Use existing StorageClasses already defined under `kubernetes/apps/longhorn-system/longhorn/storageclass/`.

Rules of thumb:

- Use `longhorn-general` for typical RWO PVCs.
- Use `longhorn-rwx` only if you truly need RWX.

## Checklist for a new app PR

- New namespace folder exists under `kubernetes/apps/<namespace>/`.
- Namespace `kustomization.yaml` includes `../../components/sops`.
- App `ks.yaml` uses `substituteFrom: cluster-secrets`.
- Ingress is defined (either `HTTPRoute` or `route:` values) and points at the correct gateway.
- PVCs specify the intended StorageClass.
- Secrets are SOPS-encrypted and referenced via `envFrom` / `secretKeyRef`.

## Observability checklist

For details, see [docs/techdocs/docs/observability.md](observability.md).

- Logs: app writes to stdout/stderr (structured logs preferred)
- Traces: set OTLP exporter to `alloy-gateway.observability.svc.cluster.local` (4317/4318)
- Metrics: expose `/metrics` and add a `ServiceMonitor`
- Alerts (optional): add `PrometheusRule` + route via Alertmanager
