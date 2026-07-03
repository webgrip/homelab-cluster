# RFC: The Postgres data layer — CNPG as the standard, single-instance as the posture

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** Eleven CloudNativePG clusters run every stateful app's database; ADR-0019 calls CNPG
> "the cluster standard" — a standard no record established. All eleven are `instances: 1` by an
> unstated policy, guac silently deviates from the backup pattern, and connection pooling is
> unresolved after the freshrss PgBouncer pause. This RFC backfills the standard, makes
> single-instance an explicit decision with criteria for exceptions, and normalizes the stragglers.

## Why

The inventory (verified in-tree 2026-07-02): 11 CNPG `Cluster`s — authentik, backstage,
dependency-track, devex, forgejo, freshrss, grafana, guac, harbor, n8n, sparkyfitness. Every one:
`instances: 1`, `storageClass: longhorn`, separate `walStorage`. Ten follow the house backup
pattern (barman-cloud plugin + `ObjectStore` + `ScheduledBackup` → Garage, credentials via the
`cnpg-backup` component); **guac** does not — it has a nightly logical `pg_dump` CronJob instead
(no WAL archiving, no PITR). The pattern is *enforced* by Kyverno (`storage-cnpg-governance`) and
*assumed* by the `cnpg-database` skill, the [backup-tiers doc](../general/database-backup-tiers.md),
and five ADRs — but the standard itself, and its single-instance posture, were never decided
anywhere.

Why the posture matters enough to record:

- **Every DB restart is app downtime.** Single instance + RWO means each CNPG operator hiccup
  recreates the primary — the authentik-restarts incident traced ~180 app restarts to exactly
  this (BestEffort operator OOM → single-instance DB churn). The
  [layered-hardware RFC](rfc-layered-hardware-architecture.md) names "single-instance CNPG" the
  L4 gap and "sync replicas + anti-affinity" the edge.
- **The constraint is real, not laziness**: with two storage nodes and 12 GiB soyos
  ([ADR-0008](../adr/adr-0008-confine-longhorn-to-workers.md)/[0028](../adr/adr-0002-application-workload-placement.md)),
  a second synchronous instance per DB doubles the footprint of eleven databases on the
  RAM-tightest resource. Accepting downtime-on-restart is a defensible trade — but today it is an
  *implicit* trade.
- **Pooling is unfinished business**: the freshrss PgBouncer sidecar
  ([ADR-0016](../adr/adr-0016-openbao-dynamic-postgres-credentials.md), paused 2026-07-02) exists
  only as a dynamic-credentials enabler; CNPG's native `Pooler` CR was never evaluated. Whatever
  is chosen shapes both the dynamic-creds endgame and any future replica topology.

## Proposal

1. **Backfill the standard as a retroactive ADR**: every app database is an external CNPG
   `Cluster` (never chart-bundled), `longhorn` + `walStorage`, monitoring label, barman
   `ObjectStore` + `ScheduledBackup` via the `cnpg-backup` component, CNPG-generated `-app`
   secret (the forgejo pattern, per ADR-0019). Alternatives that lost: chart-bundled Postgres
   (un-backed-up snowflakes), a single shared Postgres for all apps (blast radius, no per-app
   restore), operator alternatives (Zalando/Percona).
2. **Record the single-instance posture as an explicit decision** with the exception test:
   a database earns `instances: 2` only when (a) its app is genuinely restart-intolerant *and*
   user-facing, (b) worker RAM headroom demonstrably allows it, and (c) the app's own tier in the
   [backup-tiers doc](../general/database-backup-tiers.md) justifies it. Candidates to evaluate
   against the test when hardware allows (L4): forgejo (the GitOps source once ADR-0011 lands)
   and authentik (login availability). Everything else stays 1 by policy, not accident.
3. **Normalize guac**: either bring it onto the barman pattern like the other ten, or record its
   pg_dump-only status as a deliberate tier decision (its data is re-derivable from SBOM
   re-ingestion, which is a fair argument for the cheaper path) — currently it is neither.
4. **Decide pooling once**: CNPG `Pooler` CR vs per-app PgBouncer sidecar vs none-by-default.
   The sidecar exists solely for the dynamic-creds pilot; if the `Pooler` CR can serve that role
   (rotating backend creds behind stable client creds), one mechanism serves both needs. Feeds
   the paused [dynamic-credentials RFC](rfc-dynamic-database-credentials.md) rather than blocking
   on it.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | CNPG as the cluster database standard (retroactive) |
| candidate | — | Single-instance posture + the exception test (new) |
| candidate | — | guac backup normalization (or recorded tier exception) (new) |
| candidate | — | Connection-pooling mechanism (new; feeds dynamic creds) |

## Out of scope

- Backup targets and DR beyond the per-DB pattern — the [backup & DR RFC](rfc-backup-dr.md).
- Dynamic credentials themselves — their [own RFC](rfc-dynamic-database-credentials.md).
- Non-Postgres state (Redis/Valkey, SQLite-in-PVC apps) — small enough to stay app-local for now.

## References

- [database-backup-tiers](../general/database-backup-tiers.md) · [cnpg-backups runbook](../runbooks/cnpg-backups.md) ·
  the `cnpg-database` skill
- [ADR-0019](../adr/adr-0019-external-cnpg-database.md) ·
  [ADR-0016](../adr/adr-0016-openbao-dynamic-postgres-credentials.md) ·
  memory: authentik restarts ← CNPG operator OOM
