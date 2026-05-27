pr: 281

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR bumps the bootstrap CRD chart reference for `kube-prometheus-stack` from `85.3.3` to `85.4.0` in `bootstrap/helmfile.d/00-crds.yaml`. Upstream `85.4.0` adds an optional admission-webhook PromQL parser flag (`promqlOptions`) and does not change default behavior when unset. Local usage does not set this new value, and chart diff between versions shows no CRD file changes, so local breakage risk is low.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/prometheus-community/charts/kube-prometheus-stack` | Helm OCI chart | `85.3.3 → 85.4.0` | minor | deploy/infra (bootstrap CRD extraction) | Green |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[feature]` | Added `prometheusOperator.admissionWebhooks.deployment.promqlOptions`, rendered as `--promql-options` for the Prometheus Operator admission webhook deployment. Default is empty list. | [PR #6945](https://github.com/prometheus-community/helm-charts/pull/6945) | **No** — this repo does not set `prometheusOperator.admissionWebhooks.deployment.promqlOptions` in `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`, so behavior remains default. |
| `[feature]` | Chart release `kube-prometheus-stack-85.4.0` contains the above change and version bump only for this chart. | [release 85.4.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0) | **No** — local config path affected only if new value is enabled. |
| `[unknown]` | Monorepo compare view includes an unrelated `prometheus-pushgateway` commit because tags are shared across repo history. | [compare view](https://github.com/prometheus-community/helm-charts/compare/kube-prometheus-stack-85.3.3...kube-prometheus-stack-85.4.0) | **No** — unrelated chart path; not used by this PR. |

### Local impact

- PR diff only changes `bootstrap/helmfile.d/00-crds.yaml` (`version: 85.3.3 -> 85.4.0`) for the CRD extraction helmfile.
- Runtime deployment in-cluster is still sourced from Flux OCIRepository at `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml` (`tag: 85.3.3`, pinned digest), so this PR does not directly change the running HelmRelease payload.
- Local `kube-prometheus-stack` values include many `PrometheusRule` resources and operator settings (`kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`) but do not configure the new `promqlOptions` field.
- Upstream chart tarball diff (`85.3.3` vs `85.4.0`) shows only `Chart.yaml`, `Chart.lock` timestamp, admission-webhook deployment template, and `values.yaml`; no CRD manifest changes detected.

### Improvement opportunities

- **`Optionally set admission webhook PromQL parser flags when needed`** — if you adopt PromQL syntax requiring parser toggles in future rules, set `prometheusOperator.admissionWebhooks.deployment.promqlOptions` explicitly in `helmrelease.yaml` to match upstream support in 85.4.0 ([PR #6945](https://github.com/prometheus-community/helm-charts/pull/6945)).

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Alert rules / PrometheusRule | Many custom rules under `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-*.yaml` and `.../rules/` | None | Upstream change adds optional webhook parser CLI arg only; no metric, label, or alerting rule schema changes reported in 85.4.0 ([release](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0)). |
| Dashboard / scrape config | Grafana dashboards and ServiceMonitor/PodMonitor files exist elsewhere (e.g. `kubernetes/apps/observability/grafana/app/dashboards/`, `kubernetes/apps/**/servicemonitor.yaml`, `kubernetes/apps/**/podmonitor.yaml`) | None | No upstream metric/scrape endpoint changes in this release; no dashboard or alert changes identified. |

### Pre-merge checks

- [ ] Run `./scripts/verify-oci-digests.sh /tmp/workspace/webgrip/homelab-cluster` (already passes on current branch) to confirm no digest regressions.
- [ ] (Optional) Render/diff CRDs from `kube-prometheus-stack` `85.3.3` vs `85.4.0` if you want additional assurance in your bootstrap workflow.

### Follow-up

- [ ] Consider opening a separate Renovate/maintenance PR to bump `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml` tag+digest from `85.3.3` when you are ready to roll the runtime chart too, keeping bootstrap and runtime versions aligned.

### Evidence reviewed

- PR: `feat(container): update image ghcr.io/prometheus-community/charts/kube-prometheus-stack ( 85.3.3 ➔ 85.4.0 )`; labels `area/bootstrap`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, +1/-1 in `bootstrap/helmfile.d/00-crds.yaml`.
- Files in repo: `bootstrap/helmfile.d/00-crds.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`, and observability rule/dashboard/monitor files under `kubernetes/apps/observability/**`.
- Upstream sources checked: https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0, https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.3.3, https://github.com/prometheus-community/helm-charts/pull/6945, https://github.com/prometheus-community/helm-charts/commit/4ae9be6e28f182925ca08f8a86af26048ffe8ea0, https://github.com/prometheus-community/helm-charts/compare/kube-prometheus-stack-85.3.3...kube-prometheus-stack-85.4.0.
- Notable uncertainty: None material; release and commit history were available and directly inspected.
