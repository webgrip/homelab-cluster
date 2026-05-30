pr: 335

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This Renovate PR updates the GUAC container image used by two Kubernetes ingestion jobs from `v1.0.1` to `v1.1.0` and pins a digest. Upstream `v1.1.0` includes ingestion and backend stability fixes plus runtime image changes (notably Dockerfile user changes) that can affect job startup/permissions. The local blast radius is limited to `guaccollect`/`guacone` jobs in `security`, but those jobs feed core security graph data, so a smoke validation before merge is warranted.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/guacsec/guac` | Docker/OCI (GHCR) | `v1.0.1` → `v1.1.0@sha256:1d138a384016bd599e4add5fcd2d86a4ca98c1d859a98b31326a403aa47fcf9f` | minor | runtime (Kubernetes batch ingestion jobs) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| [behavior] | Dockerfile change adds a user for ent migrations. Runtime user/permissions can change container behavior. | [commit 8c812fd](https://github.com/guacsec/guac/commit/8c812fde27290cb9929216f642cb9c449804637c), [PR #2793](https://github.com/guacsec/guac/pull/2793) | **Yes** — this repo runs `ghcr.io/guacsec/guac` directly in jobs, so image user/permission changes can affect startup and file/db access. |
| [feature] | OCI collection now supports insecure registries. | [commit 5a43382](https://github.com/guacsec/guac/commit/5a433826ebfc391073a3eee95e7e410290b26eb4), [PR #2844](https://github.com/guacsec/guac/pull/2844) | **No** — updated local jobs run `guaccollect s3` / `guacone collect files`, not OCI collection flags. |
| [bugfix] | OCI collector fix for registry endpoints with explicit ports. | [commit 43b6046](https://github.com/guacsec/guac/commit/43b60467698d45941c98d0759cee8dd6e7ed8d82), [PR #2827](https://github.com/guacsec/guac/pull/2827) | **No** — same reason: this PR only updates non-OCI collector jobs. |
| [bugfix] | Vulnerability ingestion fix (`vulnerability is not getting ingested`). | [commit 2efadf1](https://github.com/guacsec/guac/commit/2efadf1bb189ed1deb52d45b4d0e175935b7460e), [PR #2790](https://github.com/guacsec/guac/pull/2790) | **Unknown** — local data pipelines can include vuln-bearing SBOM content, but exact coverage of this code path is not explicit in repo manifests. |
| [bugfix] | Ent backend bulk upsert race/`ErrNoRows` handling improvements. | [commit 945b011](https://github.com/guacsec/guac/commit/945b01125b3aeb94f1fd93706127d314400eb68e), [PR #2850](https://github.com/guacsec/guac/pull/2850) | **Yes** — local GUAC deployment uses Ent/Postgres backend (`guac.backend.ent` in Helm values). |
| [bugfix] | Added missing CycloneDX VEX status mappings (`resolved_with_pedigree`, `false_positive`). | [commit c715000](https://github.com/guacsec/guac/commit/c7150004922b2663ce266a63eab9086205dfcb99), [PR #2813](https://github.com/guacsec/guac/pull/2813) | **Unknown** — repo has security ingestion workflows, but explicit VEX artifact ingestion paths are not clearly declared in these manifests. |

### Local impact

Local direct image usage was found in:
- `kubernetes/apps/security/guac/app/s3-collector.yaml`
- `kubernetes/apps/security/guac/app/sample-data-job.yaml`

Both are batch ingestion workloads (CronJob/Job) feeding GUAC graph data. The GUAC chart config indicates Ent/Postgres backend (`kubernetes/apps/security/guac/app/helmrelease.yaml`), so upstream backend ingestion fixes are relevant to reliability. These jobs are not highly privileged (sample job drops all capabilities and runs non-root), but data-path regressions can silently reduce SBOM/vulnerability graph quality. Rollback is straightforward at manifest level (image tag/digest), but data correctness issues may be harder to detect without post-run validation.

### Improvement opportunities

- **`Document/enable OCI collector insecure-registry settings if private HTTP registries are in scope`** — GUAC now supports insecure registry handling for OCI collection, which may simplify future integration with non-TLS/internal registries. [source](https://github.com/guacsec/guac/pull/2844)

### Grafana dashboards and alerts

No dashboard or alert changes identified for this specific image bump.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard / Alert / Metric / Scrape config | No observability files under `kubernetes/apps/observability` or `kubernetes/components` were found to reference `guac` metrics directly. | None | Upstream `v1.1.0` notes reviewed did not identify metric name/label changes; local observability manifests do not currently target GUAC-specific metrics directly. |

### Pre-merge checks

- [ ] Run a one-off execution of `guac-sample-data` and confirm both `guacone collect files` commands complete successfully with `v1.1.0`.
- [ ] Trigger/observe one `guac-s3-collector` run and confirm successful ingestion + no permission/user-related startup errors.
- [ ] Check GUAC backend logs after run for ingestion/upsert errors (especially Ent/Postgres paths) to validate no regressions from runtime/backend changes.
- [ ] Verify generated graph contents are non-empty (spot-check expected sample docs/SBOM artifacts) after the upgraded jobs finish.

### Follow-up

- [ ] Add a GUAC ingestion health alert/dashboard panel (job success/failure and ingestion error signals) — helps detect silent data-quality regressions during future image upgrades. (Local context: no GUAC-specific observability references found under `kubernetes/apps/observability`.)

### Evidence reviewed

- PR: `feat(container): update image ghcr.io/guacsec/guac ( v1.0.1 ➔ v1.1.0 )`; labels `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 2 files changed, image tag+digest updated in 2 jobs.
- Files in repo: `kubernetes/apps/security/guac/app/s3-collector.yaml`, `kubernetes/apps/security/guac/app/sample-data-job.yaml`, `kubernetes/apps/security/guac/app/helmrelease.yaml`, repository-wide grep results for `guac` and observability paths.
- Upstream sources checked: https://github.com/guacsec/guac/releases/tag/v1.1.0, https://github.com/guacsec/guac/compare/v1.0.1...v1.1.0, and commit/PR links listed above.
- Notable uncertainty: Upstream release notes are commit-heavy and do not explicitly classify breaking changes; exact runtime exposure to some ingestion code paths (vuln/VEX) is inferred from manifests and may require runtime validation.
