# Platform Components

This page enumerates the controllers and gateways that are actually deployed by this repository so the Backstage catalog and TechDocs stay aligned.

## GitOps + Talos Integration

- `kubernetes/apps/flux-system/` keeps Flux controllers (`flux-instance`, `flux-operator`) and the optional GitOps UI. All components reconcile from this repo's `main` branch.
- Talos machine definitions live under `talos/clusterconfig/` with patches in `talos/patches/`. Every change should be applied with `talosctl apply-config` after it lands in Git.
- Secrets are encrypted via SOPS (`.sops.yaml`) and injected during reconciliation using the values under `kubernetes/components/sops/`.

## Networking + Access

| Endpoint | Purpose | Source | Address |
| --- | --- | --- | --- |
| `cluster_api_addr` | Talos and Kubernetes API VIP | `cluster.yaml` | `10.0.0.25` |
| `cluster_dns_gateway_addr` | `k8s-gateway` LoadBalancer for split DNS | `cluster.yaml`, `kubernetes/apps/network/k8s-gateway` | `10.0.0.26` |
| `cluster_gateway_addr` | `envoy-internal` LoadBalancer for LAN-only traffic | `cluster.yaml`, `kubernetes/apps/network/envoy-gateway` | `10.0.0.27` |
| `cloudflare_gateway_addr` | `envoy-external` / Cloudflare tunnel endpoint | `cluster.yaml`, `kubernetes/apps/network/cloudflare-tunnel` | `10.0.0.28` |

Additional networking controllers:

- `kubernetes/apps/network/k8s-gateway/` serves split-DNS responses for Gateway API hostnames.
- `kubernetes/apps/network/cloudflare-dns/` and `cloudflare-tunnel/` handle Cloudflare records + tunnels.
- `kubernetes/apps/network/envoy-gateway/` defines both `envoy-internal` and `envoy-external` gateway classes and listener routes.

## Core Cluster Add-ons

These live under `kubernetes/apps/kube-system/` and `kubernetes/apps/cert-manager/`:

- `cilium/` provides the CNI and kube-proxy-free dataplane.
- `coredns/` supplies in-cluster DNS.
- `metrics-server/`, `spegel/`, and `reloader/` supply resource metrics, image caching, and config reload automation.
- `cert-manager/` issues TLS certificates; the wildcard and issuer manifests are committed under `kubernetes/apps/cert-manager/`.

## Operational Tooling

- `kubernetes/components/sops/` ensures SOPS secrets stay in sync with Flux.
- `scripts/bootstrap-apps.sh` and `Taskfile.yaml` expose the bootstrap flow for Talos plus Flux.
- TechDocs live in `docs/techdocs/` and are referenced from Backstage via `backstage.io/techdocs-ref: dir:docs/techdocs` in `catalog-info.yaml`.

## CI Runners

- `kubernetes/apps/arc-systems/actions-runner-controller/` installs the GitHub Actions Runner Controller with Prometheus PodMonitors and the same SOPS substitution flow used elsewhere in the repo.
- `kubernetes/apps/arc-systems/gha-runner-scale-set/` provisions a Docker-in-Docker scale set. Populate `GITHUB_CONFIG_URL`, `GITHUB_APP_ID_B64`, `GITHUB_APP_INSTALLATION_ID_B64`, and `GITHUB_APP_PRIVATE_KEY_B64` in `kubernetes/components/sops/cluster-secrets.sops.yaml` so Flux can inject the GitHub App credentials.
