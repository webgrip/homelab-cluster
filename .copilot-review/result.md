pr: 196

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** High

### Executive summary

PR #196 bumps the kube-prometheus-stack chart version in the bootstrap CRD extraction helmfile from `85.2.0` to `85.3.0`. Upstream, this span includes intermediate `85.2.1` and `85.2.2` releases, with notable changes in ThanosRuler template behavior and dependency bumps (Grafana subchart and webhook certgen image). Local blast radius is limited because this PR only touches `bootstrap/helmfile.d/00-crds.yaml` (CRD bootstrap path), but the same stack has recent upgrade instability history in this repo, so a cautious merge with focused checks is appropriate.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/prometheus-community/charts/kube-prometheus-stack` | Helm OCI chart | `85.2.0 → 85.3.0` | minor (with skipped patch releases) | infra/bootstrap (CRD extraction helmfile) | Yellow |

### Important upstream changes

- [feature] `85.2.1` updated kube-prometheus-stack dependencies, including `kube-state-metrics 7.3.0 → 7.4.0` and `ghcr.io/jkroepke/kube-webhook-certgen 1.8.2 → 1.8.3` ([release `kube-prometheus-stack-85.2.1`](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.2.1), [prometheus-community/helm-charts#6932](https://github.com/prometheus-community/helm-charts/pull/6932)).
- [behavior] `85.2.2` added `thanosRuler.thanosRulerSpec.extraEnv` and template validation that fails when `extraEnv` is combined with a manual `thanos-ruler` container entry ([release `kube-prometheus-stack-85.2.2`](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.2.2), [prometheus-community/helm-charts#6902](https://github.com/prometheus-community/helm-charts/pull/6902)).
- [feature] `85.3.0` updates the Grafana subchart dependency `12.3.3 → 12.4.0` ([release `kube-prometheus-stack-85.3.0`](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.3.0), [prometheus-community/helm-charts#6937](https://github.com/prometheus-community/helm-charts/pull/6937)).
- [behavior] Grafana chart `12.4.0` itself contains only minor maintenance-level changes in release notes (CI action bump and busybox tag bump) ([release `grafana-12.4.0`](https://github.com/grafana-community/helm-charts/releases/tag/grafana-12.4.0), [grafana-community/helm-charts#519](https://github.com/grafana-community/helm-charts/pull/519)).

### Local impact

This Renovate PR changes only `bootstrap/helmfile.d/00-crds.yaml`, which is explicitly documented as a CRD extraction helmfile and "not intended to be used with helmfile apply or helmfile sync." That keeps immediate runtime risk low for day-to-day Flux reconciliation.

However, kube-prometheus-stack is a stateful/critical observability component in this repo (`kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`) and there is a documented recent failed upgrade event (`docs/techdocs/docs/runbooks/cluster-health-2026-05-21.md`) involving this chart line. Also note the active OCIRepository runtime pin remains `85.2.0` in `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`, so this PR alone does not advance the runtime chart version.

### Pre-merge checks

- [ ] Confirm this PR is intentionally bootstrap-only (CRD extraction) and not expected to change live runtime chart reconciliation.
- [ ] Run CRD bootstrap render/extract workflow used by maintainers (helmfile with `--include-crds`) and verify no template/render errors at `85.3.0`.
- [ ] If planning a follow-up runtime bump, review `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml` values against upstream `85.2.1/85.2.2/85.3.0` changes (especially any ThanosRuler overrides).
- [ ] For runtime follow-up, explicitly verify rollback path/helm history health first due prior stalled upgrade documented in `cluster-health-2026-05-21.md`.

### Evidence reviewed

- PR: `feat(container): update image ghcr.io/prometheus-community/charts/kube-prometheus-stack ( 85.2.0 ➔ 85.3.0 )`; labels: `area/bootstrap`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, `bootstrap/helmfile.d/00-crds.yaml` version line only.
- Files in repo: `bootstrap/helmfile.d/00-crds.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/ocirepository.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml`, `docs/techdocs/docs/runbooks/cluster-health-2026-05-21.md`.
- Upstream sources checked: 
  - https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.2.1
  - https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.2.2
  - https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-85.3.0
  - https://github.com/prometheus-community/helm-charts/pull/6932
  - https://github.com/prometheus-community/helm-charts/pull/6902
  - https://github.com/prometheus-community/helm-charts/pull/6937
  - https://github.com/grafana-community/helm-charts/releases/tag/grafana-12.4.0
  - https://github.com/grafana-community/helm-charts/pull/519
- Notable uncertainty: none.
