# Runbooks

Links-only index. Each runbook is its own page; authoring recipes live in skills, incident history under [incidents](../incidents/index.md).

## Flux / GitOps

- [New-machine setup (work against the live cluster from a fresh clone)](new-machine-setup.md)
- [Flux](flux.md)
- [Renovate (operator, dual-forge, Forgejo gotchas)](renovate.md)

## Talos / nodes

- [Talos rolling upgrade](talos-rolling-upgrade.md)
- [Kubernetes upgrade (via Talos)](kubernetes-upgrade-via-talos.md)
- [Add node from maintenance mode](talos-maintenance-mode-add-node.md) — full tutorial: [talos-add-workstation-node](../general/talos-add-workstation-node.md)
- [etcd health (defrag, fsync latency, disk contention)](etcd-health.md)

## Storage (Longhorn)

- [Rebuild wedge — zombie replicas hold the rebuild slot](longhorn-rebuild-wedge.md)
- [Guaranteed-IM-CPU staged convergence](longhorn-im-cpu-converge.md)

## Secrets

- [External Secrets (ESO + OpenBao) — triage, DR, gotchas](external-secrets.md)
- [Rotate a secret in OpenBao (and how it reaches pods)](secret-rotation.md)
- [OpenBao restore (unseal / raft snapshot)](openbao-restore.md)
- [cosign Transit key rotation](cosign-transit-key-rotation.md)

## Databases (CNPG)

- [CloudNativePG & backups (ObjectStore, force-prune WAL, restore/DR drill)](cnpg-backups.md)
- [Dynamic Postgres credentials (OpenBao database engine)](dynamic-db-credentials.md)

## Observability

- [VictoriaMetrics (metrics backend + namespace triage)](victoriametrics.md)
- [Authenticating Prometheus & Alertmanager endpoints (Envoy OIDC, design)](observability-auth.md)
- [Synthetic probes (blackbox, incl. Garage S3)](synthetic-probes-blackbox.md)
- [k6 canaries](k6-canaries.md)

## Apps

- [Apps baseline triage](apps-baseline.md)
- [Harbor (container registry)](harbor.md)
- [Authentik OIDC login failures](authentik-oidc-login.md)

## Network / DNS / certs

- [Cilium](cilium.md)
- [Envoy Gateway](envoy-gateway.md)
- [Split-horizon DNS (CoreDNS + k8s-gateway)](dns-split-dns.md)
- [cert-manager](cert-manager.md)

## CI

- [Forgejo Actions runner (KEDA ScaledJob, warm pool)](forgejo-runner.md)

## Incidents / postmortems

- [2026-06-09 — Longhorn OOM cascade + dependency-track-db outage](../incidents/2026-06-09-longhorn-oom-cascade.md)
- [2026-06-18 — Longhorn rolling-IM detonation + guac-db faulted](../incidents/2026-06-18-longhorn-im-cpu-rolling-detonation.md)
- [2026-06-19 — Node-taxonomy migration storage churn / rebuild wedge](../incidents/2026-06-19-node-taxonomy-migration-storage-churn.md)
