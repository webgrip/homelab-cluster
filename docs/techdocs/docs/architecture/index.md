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

### ADRs

| ADR | Status | Decision |
|-----|--------|----------|
| [ADR-0001](adr-0001-adopt-harbor.md) | Accepted | Adopt Harbor as the self-hosted OCI registry. |
| [ADR-0002](adr-0002-registry-blob-storage-garage-s3.md) | Accepted | Store registry blobs on Garage S3, not a Longhorn PVC. |
| [ADR-0003](adr-0003-external-cnpg-database.md) | Accepted | Back Harbor with an external CNPG Postgres (no bootstrap secret). |
| [ADR-0004](adr-0004-chart-internal-redis.md) | Accepted | Use the chart-bundled `redis-photon`, not an external Valkey. |
| [ADR-0005](adr-0005-lan-only-exposure.md) | Accepted | Expose Harbor LAN-only via `envoy-internal`. |
| [ADR-0006](adr-0006-authentik-oidc-phased.md) | Accepted | Authenticate via Authentik OIDC, layered in a second phase. |
