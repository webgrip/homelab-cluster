pr: 278

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates the Renovate runtime container used by the `RenovateJob` from `43.195.4-full` to `43.195.5-full` and updates the pinned digest. Upstream `43.195.5` only contains two dependency bumps (`oxlint-tsgolint` and `@renovatebot/pgp`) with no documented breaking/runtime feature changes in release notes. Risk is still non-zero because this image runs scheduled dependency automation with GitHub credentials and can affect repo-wide update behavior. Merge is reasonable after a quick post-deploy functional check of Renovate runs and existing Renovate operator alerts.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/renovate/renovate` | Docker/OCI | `43.195.4-full@sha256:7b69...cb4f` → `43.195.5-full@sha256:ca5f...4e32` | patch | deploy/automation runtime | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[behavior]` | Renovate `43.195.5` consists of 2 commits; compare shows only `package.json` and `pnpm-lock.yaml` changed upstream. | [compare 43.195.4...43.195.5](https://github.com/renovatebot/renovate/compare/43.195.4...43.195.5) | **Unknown** — no explicit runtime behavior notes; patch touches transitive/runtime deps only. |
| `[feature]` | Dependency update: `oxlint-tsgolint` `0.22.1` → `0.23.0` (chore). | [PR #43585](https://github.com/renovatebot/renovate/issues/43585), [commit 1be6bbb](https://github.com/renovatebot/renovate/commit/1be6bbb7f88d2aec1abb17d9be13ef5a036516b5) | **No** — this is Renovate project maintenance; no repo config in `configmap-gitops.yaml` indicates direct reliance on this tooling internals. |
| `[behavior]` | Build dependency update: `@renovatebot/pgp` `1.3.11` → `1.3.12`. | [PR #43586](https://github.com/renovatebot/renovate/issues/43586), [commit 98762c4](https://github.com/renovatebot/renovate/commit/98762c420154503ee134efb0aceb50d0d4b59d7c) | **Yes** — Renovate runtime image includes this dependency; if PGP handling changed, signature-related package processing could differ. No breaking note found. |
| `[unknown]` | Container tag + digest update in Docker Hub for `43.195.5-full`. | [Docker Hub tag 43.195.5-full](https://hub.docker.com/layers/renovate/renovate/43.195.5-full/images/sha256-ca5fb31e87887f49d1d818d8a4d57e0e85241e0297a7cf906d0a1befcb734e32) | **Yes** — exact image referenced by `RenovateJob` (`webgrip-gitops.yaml`). |

### Local impact

- Runtime usage is explicit in `kubernetes/apps/renovate/renovate-operator/jobs/webgrip-gitops.yaml` (`spec.image`), so this changes the executable used by scheduled and webhook-triggered Renovate runs.
- This workload has operational importance (dependency PR generation for `webgrip/*`) and uses `secretRef: renovate-runtime-token`, so regressions can stall updates across repositories.
- Security posture is relatively strong (`runAsNonRoot`, `allowPrivilegeEscalation: false`), reducing container breakout risk, but functional regression risk remains in automation behavior.
- Rollback is straightforward (revert one image line/digest), so recovery difficulty is low.

### Improvement opportunities

- **`Advance directly to newer patch release in same series`** — PR body already indicates `43.195.8-full` is pending; consolidating to latest patch can reduce churn if you prefer fewer deploys. [PR body release metadata](https://github.com/webgrip/homelab-cluster/pull/278)
- **`Add an explicit smoke-run procedure to runbook after Renovate image bumps`** — current alerts/runbook references exist, but a standard post-upgrade trigger/checklist would reduce uncertainty for patch updates. [Prometheus rule runbook refs](https://github.com/webgrip/homelab-cluster/blob/main/kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml)

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | `kubernetes/apps/observability/grafana/app/dashboards/platform-renovate-operator.yaml` | None | Upstream `43.195.5` notes do not mention new/renamed metrics; no metric schema change identified in release notes/compare. [release 43.195.5](https://github.com/renovatebot/renovate/releases/tag/43.195.5) |
| Alert | `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml` | None | Existing alerts already cover operator availability, run failures, and dependency issues; no upstream metric deprecations noted for this patch. [release 43.195.5](https://github.com/renovatebot/renovate/releases/tag/43.195.5) |
| Metric / Scrape config | none found specific to this image tag change | None | PR only changes Renovate executor image tag+digest in one `RenovateJob`; no scrape config touched. [PR files changed](https://github.com/webgrip/homelab-cluster/pull/278/files) |

### Pre-merge checks

- [ ] Confirm the pinned digest in the PR (`sha256:ca5fb31e...`) matches Docker Hub tag `43.195.5-full` manifest list.
- [ ] After Flux reconciliation, trigger/observe one Renovate run and verify it completes without `RenovateProjectRunFailed` alerts.
- [ ] Check operator/job logs for PGP/signature-related warnings in first run post-upgrade.

### Follow-up

- [ ] Consider fast-following to `43.195.8-full` (already shown as pending) to reduce patch lag on Renovate runtime — [PR #278 body](https://github.com/webgrip/homelab-cluster/pull/278)
- [ ] Document a standard post-upgrade Renovate smoke test in platform runbooks to increase confidence on future image bumps — `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml`

### Evidence reviewed

- PR: `fix(container): update image docker.io/renovate/renovate ( 43.195.4 ➔ 43.195.5 )`; labels `area/kubernetes`, `renovate/container`, `type/patch`, `dependencies`; diff summary `1 file changed, +1/-1`.
- Files in repo: `kubernetes/apps/renovate/renovate-operator/jobs/webgrip-gitops.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/platform-renovate-operator.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml`.
- Upstream sources checked: `https://github.com/renovatebot/renovate/releases/tag/43.195.5`, `https://github.com/renovatebot/renovate/compare/43.195.4...43.195.5`, `https://github.com/renovatebot/renovate/issues/43585`, `https://github.com/renovatebot/renovate/commit/1be6bbb7f88d2aec1abb17d9be13ef5a036516b5`, `https://github.com/renovatebot/renovate/issues/43586`, `https://github.com/renovatebot/renovate/commit/98762c420154503ee134efb0aceb50d0d4b59d7c`, `https://hub.docker.com/v2/repositories/renovate/renovate/tags/43.195.5-full`.
- Notable uncertainty: No detailed changelog beyond dependency bumps; runtime impact of `@renovatebot/pgp` patch is inferred from dependency scope, not explicitly documented as behavior change.
