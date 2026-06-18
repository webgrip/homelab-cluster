# Runbooks

This page is intentionally a **links-only index**. Each runbook has its own dedicated tutorial page.

## Incidents / postmortems

- 2026-06-09 Longhorn OOM cascade + dependency-track-db outage: [docs/techdocs/docs/incidents/2026-06-09-longhorn-oom-cascade.md](../incidents/2026-06-09-longhorn-oom-cascade.md)

## Platform / GitOps

- Cluster health: [docs/techdocs/docs/runbooks/cluster-health.md](cluster-health.md)
- Flux: [docs/techdocs/docs/runbooks/flux.md](flux.md)
- Renovate: [docs/techdocs/docs/runbooks/renovate.md](renovate.md)

## Networking / Ingress

- Synthetic probes (blackbox): [docs/techdocs/docs/runbooks/synthetic-probes-blackbox.md](synthetic-probes-blackbox.md)
- Cilium: [docs/techdocs/docs/runbooks/cilium.md](cilium.md)
- Envoy Gateway: [docs/techdocs/docs/runbooks/envoy-gateway.md](envoy-gateway.md)
- Split-horizon DNS (CoreDNS + k8s-gateway): [docs/techdocs/docs/runbooks/dns-split-dns.md](dns-split-dns.md)

## Storage

- Longhorn: [docs/techdocs/docs/runbooks/longhorn.md](longhorn.md)
- Longhorn capacity remediation (in progress): [docs/techdocs/docs/runbooks/longhorn-capacity-remediation.md](longhorn-capacity-remediation.md)

## Certificates

- cert-manager: [docs/techdocs/docs/runbooks/cert-manager.md](cert-manager.md)

## Secrets

- External Secrets (ESO): [docs/techdocs/docs/runbooks/external-secrets.md](external-secrets.md)

## Observability

- Observability stack: [docs/techdocs/docs/runbooks/observability-stack.md](observability-stack.md)
- Prometheus remote_write: [docs/techdocs/docs/runbooks/prometheus-remote-write.md](prometheus-remote-write.md)
- Mimir Kafka: [docs/techdocs/docs/runbooks/mimir-kafka.md](mimir-kafka.md)

## Apps

- Apps (baseline): [docs/techdocs/docs/runbooks/apps-baseline.md](apps-baseline.md)
- Harbor (container registry): [docs/techdocs/docs/runbooks/harbor.md](harbor.md)

## Identity / Auth

- Authentik OIDC login failures: [docs/techdocs/docs/runbooks/authentik-oidc-login.md](authentik-oidc-login.md)
- Authenticating Prometheus & Alertmanager (Envoy OIDC, design): [docs/techdocs/docs/runbooks/observability-auth.md](observability-auth.md)

## Talos / Kubernetes

- Add node from maintenance mode (index): [docs/techdocs/docs/runbooks/talos-maintenance-mode-add-node.md](talos-maintenance-mode-add-node.md)
  - Full tutorial: [docs/techdocs/docs/talos-add-workstation-node.md](../general/talos-add-workstation-node.md)
- Talos rolling upgrade: [docs/techdocs/docs/runbooks/talos-rolling-upgrade.md](talos-rolling-upgrade.md)
- Kubernetes upgrade (via Talos): [docs/techdocs/docs/runbooks/kubernetes-upgrade-via-talos.md](kubernetes-upgrade-via-talos.md)

## Canaries

- k6 canaries: [docs/techdocs/docs/runbooks/k6-canaries.md](k6-canaries.md)
