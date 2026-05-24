pr: 220

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates the Flux distribution artifact used by `flux-instance` from `v0.36.0` to `v0.50.0` in one jump. Upstream release notes include a security advisory fix (CVE-2026-23990 in v0.40.0), multiple operator/runtime behavior changes, and incremental Flux compatibility updates through the 2.8.x line. In this repo, this is cluster-control-plane infrastructure, so blast radius is high even though the diff is one line. Merge is reasonable after targeted runtime checks on controller startup flags, reconciliation health, and Flux observability.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/controlplaneio-fluxcd/flux-operator-manifests` | OCI container image | `v0.36.0 → v0.50.0` | minor (multiple skipped minors) | infra / deploy / runtime (GitOps control plane manifests) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[security]` | Security advisory in v0.40.0: CVE-2026-23990 (Web UI impersonation bypass via empty OIDC claims). | [source](https://github.com/controlplaneio-fluxcd/flux-operator/releases/tag/v0.40.0), [advisory](https://github.com/controlplaneio-fluxcd/flux-operator/security/advisories/GHSA-4xh5-jcj2-ch8q) | **Unknown** — this repo installs Flux Operator and also Weave GitOps UI; no explicit Flux Operator web auth values were found, so exposure depends on whether Flux Operator web endpoints are enabled in deployed manifests. |
| `[behavior]` | Removed operator flag/env: `--disable-wait-interruption` / `DISABLE_WAIT_INTERRUPTION` (v0.39.0). | [source](https://github.com/controlplaneio-fluxcd/flux-operator/pull/583) | **No** — no such flag/env is set in repo manifests. |
| `[behavior]` | Leader election behavior changed (flags added in v0.39.0; default fix in v0.41.0). | [source](https://github.com/controlplaneio-fluxcd/flux-operator/pull/592), [source](https://github.com/controlplaneio-fluxcd/flux-operator/pull/646) | **Unknown** — repo does not override leader-election settings; runtime behavior depends on new defaults. |
| `[migration]` | Flux compatibility advanced across releases (explicit support for Flux v2.8.0/2.8.1/2.8.2/2.8.3; plus bump to Flux 2.8.5 in v0.47.0). | [v0.42.1](https://github.com/controlplaneio-fluxcd/flux-operator/releases/tag/v0.42.1), [v0.43.0](https://github.com/controlplaneio-fluxcd/flux-operator/releases/tag/v0.43.0), [v0.44.0](https://github.com/controlplaneio-fluxcd/flux-operator/releases/tag/v0.44.0), [v0.45.0](https://github.com/controlplaneio-fluxcd/flux-operator/releases/tag/v0.45.0), [PR](https://github.com/controlplaneio-fluxcd/flux-operator/pull/808) | **Yes** — this PR directly changes the Flux distribution artifact consumed by `flux-instance`, so controller/runtime version behavior can shift. |
| `[feature]` | Added ResourceSet/InputProvider features (AWS provider, drift events, `convertKubeConfigFrom` handling). | [source](https://github.com/controlplaneio-fluxcd/flux-operator/pull/834), [source](https://github.com/controlplaneio-fluxcd/flux-operator/pull/849), [source](https://github.com/controlplaneio-fluxcd/flux-operator/pull/786) | **No** — no `ResourceSet` / provider configuration found in this repo. |
| `[behavior]` | MCP/CLI oriented changes such as OCIRepository v1 migration and migrate commands. | [source](https://github.com/controlplaneio-fluxcd/flux-operator/pull/842), [source](https://github.com/controlplaneio-fluxcd/flux-operator/pull/823) | **No** — this repo change is runtime manifests, not MCP/CLI workflows. |

Release notes were reviewed for all intermediate versions between old and new (`v0.37.0` through `v0.50.0`) via each release page and compare links.

### Local impact

The PR changes one file: `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml`, updating `instance.distribution.artifact` from `v0.36.0` to `v0.50.0`.

This is high-importance infrastructure in this repo: Flux controllers are the GitOps control plane and this file also injects many controller args/feature-gates (concurrency, cache, OOM watch, digest tracking, SOPS, watch-config selectors, health-check behavior). Any controller flag incompatibility or behavior drift can block cluster reconciliation.

Related local context:
- `kubernetes/apps/flux-system/flux-operator/app/helmrelease.yaml` (operator installed with ServiceMonitor enabled)
- `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-flux.yaml`
- `kubernetes/apps/observability/grafana/app/dashboards/flux-gitops-health.yaml`
- `docs/techdocs/docs/runbooks/cluster-health-2026-05-21.md` (documents prior Flux/source-controller reconciliation issues)

### Improvement opportunities

- **None identified.**

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | `kubernetes/apps/observability/grafana/app/dashboards/flux-gitops-health.yaml` uses `gotk_*` and `controller_runtime_*` metrics | None | Upstream release notes in this range did not call out Flux metrics renames/removals for this artifact update. |
| Alert | `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-flux.yaml` alerts on `gotk_reconcile_condition` | None | No explicit metric schema changes were documented in reviewed release notes/PRs. |
| Metric / Scrape config | `kubernetes/apps/flux-system/flux-operator/app/helmrelease.yaml` has `serviceMonitor.create: true` | None | No release note item indicates scrape endpoint or metric-name migration required here. |

### Pre-merge checks

- [ ] Confirm rendered Flux controllers start cleanly after reconcile (no `unknown flag` / `invalid argument` errors) because this repo sets many controller args in `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml`.
- [ ] Confirm `flux-instance` and `flux-operator` reconcile to `Ready=True` and no prolonged `Stalled`/`False` conditions.
- [ ] Verify OCIRepository/HelmRelease health after upgrade (especially digest-pinned OCI sources noted in `docs/techdocs/docs/runbooks/cluster-health-2026-05-21.md`).
- [ ] If Flux Operator web endpoints are enabled in-cluster, validate OIDC/web auth behavior post-upgrade due the v0.40.0 security advisory fix.
- [ ] Check `FluxKustomizationNotReady` / `FluxHelmReleaseNotReady` alerts and the `GitOps / Flux Health` dashboard for regressions during/after rollout.

### Follow-up

- [ ] Consider adding a quick runbook note for this version jump (`v0.36.0 → v0.50.0`) under Flux operations docs, including rollback command path and expected controller versions.
- [ ] Consider reducing Renovate jump size for Flux control-plane artifacts (fewer skipped minors) to lower debugging surface for future upgrades.

### Evidence reviewed

- PR: `feat(container): update image ghcr.io/controlplaneio-fluxcd/flux-operator-manifests ( v0.36.0 ➔ v0.50.0 )`; labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, +1/-1.
- Files in repo: `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml`, `kubernetes/apps/flux-system/flux-operator/app/helmrelease.yaml`, `kubernetes/apps/flux-system/flux-operator/app/ocirepository.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-flux.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/flux-gitops-health.yaml`, `docs/techdocs/docs/platform-components.md`, `docs/techdocs/docs/runbooks/cluster-health-2026-05-21.md`.
- Upstream sources checked: PR metadata/files via GitHub API; `https://api.github.com/repos/controlplaneio-fluxcd/flux-operator/releases?per_page=100`; release pages `v0.37.0` through `v0.50.0`; compare links from each release; security advisory URL above.
- Notable uncertainty: the `flux-operator-manifests` image changelog is represented via `flux-operator` release notes; exact in-cluster enablement of Flux Operator web endpoints is not explicit in repo values.
