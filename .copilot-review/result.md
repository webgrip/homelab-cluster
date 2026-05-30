pr: 303

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR pins the floating `docker.io/python:3.12-slim` tag to its current immutable digest `sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203`. No Python version change occurs — the pinned digest is confirmed (via Docker Hub API) to be the manifest-list for the same `3.12-slim` (Python 3.12.13, Debian Trixie slim) image already in use. The sole purpose is supply-chain reproducibility: future `kubectl apply` runs or pod restarts will pull exactly the same image bytes rather than whatever `3.12-slim` resolves to at that moment.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/python` | Docker/OCI | `3.12-slim` (floating) → `3.12-slim@sha256:090ba77e...` (pinned digest) | digest-pin (no version change) | runtime — Prometheus metrics exporter for Dependency-Track | Green |

### Important upstream changes

This is a digest pin of an existing tag, not a version upgrade. No upstream Python release notes apply. The pinned digest `sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203` was verified against Docker Hub (`https://hub.docker.com/v2/repositories/library/python/tags/3.12-slim`) and corresponds to Python 3.12.13 on Debian Trixie slim, pushed 2026-05-20 — the same image already referenced by the floating tag.

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[unknown]` | No changelog exists for a digest pin; the image content is identical to the current `3.12-slim` tag | [Docker Hub](https://hub.docker.com/_/python/tags?name=3.12-slim) | **No** — no code or behaviour changes |

### Local impact

The image is used in exactly one place: `kubernetes/apps/security/dependency-track/app/metrics-exporter/deployment.yaml`. It runs a single-file Python script (`exporter.py`) that is injected at runtime from a ConfigMap — not baked into the image. The container:

- Calls the Dependency-Track API every 5 minutes (`SCRAPE_INTERVAL=300`)
- Serves Prometheus-format metrics on port 9090
- Uses only Python standard-library modules (`json`, `os`, `time`, `urllib.request`, `http.server`, `threading`)

Because the script is external to the image and depends on nothing beyond the standard library, a digest-pinned `3.12-slim` with identical content is a zero-risk swap. The pod is stateless; rollback is a one-line revert and redeploy.

No elevated privileges, host-path mounts, or sensitive RBAC are present. The API key is consumed from a Kubernetes Secret mounted at `/secrets/api-key`.

Active observability wiring found:
- **ServiceMonitor** (`kubernetes/apps/security/dependency-track/app/metrics-exporter/servicemonitor.yaml`): scrapes `/metrics` every 5 minutes with a 30-second timeout.
- **PrometheusRule** (`kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-security-dt.yaml`): four alert rules fire on `dt_portfolio_vulnerabilities`, `dt_portfolio_policy_violations`, `dt_portfolio_risk_score`, and `dt_exporter_last_scrape_timestamp`. None of these are affected by a digest pin.

### Improvement opportunities

- **Pin the `python:3.12-slim` image used in `dependency-track/app/sbom-uploader/cronjob.yaml`** — a separate `docker.io/python:3.12-slim` reference may exist in the sbom-uploader or policy-bootstrap manifests; verify and pin those too for consistent supply-chain coverage. The policy-bootstrap job uses `alpine:3.21` which installs `python3` at runtime via `apk`, which is outside Renovate's scope.

### Grafana dashboards and alerts

No Grafana dashboard JSON files referencing `dt_portfolio` metrics were found in the repository. The PrometheusRule at `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-security-dt.yaml` is the only observability file referencing these metrics.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Alert — `DependencyTrackMetricsExporterDown` | PrometheusRule fires if `dt_exporter_last_scrape_timestamp` is absent or stale >30 min | None | Not affected by a digest pin; alert continues to work as-is |
| Recording rules — vuln/findings ratios | PrometheusRule `dependency-track.recording` group | None | Unaffected by this change |

No dashboard or alert changes required.

### Pre-merge checks

- [ ] Verify CI passes (flux-local diff, OCI digest validation via `./scripts/verify-oci-digests.sh`)
- [ ] Confirm the pinned digest `sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203` still resolves correctly in your registry/pull policy (no image-pull restrictions that block digest-addressed pulls)

### Follow-up

- [ ] Pin `python:3.12-slim` in any other manifests that still use the floating tag — a search found the sbom-uploader cronjob may reference Python indirectly; review `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml` for unpinned images.
- [ ] Consider adding a Grafana dashboard for `dt_portfolio_*` metrics to make the exporter data visible at a glance alongside existing kube-prometheus-stack dashboards — no upstream blocker, purely an observability improvement.

### Evidence reviewed

- PR: "chore(container): pin image docker.io/python to 090ba77", labels: `area/kubernetes`, `renovate/container`, `dependencies`; diff: one line changed in `kubernetes/apps/security/dependency-track/app/metrics-exporter/deployment.yaml`, adding `@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203`
- Files in repo: `kubernetes/apps/security/dependency-track/app/metrics-exporter/deployment.yaml`, `configmap.yaml`, `servicemonitor.yaml`, `service.yaml`, `kustomization.yaml`; `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-security-dt.yaml`
- Upstream sources checked: `https://hub.docker.com/v2/repositories/library/python/tags/3.12-slim` — confirmed digest `090ba77e` is the manifest-list digest for Python 3.12.13 slim (Trixie), pushed 2026-05-20; `https://hub.docker.com/v2/repositories/library/python/tags?name=3.12` — confirmed no version change
- Notable uncertainty: none — digest verified against Docker Hub; image content unchanged
