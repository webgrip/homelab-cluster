# ADR-0002: Registry blob storage on Garage S3

> Status: **Accepted** · Date: 2026-06-12 · Part of [RFC: Harbor Container Registry](../rfc/rfc-harbor-registry.md)

## Context

Image and chart **blobs are the bulk of a registry's data** and grow without bound. The cluster's
Longhorn SSD tier is replicated and capacity-constrained (storage reclaim is an ongoing concern),
so parking a large, ever-growing registry volume on it is the wrong place for that data. The
cluster already runs **Garage** as an S3 backend (`10.0.0.110:3900`) that several apps lean on
(Loki, Forgejo bulk storage, CNPG backups), so S3-backed blob storage is a proven, available path.

## Decision

Configure Harbor's registry with `persistence.imageChartStorage.type: s3` pointing at a dedicated
Garage bucket **`harbor`**. Garage requires path-style, redirect-disabled access:
`regionendpoint: http://10.0.0.110:3900`, `secure: false`, `v4auth: true`, and
**`disableredirect: true`** (clients can't follow S3 redirects to an internal endpoint, so the
core proxies blobs). Credentials come from OpenBao via the `harbor-s3` ExternalSecret
(`secret/harbor/s3`).

## Consequences

- Keeps bulk artifact data **off the constrained Longhorn SSD tier** — the primary win.
- **Garage becomes a hard dependency for blob I/O:** if Garage is down, push/pull of blob content
  fails. This is the same class of single-point dependency as the CNPG ↔ Garage WAL coupling
  documented in [CNPG Backups](../runbooks/cnpg-backups.md); acceptable degradation for a homelab registry.
- Requires a one-time human step at bring-up: create the `harbor` bucket and an access key on the
  Garage host, then store the key in OpenBao.
- Small per-component PVCs are still needed (jobservice job-logs, trivy cache) — those stay on
  `longhorn-general`, `ReadWriteOnce`.

## Alternatives considered

- **A large Longhorn RWO PVC** (`filesystem` driver) — self-contained with no Garage dependency,
  but consumes replicated SSD capacity that is already under pressure, and scales poorly as the
  registry grows.
