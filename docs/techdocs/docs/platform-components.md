# Platform Components

This page stays synchronized with the README so Backstage catalog entries describe the same GitOps flow, networking gateways, and hardware wiring depicted there.

## GitOps + Talos Integration

- `kubernetes/apps/flux-system/` installs Flux controllers (`flux-instance`, `flux-operator`) and the Weave GitOps UI. Reconciliation tracks `main` by default.
- Talos machine configs under `talos/clusterconfig/` plus patches in `talos/patches/` match the hardware + wiring section. Apply changes with `talosctl apply-config` after committing updates.
- Bootstrap artifacts live in `bootstrap/` (Helmfile, SOPS age keys, GitHub deploy keys). `scripts/bootstrap-apps.sh` + `Taskfile.yaml` automate the same steps described in the README overview.
- Secrets flow through Age-encrypted SOPS files (`kubernetes/components/sops/cluster-secrets.sops.yaml` etc.). Flux decrypts them inside the cluster so no plaintext lands in Git.

## Workload Layers

| Layer | Location | Notes |
| --- | --- | --- |
| Platform control | `kubernetes/apps/flux-system`, `kube-system` | Flux controllers, notification receiver, Weave GitOps UI, Cilium, CoreDNS, metrics-server, Spegel, Reloader. |
| Networking & ingress | `kubernetes/apps/network` | Envoy internal/external Gateway API stacks, `k8s-gateway`, Cloudflare DNS + Tunnel. |
| PKI & security | `kubernetes/apps/cert-manager`, `kubernetes/components/sops` | ACME HTTP-01/DNS-01 issuers, wildcard certs, encrypted secret distribution. |
| CI infrastructure | `kubernetes/apps/arc-systems` | actions-runner-controller with gha-runner-scale-set for GitHub burst compute. |
| Applications | `kubernetes/apps/default`, `kubernetes/apps/freshrss` | Echo sample service and FreshRSS HelmRelease wired to an external Postgres via Bitnami bootstrap job.

Use this table when linking Backstage components (catalog entries live under `catalog/components/*.yaml`).

## Networking + Access

| Endpoint | Purpose | Source | Address |
| --- | --- | --- | --- |
| `cluster_api_addr` | Talos and Kubernetes API VIP | `cluster.yaml` | `10.0.0.25` |
| `cluster_dns_gateway_addr` | `k8s-gateway` LoadBalancer for split DNS | `cluster.yaml`, `kubernetes/apps/network/k8s-gateway` | `10.0.0.26` |
| `cluster_gateway_addr` | `envoy-internal` LoadBalancer for LAN-only traffic | `cluster.yaml`, `kubernetes/apps/network/envoy-gateway` | `10.0.0.27` |
| `cloudflare_gateway_addr` | `envoy-external` / Cloudflare tunnel endpoint | `cluster.yaml`, `kubernetes/apps/network/cloudflare-tunnel` | `10.0.0.28` |

Supporting controllers:

- `kubernetes/apps/network/k8s-gateway/` answers split DNS the same way the README mermaid diagram shows (OPNsense → k8s-gateway → Envoy).
- `kubernetes/apps/network/cloudflare-dns/` and `cloudflare-tunnel/` reconcile Cloudflare records, tunnels, and Zero Trust access.
- `kubernetes/apps/network/envoy-gateway/` defines the Gateway API classes (`envoy-internal`, `envoy-external`) and listener resources consumed by workloads.

Physical wiring (Protectli → TP-Link TL-SG108PE → Q-Link → Zyxel) is documented in `docs/techdocs/docs/talos-cluster.md` and should be mirrored whenever networking manifests change.

## Core Cluster Add-ons

- `kubernetes/apps/kube-system/cilium/` provides the eBPF CNI and kube-proxy-free dataplane.
- `kubernetes/apps/kube-system/coredns/` keeps in-cluster DNS consistent with split-horizon rules.
- `kubernetes/apps/kube-system/metrics-server/`, `reloader/`, and `spegel/` power autoscaling metrics, deployment reloads, and an OCI image cache respectively.
- `kubernetes/apps/cert-manager/` issues TLS for both Envoy gateways and any workload referencing cluster issuers.

## Security + Secrets

- Age keys live under `bootstrap/` and are distributed via Taskfile targets.
- `kubernetes/components/sops/` renders secret values into namespaces. Renovate ignores these paths via `makejinja.toml` filters to avoid leaking diffs.
- FreshRSS pulls database credentials from the same component; Bitnami's bootstrap Job is purposefully constrained with read-only file systems and non-root UIDs, matching the security stance called out in the README.

## CI Runners & Automation

- `kubernetes/apps/arc-systems/actions-runner-controller/` is the control plane for GitHub Actions scale sets. It uses the shared SOPS secret for the GitHub App.
- `kubernetes/apps/arc-systems/gha-runner-scale-set/` provisions Docker-in-Docker runners that register against the App URL stored in `cluster-secrets.sops.yaml`.
- Renovate + GitHub Actions automation resides under `.github/workflows/` and is referenced from `catalog/components/flux-gitops.yaml` so Backstage shows build status next to the manifests.
