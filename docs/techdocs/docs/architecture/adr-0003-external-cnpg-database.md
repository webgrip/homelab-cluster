# ADR-0003: External CNPG Postgres for Harbor

> Status: **Accepted** · Date: 2026-06-12 · Part of [RFC: Harbor Container Registry](rfc-harbor-registry.md)

## Context

Harbor needs a PostgreSQL database (one database in 2.x — Notary, which needed extra DBs, was
removed). The Helm chart can bundle its own Postgres, but the cluster standard is
**CloudNativePG (CNPG)** with WAL archiving and scheduled backups to Garage S3, plus restore
drills — see [CNPG Backups](../cnpg-backups.md). Every stateful app here (forgejo, grafana, n8n,
backstage, dependency-track …) runs on CNPG, and that path is governed by kyverno policy.

## Decision

Provision an external CNPG `Cluster` **`harbor-db`** (database `registry`, owner `harbor`) under
`kubernetes/apps/harbor/harbor/app/database/`, and point Harbor at it with
`database.type: external` / `database.external.existingSecret: harbor-db-app`.

Follow the **forgejo pattern with no hand-authored bootstrap secret**: the `Cluster` declares only
`bootstrap.initdb: { database, owner }`, and CNPG generates the `harbor-db-app` Secret
(username/password) itself. Harbor consumes that generated Secret directly — no ExternalSecret and
no password duplication for the DB. Backups use the shared `cnpg-backup` component (an
`ObjectStore` + `ScheduledBackup` to `s3://cnpg-backups-bucket/homelab-cluster/harbor-db/`).

## Consequences

- Harbor's database inherits the cluster's backup/restore guarantees and monitoring for free.
- CNPG governance is **mandatory**: the `Cluster` must set `storageClass: longhorn`, declare a
  separate `walStorage`, and carry the `monitoring.webgrip.io/enabled: "true"` label.
- One fewer secret to manage — the DB credential is CNPG-owned, not in OpenBao.
- Adds a CNPG instance (plus its WAL volume) to the namespace; ties Harbor's DB backups to Garage
  like every other CNPG app.

## Alternatives considered

- **The chart-bundled Postgres** — simplest to enable, but un-backed-up, outside CNPG governance
  and monitoring, and a snowflake compared to every other database in the cluster.
- **A hand-authored bootstrap/owner secret via ExternalSecret** (the dependency-track style) —
  works, but it's an extra secret and moving part that the forgejo "let CNPG generate `-app`"
  approach removes entirely.
