# Registry blob storage on Garage S3

* Status: accepted
* Date: 2026-06-12

Technical Story: [RFC: Harbor Container Registry](../rfc/rfc-harbor-registry.md)

## Context and Problem Statement

Image and chart **blobs are the bulk of a registry's data** and grow without bound. The cluster's
Longhorn SSD tier is replicated and capacity-constrained (storage reclaim is an ongoing concern),
so parking a large, ever-growing registry volume on it is the wrong place for that data. The
cluster already runs **Garage** as an S3 backend (`10.0.0.110:3900`) that several apps lean on
(Loki, Forgejo bulk storage, CNPG backups), so S3-backed blob storage is a proven, available path.

## Considered Options

* S3 blob storage on a dedicated Garage bucket
* A large Longhorn RWO PVC (`filesystem` driver)

## Decision Outcome

Chosen option: "S3 blob storage on a dedicated Garage bucket", because blobs are the bulk of a
registry's data and grow without bound — the wrong fit for the replicated, capacity-constrained
Longhorn SSD tier — while Garage is already a proven, available S3 path in the cluster.

Configure Harbor's registry with `persistence.imageChartStorage.type: s3` pointing at a dedicated
Garage bucket **`harbor`**. Garage requires path-style, redirect-disabled access:
`regionendpoint: http://10.0.0.110:3900`, `secure: false`, `v4auth: true`, and
**`disableredirect: true`** (clients can't follow S3 redirects to an internal endpoint, so the
core proxies blobs — redirect loops otherwise). Credentials come from OpenBao via the `harbor-s3`
ExternalSecret (`secret/harbor/s3`). Lives in `kubernetes/apps/harbor/harbor/app/`.

### Positive Consequences

* Keeps bulk artifact data **off the constrained Longhorn SSD tier** — the primary win.

### Negative Consequences

* **Garage becomes a hard dependency for blob I/O:** if Garage is down, push/pull of blob content
  fails. This is the same class of single-point dependency as the CNPG ↔ Garage WAL coupling
  documented in [CNPG Backups](../runbooks/cnpg-backups.md); acceptable degradation for a homelab
  registry.
* Requires a one-time human step at bring-up: create the `harbor` bucket and an access key on the
  Garage host, then store the key in OpenBao.
* Small per-component PVCs are still needed (jobservice job-logs, trivy cache) — those stay on
  `longhorn-general`, `ReadWriteOnce`.

## Pros and Cons of the Options

### S3 blob storage on a dedicated Garage bucket

* Good, because it keeps the ever-growing blob data off the replicated, capacity-constrained
  Longhorn SSD tier.
* Good, because Garage is a proven path that several apps already lean on (Loki, Forgejo bulk
  storage, CNPG backups).
* Bad, because Garage becomes a hard dependency for blob push/pull.

### A large Longhorn RWO PVC (`filesystem` driver)

* Good, because self-contained with no Garage dependency.
* Bad, because it consumes replicated SSD capacity that is already under pressure.
* Bad, because it scales poorly as the registry grows.

## Links

* 2026-06-12 — accepted; deployed with the Harbor stack
