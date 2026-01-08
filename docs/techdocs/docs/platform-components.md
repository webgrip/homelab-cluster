# Platform Components

This page documents the platform building blocks that applications rely on: GitOps, networking, DNS, storage, databases, secrets, and CI.

## GitOps + Talos Integration

- `kubernetes/apps/flux-system/` installs Flux controllers (`flux-instance`, `flux-operator`) and the Weave GitOps UI.
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
| Applications | `kubernetes/apps/default`, `kubernetes/apps/freshrss`, `kubernetes/apps/invoiceninja` | Echo sample service, FreshRSS backed by a namespace-local CNPG PostgreSQL cluster, and Invoice Ninja 5.12.39 backed by an app-template MariaDB 11.8.5 StatefulSet on Longhorn.

Use this table when linking Backstage components (catalog entries live under `catalog/components/*.yaml`).

## Networking + Access

| Endpoint | Purpose | Source | Address |
| --- | --- | --- | --- |
| `cluster_api_addr` | Talos and Kubernetes API VIP | `cluster.yaml` | `10.0.0.25` |
| `cluster_dns_gateway_addr` | `k8s-gateway` LoadBalancer for split DNS | `cluster.yaml`, `kubernetes/apps/network/k8s-gateway` | `10.0.0.26` |
| `cluster_gateway_addr` | `envoy-internal` LoadBalancer for LAN-only traffic | `cluster.yaml`, `kubernetes/apps/network/envoy-gateway` | `10.0.0.27` |
| `cloudflare_gateway_addr` | `envoy-external` / Cloudflare tunnel endpoint | `cluster.yaml`, `kubernetes/apps/network/cloudflare-tunnel` | `10.0.0.28` |

Supporting controllers:

- `kubernetes/apps/network/k8s-gateway/` answers split DNS for `${SECRET_DOMAIN}` inside the LAN and watches `HTTPRoute` + `Service` resources.
- `kubernetes/apps/network/envoy-gateway/` installs Envoy Gateway and defines the `envoy-internal` and `envoy-external` `Gateway` resources.
- `kubernetes/apps/network/cloudflare-tunnel/` runs `cloudflared` and forwards `*.${SECRET_DOMAIN}` traffic from Cloudflare to the in-cluster `envoy-external` service.
- `kubernetes/apps/network/cloudflare-dns/` runs ExternalDNS against Cloudflare and can publish records from Gateway API `HTTPRoute` (and `DNSEndpoint` CRs).

Physical wiring (Protectli → TP-Link TL-SG108PE → Q-Link → Zyxel) is documented in `docs/techdocs/docs/talos-cluster.md` and should be mirrored whenever networking manifests change.

## Core Cluster Add-ons

- `kubernetes/apps/kube-system/cilium/` provides the eBPF CNI and kube-proxy-free dataplane.
- `kubernetes/apps/kube-system/coredns/` keeps in-cluster DNS consistent with split-horizon rules.
- `kubernetes/apps/kube-system/metrics-server/`, `reloader/`, and `spegel/` power autoscaling metrics, deployment reloads, and an OCI image cache respectively.
- `kubernetes/apps/cert-manager/` issues TLS for both Envoy gateways and any workload referencing cluster issuers.
- `kubernetes/apps/cnpg-system/` installs the CloudNativePG operator for in-cluster PostgreSQL clusters.

## Storage

- `kubernetes/apps/longhorn-system/` installs Longhorn and defines StorageClasses under `kubernetes/apps/longhorn-system/longhorn/storageclass/`.
- Application PVCs typically use `longhorn-general`.
- CNPG clusters in this repo use the `longhorn` storageClass (see `*/app/database/cluster.yaml`).

CloudNativePG details:

- Operator is installed cluster-wide in `cnpg-system` via a HelmRelease that exposes Prometheus metrics with a PodMonitor and publishes a Grafana dashboard ConfigMap labelled `grafana_dashboard=1` so your existing Grafana sidecar/operator can auto-import it.
- When you're ready to enable CNPG backups, include the component at `kubernetes/components/cnpg-backup/` in the namespace Kustomization.

## Security + Secrets

- Age keys live under `bootstrap/` and are distributed via Taskfile targets.
- `kubernetes/components/sops/` renders secret values into namespaces. Renovate is configured to ignore `**/*.sops.*` via `.renovaterc.json5`.
- FreshRSS pulls database credentials from SOPS secrets in-namespace and connects to the CNPG `*-db-rw` service.

## Platform options (what you can choose)

When adding apps, you generally choose between:

- Deployment style: HelmRelease (recommended) vs raw YAML + Kustomize.
- Ingress exposure: `envoy-internal` (LAN-only) vs `envoy-external` (public via Cloudflare).
- Data services: CNPG Postgres vs app-managed DB (e.g. MariaDB in `invoiceninja`).
- Persistence: Longhorn StorageClasses (`longhorn-general` for typical RWO; `longhorn-rwx` only when needed).

See [docs/techdocs/docs/adding-applications.md](adding-applications.md) for the step-by-step.

## CI Runners & Automation

- `kubernetes/apps/arc-systems/actions-runner-controller/` is the control plane for GitHub Actions scale sets. It uses the shared SOPS secret for the GitHub App.
- `kubernetes/apps/arc-systems/gha-runner-scale-set/` provisions Docker-in-Docker runners that register against the App URL stored in `cluster-secrets.sops.yaml`.
- `talos/patches/global/machine-kernel.yaml` keeps the `binfmt_misc` kernel module loaded on every Talos node so QEMU binfmt handlers can be registered inside runner jobs for multi-arch Docker builds.
- Renovate + GitHub Actions automation resides under `.github/workflows/` and is referenced from `catalog/components/flux-gitops.yaml` so Backstage shows build status next to the manifests.
