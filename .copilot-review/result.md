pr: 224

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR adds a digest pin (`@sha256:16bc17c...`) to the previously floating `postgres:16-alpine` image tag used in a one-off Kubernetes Job. The pinned digest corresponds to the current `16-alpine3.23` image (Alpine base upgraded from 3.21→3.23, last pushed 2026-05-16), which is the same content the floating `16-alpine` tag already resolves to today. This is a pure supply-chain hardening change with no functional impact. Primary risk is near-zero: the image is used only as a `psql` client to run a DDL/permissions script, not as a PostgreSQL server.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `postgres` | Docker/OCI | `16-alpine` (floating) → `16-alpine@sha256:16bc17c...` (digest-pinned) | digest pin | Kubernetes Job — one-shot `psql` client for `pg_stat_statements` setup | Green |

### Important upstream changes

The PR does not bump a semantic version. It pins the existing floating `16-alpine` tag to the digest that currently resolves from Docker Hub (`16-alpine3.23`, last pushed 2026-05-16). Intermediate Alpine base rebuild changes (3.21 → 3.22 → 3.23) carry only OS-level security patches; no PostgreSQL 16 server-breaking changes are included because this image is used purely as a client binary (`psql`).

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[feature]` | Alpine base bumped 3.21 → 3.22 → 3.23; OS-level security patches applied to PostgreSQL 16 Alpine image | [Docker Hub – 16-alpine tag](https://hub.docker.com/r/library/postgres/tags?name=16-alpine) | **No** — only the psql binary version and Alpine OS packages are updated; no API/config changes affect this repo's usage |
| `[unknown]` | PostgreSQL 16 minor-version included in the 3.23 image may differ from the 3.21 image; Docker Hub does not surface the exact PG minor version per tag | [Docker Hub tag history](https://hub.docker.com/r/library/postgres/tags?name=16-alpine) | **No** — this repo uses `psql` only as a DDL client; minor server version differences in the client binary do not affect the SQL executed |

No dedicated release notes were found beyond Docker Hub tag metadata. The PostgreSQL project's own release notes for PG 16 are at https://www.postgresql.org/docs/16/release.html but do not apply here because the managed server (CloudNativePG) is a separate image.

### Local impact

The image is used in exactly **one file**:

- `kubernetes/apps/sparkyfitness/sparkyfitness/app/database/pgstatstatements-perms-job.yaml`

It runs a Kubernetes `Job` (`sparkyfitness-db-pgstatstatements-perms`) that:
1. Connects to the CloudNativePG cluster (`sparkyfitness-db-rw:5432`) using the superuser secret.
2. Creates the `pg_stat_statements` extension and grants `EXECUTE` on `pg_stat_statements_reset` to the `sparky` role.

The actual PostgreSQL **server** runs as a CloudNativePG Cluster (managed separately via the `cnpg` Helm chart — not this image). This job is therefore stateless, idempotent, and carries no rollback complexity. A pinned digest prevents supply-chain substitution of the psql client binary.

### Improvement opportunities

- **Consider aligning the psql client version with the CNPG server version** — the CNPG cluster image may be at a different PostgreSQL 16 minor version than what `16-alpine3.23` ships. While the SQL used here (`CREATE EXTENSION`, `DO $$ ... $$`, `GRANT`) is version-agnostic, explicit version alignment is best practice for client/server tooling.
- **Apply the same digest-pinning pattern to other `image:` references in the repo** — this PR shows the Renovate pinDigest workflow working correctly. Other jobs or init containers that use floating tags would benefit from the same treatment.

### Grafana dashboards and alerts

No dashboard or alert changes identified. The `postgres:16-alpine` image is a one-shot psql client job and does not expose metrics, nor is it referenced in any Prometheus/Grafana configuration. All cnpg monitoring (`kubernetes/components/cnpg-monitoring/prometheus-rules.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/cnpg-backups-dr.yaml`) targets the CloudNativePG operator and cluster, not this utility image.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Metrics / Dashboards | None — image is a psql client Job only | None | No metrics exposed by this workload |

### Pre-merge checks

- [ ] Confirm `kubectl get job -n sparkyfitness sparkyfitness-db-pgstatstatements-perms` completes successfully after Flux reconciles the change (expected: `COMPLETIONS: 1/1`).
- [ ] Verify image pull succeeds in the cluster (no `ErrImagePull` / `ImagePullBackOff` events): `kubectl describe pod -n sparkyfitness -l job-name=sparkyfitness-db-pgstatstatements-perms`.

### Follow-up

- [ ] Pin the `postgres:16-alpine` image digest in any other locations if more floating references are added in future — Renovate's `pinDigest` config handles this automatically once enabled globally.

### Evidence reviewed

- **PR**: "chore(container): pin image postgres to 16bc17c" — labels: `area/kubernetes`, `renovate/container`, `dependencies`; diff: +1/-1 in `pgstatstatements-perms-job.yaml` adding `@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229` to the `postgres:16-alpine` image reference.
- **Files in repo**: `kubernetes/apps/sparkyfitness/sparkyfitness/app/database/pgstatstatements-perms-job.yaml` (only file changed and only file using the `postgres:` image directly).
- **Upstream sources checked**: `https://hub.docker.com/v2/repositories/library/postgres/tags?name=16-alpine&page_size=10` — confirmed digest `sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229` is the current `16-alpine` and `16-alpine3.23` tag, last pushed 2026-05-16.
- **Notable uncertainty**: Docker Hub does not surface the exact PostgreSQL minor version included in each Alpine rebuild; however this is immaterial given the client-only use case.
