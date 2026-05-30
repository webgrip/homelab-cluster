pr: 344

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates the bootstrap CRD source chart `ghcr.io/prometheus-community/charts/kube-prometheus-stack` from `85.3.3` to `86.1.0` in `bootstrap/helmfile.d/00-crds.yaml`. The highest-risk upstream step in this range is `86.0.0`, which upgrades Prometheus Operator to `v0.91.0` and includes explicit CRD migration guidance. In this repository, that matters because bootstrap applies CRDs server-side and many `ServiceMonitor`/`PrometheusRule` resources depend on those CRDs. Recommended action is merge after validating CRD apply/reconcile behavior on a non-prod cluster path.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/prometheus-community/charts/kube-prometheus-stack` | Helm OCI chart | `85.3.3 → 86.1.0` | major | bootstrap/deploy (CRD rendering+apply) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[migration]` | `86.0.0` bumps Prometheus Operator to `v0.91.0`; upstream `UPGRADE.md` adds explicit CRD update commands for `85.x → 86.x`. | [release 86.0.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-86.0.0), [PR #6947](https://github.com/prometheus-community/helm-charts/pull/6947) | **Yes** — this repo applies CRDs from bootstrap (`scripts/bootstrap-apps.sh`) and uses many Prometheus Operator CRs (`ServiceMonitor`/`PrometheusRule`). |
| `[feature]` | `85.4.0` adds `prometheusOperator.admissionWebhooks.deployment.promqlOptions` for admission webhook PromQL parser flags. | [release 85.4.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0), [PR #6945](https://github.com/prometheus-community/helm-charts/pull/6945) | **No** — repository values do not set this new option. |
| `[bugfix]` | `86.0.1` fixes etcd dashboard cluster variable behavior for multicluster dashboards. | [release 86.0.1](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-86.0.1), [PR #6948](https://github.com/prometheus-community/helm-charts/pull/6948) | **No** — kube-prometheus-stack Grafana is disabled locally (`grafana.enabled: false`), so bundled dashboard fixes are not consumed by this chart deployment. |
| `[bugfix]` | `86.0.2` fixes `hostUsers` reference links in chart values docs/comments. | [release 86.0.2](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-86.0.2), [PR #6953](https://github.com/prometheus-community/helm-charts/pull/6953) | **No** — documentation/comment fix only. |
| `[behavior]` | `86.1.0` updates non-major dependencies; includes default Prometheus image tag bump (`v3.11.3-distroless → v3.12.0-distroless`). | [release 86.1.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-86.1.0), [PR #6954](https://github.com/prometheus-community/helm-charts/pull/6954) | **No** — repo overrides Prometheus image/tag/sha in HelmRelease (`kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`). |

### Local impact

This PR modifies only `bootstrap/helmfile.d/00-crds.yaml`, which is consumed by `scripts/bootstrap-apps.sh` (`apply_crds`) to template and server-side apply CRDs before syncing Helm releases. So the direct effect is on bootstrap-time CRD content, not immediate Flux runtime chart version. The repository has high observability coupling to Prometheus Operator CRDs (many `ServiceMonitor` and `PrometheusRule` manifests, plus kustomization dependencies on `kube-prometheus-stack`), so CRD schema compatibility is the key local risk surface. Rollback is feasible by reverting this file, but partial rollout can leave CRD/operator/chart drift if follow-on updates are not coordinated.

### Improvement opportunities

- **`Enable chart-managed CRD upgrade job evaluation`** — upstream notes that `crds.upgradeJob.enabled` is available for CRD upgrades; assess whether adopting it simplifies/standardizes current manual bootstrap CRD apply flow. [UPGRADE.md via PR #6947](https://github.com/prometheus-community/helm-charts/pull/6947)
- **`Plan aligned runtime chart bump PR`** — this PR updates bootstrap CRD source only; follow with a coordinated runtime chart/OCI tag bump to reduce version drift between bootstrap and Flux-managed chart state. [PR #344 diff](https://github.com/webgrip/homelab-cluster/pull/344/files)

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | kube-prometheus-stack bundled Grafana disabled (`kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`) | None | Upstream dashboard fix in `86.0.1` targets bundled etcd dashboard; local chart deployment does not use bundled Grafana dashboards. [PR #6948](https://github.com/prometheus-community/helm-charts/pull/6948) |
| Alert / Metric / Scrape config | Multiple local `PrometheusRule`/`ServiceMonitor` manifests labeled for `kube-prometheus-stack` across `kubernetes/apps/**` | None in this PR | Upstream changes in this range do not document metric renames/removals affecting local alert rules; primary change is CRD/operator version migration guidance. [release 86.0.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-86.0.0) |

### Pre-merge checks

- [ ] Render and inspect CRD diff from updated bootstrap chart (`scripts/bootstrap-apps.sh` path) before applying to shared clusters.
- [ ] Validate server-side apply of upgraded monitoring CRDs succeeds without conversion/validation errors.
- [ ] Reconcile observability stack and confirm `PrometheusRule`/`ServiceMonitor` resources remain accepted and healthy.
- [ ] Confirm no drift/conflict with current Flux-managed `kube-prometheus-stack` runtime version (`kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`).

### Follow-up

- [ ] Prepare a coordinated runtime `kube-prometheus-stack` version update PR (OCI tag/digest and any required values adjustments) to keep bootstrap CRD source and runtime chart path aligned — reduces long-term upgrade ambiguity. (Local files: `bootstrap/helmfile.d/00-crds.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`)

### Evidence reviewed

- PR: `feat(container)!: Update image ghcr.io/prometheus-community/charts/kube-prometheus-stack ( 85.3.3 ➔ 86.1.0 )`; labels: `area/bootstrap`, `type/major`, `renovate/container`, `dependencies`, `major`; diff: 1 file, 1 line changed (`bootstrap/helmfile.d/00-crds.yaml`).
- Files in repo: `bootstrap/helmfile.d/00-crds.yaml`, `scripts/bootstrap-apps.sh`, `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`, plus repository-wide `kube-prometheus-stack` reference search in `kubernetes/apps/**` and docs.
- Upstream sources checked: `kube-prometheus-stack` releases `85.4.0`, `86.0.0`, `86.0.1`, `86.0.2`, `86.1.0` and linked PRs [#6945](https://github.com/prometheus-community/helm-charts/pull/6945), [#6947](https://github.com/prometheus-community/helm-charts/pull/6947), [#6948](https://github.com/prometheus-community/helm-charts/pull/6948), [#6953](https://github.com/prometheus-community/helm-charts/pull/6953), [#6954](https://github.com/prometheus-community/helm-charts/pull/6954).
- Notable uncertainty: No direct in-repo execution proof of bootstrap CRD apply against a live cluster in this environment; impact confidence depends on runtime cluster reconciliation behavior.
