pr: 252

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR updates the `kube-prometheus-stack` chart reference in bootstrap CRD extraction from `85.3.2` to `85.3.3`. Upstream release `85.3.3` contains only a chart version bump and a typo fix in a comment (`values.yaml`), with no runtime template, metric, or behavior changes. Given this repo’s usage, blast radius is limited to bootstrap CRD extraction flow, so merge risk is low.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/prometheus-community/charts/kube-prometheus-stack` | Helm OCI chart | `85.3.2 → 85.3.3` | patch | deploy/infra (bootstrap CRD extraction) | Green |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[bugfix]` | Release notes: “Fix comment grammar” via upstream PR #6940 | [release 85.3.3](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.3.3) | **No** — release content is a comment text correction only. |
| `[unknown]` | Compare view shows only `Chart.yaml` version bump and one `values.yaml` comment typo fix | [compare 85.3.2...85.3.3](https://github.com/prometheus-community/helm-charts/compare/kube-prometheus-stack-85.3.2...kube-prometheus-stack-85.3.3) | **No** — no functional chart/template/config behavior changes appear in upstream diff. |
| `[bugfix]` | Upstream PR changed `"Extra rape settings."` comment to `"Extra scrape settings."` | [PR #6940](https://github.com/prometheus-community/helm-charts/pull/6940) | **No** — comment-only update; no rendered manifest or runtime path change. |

### Local impact

The PR changes only `bootstrap/helmfile.d/00-crds.yaml`, where this repo pins `kube-prometheus-stack` for CRD extraction bootstrap. Runtime deployment in-cluster is managed separately via Flux `OCIRepository` + `HelmRelease` (`kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`, `.../helmrelease.yaml`), and this PR does not touch those runtime manifests. This chart is foundational for monitoring/alerting in this repo (multiple `PrometheusRule`, `Probe`, `ServiceMonitor`, and downstream observability integrations), but upstream delta here is non-functional.

### Improvement opportunities

None identified.

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Alert / Metric / Scrape config | PrometheusRule/Probe/ServiceMonitor files under `kubernetes/apps/observability/**` (e.g. `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-*.yaml`, `kubernetes/apps/observability/blackbox-exporter/app/probe-*.yaml`, `kubernetes/apps/observability/github-billing-exporter/app/servicemonitor.yaml`) | None | Upstream 85.3.3 release and compare show comment-only change; no metric/schema/label changes were introduced. ([release](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.3.3), [compare](https://github.com/prometheus-community/helm-charts/compare/kube-prometheus-stack-85.3.2...kube-prometheus-stack-85.3.3)) |
| Dashboard | No dashboard JSON changes in this PR; Grafana managed separately under `kubernetes/apps/observability/grafana/app/` | None | Dependency update does not alter chart behavior or emitted metrics; no dashboard adaptation indicated by upstream notes. |

### Pre-merge checks

- [ ] No special pre-merge checks beyond normal CI.
- [ ] (Optional) If bootstrap CRD extraction is run manually, regenerate once to confirm no effective manifest delta beyond chart metadata/version bump.

### Follow-up

- [ ] Consider documenting bootstrap-vs-runtime chart version intent for `kube-prometheus-stack` (`bootstrap/helmfile.d/00-crds.yaml` vs `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`) to reduce operator confusion during upgrades.

### Evidence reviewed

- PR: fix(container): update image ghcr.io/prometheus-community/charts/kube-prometheus-stack ( 85.3.2 ➔ 85.3.3 ); labels: `area/bootstrap`, `renovate/container`, `type/patch`, `dependencies`; diff summary: 1 file changed, 1 line added, 1 line removed.
- Files in repo: `bootstrap/helmfile.d/00-crds.yaml`; `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`; `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`; observability rule/probe/monitor files under `kubernetes/apps/observability/**`.
- Upstream sources checked: https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.3.3 ; https://github.com/prometheus-community/helm-charts/compare/kube-prometheus-stack-85.3.2...kube-prometheus-stack-85.3.3 ; https://github.com/prometheus-community/helm-charts/pull/6940 ; GitHub releases/tags API for `kube-prometheus-stack-85.3.2` and `kube-prometheus-stack-85.3.3`.
- Notable uncertainty: None material; upstream delta is explicitly comment-only.
