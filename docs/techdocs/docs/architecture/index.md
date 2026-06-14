# Architecture Decision Records

This section holds the cluster's **RFCs** (broad proposals up for review) and **ADRs**
(Architecture Decision Records — one defensible decision each). It is the durable record of
*why* the homelab is built the way it is, so a decision can be revisited later without
re-litigating the context from memory.

This is the repo's first ADR section; the conventions below apply to everything added here.

## Conventions

- **Location:** `docs/techdocs/docs/architecture/`. RFCs are `rfc-<topic>.md`; ADRs are
  `adr-NNNN-<kebab-title>.md` with a **zero-padded, monotonically increasing** number. ADR
  numbers are never reused — a reversed decision gets a *new* ADR that supersedes the old one.
- **No front-matter.** A doc opens with its `# H1`, then a one-line `> Status:` banner.
- **An RFC is the umbrella**; the ADRs under it capture the individual choices it makes. Each
  ADR links back to its RFC, and the RFC's *Decisions* table links out to each ADR.

## ADR format

```markdown
# ADR-NNNN: <short title>

> Status: **Accepted** · Date: YYYY-MM-DD · Part of [RFC: …](rfc-….md)

## Context        # the forces — problem, constraints, what made this a decision
## Decision       # the choice, in a sentence or two
## Consequences   # what it commits us to — positive and negative, operational follow-ons
## Alternatives considered   # each rejected option and why
```

## Status legend

| Status | Meaning |
|--------|---------|
| **Proposed** | Under review; not yet ratified (RFCs sit here until accepted). |
| **Accepted** | Decided. The current source of truth. |
| **Superseded** | Replaced by a later ADR (links to it). Kept for history, never deleted. |
| **Deprecated** | No longer relevant, but not directly replaced. |

## Records

### RFCs

| RFC | Status | Summary |
|-----|--------|---------|
| [Harbor Container Registry](rfc-harbor-registry.md) | Proposed | Deploy a feature-complete Harbor as the cluster's private OCI registry + artifact store. |
| [Security Hardening — Closing the Loops](rfc-security-hardening.md) | Proposed | Finish the security loops already built: wire encryption, rootless CI, rotation, enforce mode. |
| [Dynamic Database Credentials](rfc-dynamic-database-credentials.md) | Proposed | Short-lived, per-workload, auto-revoked Postgres creds via OpenBao's database engine. |
| [Renovate on Forgejo](rfc-renovate-forgejo.md) | Proposed | Migrate Renovate off GitHub onto Forgejo via a second dual-run RenovateJob; cut repos over as each becomes authoritative. |
| [Cutting the GitOps umbilical](rfc-flux-forgejo-source.md) | Proposed | Repoint Flux's source from GitHub to in-cluster Forgejo; keep an external mirror for bootstrap + break-glass. |
| [Harbor Pull-Through Proxy Cache](rfc-harbor-proxy-cache.md) | Proposed | Route docker.io/ghcr.io pulls through Harbor proxy-cache projects at the containerd-mirror layer, with upstream fallback. |

### ADRs

| ADR | Status | Decision |
|-----|--------|----------|
| [ADR-0001](adr-0001-adopt-harbor.md) | Accepted | Adopt Harbor as the self-hosted OCI registry. |
| [ADR-0002](adr-0002-registry-blob-storage-garage-s3.md) | Accepted | Store registry blobs on Garage S3, not a Longhorn PVC. |
| [ADR-0003](adr-0003-external-cnpg-database.md) | Accepted | Back Harbor with an external CNPG Postgres (no bootstrap secret). |
| [ADR-0004](adr-0004-chart-internal-redis.md) | Accepted | Use the chart-bundled `redis-photon`, not an external Valkey. |
| [ADR-0005](adr-0005-lan-only-exposure.md) | Accepted | Expose Harbor LAN-only via `envoy-internal`. |
| [ADR-0006](adr-0006-authentik-oidc-phased.md) | Accepted | Authenticate via Authentik OIDC, layered in a second phase. |
| [ADR-0007](adr-0007-cilium-wireguard-encryption.md) | Accepted | Encrypt pod-to-pod traffic with Cilium WireGuard (`nodeEncryption` off). |
| [ADR-0008](adr-0008-rootless-ci-image-builds.md) | Proposed | Replace privileged DinD with rootless BuildKit for CI image builds. |
| [ADR-0009](adr-0009-secret-rotation-model.md) | Accepted | Rotate via OpenBao write → ESO refresh → Reloader restart; at-rest keys excluded. |
| [ADR-0010](adr-0010-openbao-dynamic-postgres-credentials.md) | Proposed | Mint short-lived per-workload Postgres creds via OpenBao's database engine. |
| [ADR-0011](adr-0011-dual-run-renovate-forgejo.md) | Proposed | Dual-run a second Forgejo RenovateJob beside the GitHub one; retire GitHub at cutover. |
| [ADR-0012](adr-0012-forgejo-static-bot-pat.md) | Proposed | Authenticate Renovate to Forgejo with a static bot PAT; delete the GitHub-App token-minter. |
| [ADR-0013](adr-0013-github-as-renovate-data-oracle.md) | Proposed | Keep GitHub as a read-only data oracle (datasources, presets, GHCR via the App-minter's host-rules). |
| [ADR-0014](adr-0014-flux-source-forgejo.md) | Proposed | Make in-cluster Forgejo the authoritative Flux GitOps source via its internal Service URL. |
| [ADR-0015](adr-0015-external-bootstrap-fallback-source.md) | Proposed | Keep GitHub (push-mirror) as the cold-bootstrap + break-glass GitOps source. |
| [ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md) | Proposed | Adopt two Harbor proxy-cache projects (dockerhub → docker.io, ghcr → ghcr.io). |
| [ADR-0017](adr-0017-registry-mirror-talos-spegel.md) | Proposed | Inject the mirror via Talos `machine.registries.mirrors` + Spegel `prependExisting`; fail open to upstream. |
| [ADR-0018](adr-0018-harbor-config-idempotent-job.md) | Proposed | Provision the proxy registries/projects via an idempotent Harbor-API CronJob (no operator). |
| [ADR-0019](adr-0019-bootstrap-task-pattern.md) | Accepted | Bootstrap/one-shot tasks: pick the lowest trigger tier (controller > change-triggered Job > timer CronJob), gated by Flux. |
