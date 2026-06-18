# ADR-0001: Adopt Harbor as the self-hosted OCI registry

> Status: **Accepted** · Date: 2026-06-12 · Part of [RFC: Harbor Container Registry](../rfc/rfc-harbor-registry.md)

## Context

The cluster has no artifact registry of its own. Images and charts are pulled from public
registries (`ghcr.io`, `mirror.gcr.io`, `docker.io`), and there is nowhere first-party to *store*
the homelab's own artifacts — built images, OCI Helm charts, SBOM/attestation blobs. Forgejo
Actions and the ARC runners can build images but have no in-cluster publish target, and nothing
scans artifacts at rest. We want a private OCI store with vulnerability scanning that feeds the
existing [supply-chain story](../general/supply-chain-pipeline.md) (dependency-track / guac), with
projects, RBAC, robot accounts, and metrics — managed the same GitOps way as everything else.

## Decision

Deploy **[Harbor](https://goharbor.io/) 2.x** via its official Helm chart
(`https://helm.goharbor.io`), GitOps-managed under `kubernetes/apps/harbor/`, structured like the
existing `kubernetes/apps/forgejo/` app (HelmRelease + external CNPG + Gateway API + ESO secrets).
Harbor provides the full feature set in one product: OCI image/chart/artifact storage, projects
and robot accounts, an integrated **Trivy** scanner, replication, and Prometheus metrics.

## Consequences

- Adds ~9 pods to the **soyo** pool (core, portal, jobservice, registry, registryctl, trivy,
  redis, exporter) plus the CNPG database — a meaningful but acceptable footprint.
- Introduces new dependencies — Postgres ([ADR-0003](adr-0003-external-cnpg-database.md)), Redis
  ([ADR-0004](adr-0004-chart-internal-redis.md)), and S3 blob storage
  ([ADR-0002](adr-0002-registry-blob-storage-garage-s3.md)).
- Gains a private publish target, an at-rest scanning gate, projects/RBAC/robot-accounts, and
  replication — closing the gaps in the RFC's *Why*.
- Commits us to operating Harbor's multi-component release (upgrades touch several images at once).

## Alternatives considered

- **Forgejo's built-in package registry** — already in the cluster, but lacks Trivy scanning,
  project-level RBAC, robot accounts, and replication; not a full registry product.
- **Zot / CNCF `distribution`** — lean and OCI-native, but no UI, no projects, no integrated
  scanning; we'd have to assemble the surrounding features ourselves.
- **A managed cloud registry** (GHCR/ECR/GAR) — recurring cost, off-prem, and counter to the
  self-hosted homelab goal; no in-cluster scanning gate.
