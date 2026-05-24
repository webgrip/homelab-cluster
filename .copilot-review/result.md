pr: 251

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR upgrades a single helper image in `sparkyfitness` from `postgres:16-alpine` to `postgres:18-alpine` (digest-pinned). The image is used by a one-off Kubernetes `Job` that runs `psql` to create `pg_stat_statements` and grant execute permissions, not as the primary CNPG database server image. Primary risk comes from cross-major PostgreSQL client behavior changes (16 → 17 → 18), especially around migration-era incompatibilities and extension/statistics changes. Merge is reasonable after a targeted runtime check of the job in-cluster.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `postgres` | Docker/OCI | `16-alpine@sha256:16bc17...` → `18-alpine@sha256:96d56f...` | major | infra/runtime (Kubernetes batch job helper client) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| [migration] | PostgreSQL 17 renamed `pg_stat_statements` I/O timing columns. | [source](https://www.postgresql.org/docs/release/17.0/) · [commit](https://postgr.es/c/13d00729d) | **No** — this repo’s updated job uses `CREATE EXTENSION` + `GRANT` on `pg_stat_statements_reset`, not these renamed stats columns. |
| [migration] | PostgreSQL 17 removed `pg_stat_bgwriter.buffers_backend` / `buffers_backend_fsync`. | [source](https://www.postgresql.org/docs/release/17.0/) · [commit](https://postgr.es/c/74604a37f) | **No** — current repo alerting/dashboard files for CNPG use backup/restore metrics, not `pg_stat_bgwriter` fields. |
| [feature] | PostgreSQL 18 changed `initdb` default to enable data checksums. | [source](https://www.postgresql.org/docs/release/18.0/) · [commit](https://postgr.es/c/04bec894a04) | **No** — this PR updates a client utility image for a Job; it does not change CNPG server initialization settings. |
| [migration] | PostgreSQL 18 deprecates MD5 password authentication. | [source](https://www.postgresql.org/docs/release/18.0/) · [commit](https://postgr.es/c/db6a4a985) | **Unknown** — credentials are secret-driven and auth method is not explicitly declared in reviewed manifests. |
| [behavior] | PostgreSQL 18 changes `COPY FROM CSV` handling of `\.` EOF marker. | [source](https://www.postgresql.org/docs/release/18.0/) · [commit](https://postgr.es/c/770233748) | **No** — this repo job script does not use `COPY`; it runs DDL + PL/pgSQL grant logic only. |

### Local impact

- PR changes exactly one file: `kubernetes/apps/sparkyfitness/sparkyfitness/app/database/pgstatstatements-perms-job.yaml`.
- The image is used in a `batch/v1 Job` container named `psql`, with superuser credentials from secret `sparkyfitness-db-superuser`, to run:
  - `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;`
  - a loop granting execute on all overloads of `pg_stat_statements_reset`.
- The same extension setup intent is also present in `kubernetes/apps/sparkyfitness/sparkyfitness/app/database/cluster.yaml` via `shared_preload_libraries`, parameters, and `postInitSQL`.
- Blast radius is narrower than a server-image upgrade (stateless helper pod), but privilege is high (superuser DB credentials), so a post-upgrade job execution check is important.

### Improvement opportunities

- **Pin and document expected server/client major compatibility for this admin job** — major client jumps can be surprising even when server stays unchanged; clarifying expected compatibility in the manifest or runbook would reduce future review uncertainty. [PostgreSQL 17 release notes](https://www.postgresql.org/docs/release/17.0/), [PostgreSQL 18 release notes](https://www.postgresql.org/docs/release/18.0/)

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard / Alert / Metric / Scrape config | `kubernetes/components/cnpg-monitoring/prometheus-rules.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/cnpg-backups-dr.yaml` track CNPG backup/restore and DR metrics | None | This PR only updates a helper `psql` image for a permission job; no metric names in these files depend on that image version. |

### Pre-merge checks

- [ ] Reconcile this PR in a non-prod cluster and confirm `sparkyfitness-db-pgstatstatements-perms` Job completes successfully.
- [ ] Verify the job still grants execute on `pg_stat_statements_reset` (all overloads) to role `sparky`.
- [ ] Confirm no authentication regression for the superuser secret path (`sparkyfitness-db-superuser`) when using `psql` from postgres 18 image.
- [ ] Check job logs for SQL errors/warnings (function signature, privilege, or extension-loading issues).

### Follow-up

- [ ] Consider replacing/retiring the standalone perms Job if `postInitSQL` in `cluster.yaml` fully covers steady-state permission requirements — reduces moving parts and future image-major churn review overhead.

### Evidence reviewed

- PR: `feat(container)!: Update image postgres ( 16 ➔ 18 )`; labels: `area/kubernetes`, `type/major`, `renovate/container`, `dependencies`, `major`; diff summary: 1 file changed (+1/-1).
- Files in repo:
  - `kubernetes/apps/sparkyfitness/sparkyfitness/app/database/pgstatstatements-perms-job.yaml`
  - `kubernetes/apps/sparkyfitness/sparkyfitness/app/database/cluster.yaml`
  - `kubernetes/apps/sparkyfitness/sparkyfitness/app/database/kustomization.yaml`
  - `kubernetes/components/cnpg-monitoring/prometheus-rules.yaml`
  - `kubernetes/apps/observability/grafana/app/dashboards/cnpg-backups-dr.yaml`
- Upstream sources checked:
  - https://www.postgresql.org/docs/release/17.0/
  - https://www.postgresql.org/docs/release/18.0/
  - https://hub.docker.com/v2/repositories/library/postgres/tags/16-alpine?page_size=1
  - https://hub.docker.com/v2/repositories/library/postgres/tags/18-alpine?page_size=1
  - https://postgr.es/c/13d00729d
  - https://postgr.es/c/74604a37f
  - https://postgr.es/c/04bec894a04
  - https://postgr.es/c/db6a4a985
  - https://postgr.es/c/770233748
- Notable uncertainty: The manifests reviewed do not explicitly show configured DB password encryption/auth method, so MD5-deprecation exposure is not fully provable from repo state alone.
