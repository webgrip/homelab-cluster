# External CNPG Postgres for Harbor

* Status: accepted
* Date: 2026-06-12

Technical Story: [RFC: Harbor Container Registry](../rfc/rfc-harbor-registry.md)

## Context and Problem Statement

Harbor needs a PostgreSQL database (one database in 2.x — Notary, which needed extra DBs, was
removed). The Helm chart can bundle its own Postgres, but the cluster standard is
**CloudNativePG (CNPG)** with WAL archiving and scheduled backups to Garage S3, plus restore
drills — see [CNPG Backups](../runbooks/cnpg-backups.md). Every stateful app here (forgejo,
grafana, n8n, backstage, dependency-track …) runs on CNPG, and that path is governed by kyverno
policy.

## Considered Options

* An external CNPG `Cluster` (`harbor-db`)
* The chart-bundled Postgres
* A hand-authored bootstrap/owner secret via ExternalSecret (the dependency-track style)

## Decision Outcome

Chosen option: "An external CNPG `Cluster` (`harbor-db`)", because CloudNativePG with WAL
archiving, scheduled backups to Garage S3, and restore drills is the cluster standard — every
stateful app here runs on it, and that path is governed by kyverno policy.

Provision an external CNPG `Cluster` **`harbor-db`** (database `registry`, owner `harbor`) under
`kubernetes/apps/harbor/harbor/app/database/`, and point Harbor at it with
`database.type: external` / `database.external.existingSecret: harbor-db-app`.

Follow the **forgejo pattern with no hand-authored bootstrap secret**: the `Cluster` declares only
`bootstrap.initdb: { database, owner }`, and CNPG generates the `harbor-db-app` Secret
(username/password) itself. Harbor consumes that generated Secret directly — no ExternalSecret and
no password duplication for the DB. Backups use the shared `cnpg-backup` component (an
`ObjectStore` + `ScheduledBackup` to `s3://cnpg-backups-bucket/homelab-cluster/harbor-db/`).

### Positive Consequences

* Harbor's database inherits the cluster's backup/restore guarantees and monitoring for free.
* One fewer secret to manage — the DB credential is CNPG-owned, not in OpenBao.

### Negative Consequences

* CNPG governance is **mandatory**: the `Cluster` must set `storageClass: longhorn`, declare a
  separate `walStorage`, and carry the `monitoring.webgrip.io/enabled: "true"` label.
* Adds a CNPG instance (plus its WAL volume) to the namespace; ties Harbor's DB backups to Garage
  like every other CNPG app.

## Pros and Cons of the Options

### An external CNPG `Cluster` (`harbor-db`)

* Good, because the database inherits the cluster's backup/restore guarantees and monitoring for
  free.
* Good, because the forgejo "let CNPG generate `-app`" approach leaves no secret to manage — the
  DB credential is CNPG-owned, not in OpenBao.
* Bad, because it adds a CNPG instance (plus its WAL volume) to the namespace.

### The chart-bundled Postgres

* Good, because simplest to enable.
* Bad, because un-backed-up, outside CNPG governance and monitoring, and a snowflake compared to
  every other database in the cluster.

### A hand-authored bootstrap/owner secret via ExternalSecret (the dependency-track style)

* Good, because it works.
* Bad, because it's an extra secret and moving part that the forgejo "let CNPG generate `-app`"
  approach removes entirely.

## Links

* 2026-06-12 — accepted; `harbor-db` deployed with the Harbor stack
