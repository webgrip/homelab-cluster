# Applications

This page documents the **self-hosted applications and UIs deployed by this repo**, where they live (namespace), and how they are exposed.

> Naming convention: `${SECRET_DOMAIN}` is injected via the `cluster-secrets` Secret from `kubernetes/components/sops/cluster-secrets.sops.yaml`.

## Access model

- **Internal (LAN-only)** apps generally use `Gateway` **envoy-internal** and get hostnames like `app.${SECRET_DOMAIN}`.
- **External (public)** apps use `Gateway` **envoy-external**. Public access is typically via Cloudflare Tunnel (`cloudflare-tunnel`) terminating at Cloudflare and forwarding to `envoy-external` inside the cluster.

## Published endpoints

| App / UI | Namespace | Exposure | Hostname | Backing services / notes |
| --- | --- | --- | --- | --- |
| Weave GitOps UI | `flux-system` | Internal | `gitops.${SECRET_DOMAIN}` | Flux UI for reconciliation, drift, and sources. |
| Flux webhook receiver | `flux-system` | External | `flux-webhook.${SECRET_DOMAIN}` | Receives GitHub webhooks at `/hook/` to trigger reconciles. |
| Longhorn dashboard | `longhorn-system` | Internal | `longhorn.${SECRET_DOMAIN}` | Longhorn UI (storage). |
| Backstage | `backstage` | Internal | `backstage.${SECRET_DOMAIN}` | Backstage app + a CNPG Postgres cluster in-namespace. |
| FreshRSS | `freshrss` | Internal | `freshrss.${SECRET_DOMAIN}` | FreshRSS app-template + a CNPG Postgres cluster in-namespace. |
| SearXNG | `searxng` | Internal | `searxng.${SECRET_DOMAIN}` | SearXNG app-template + a Valkey StatefulSet (`searxng-valkey`). |
| SparkyFitness | `sparkyfitness` | Internal | `sparkyfitness.${SECRET_DOMAIN}` | Two controllers (frontend + server) via app-template; CNPG Postgres in-namespace. |
| Echo (test) | `default` | External | `echo.${SECRET_DOMAIN}` | Simple HTTP echo service, useful for ingress/DNS validation. |
| Invoice Ninja | `invoiceninja` | External | `invoice.webgrip.dev` | Custom manifests (nginx + app + MariaDB). Not tied to `${SECRET_DOMAIN}`.

## Where to look in Git

- Namespaces and app definitions live under `kubernetes/apps/<namespace>/`.
- Most apps are deployed via:
  - Flux `Kustomization` resources (`kubernetes/apps/**/ks.yaml`)
  - `HelmRelease` resources (often using an `OCIRepository` source)
  - `HTTPRoute` resources for Gateway API ingress

If you need to add or change an app, see [docs/techdocs/docs/adding-applications.md](adding-applications.md).
