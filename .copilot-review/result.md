pr: 314

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR pins the Grafana image renderer sidecar from floating `latest` to `latest@sha256:a30a68c…`, which Docker Hub currently maps to `v5.8.8`. That improves reproducibility and supply-chain traceability, but because the repo was previously on an unpinned `latest`, the effective before-state in the cluster is unknown: merging may be a no-op or may implicitly roll the renderer forward to `v5.8.8` on the next pull/restart. The local blast radius is limited to Grafana image rendering, but a render smoke test is still warranted because Grafana uses the sidecar for `/render` requests and the pod runs with `Recreate` strategy.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `grafana/grafana-image-renderer` | Docker/OCI | `latest` → `latest@sha256:a30a68c2de11a1aad5733452536ac50fbc2f3958e6d0aa046ef9eb56db7c6a6d` (Docker Hub `latest`/`v5.8.8`) | digest pin | runtime / observability | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[migration]` | `v5.8.8` explicitly skips `v5.8.4`-`v5.8.7` after upstream release issues and publishes a cumulative changelog from `v5.8.3...v5.8.8`. | [source](https://github.com/grafana/grafana-image-renderer/releases/tag/v5.8.8) | **Unknown** — this repo used floating `latest`, so the currently running digest in-cluster is unknown; merge may simply pin the already-running image or may advance an older cached pull. |
| `[behavior]` | Renderer API now falls back to the server timezone when an invalid timezone is supplied in the query string. | [PR #983](https://github.com/grafana/grafana-image-renderer/pull/983) | **Yes** — this repo enables remote rendering in Grafana and sends render traffic to the sidecar/service (`kubernetes/apps/observability/grafana/app/helmrelease.yaml`, `kubernetes/apps/observability/grafana/app/grafana-instance.yaml`). |
| `[bugfix]` | Bundled Chromium was updated to `148.0.7778.167`, which can change rendering behavior for panels/PDFs even when Grafana config is unchanged. | [PR #985](https://github.com/grafana/grafana-image-renderer/pull/985) | **Yes** — every dashboard/panel render in this repo depends on the renderer container’s Chromium build. |
| `[security]` | Debian base image tag was updated to `trixie-20260505`, pulling in newer OS packages. | [PR #982](https://github.com/grafana/grafana-image-renderer/pull/982) | **Yes** — the sidecar runs continuously in the `observability` namespace, so base-image package changes affect the deployed runtime surface. |
| `[unknown]` | Upstream also migrated Docker publishing/attestation work during this release (`GAR` migration and attestation fixes). | [PR #987](https://github.com/grafana/grafana-image-renderer/pull/987) | **No** — this does not change the renderer API or local config directly, but it is relevant context for provenance review of the published image. |

### Local impact

This dependency is used only in the Grafana deployment under `kubernetes/apps/observability/grafana/app/grafana-instance.yaml`, where `grafana-image-renderer` runs as a sidecar on port `8081`, exposes metrics, and requires the shared `grafana-renderer-token` secret. Grafana is configured to use rendering both in the HelmRelease (`kubernetes/apps/observability/grafana/app/helmrelease.yaml`) and inside the operator-managed instance (`kubernetes/apps/observability/grafana/app/grafana-instance.yaml`), so any behavior change affects dashboard/panel image rendering, report generation, and other `/render` flows.

The sidecar itself is stateless, but it is co-scheduled with Grafana, and the Grafana deployment uses `Recreate`; any rollout that repulls the image can briefly interrupt Grafana availability. Rollback is operationally simple at the manifest level, but the current unpinned pre-merge state makes an exact rollback target ambiguous unless the running digest is recorded first.

### Improvement opportunities

None identified.

### Grafana dashboards and alerts

No dashboard or alert changes identified. This repo enables renderer metrics (`ENABLE_METRICS=true` in `kubernetes/apps/observability/grafana/app/grafana-instance.yaml`), but the only local scrape config I found is the Grafana `ServiceMonitor` on the Grafana service/port (`kubernetes/apps/observability/grafana/app/servicemonitor.yaml`); I found no renderer-specific `ServiceMonitor`/`PodMonitor`, PromQL rules, or dashboards tied to renderer metrics.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Metric / Scrape config | Grafana itself is scraped via `kubernetes/apps/observability/grafana/app/servicemonitor.yaml`; no renderer-specific scrape config found for port `8081` | None | `v5.8.8` release notes do not call out metric renames/removals, and no local dashboards/alerts reference renderer-specific metrics. |
| Dashboard / Alert | No renderer-specific dashboards or alerts found in `kubernetes/apps/observability/grafana/app/dashboards`, `.../alerting`, or `kubernetes/apps/observability/kube-prometheus-stack/app` | None | Local search found only generic dashboard JSON `"renderer": "flot"` keys, not Grafana image renderer metrics or alert rules. |

### Pre-merge checks

- [ ] Check the currently running renderer image digest in-cluster; if it is already `sha256:a30a68c2de11a1aad5733452536ac50fbc2f3958e6d0aa046ef9eb56db7c6a6d`, this PR is functionally a reproducibility pin rather than a rollout.
- [ ] After reconcile or the next Grafana pod restart, trigger a real dashboard/panel render and confirm Grafana can still reach the sidecar on `localhost:8081` using the existing renderer token.
- [ ] Watch the Grafana rollout because the pod uses `Recreate`; even a renderer-only image change can temporarily interrupt Grafana while the shared pod is replaced.

### Follow-up

- [ ] Consider switching the image reference to an explicit versioned tag such as `v5.8.8@sha256:...` in `kubernetes/apps/observability/grafana/app/grafana-instance.yaml` — the digest pin makes pulls deterministic, but leaving `latest` in the reference still hides the intended upstream version from quick manifest inspection.
- [ ] Consider scraping the renderer’s own metrics endpoint on port `8081` — the repo already enables renderer metrics in `kubernetes/apps/observability/grafana/app/grafana-instance.yaml`, but no matching `ServiceMonitor`/`PodMonitor` is present locally.

### Evidence reviewed

- PR: `chore(container): pin image grafana/grafana-image-renderer to a30a68c`; labels `area/kubernetes`, `renovate/container`, `dependencies`; diff is 1 file changed (`kubernetes/apps/observability/grafana/app/grafana-instance.yaml`, `+1/-1`). Live checks were mostly green during review, with Flux Local/Test and rendered-config validation successful and one diff job still in progress.
- Files in repo: `kubernetes/apps/observability/grafana/app/grafana-instance.yaml`, `kubernetes/apps/observability/grafana/app/helmrelease.yaml`, `kubernetes/apps/observability/grafana/app/servicemonitor.yaml`, `Taskfile.yaml`.
- Upstream sources checked: https://hub.docker.com/v2/repositories/grafana/grafana-image-renderer/tags?page_size=25, https://github.com/grafana/grafana-image-renderer/releases/tag/v5.8.8, https://github.com/grafana/grafana-image-renderer/releases/tag/v5.8.3, https://github.com/grafana/grafana-image-renderer/blob/master/docs/sources/flags.md, https://github.com/grafana/grafana-image-renderer/pull/982, https://github.com/grafana/grafana-image-renderer/pull/983, https://github.com/grafana/grafana-image-renderer/pull/985, https://github.com/grafana/grafana-image-renderer/pull/987.
- Notable uncertainty: the cluster’s current renderer digest/version was not available from this environment, so I could not determine whether merge would be a no-op pin or the first pull of `v5.8.8`.
