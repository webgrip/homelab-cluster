pr: 318

## Dependency Update Review

**Verdict:** Green — Low risk  
**Recommendation:** Merge  
**Confidence:** High

### Executive summary

This PR updates the `mariadb:12.2` image digest from `sha256:3502612...` to `sha256:6a4c4bb...`. Both digests resolve to **MariaDB 12.2.2** (unchanged server version, released 2026-02-12); the rebuild incorporates a security improvement to the Docker entrypoint — password env vars are now unset from the process environment before `mariadbd` starts — plus routine Ubuntu Noble base-image OS patches. No breaking changes were identified. The deployment uses `MARIADB_AUTO_UPGRADE=1`, which is appropriate and will be a no-op since the server version has not changed.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `mariadb` | Docker/OCI | `sha256:3502612… → sha256:6a4c4bb…` (tag `12.2`, server v12.2.2 unchanged) | digest | runtime (database for Invoice Ninja) | Green |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[security]` | Password-related env vars (`MARIADB_ROOT_PASSWORD`, `MARIADB_PASSWORD`, `MYSQL_ROOT_PASSWORD`, `MARIADB_ROOT_PASSWORD_HASH`, `MARIADB_ROOT_HOST`, etc.) are now unset from the process environment after initialization, immediately before `exec mariadbd`. Prevents credential leakage via `/proc/<pid>/environ` or `ps e` inspection on the container host. | [mariadb-docker commit 4d2a464d](https://github.com/MariaDB/mariadb-docker/commit/4d2a464d834710b1e7b7f42c7a0b21362d9f1b13) / [original commit 55ea769c](https://github.com/MariaDB/mariadb-docker/commit/55ea769c85b61810993cfec6ce47de2d9988aac5) | **Yes — positive**. This repo passes `MARIADB_ROOT_PASSWORD`, `MARIADB_PASSWORD`, `MARIADB_USER`, `MARIADB_DATABASE` via Kubernetes Secrets in `mariadb.yaml`. The passwords are consumed during init and will now be removed from the running process environment. `MARIADB_USER` and `MARIADB_DATABASE` (non-password vars) are retained as expected. |
| `[behavior]` | Env-var unsetting was refined to only run inside the `if` block that starts `mariadbd` (not in helper/client invocations), per [commit 1b6429ba](https://github.com/MariaDB/mariadb-docker/commit/1b6429ba3544e134715c15f8c56cc6f665f827c9). | [mariadb-docker commit 1b6429ba](https://github.com/MariaDB/mariadb-docker/commit/1b6429ba3544e134715c15f8c56cc6f665f827c9) | **No** — affects entrypoint logic branches only. No operational change for normal `docker run mariadb` or Kubernetes deployment startup. |
| `[bugfix]` | Base Ubuntu Noble packages refreshed with OS-level security patches (routine image rebuild). Exact CVEs depend on Ubuntu advisory timeline. | [Docker Hub tag `12.2` last pushed 2026-05-30T05:37:43Z](https://hub.docker.com/r/library/mariadb/tags?name=12.2) | **Yes — positive**. Base OS CVEs patched on the running Pod. |
| `[unknown]` | MariaDB server binary version: confirmed as 12.2.2 in both old and new digests; no server-level changelog entries apply to this update. | [versions.json](https://raw.githubusercontent.com/docker-library/mariadb/master/versions.json) | **No** — server version unchanged. |

### Local impact

MariaDB is used as the sole database backend for Invoice Ninja (`invoiceninja` namespace), exposed via `invoiceninja-mariadb` Service on port 3306, consumed by the Invoice Ninja Deployment (`invoiceninja-deployment.yaml`) and configured in `configmap.yaml` (`DB_HOST: invoiceninja-mariadb`, `DB_TYPE: mysql`).

The MariaDB container is defined in `kubernetes/apps/invoiceninja/invoiceninja/app/mariadb.yaml` as a `Deployment` (replicas: 1) with:
- **Credentials** injected from Kubernetes Secret `invoiceninja-secrets` — `MARIADB_ROOT_PASSWORD`, `MARIADB_DATABASE`, `MARIADB_USER`, `MARIADB_PASSWORD`. All four password-type vars will be cleared from the running process environment after init in the new image.
- **`MARIADB_AUTO_UPGRADE=1`** — triggers `mariadb-upgrade` on startup if the schema version differs from the server version. Since the server version is unchanged (12.2.2), this runs as a no-op.
- **`MARIADB_DISABLE_UPGRADE_BACKUP=1`** — skips the pre-upgrade backup step. Acceptable since no actual upgrade is occurring.
- **PVC**: `invoiceninja-mariadb` on Longhorn. Persistent volume is not affected by image rebuild.
- **Rolling strategy**: `maxSurge=0, maxUnavailable=1` — a single brief downtime window (~30–60 s) when the old Pod terminates and the new one passes its readiness probe (`healthcheck.sh --connect --innodb_initialized`, 10 s initial delay, 5 s period).
- **Rollback**: straightforward via `kubectl rollout undo` since Longhorn data is separate from the image layer.

The Kyverno policies `exception-third-party-images.yaml` and `exception-third-party-workloads.yaml` already exempt `invoiceninja-mariadb`, so no policy changes are needed.

### Improvement opportunities

- **`MARIADB_DISABLE_UPGRADE_BACKUP=1`** — Now that the image clears password env vars during startup, the risk surface of the init process is reduced. However, if a MariaDB server version bump ever does occur, keeping `MARIADB_DISABLE_UPGRADE_BACKUP=1` means you have no rollback snapshot inside the container. Consider maintaining a periodic Longhorn snapshot schedule for `invoiceninja-mariadb` PVC as a compensating control. This is not introduced by the current update but is worth noting given the stateful nature of the workload.
- **Move to StatefulSet** — the MariaDB workload is stateful (Longhorn PVC for `/var/lib/mysql`) but is currently deployed as a `Deployment`. Kubernetes `StatefulSet` provides ordered rolling updates and stable pod identity, which can reduce the risk of split-brain or data corruption during restarts. No upstream change forces this now, but the `12.2` release series supports it cleanly.

### Grafana dashboards and alerts

No dashboard or alert changes identified.

A search of the repository found no Grafana dashboard JSON files, PrometheusRule resources, ServiceMonitor/PodMonitor resources, or Loki/Alloy configs that reference MariaDB or MySQL metrics. There is no observability stack for the `invoiceninja` namespace in this repository.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard / Metrics | None found | None | No monitoring manifests reference `mariadb`, `mysql_*`, or `invoiceninja` metrics in the repo. |

### Pre-merge checks

- [ ] Confirm Invoice Ninja is not processing critical invoices or large batch jobs at merge time (rolling restart causes ~30–60 s DB downtime).
- [ ] After merge, verify the new Pod reaches `Running` and passes both readiness and liveness probes (`kubectl get pods -n invoiceninja -w`).
- [ ] Confirm Invoice Ninja reconnects cleanly after the MariaDB Pod restart (`kubectl logs -n invoiceninja <invoiceninja-pod>`).

### Follow-up

- [ ] Consider a periodic Longhorn snapshot schedule for the `invoiceninja-mariadb` PVC — the current `MARIADB_DISABLE_UPGRADE_BACKUP=1` setting means no automated pre-upgrade backup exists if a future version bump occurs. Related PVC: `kubernetes/apps/invoiceninja/invoiceninja/app/pvc.yaml`.
- [ ] Evaluate migrating the MariaDB workload from `Deployment` to `StatefulSet` for safer rolling updates on stateful DB storage (`kubernetes/apps/invoiceninja/invoiceninja/app/mariadb.yaml`).

### Evidence reviewed

- **PR**: "chore(container): update image mariadb ( 3502612 ➔ 6a4c4bb )" — labels: `area/kubernetes`, `renovate/container`, `type/digest`, `dependencies`. Diff: single line change in `kubernetes/apps/invoiceninja/invoiceninja/app/mariadb.yaml` updating the SHA256 digest for `mariadb:12.2`.
- **Files in repo**: `kubernetes/apps/invoiceninja/invoiceninja/app/mariadb.yaml`, `configmap.yaml`, `secret.sops.yaml`, `invoiceninja-deployment.yaml`, `pvc.yaml`, `kustomization.yaml`, `kubernetes/apps/kyverno/policies/app/exception-third-party-images.yaml`, `exception-third-party-workloads.yaml`.
- **Upstream sources checked**:
  - Docker Hub API: `https://hub.docker.com/v2/repositories/library/mariadb/tags?name=12.2` — confirmed `12.2` tag last pushed 2026-05-30, still at MariaDB 12.2.2.
  - `docker-library/mariadb` (mirrored at `MariaDB/mariadb-docker`) commit log: confirmed 5 commits between 2026-05-25 and 2026-05-29 affecting the `12.2` branch.
  - MariaDB GitHub releases API: `https://api.github.com/repos/MariaDB/server/releases` — confirmed 12.2.2 is the latest GA release (2026-02-12), no newer 12.2.x release.
  - `docker-library/mariadb` `versions.json`: confirmed `12.2` → `12.2.2+maria~ubu2404`.
- **Notable uncertainty**: The exact Ubuntu Noble CVEs patched in this rebuild were not enumerated (Ubuntu Security Notices were not fetched). Impact is expected to be low since no known critical CVEs in the Ubuntu Noble base at this time, but this cannot be confirmed without checking `https://ubuntu.com/security/notices`.
