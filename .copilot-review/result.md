pr: 287

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates the Flux OCI chart source for `kube-prometheus-stack` from `85.3.3` to `86.0.0` in `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`. Upstream release notes in this range show two relevant chart changes: a new admission-webhook `promqlOptions` value (85.4.0) and a bump to Prometheus Operator `v0.91.0` with CRD sync (86.0.0). The main local risk is schema/validation tightening in operator CRDs and admission behavior around rules, because this repo has broad PrometheusRule/ServiceMonitor/PodMonitor usage. Recommended action is to merge after focused render/admission checks.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/prometheus-community/charts/kube-prometheus-stack` | OCI Helm chart | `85.3.3 → 86.0.0` | major | runtime/infra observability stack (Prometheus operator + CRDs + alerts) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[feature]` | Added `prometheusOperator.admissionWebhooks.deployment.promqlOptions` chart value (85.4.0), rendered as `--promql-options` for admission webhook deployment. | [PR #6945](https://github.com/prometheus-community/helm-charts/pull/6945), [release 85.4.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0) | **No** — repo does not set `promqlOptions`, and default `admissionWebhooks.deployment.enabled` is `false` (from chart values). |
| `[migration]` | Chart 86.0.0 bumps Prometheus Operator to `v0.91.0` and syncs bundled CRDs. | [PR #6947](https://github.com/prometheus-community/helm-charts/pull/6947), [release 86.0.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-86.0.0) | **Yes** — this repo deploys the chart as core monitoring stack and defines many `PrometheusRule`/`PodMonitor`/`ServiceMonitor` resources. |
| `[behavior]` | Prometheus Operator `v0.91.0` validates `PrometheusRule` resources against enabled PromQL features. | [prometheus-operator v0.91.0 notes (#8545)](https://github.com/prometheus-operator/prometheus-operator/releases/tag/v0.91.0) | **Yes** — repo has many custom `PrometheusRule` resources under `kubernetes/apps/observability/kube-prometheus-stack/app/` and related apps. |
| `[behavior]` | Prometheus Operator `v0.91.0` adds stricter CRD validations (e.g., mutual exclusion and field validations in `ScrapeConfig`, receiver validations in `AlertmanagerConfig`). | [prometheus-operator v0.91.0 notes (#8480, #8479, #8220, #8267, #8270)](https://github.com/prometheus-operator/prometheus-operator/releases/tag/v0.91.0) | **No (currently)** — no `ScrapeConfig` or `AlertmanagerConfig` manifests were found in this repo search. |

### Local impact

`kube-prometheus-stack` is a central dependency in this repo’s observability plane (`kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml` + `ocirepository.yaml`) and is referenced by many dependent workloads via `release: kube-prometheus-stack` labels and `dependsOn` links. The repo contains many custom `PrometheusRule` manifests (platform/app/security/canary rules) plus `ServiceMonitor`/`PodMonitor`/`Probe` resources across observability and security apps.

Because this chart manages Prometheus Operator and CRDs, upgrade impact is broad: admission/validation behavior can affect rule acceptance and reconciliation; rollback can be non-trivial if CRD schema or webhook behavior changes interact with existing custom resources. The PR changes only the OCI tag/digest pin, so deployment behavior changes come from upstream chart payload, not local values edits.

### Improvement opportunities

- **Evaluate enabling `prometheusOperator.admissionWebhooks.deployment.promqlOptions` only if needed** — upstream added this knob to support PromQL parser feature validation when using webhook deployment mode; currently unused here. [PR #6945](https://github.com/prometheus-community/helm-charts/pull/6945)
- **Track bootstrap CRD extraction version alignment** — bootstrap Helmfile still references `kube-prometheus-stack` `85.3.3` (`bootstrap/helmfile.d/00-crds.yaml`) while GitOps runtime source is moving to `86.0.0`; keeping them aligned reduces drift during rebuild/bootstrap scenarios.

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard / Alert / Metric / Scrape config | Extensive Grafana dashboards and many `PrometheusRule` files under `kubernetes/apps/observability/grafana/app/dashboards/` and `kubernetes/apps/observability/kube-prometheus-stack/app/` | None | Release notes in this range describe webhook/CRD/operator behavior updates, but no explicit metric name/label removals or dashboard-facing metric schema changes were documented in chart releases; monitor alerts after rollout. [85.4.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0), [86.0.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-86.0.0), [operator v0.91.0](https://github.com/prometheus-operator/prometheus-operator/releases/tag/v0.91.0) |

### Pre-merge checks

- [ ] Render and diff chart manifests for current values (`helm template` via your standard pipeline) and confirm no unexpected CRD/admission webhook deltas beyond expected operator bump.
- [ ] Validate existing Prometheus rules against upgraded operator admission behavior (server-side dry run or staging apply), focusing on custom rules under `kubernetes/apps/observability/kube-prometheus-stack/app/`.
- [ ] Re-run OCI digest verification after merging/rebasing (`./scripts/verify-oci-digests.sh .`).

### Follow-up

- [ ] Consider updating `bootstrap/helmfile.d/00-crds.yaml` chart version to match runtime chart line — reduce bootstrap/runtime CRD divergence risk.
- [ ] Add/refresh an observability upgrade runbook note for Prometheus Operator `v0.91.x` validation changes — helps future major chart bumps.

### Evidence reviewed

- PR: `feat(container)!: Update image ghcr.io/prometheus-community/charts/kube-prometheus-stack ( 85.3.3 ➔ 86.0.0 )`; labels `area/kubernetes`, `type/major`, `renovate/container`, `dependencies`, `major`; diff modifies only `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml` tag+digest.
- Files in repo: `kubernetes/apps/observability/kube-prometheus-stack/app/{ocirepository.yaml,helmrelease.yaml,*prometheusrule*.yaml}`, `kubernetes/apps/observability/grafana/app/dashboards/*.yaml`, `bootstrap/helmfile.d/00-crds.yaml`, plus dependent ServiceMonitor/PodMonitor/Probe manifests.
- Upstream sources checked: https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0, https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-86.0.0, https://github.com/prometheus-community/helm-charts/pull/6945, https://github.com/prometheus-community/helm-charts/pull/6947, https://github.com/prometheus-operator/prometheus-operator/releases/tag/v0.91.0
- Notable uncertainty: upstream chart release notes are concise; no explicit metric-level changelog in this range, so metric/dashboard impact confidence is moderate.
