pr: 290

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This patch updates the Loki community Helm chart from `17.1.1` to `17.1.2`. The sole change is a Renovate-automated bump of the optional `ghcr.io/jkroepke/access-log-exporter` sidecar image from `v0.3.13` to `v0.3.14`. This repository does not enable or reference the access-log-exporter feature, so the change has zero functional impact on the deployed workload. The digest is pinned, providing strong supply-chain guarantees.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/grafana-community/helm-charts/loki` | OCI Helm chart | `17.1.1` → `17.1.2` | patch | runtime / observability | Green |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[bugfix]` | Bump `ghcr.io/jkroepke/access-log-exporter` sidecar image from `v0.3.13` → `v0.3.14` inside chart defaults | [grafana-community/helm-charts#533](https://github.com/grafana-community/helm-charts/pull/533) | **No** — the access-log-exporter sidecar is an opt-in feature. The repo's `helmrelease.yaml` sets no `accessLogExporter.*` values and no reference to this image exists anywhere in the cluster manifests. |

### Local impact

Loki is deployed in **SingleBinary mode** (`deploymentMode: SingleBinary`, 1 replica) backed by S3-compatible object storage. Configuration lives in two files:

- `kubernetes/apps/observability/loki/app/ocirepository.yaml` — the only changed file; updates tag `17.1.1` → `17.1.2` and replaces the digest pin.
- `kubernetes/apps/observability/loki/app/helmrelease.yaml` — unchanged; does not set any value that would activate the access-log-exporter.

Grafana datasource (`kubernetes/apps/observability/grafana/app/datasources/loki.yaml`) points to `http://loki-gateway.observability.svc.cluster.local` and remains unaffected. The LGTM health dashboard queries `loki_distributor_bytes_received_total` and `up{job=~"loki.*"}` — no metric renames in this chart release.

No stateful schema changes, no migration steps, and no privileged component changes are introduced. Rollback requires only reverting the two changed lines in `ocirepository.yaml`.

### Improvement opportunities

None identified. The 17.1.2 release contains only a sidecar image bump with no new configuration options or deprecation notices relevant to this repo.

### Grafana dashboards and alerts

No dashboard or alert changes identified. The only change in 17.1.2 is an internal sidecar image tag. No Loki metrics are renamed or removed in this release. Existing PromQL expressions (`loki_distributor_bytes_received_total`, `up{job=~"loki.*"}`) remain valid.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | `observability-lgtm-health.yaml` queries Loki metrics | None | No metric changes in this release |
| ServiceMonitor | `monitoring.serviceMonitor.enabled: true` in helmrelease | None | No scrape config changes |

### Pre-merge checks

- [ ] No special pre-merge checks beyond normal CI. Flux will automatically pull the new OCI digest and reconcile the chart.

### Follow-up

None.

### Evidence reviewed

- **PR:** "fix(container): update image ghcr.io/grafana-community/helm-charts/loki ( 17.1.1 ➔ 17.1.2 )" — labels: `area/kubernetes`, `renovate/container`, `type/patch`, `dependencies`; diff: 2 additions / 2 deletions in `ocirepository.yaml` (tag + digest)
- **Files in repo:** `kubernetes/apps/observability/loki/app/ocirepository.yaml`, `kubernetes/apps/observability/loki/app/helmrelease.yaml`, `kubernetes/apps/observability/loki/app/kustomization.yaml`, `kubernetes/apps/observability/loki/ks.yaml`, `kubernetes/apps/observability/grafana/app/datasources/loki.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/observability-lgtm-health.yaml`
- **Upstream sources checked:** [GitHub releases — grafana-community/helm-charts loki-17.1.2](https://github.com/grafana-community/helm-charts/releases/tag/loki-17.1.2); [PR #533 — access-log-exporter bump](https://github.com/grafana-community/helm-charts/pull/533)
- **Notable uncertainty:** None. Release notes are clear and complete for this patch.
