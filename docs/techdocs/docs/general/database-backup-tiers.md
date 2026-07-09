# Database Backup Tiers

A classification of every CloudNativePG (CNPG) Postgres database by **how much
its data is worth protecting**, and the backup strategy that follows from it.
Tiering exists so we spend backup budget — storage on Garage S3, WAL write
amplification, and the Proxmox backup of the Garage VM — where the data actually
matters, instead of treating a regenerable cache the same as the identity
provider.

> Why this exists: the shared `cnpg-backups-bucket` reached **76 GiB**, of which
> `guac-db` (47 GiB) and `dependency-track-db` (27 GiB) were **96%** — almost
> entirely WAL archive from two *regenerable* supply-chain databases. The Garage
> VM's Proxmox backup had grown past 100 GiB as a result. Continuous
> point-in-time recovery (PITR) is the most expensive backup mode there is; most
> databases here do not need it.

## The tiers

| Tier | Meaning | Loss impact | Retention (WAL/PITR) | PITR? |
| ---- | ------- | ----------- | -------------------- | ----- |
| **1** | Irreplaceable **and** outage-critical | Cluster-wide blast radius (auth, money) | **30d** | Yes |
| **2** | Irreplaceable user-authored data | Permanent data loss, no wider outage | **14d** | Yes |
| **3** | Important, but re-derivable with effort | Painful rebuild from an external source of truth | **7d** | Yes |
| **4** | Cache / config; source of truth lives elsewhere | Re-login / re-sync; minutes-to-hours to rebuild | **3d** | Short |
| **5** | Ephemeral / decommissioned | None — no real data, or app is gone | **none** | No |

**Universal settings (all tiers that keep physical backups, i.e. 1–4):**

- `wal_compression = zstd` — compresses full-page images *inside* the WAL stream
  before Barman ever sees them. Pure win: shrinks both the S3 archive **and** the
  local WAL PVC, with no storage-pressure downside.
- Daily base backup (`ScheduledBackup`, `method: plugin`) to `cnpg-backups-bucket`.
- Retention enforced by the Barman ObjectStore `retentionPolicy`; the next
  scheduled backup prunes anything outside the window — no manual S3 deletes.

**Heavy WAL writers** additionally get checkpoint tuning (`max_wal_size`,
`checkpoint_timeout`) to cut full-page-image frequency. This is applied
selectively, sized to each WAL PVC, because larger checkpoint distance raises the
*local* WAL floor — and a past Garage outage already proved that a WAL backlog
that cannot drain will crashloop a cluster (see
[CNPG backups](../runbooks/cnpg-backups.md) and the WAL-SPOF runbook). We do **not** grow WAL
PVCs to chase this while Longhorn is capacity-constrained.

## Current assignments

Footprint is the *current* backup size in `cnpg-backups-bucket` (base + WAL). For
the WAL-heavy tiers this is dominated by WAL accumulation, **not** database size —
e.g. `guac-db`'s actual data is ~1 GiB; the rest was WAL.

| Database | Namespace | Tier | Footprint | Why |
| -------- | --------- | ---- | --------- | --- |
| `authentik-db` | authentik | **1** | 0.8 GiB | SSO/identity. Loss locks every OIDC app out and means re-enrolling users/MFA. Small — long retention is cheap insurance. |
| `forgejo-db` | forgejo | **2** | 0.15 GiB | Issues, PRs, reviews, users, tokens, webhooks — none of it in git. Irreplaceable user content. |
| `n8n-db` | n8n | **2** | 0.16 GiB | User-authored workflows + (encrypted) credentials. Hand-built automation, not regenerable. |
| `sparkyfitness-db` | sparkyfitness | **2** | 0.24 GiB | Personal health/fitness logs. Irreplaceable personal data. |
| `vikunja-db` | vikunja | **2** | new (2026-07-09) | Tasks, projects, comments — user-authored, stored nowhere else (ADR-0040). |
| `devex-db` | observability | **2** | new (2026-06-30) | Raw DevEx survey answers — irreplaceable human input (unlike `grafana-db`). Deliberately keeps **30d** retention, above the Tier-2 default. |
| `dependency-track-db` | security | **3** | 27 GiB | Findings re-derive from re-uploaded SBOMs, but audit state (suppressions, project tags) is user-authored. Heavy WAL writer. |
| `backstage-db` | backstage | **3** | 2.3 GiB | Catalog largely re-discovered from SCM, but holds local TechDocs/state. |
| `grafana-db` | observability | **4** | 0.5 GiB | Dashboards/datasources/alerts are Grafana Operator CRDs in git. DB = sessions/prefs/annotations — regenerable. |
| `harbor-db` | harbor | **4** | 0.02 GiB | Registry metadata; blobs live in Garage S3, images are re-pushable from CI. |
| `guac-db` | security | **4** | <1 GiB | Graph is fully rebuilt from re-ingested SBOMs/attestations by the collectors. Was the single biggest WAL producer (~4 GiB/day), so it's the one DB moved off WAL archiving to a **nightly `pg_dump`** (no PITR) — see Trade-offs below. |
| `freshrss-db` | freshrss | **4** | 0.11 GiB | Subscriptions re-importable (OPML), articles re-fetch; only read/favorite state is mildly precious. |

## How to classify a new database

Ask, in order:

1. **Does losing it lock people out of the cluster, or lose money/legal records?**
   → Tier 1.
2. **Is the data authored by a human and stored nowhere else** (issues, workflows,
   personal logs)? → Tier 2.
3. **Can it be rebuilt from an external source of truth, but only with real effort
   or loss of curated state?** → Tier 3.
4. **Is the real source of truth elsewhere** (git/GitOps CRDs, object storage,
   an upstream feed) so the DB is effectively cache/config? → Tier 4.
5. **Is it throwaway, or is the app gone?** → Tier 5, no backup.

Then wire backups to match the tier's retention row, set `wal_compression = zstd`,
and only add checkpoint tuning if it proves to be a heavy WAL writer.

## Trade-offs and what we deliberately did *not* do

- **We kept Barman physical backups for most live DBs** rather than ripping out
  WAL archiving in favour of logical `pg_dump`. Physical PITR is already wired,
  validated by the restore-drill tooling, and reversible. Tier-appropriate
  **retention** captures the bulk of the savings without a new backup pipeline.
  **The exception is `guac-db`**: at ~4 GiB/day of WAL for a graph that rebuilds
  from re-ingested SBOMs, continuous PITR was pure waste, so it was moved to a
  nightly `pg_dump` (`guac-db-backup` CronJob → `s3://guac/_db-backups/`, keep 7)
  with the barman plugin/ObjectStore/ScheduledBackup removed. Restore path: redeploy
  the cluster and `psql -d guac -f` the latest dump (or just let the collectors
  re-ingest). This is the template for promoting any DB to logical-only.
- **We did not enlarge WAL PVCs** to push checkpoint distance further, because
  Longhorn is capacity-constrained and an undrainable WAL backlog is exactly what
  caused a prior outage.
