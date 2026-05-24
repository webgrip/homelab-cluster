pr: 261

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary
This PR updates the cert-manager Helm OCI chart reference from `v1.19.5` to `v1.20.2` in Flux. Upstream `v1.20.x` includes behavior/security changes in the cert-manager controller and chart, plus fixes for Gateway API and Helm template rendering. The main local risk is operational (PKI issuance/renewal impact) rather than manifest complexity, because this cluster relies on cert-manager for TLS and has cert-manager-specific alerts/dashboards wired in. Merge is reasonable after targeted post-upgrade checks for cert issuance health and controller errors.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `quay.io/jetstack/charts/cert-manager` | OCI Helm chart | `v1.19.5 → v1.20.2` | minor | infra / runtime (cluster PKI controller via Flux HelmRelease) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| [behavior] | Default cert-manager container UID/GID changed to `65532`/`65532`. | [source](https://github.com/cert-manager/cert-manager/pull/8408) | **Unknown** — repo does not override cert-manager pod securityContext in `helmrelease.yaml`; runtime compatibility depends on cluster policies and any implicit filesystem expectations. |
| [security] | Moderate DoS fix for potential panic in controller DNS response handling. | [source](https://github.com/cert-manager/cert-manager/pull/8469) | **Yes** — this cluster runs cert-manager controller; fix is directly relevant to controller robustness. |
| [behavior] | Prometheus monitoring label normalization: metrics label intended to be `cert-manager`. | [source](https://github.com/cert-manager/cert-manager/pull/8162) | **No** — local cert-manager alert/dashboard queries in `prometheusrule-platform-cert-manager.yaml` and `cert-manager-certificates.yaml` use metric names/rates and do not depend on this label. |
| [bugfix] | Fix duplicate `parentRef` behavior for Gateway API when issuer config and annotations are both set. | [source](https://github.com/cert-manager/cert-manager/pull/8658) | **Unknown** — repo has multiple `HTTPRoute` resources, but this cert-manager install appears DNS01-focused; no explicit local cert-manager Gateway-API ACME solver config found. |
| [bugfix] | Helm chart fix for invalid YAML when both `webhook.config` and `webhook.volumes` are set. | [source](https://github.com/cert-manager/cert-manager/pull/8665) | **No** — local `helmrelease.yaml` does not set `webhook.config` or `webhook.volumes`. |
| [security] | Go/dependency vulnerability remediation in `v1.20.2`. | [source](https://github.com/cert-manager/cert-manager/pull/8704) | **Yes** — this affects shipped controller/webhook binaries used by this cluster. |

### Local impact
cert-manager is managed via Flux `OCIRepository` + `HelmRelease` at `kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml` and `.../helmrelease.yaml`, with `crds.enabled: true` and Prometheus `ServiceMonitor` enabled. This is a high-importance control-plane dependency for cluster TLS issuance (`clusterissuer.yaml`, `envoy-gateway` certificate usage), so regressions can impact ingress TLS renewals. Observability is already in place through cert-manager-specific Prometheus rules and Grafana dashboard (`kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-cert-manager.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/cert-manager-certificates.yaml`), which lowers detection time if upgrade issues occur.

### Improvement opportunities
- **Evaluate cert-manager Pod security context explicitly in values** — upstream switched default UID/GID in `v1.20.0`; setting explicit expectations in Helm values can reduce surprise in future upgrades. [source](https://github.com/cert-manager/cert-manager/pull/8408)
- **Consider whether Gateway API ACME `parentRef` annotation support can simplify any future HTTP-01 flows** — available in `v1.20.0` and patched in `v1.20.1`. [source](https://github.com/cert-manager/cert-manager/pull/8518), [source](https://github.com/cert-manager/cert-manager/pull/8658)

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Alert rules | `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-cert-manager.yaml` tracks cert expiry and controller sync errors using dual label fallback (`result`/`status`). | None | Current queries already defensively handle label shape differences; no metric rename/removal in release notes for these series. [v1.20.0 notes](https://github.com/cert-manager/cert-manager/releases/tag/v1.20.0) |
| Dashboard | `kubernetes/apps/observability/grafana/app/dashboards/cert-manager-certificates.yaml` tracks expiry, controller errors, and order failures. | None | Release notes do not indicate breaking metric name removals for these panels; existing expressions are resilient. [v1.20.0 notes](https://github.com/cert-manager/cert-manager/releases/tag/v1.20.0) |
| Scrape config | Metrics scraping is enabled via cert-manager Helm values `prometheus.servicemonitor.enabled: true` in `helmrelease.yaml`. | None | No release-note requirement to change ServiceMonitor wiring for `v1.20.2`. |

### Pre-merge checks
- [ ] Confirm Flux applies the new chart artifact digest cleanly (`OCIRepository`/`HelmRelease` Ready after reconcile).
- [ ] Verify cert-manager pods (controller/webhook/cainjector/startupapicheck) are Ready in `cert-manager` namespace post-upgrade.
- [ ] Validate no new `CertManagerHighErrorRate` alerts and no sustained `certmanager_controller_sync_call_count` error rate after rollout.
- [ ] Spot-check at least one active Certificate renewal/Order/Challenge path (or force a safe non-prod renewal check) to confirm issuance pipeline health.

### Follow-up
- [ ] Document whether this cluster needs explicit cert-manager `securityContext` pinning after the upstream UID/GID default change — improves future upgrade predictability. ([#8408](https://github.com/cert-manager/cert-manager/pull/8408))
- [ ] If Gateway API ACME flows are introduced later, update runbooks to include `parentRef` annotation behavior introduced/fixed in `v1.20.x`. ([#8518](https://github.com/cert-manager/cert-manager/pull/8518), [#8658](https://github.com/cert-manager/cert-manager/pull/8658))

### Evidence reviewed
- PR: feat(container): update image quay.io/jetstack/charts/cert-manager ( v1.19.5 ➔ v1.20.2 ); labels `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff updates `kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml` tag+digest only.
- Files in repo: `kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml`, `kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml`, `kubernetes/apps/cert-manager/cert-manager/app/clusterissuer.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-cert-manager.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/cert-manager-certificates.yaml`.
- Upstream sources checked: https://github.com/cert-manager/cert-manager/releases/tag/v1.20.0, https://github.com/cert-manager/cert-manager/releases/tag/v1.20.1, https://github.com/cert-manager/cert-manager/releases/tag/v1.20.2, and linked upstream PRs cited above.
- Notable uncertainty: cert-manager release notes do not provide a dedicated migration guide section for this range; cluster-specific runtime exposure to the UID/GID default change and any Gateway API ACME usage could not be fully confirmed from manifests alone.
