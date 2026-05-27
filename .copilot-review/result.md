pr: 283

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** High

### Executive summary

This PR updates the Flux `OCIRepository` reference for `ghcr.io/prometheus-community/charts/kube-prometheus-stack` from `85.3.3` to `85.4.0` with a new digest pin. Upstream `85.4.0` contains a single chart change: an optional new `prometheusOperator.admissionWebhooks.deployment.promqlOptions` value that renders `--promql-options` for the separate admission webhook deployment. In this repo, that webhook deployment is not overridden/enabled in local values, so no direct behavior change is expected from current configuration. Risk remains cautionary (not green) because this is core observability/deploy infrastructure and past kube-prometheus-stack upgrades have previously stalled in this repo.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/prometheus-community/charts/kube-prometheus-stack` | Helm chart (OCI/GHCR) | `85.3.3` → `85.4.0` | minor | deploy / infra / observability runtime | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[feature]` | Adds `prometheusOperator.admissionWebhooks.deployment.promqlOptions` and renders `--promql-options=<csv>` for the separate admission-webhook deployment. | [release 85.4.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0), [PR #6945](https://github.com/prometheus-community/helm-charts/pull/6945) | **No** — this repo does not set `prometheusOperator.admissionWebhooks.deployment.*` in `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`, and upstream default `deployment.enabled` is `false`. |
| `[migration]` | New option requires admission-webhook image `v0.91.0+` when used. | [PR #6945 note](https://github.com/prometheus-community/helm-charts/pull/6945) | **No** — feature not enabled locally; also local `prometheusOperator.image.tag` is already `v0.91.0`. |
| `[unknown]` | No other release-note items were listed for this chart version. | [release 85.4.0](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0) | **Unknown** — release body is brief; verified upstream PR diff directly to reduce uncertainty. |

### Local impact

The only PR diff is in `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml` (tag+digest bump). The chart powers Prometheus/Alertmanager and is depended on by multiple workloads and alerting resources (`kubernetes/apps/observability/*`, plus many `PrometheusRule`/`ServiceMonitor` consumers in `kubernetes/apps/security/*` and `kubernetes/apps/kyverno/*`). This is high blast-radius observability infrastructure, but upstream change is additive and gated behind values not set here. Stateful pieces remain (Prometheus/Alertmanager PVC-backed), so rollback still needs care even when functional change is expected to be minimal.

### Improvement opportunities

- **`Evaluate enabling admission webhook PromQL options when adopting experimental PromQL features`** — upstream now supports parser flags via `prometheusOperator.admissionWebhooks.deployment.promqlOptions`; this can proactively align admission validation with intended rule syntax when needed ([PR #6945](https://github.com/prometheus-community/helm-charts/pull/6945)).

### Grafana dashboards and alerts

No dashboard or alert changes identified for this update. The upstream change adds an optional admission-webhook parser flag path and does not introduce/remap Prometheus metrics, labels, or scrape targets by default.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | Extensive custom Grafana dashboards under `kubernetes/apps/observability/grafana/app/dashboards/*.yaml` | None | Upstream 85.4.0 change is config-path additive, not metric schema change ([release](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0), [PR #6945](https://github.com/prometheus-community/helm-charts/pull/6945)) |
| Alert / Rule | Multiple custom `PrometheusRule` files under `kubernetes/apps/observability/kube-prometheus-stack/app/` and related apps | None (unless enabling `promqlOptions`) | Current local values do not enable the separate admission webhook deployment options; no default rule behavior change shown upstream |
| Scrape config | ServiceMonitor/PodMonitor usage across observability/security apps | None | No scrape target/metric rename changes documented in this release |

### Pre-merge checks

- [ ] Confirm OCI digest integrity still passes: `./scripts/verify-oci-digests.sh /tmp/workspace/webgrip/homelab-cluster`.
- [ ] Run Flux/Helm reconciliation for `kube-prometheus-stack` and verify no `InvalidImageName` or stalled Helm release regression (see prior runbook context in `docs/techdocs/docs/runbooks/cluster-health-2026-05-21.md`).
- [ ] Verify Prometheus and Alertmanager pods in `observability` become Ready and key scrape targets remain up after rollout.

### Follow-up

- [ ] Add a short runbook note for when to use `prometheusOperator.admissionWebhooks.deployment.promqlOptions` if future `PrometheusRule` syntax requires experimental parser flags — helps future upgrades and avoids ad-hoc tuning ([PR #6945](https://github.com/prometheus-community/helm-charts/pull/6945)).

### Evidence reviewed

- PR: feat(container): update image ghcr.io/prometheus-community/charts/kube-prometheus-stack ( 85.3.3 ➔ 85.4.0 ); labels `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 2 additions, 2 deletions (`kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`).
- Files in repo: `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/ks.yaml`, cross-references from `kubernetes/apps/observability/*`, `kubernetes/apps/security/*`, `kubernetes/apps/kyverno/*`, and observability docs/runbook files.
- Upstream sources checked: https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.4.0, https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.3.3, https://github.com/prometheus-community/helm-charts/pull/6945, https://raw.githubusercontent.com/prometheus-community/helm-charts/kube-prometheus-stack-85.4.0/charts/kube-prometheus-stack/values.yaml
- Notable uncertainty: Upstream release body is concise and does not enumerate broad compatibility impacts; assessment is based on direct PR/file diff inspection.
