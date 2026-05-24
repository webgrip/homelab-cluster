pr: 232

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR updates the Pyroscope Helm chart OCI reference from `2.0.1` to `2.0.2` (patch). The release contains a notable concurrency bug fix (buffer reuse-after-free in label value queries), security dependency bumps, and documentation cleanup. No breaking changes or API removals are present. The change is digest-pinned, stateless in terms of API surface, and consistent with the existing deployment pattern in this repo.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/grafana/helm-charts/pyroscope` | OCI / Helm | `2.0.1 → 2.0.2` | patch | runtime / observability | Green |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[bugfix]` | Clone label values to prevent buffer reuse-after-free in concurrent `LabelValues` queries | [#5116](https://github.com/grafana/pyroscope/issues/5116) / [#5121](https://github.com/grafana/pyroscope/issues/5121) | **Yes** — Pyroscope is deployed here with a service monitor and Grafana datasource; concurrent label queries are expected from Grafana dashboards. This fix prevents potential data corruption or panics. |
| `[security]` | Bumped security-related dependency versions for the v2.0 branch | [#5125](https://github.com/grafana/pyroscope/issues/5125) | **Yes** — directly affects the deployed runtime. Specific CVEs were not listed but this is a proactive security posture improvement. |
| `[unknown]` | Specific CVEs or dependency names for the security bump are not enumerated in the release notes | [#5125](https://github.com/grafana/pyroscope/issues/5125) | **Unknown** — the upstream PR title is "Bump security deps for v2.0" but the full dep delta was not disclosed in the changelog. Low concern for a patch release. |
| `[feature]` | Documentation: v2.0.1 release notes added, outdated v2 note removed | [#5087](https://github.com/grafana/pyroscope/issues/5087) / [#5109](https://github.com/grafana/pyroscope/issues/5109) | **No** — docs-only, no operational impact. |

### Local impact

Pyroscope is deployed in the `observability` namespace via a Flux `HelmRelease` (`kubernetes/apps/observability/pyroscope/app/helmrelease.yaml`) backed by an `OCIRepository` (`kubernetes/apps/observability/pyroscope/app/ocirepository.yaml`).

**Storage:** Persistent storage is enabled (`20Gi` PVC). This is a Helm chart-level patch; no storage schema migrations are in scope for this release.

**Grafana integration:** Grafana (`kubernetes/apps/observability/grafana/app/helmrelease.yaml`) provisions a `pyroscope` datasource pointing at `http://pyroscope.observability.svc.cluster.local:4040`, and installs the `grafana-pyroscope-app` plugin. The bug fix for label value buffer reuse directly improves reliability for Grafana-initiated profiling queries.

**Privilege:** Pyroscope runs as a standard Kubernetes workload with no elevated cluster permissions. Rollback is straightforward: revert the `ocirepository.yaml` tag and digest.

**Digest pinning:** Both old and new refs are digest-pinned (`sha256:…`), providing strong supply-chain guarantees.

### Improvement opportunities

- **Enable object storage for Pyroscope** — The release notes and v2 docs note that `pyroscope.storage.backend` (S3/GCS/Azure) is now stable in v2. The current config uses local PVC storage with a comment `# Pyroscope object storage can be enabled later`. Now that v2 is fully stable and actively patched, this is a good time to plan the migration. See [v2 storage docs](https://grafana.com/docs/pyroscope/latest/reference-pyroscope-v2-architecture/migrate-from-v1/).

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Datasource | `pyroscope` datasource in Grafana HelmRelease pointing to port 4040 | None | No metric or label renames in this release |
| Plugin | `grafana-pyroscope-app` installed in Grafana | None | Plugin is independently versioned; chart upgrade does not affect plugin |
| ServiceMonitor | `serviceMonitor.enabled: true` in Pyroscope HelmRelease | None | No scrape config or metric changes documented in v2.0.2 |

No dashboard or alert changes are required by this update.

### Pre-merge checks

- [ ] Confirm Flux reconciles the `OCIRepository` and `HelmRelease` without errors after merge (check `flux get helmrelease pyroscope -n observability`).
- [ ] Verify Pyroscope pod restarts cleanly and reaches `Running` state (`kubectl get pods -n observability -l app.kubernetes.io/name=pyroscope`).
- [ ] Spot-check Grafana Pyroscope datasource still returns data post-upgrade.

### Follow-up

- [ ] Evaluate object storage backend for Pyroscope — the current local PVC approach is noted as temporary in the HelmRelease comment; v2 storage is now stable. See `kubernetes/apps/observability/pyroscope/app/helmrelease.yaml` line 26–27.

### Evidence reviewed

- **PR:** "fix(container): update image ghcr.io/grafana/helm-charts/pyroscope ( 2.0.1 ➔ 2.0.2 )", labels: `area/kubernetes`, `renovate/container`, `type/patch`, `dependencies`. Diff: 2 lines changed in `ocirepository.yaml` (tag + digest).
- **Files in repo:** `kubernetes/apps/observability/pyroscope/app/ocirepository.yaml`, `kubernetes/apps/observability/pyroscope/app/helmrelease.yaml`, `kubernetes/apps/observability/pyroscope/ks.yaml`, `kubernetes/apps/observability/grafana/app/helmrelease.yaml`, `kubernetes/apps/observability/kustomization.yaml`.
- **Upstream sources checked:** GitHub releases API `https://api.github.com/repos/grafana/pyroscope/releases/tags/v2.0.2` (confirmed); upstream commit links for PRs #5125, #5116, #5121, #5087, #5109.
- **Notable uncertainty:** The exact packages bumped in the "Bump security deps" commit (#5125) are not enumerated in the release notes. This is minor for a patch release and does not change the low-risk assessment.
