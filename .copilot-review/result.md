pr: 338

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates the ARC runner image `ghcr.io/webgrip/github-runner` from `1.2.2` to `1.3.0` (with digest pin update) in one HelmRelease file. Upstream release notes for `github-runner-v1.3.0` show mostly supply-chain/release-process changes and OCI metadata updates, with no declared runtime package version bump in the runner Dockerfile itself. Primary risk is operational compatibility (runner behavior in live jobs and image provenance expectations), not schema/config breakage in this repo. Merge is reasonable after a short smoke test and policy-report verification.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/webgrip/github-runner` | Docker/OCI (GHCR) | `1.2.2@sha256:7b7a...` → `1.3.0@sha256:9d11...` | minor | runtime (ARC runner pods) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[feature]` | Added supply-chain security pipeline items (cosign signing, SBOM, SLSA provenance, Trivy, Kyverno) in source repo release range. | [release note](https://github.com/webgrip/infrastructure/releases/tag/github-runner-v1.3.0), [commit](https://github.com/webgrip/infrastructure/commit/001fc74efd32cd6d06abea764609d53ab3390544) | **Yes** — this repo deploys `ghcr.io/webgrip/*` images and already has Kyverno verification/attestation policies for this publisher/workflow. |
| `[behavior]` | `ops/docker/github-runner/Dockerfile` gained OCI metadata args/labels (`IMAGE_CREATED`, `IMAGE_VERSION`, `IMAGE_REVISION`, title/url/docs/vendor/authors). Runtime package install steps remained effectively the same in tagged file comparison. | [tagged file v1.2.2](https://github.com/webgrip/infrastructure/blob/github-runner-v1.2.2/ops/docker/github-runner/Dockerfile), [tagged file v1.3.0](https://github.com/webgrip/infrastructure/blob/github-runner-v1.3.0/ops/docker/github-runner/Dockerfile), [commit](https://github.com/webgrip/infrastructure/commit/aca228e1244b56c74b7f6b37ba8b690c4d6217ed) | **Yes** — this exact image runs in ARC runner `initContainers` and `containers` in this repo; metadata/provenance fields can affect policy/reporting, even if runtime behavior is likely unchanged. |
| `[bugfix]` | Release workflow fixed to force docker builds to `linux/amd64`. | [commit](https://github.com/webgrip/infrastructure/commit/af853d301a609153bc377480ef97e374efbedcfa), [release note](https://github.com/webgrip/infrastructure/releases/tag/github-runner-v1.3.0) | **Unknown** — current image tag still publishes a multi-arch index in GHCR, but release-process changes can alter future platform behavior; verify runner node architecture compatibility in-cluster. |
| `[unknown]` | Release notes include `techdocs-builder` changes in same release range (monorepo noise) not obviously related to runtime behavior of `github-runner` image. | [release note](https://github.com/webgrip/infrastructure/releases/tag/github-runner-v1.3.0), [compare](https://github.com/webgrip/infrastructure/compare/github-runner-v1.2.2...github-runner-v1.3.0) | **No** — this PR updates only the `github-runner` image reference used by ARC pods. |

### Local impact

`ghcr.io/webgrip/github-runner` is referenced in exactly one workload definition: `kubernetes/apps/arc-systems/gha-runner-scale-set/app/helmrelease.yaml` (both `initContainers.init-dind-externals` and `containers.runner`). The namespace (`arc-systems`) runs CI runner workloads and includes a privileged `docker:dind` sidecar in the same pod, so runner-image regressions can impact build execution for self-hosted GitHub Actions jobs. Rollback is straightforward (tag+digest revert in one file), but blast radius includes all jobs scheduled onto this scale set.

### Improvement opportunities

- **`Move Kyverno image verification/attestation policies from Audit to Enforce when confidence is sufficient`** — upstream now emphasizes signed/attested release flow for `webgrip` images; this repo already has matching audit policies for `ghcr.io/webgrip/*`, so enforcing would convert detection into prevention once rollout is validated. [upstream release](https://github.com/webgrip/infrastructure/releases/tag/github-runner-v1.3.0), [local verify policy](https://github.com/webgrip/homelab-cluster/blob/main/kubernetes/apps/kyverno/policies/app/image-verify-audit.yaml), [local attestation policy](https://github.com/webgrip/homelab-cluster/blob/main/kubernetes/apps/kyverno/policies/app/image-attestations-audit.yaml)

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | `kubernetes/apps/observability/grafana/app/dashboards/apps-arc-systems.yaml` tracks ARC pod/runner/job metrics | None | Upstream notes for this image bump do not document ARC metric renames/additions/removals; change appears centered on image release/security metadata. [release](https://github.com/webgrip/infrastructure/releases/tag/github-runner-v1.3.0) |
| Alert | `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-apps.yaml` and `.../prometheusrule-github-billing-copilot.yaml` include `arc-systems` health checks | None | No evidence of metric contract changes tied to this image update. Existing namespace-level health alerts remain applicable. [release](https://github.com/webgrip/infrastructure/releases/tag/github-runner-v1.3.0) |
| Metric / Scrape config | `kubernetes/apps/arc-systems/gha-runner-scale-set/app/podmonitor.yaml` scrapes `/metrics` on port 8080 | None | PodMonitor targets ARC components; this PR only changes runner image tag+digest and does not alter scrape endpoint config. [PR diff](https://github.com/webgrip/homelab-cluster/pull/338/files) |

### Pre-merge checks

- [ ] Run one real ARC workflow job on this scale set after deploy and confirm runner registration + job completion (including Docker-in-Docker usage) in `arc-systems`.
- [ ] Verify Kyverno PolicyReports for `image-verify-audit` and `image-attestations-audit` do not introduce new failures for digest `sha256:9d11657cd7e278b0b3b53b0158c0453000e30dd8e5ff1287d4659adf3d73ec25`.
- [ ] Confirm runner pods schedule on intended node architecture(s) for `nodegroup: fringe` and do not enter CrashLoop/Pending after image rollout.

### Follow-up

- [ ] Consider adding/adjusting an alert on sustained ARC runner Pending pods during image rollouts in `arc-systems` to catch regressions earlier — existing dashboards already visualize this signal. (`kubernetes/apps/observability/grafana/app/dashboards/apps-arc-systems.yaml`)
- [ ] Evaluate readiness to promote Kyverno `ghcr.io/webgrip/*` signature+attestation policies from Audit to Enforce once sufficient successful releases are observed. [upstream release](https://github.com/webgrip/infrastructure/releases/tag/github-runner-v1.3.0)

### Evidence reviewed

- PR: `feat(container): update image ghcr.io/webgrip/github-runner ( 1.2.2 ➔ 1.3.0 )`; labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 2 additions, 2 deletions.
- Files in repo: `kubernetes/apps/arc-systems/gha-runner-scale-set/app/helmrelease.yaml`, `kubernetes/apps/arc-systems/gha-runner-scale-set/app/podmonitor.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/apps-arc-systems.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-apps.yaml`, `kubernetes/apps/kyverno/policies/app/image-verify-audit.yaml`, `kubernetes/apps/kyverno/policies/app/image-attestations-audit.yaml`.
- Upstream sources checked: `https://github.com/webgrip/infrastructure/releases/tag/github-runner-v1.3.0`, `https://github.com/webgrip/infrastructure/releases/tag/github-runner-v1.2.2`, `https://github.com/webgrip/infrastructure/compare/github-runner-v1.2.2...github-runner-v1.3.0`, `https://github.com/webgrip/infrastructure/commit/001fc74efd32cd6d06abea764609d53ab3390544`, `https://github.com/webgrip/infrastructure/commit/af853d301a609153bc377480ef97e374efbedcfa`, `https://github.com/webgrip/infrastructure/commit/aca228e1244b56c74b7f6b37ba8b690c4d6217ed`, `https://ghcr.io/v2/webgrip/github-runner/manifests/1.2.2`, `https://ghcr.io/v2/webgrip/github-runner/manifests/1.3.0`.
- Notable uncertainty: release notes are generated from a monorepo and include some unrelated component changes; no dedicated standalone changelog for only `github-runner` runtime behavior was found.
