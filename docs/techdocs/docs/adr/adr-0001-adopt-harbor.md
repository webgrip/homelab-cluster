# ADR-0001: Adopt Harbor as the self-hosted OCI registry

> Status: **Accepted** · Date: 2026-06-12 · Part of [RFC: Harbor Container Registry](../rfc/rfc-harbor-registry.md)

## Context

The cluster had no artifact registry of its own. Images and charts were pulled from public
registries (`ghcr.io`, `mirror.gcr.io`, `docker.io`), and there was nowhere first-party to *store*
the homelab's own artifacts — built images, OCI Helm charts, SBOM/attestation blobs. Forgejo
Actions and the CI runners could build images but had no in-cluster publish target, and nothing
scanned artifacts at rest. We want a private OCI store with vulnerability scanning that feeds the
existing [supply-chain story](../general/supply-chain-pipeline.md) (dependency-track / guac), with
projects, RBAC, robot accounts, and metrics — managed the same GitOps way as everything else.

## Decision

Deploy **[Harbor](https://goharbor.io/) 2.x** via its official Helm chart
(`https://helm.goharbor.io`), GitOps-managed under `kubernetes/apps/harbor/`, structured like the
existing `kubernetes/apps/forgejo/` app (HelmRelease + external CNPG + Gateway API + ESO secrets).
Harbor provides the full feature set in one product: OCI image/chart/artifact storage, projects
and robot accounts, an integrated **Trivy** scanner, replication, and Prometheus metrics.

The supporting choices are recorded in ADR-0002…0006 (blob storage, database, Redis, exposure,
auth). The registry was later extended with a pull-through proxy cache
([ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md)), the Spegel node-local mirror
([ADR-0017](adr-0017-registry-mirror-talos-spegel.md)), and an idempotent config Job
([ADR-0018](adr-0018-harbor-config-idempotent-job.md)).

## Alternatives considered

- **Forgejo's built-in package registry** — already in the cluster, but lacks Trivy scanning,
  project-level RBAC, robot accounts, and replication; not a full registry product.
- **Zot / CNCF `distribution`** — lean and OCI-native, but no UI, no projects, no integrated
  scanning; we'd have to assemble the surrounding features ourselves.
- **A managed cloud registry** (GHCR/ECR/GAR) — recurring cost, off-prem, and counter to the
  self-hosted homelab goal; no in-cluster scanning gate.

## Consequences

- Adds Harbor's multi-component pod set (core, portal, jobservice, registry, registryctl, trivy,
  redis, exporter) plus the CNPG database — a meaningful but acceptable footprint, pinned to the
  worker pool per [ADR-0028](adr-0028-application-workload-placement.md).
- Introduces new dependencies — Postgres ([ADR-0003](adr-0003-external-cnpg-database.md)), Redis
  ([ADR-0004](adr-0004-chart-internal-redis.md)), and S3 blob storage
  ([ADR-0002](adr-0002-registry-blob-storage-garage-s3.md)).
- Gains a private publish target, an at-rest scanning gate, projects/RBAC/robot-accounts, and
  replication — closing the gaps in the RFC's *Why*.
- Commits us to operating Harbor's multi-component release (upgrades touch several images at once).

## Status log

- 2026-06-12 — Accepted; Harbor deployed (CNPG + Garage S3 + ESO + OIDC).
- 2026-06-21 — All Harbor components pinned to the worker pool
  ([ADR-0028](adr-0028-application-workload-placement.md)); the original soyo-pool placement note
  is obsolete.
- 2026-06-23 — Extended: pull-through proxy cache ([ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md))
  and Spegel node mirror ([ADR-0017](adr-0017-registry-mirror-talos-spegel.md)) accepted on top of
  this registry.
