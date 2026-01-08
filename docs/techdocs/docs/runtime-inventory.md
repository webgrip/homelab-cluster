# Runtime Inventory

This repo deploys workloads through Flux under `kubernetes/apps/**`. This page answers two questions:

1. What is supposed to be running (per Git)
2. How to confirm what is running (per cluster)

## Deployed namespaces (source of truth)

These namespaces are managed by this repo:

| Namespace | Purpose |
| --- | --- |
| `arc-systems` | GitHub Actions Runner Controller + scale set runners. |
| `backstage` | Backstage + CNPG Postgres in-namespace. |
| `cert-manager` | Cluster-wide certificate issuance and issuers. |
| `cnpg-system` | CloudNativePG operator (Postgres controller). |
| `default` | Demo/test workloads (e.g. `echo`). |
| `flux-system` | Flux controllers, webhook receiver, and Weave GitOps UI. |
| `freshrss` | FreshRSS + CNPG Postgres in-namespace. |
| `invoiceninja` | Invoice Ninja stack (custom manifests + MariaDB). |
| `kube-system` | Core cluster add-ons (Cilium, CoreDNS, metrics-server, reloader, spegel). |
| `longhorn-system` | Longhorn storage system + StorageClasses. |
| `network` | Envoy Gateway, Cloudflare tunnel + DNS automation, split-DNS (`k8s-gateway`). |
| `searxng` | SearXNG + Valkey cache. |
| `sparkyfitness` | SparkyFitness frontend/server + CNPG Postgres in-namespace. |

For app entrypoints (hostnames), see [docs/techdocs/docs/applications.md](applications.md).

## How to refresh the live snapshot

When you want a point-in-time “what is running” snapshot, capture:

```bash
kubectl get nodes -o wide
kubectl get pods -A -o wide
kubectl get svc -A
kubectl get httproute -A
kubectl get gateway -A
```

If you need to validate ingress end-to-end, focus on:

```bash
kubectl -n network get svc envoy-internal envoy-external k8s-gateway -o wide
kubectl -n network get gateway envoy-internal envoy-external -o yaml
kubectl get httproute -A
```

## Common “is it wired?” checks

- DNS-internal: `k8s-gateway` is a `LoadBalancer` on `10.0.0.26:53/udp`.
- Ingress-internal: `envoy-internal` is a `LoadBalancer` on `10.0.0.27`.
- Ingress-external: `envoy-external` is a `LoadBalancer` on `10.0.0.28` and is the origin for Cloudflare Tunnel.
- Certificates: both gateways reference `${SECRET_DOMAIN/./-}-production-tls` in `network`.
