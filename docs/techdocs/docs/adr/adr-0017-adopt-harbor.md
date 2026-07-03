# Adopt Harbor as the self-hosted OCI registry

* Status: accepted
* Date: 2026-06-23

Technical Story: [RFC: Harbor Container Registry](../rfc/rfc-harbor-registry.md)

## Context and Problem Statement

The cluster had no artifact registry of its own. Images and charts were pulled from public
registries (`ghcr.io`, `mirror.gcr.io`, `docker.io`), and there was nowhere first-party to *store*
the homelab's own artifacts — built images, OCI Helm charts, SBOM/attestation blobs. Forgejo
Actions and the CI runners could build images but had no in-cluster publish target, and nothing
scanned artifacts at rest. We want a private OCI store with vulnerability scanning that feeds the
existing [supply-chain story](../general/supply-chain-pipeline.md) (dependency-track / guac), with
projects, RBAC, robot accounts, and metrics — managed the same GitOps way as everything else.

## Considered Options

* Harbor via its official Helm chart
* Forgejo's built-in package registry
* Zot / CNCF `distribution`
* A managed cloud registry (GHCR/ECR/GAR)

## Decision Outcome

Chosen option: "Harbor via its official Helm chart", because it is the only option that covers
the whole requirement in one product — OCI image/chart/artifact storage, projects and robot
accounts, an integrated **Trivy** scanner, replication, and metrics.

Deploy **[Harbor](https://goharbor.io/) 2.x** via its official Helm chart
(`https://helm.goharbor.io`), GitOps-managed under `kubernetes/apps/harbor/`, structured like the
existing `kubernetes/apps/forgejo/` app (HelmRelease + external CNPG + Gateway API + ESO secrets).
The supporting choices are recorded in ADR-0018…0006 (blob storage, database, Redis, exposure,
auth).

### Positive Consequences

* A private publish target, an at-rest scanning gate, projects/RBAC/robot-accounts, and
  replication — closing the gaps in the RFC's *Why*.

### Negative Consequences

* Adds Harbor's multi-component pod set (core, portal, jobservice, registry, registryctl, trivy,
  redis, exporter) plus the CNPG database — a meaningful but acceptable footprint, pinned to the
  worker pool per [ADR-0002](adr-0002-application-workload-placement.md).
* Introduces new dependencies — Postgres ([ADR-0019](adr-0019-external-cnpg-database.md)), Redis
  ([ADR-0020](adr-0020-chart-internal-redis.md)), and S3 blob storage
  ([ADR-0018](adr-0018-registry-blob-storage-garage-s3.md)).
* Commits us to operating Harbor's multi-component release (upgrades touch several images at
  once).

## Pros and Cons of the Options

### Harbor via its official Helm chart

* Good, because the full feature set ships in one product (registry, projects, robots, Trivy,
  replication, metrics).
* Bad, because it is a multi-component release — upgrades touch several images at once.

### Forgejo's built-in package registry

* Good, because it is already in the cluster.
* Bad, because it lacks Trivy scanning, project-level RBAC, robot accounts, and replication —
  not a full registry product.

### Zot / CNCF `distribution`

* Good, because lean and OCI-native.
* Bad, because no UI, no projects, no integrated scanning — we'd have to assemble the
  surrounding features ourselves.

### A managed cloud registry (GHCR/ECR/GAR)

* Bad, because recurring cost, off-prem, and counter to the self-hosted homelab goal; no
  in-cluster scanning gate.

## Links

* 2026-06-12 — accepted; Harbor deployed (CNPG + Garage S3 + ESO + OIDC)
* 2026-06-21 — all Harbor components pinned to the worker pool
  ([ADR-0002](adr-0002-application-workload-placement.md)); the original soyo-pool placement note
  is obsolete
* 2026-06-23 — extended by [ADR-0023](adr-0023-harbor-pull-through-proxy-cache.md) (pull-through
  proxy cache) and [ADR-0024](adr-0024-registry-mirror-talos-spegel.md) (Spegel node mirror)
* Supported by [ADR-0018](adr-0018-registry-blob-storage-garage-s3.md) ·
  [ADR-0019](adr-0019-external-cnpg-database.md) · [ADR-0020](adr-0020-chart-internal-redis.md) ·
  [ADR-0021](adr-0021-lan-only-exposure.md) · [ADR-0022](adr-0022-authentik-oidc-phased.md)
* 2026-07-03 — renumbered from ADR-0001 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
