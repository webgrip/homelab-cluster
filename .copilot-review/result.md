pr: 244

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

PR #244 updates only the bootstrap Helmfile entry for `kube-prometheus-stack` from `85.3.0` to `85.3.2`. Upstream changes across `85.3.1` and `85.3.2` are limited to Grafana subchart/serviceMonitor defaults (fixing scrape interval/timeout behavior) and the Grafana dependency bump (`12.4.0` → `12.4.1`). In this repo, `kube-prometheus-stack` has `grafana.enabled: false` and Grafana is deployed separately, so the changed path is not used by the runtime release. Risk is low; merge is reasonable after normal CI/validation.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/prometheus-community/charts/kube-prometheus-stack` | Helm OCI chart | `85.3.0 → 85.3.2` | patch | infra/bootstrap (CRD extraction Helmfile) | Low |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[behavior]` | `[kube-prometheus-stack] Fix Grafana upstream values` (stop overriding Grafana scrape-related defaults in chart values) | [source](https://github.com/prometheus-community/helm-charts/pull/6938) | **No** — this repo disables bundled Grafana in `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml` (`grafana.enabled: false`). |
| `[bugfix]` | `[kube-prometheus-stack] Update Helm release grafana to v12.4.1` | [source](https://github.com/prometheus-community/helm-charts/pull/6939) | **No** — affects kube-prometheus-stack’s Grafana dependency path, but bundled Grafana is not enabled here. |
| `[behavior]` | Grafana chart `12.4.1` change: remove default ServiceMonitor interval/scrapeTimeout so Prometheus global defaults apply | [source](https://github.com/grafana-community/helm-charts/pull/522) | **No** for this PR’s changed workload path — this PR only bumps bootstrap kube-prometheus-stack chart version in `bootstrap/helmfile.d/00-crds.yaml`; it does not modify the separately managed Grafana release. |

### Local impact

`kube-prometheus-stack` is central to observability in-cluster (`kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`, multiple `PrometheusRule` files, blackbox probes, and HTTProutes). However, this PR changes only `bootstrap/helmfile.d/00-crds.yaml`, which is used for CRD extraction/bootstrap workflows, not the Flux-managed runtime HelmRelease. The runtime OCI source remains pinned at `tag: 85.3.0` in `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`. Given that upstream changes are Grafana-subchart focused and bundled Grafana is disabled in kube-prometheus-stack values, practical blast radius is minimal.

### Improvement opportunities

- **Align bootstrap and runtime chart versions intentionally** — currently this PR updates bootstrap `00-crds.yaml` while runtime still pins `85.3.0` in `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`; keeping these in sync reduces operator confusion during incident/debug sessions (context from PR diff + local files).
- **Optionally set explicit `serviceMonitor.interval`/`scrapeTimeout` in standalone Grafana release if fixed scrape cadence is required** — upstream Grafana chart behavior now prefers inheriting Prometheus global defaults ([PR #522](https://github.com/grafana-community/helm-charts/pull/522)).

### Grafana dashboards and alerts

No dashboard or alert changes identified for this PR’s dependency bump scope.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | Grafana dashboards are managed under `kubernetes/apps/observability/grafana/app/dashboards` | None | Upstream change is ServiceMonitor scrape defaults, not dashboard schema/queries ([PR #522](https://github.com/grafana-community/helm-charts/pull/522)). |
| Alert | Prometheus alerts are custom `PrometheusRule` resources under `kubernetes/apps/observability/kube-prometheus-stack/app/` and `.../rules/` | None | No upstream kube-prometheus-stack 85.3.0→85.3.2 changes to alert rules or alertmanager behavior were found ([compare](https://api.github.com/repos/prometheus-community/helm-charts/compare/kube-prometheus-stack-85.3.0...kube-prometheus-stack-85.3.2)). |
| Metric / Scrape config | Scrape config in this repo includes blackbox probes and Prometheus Operator selectors; bundled Grafana in kube-prometheus-stack is disabled | None | Changed upstream scrape-default behavior is in Grafana subchart path not enabled here (`grafana.enabled: false`). |

### Pre-merge checks

- [ ] Confirm CI passes for PR #244.
- [ ] If you intend this bump for runtime as well (not just bootstrap CRD workflow), open or include a matching update for `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml` (tag/digest).
- [ ] Optionally run `./scripts/verify-oci-digests.sh /home/runner/work/homelab-cluster/homelab-cluster` after merge if any OCI tag/digest files are updated in follow-up.

### Follow-up

- [ ] Decide whether bootstrap-only chart bumps are desired policy, and document it in renovate/bootstrap docs to avoid ambiguous update intent — current PR only touches `bootstrap/helmfile.d/00-crds.yaml`.
- [ ] Review standalone Grafana HelmRelease scrape expectations; set explicit interval/timeout only if required for SLO/alert latency goals, given upstream default behavior change ([grafana-community/helm-charts#522](https://github.com/grafana-community/helm-charts/pull/522)).

### Evidence reviewed

- PR: `fix(container): update image ghcr.io/prometheus-community/charts/kube-prometheus-stack ( 85.3.0 ➔ 85.3.2 )`; labels: `area/bootstrap`, `renovate/container`, `type/patch`, `dependencies`; diff summary: 1 file changed, 1 insertion, 1 deletion (`bootstrap/helmfile.d/00-crds.yaml`).
- Files in repo: `bootstrap/helmfile.d/00-crds.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`, `kubernetes/apps/observability/grafana/app/helmrelease.yaml`, observability rule/probe/dashboard directories under `kubernetes/apps/observability`.
- Upstream sources checked: https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.3.1, https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.3.2, https://github.com/prometheus-community/helm-charts/pull/6938, https://github.com/prometheus-community/helm-charts/pull/6939, https://api.github.com/repos/prometheus-community/helm-charts/compare/kube-prometheus-stack-85.3.0...kube-prometheus-stack-85.3.2, https://github.com/grafana-community/helm-charts/releases/tag/grafana-12.4.1, https://github.com/grafana-community/helm-charts/pull/522.
- Notable uncertainty: None significant; upstream release notes are brief but compare + linked PRs were reviewed.
