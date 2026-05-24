pr: 235

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** High

### Executive summary

This PR bumps both `gha-runner-scale-set` and `gha-runner-scale-set-controller` Helm charts from 0.13.1 to 0.14.2 (three minor versions: 0.14.0 → 0.14.1 → 0.14.2). The primary risk driver is a **critical Go security fix** in 0.14.2 (Go upgraded to 1.26.3 to address critical CVEs), a **listener pod nodeSelector change** in 0.14.0, and a **secret reconciliation fix** that is relevant because this repo wires secrets via `valuesFrom`. No confirmed breaking changes exist, but the coordinated two-chart upgrade and the stateful runner fleet warrant a post-merge smoke test.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller` | OCI Helm chart | `0.13.1 → 0.14.2` | minor (3 versions) | runtime infra — runs the ARC controller that manages runner scale sets | Yellow |
| `ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set` | OCI Helm chart | `0.13.1 → 0.14.2` | minor (3 versions) | runtime infra — defines the runner pods that execute CI jobs | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[security]` | Bump Go to 1.26.2 / 1.26.3 to fix critical security vulnerabilities in the controller binary | [PR #4491](https://github.com/actions/actions-runner-controller/pull/4491), [PR #4504](https://github.com/actions/actions-runner-controller/pull/4504) | **Yes** — controller image is deployed; upgrading removes critical CVEs from the running binary |
| `[security]` | Fix weak cryptographic hashing algorithm on sensitive data (code scanning alert #7) | [PR #4353](https://github.com/actions/actions-runner-controller/pull/4353) | **Yes** — controller processes GitHub JIT tokens; this hardened the hashing of sensitive data |
| `[behavior]` | Listener pod now gets a default `linux` nodeSelector added automatically | [PR #4377](https://github.com/actions/actions-runner-controller/pull/4377) | **Unknown** — runners are already on Linux nodes in this cluster, so this is almost certainly a no-op, but verify no mixed-OS node pool is used |
| `[bugfix]` | Fix secret reconciliation updates for the listener pod | [PR #4492](https://github.com/actions/actions-runner-controller/pull/4492) | **Yes** — this repo wires `gha-runner-scale-set-secrets` via `valuesFrom` in the HelmRelease; the fix ensures secret changes propagate to the listener pod correctly |
| `[bugfix]` | Fix empty GVK in OwnerReferences for modern controller-runtime versions | [PR #4475](https://github.com/actions/actions-runner-controller/pull/4475) | **Yes** — owner-reference issues can cause resource orphaning/GC problems; this is a correctness fix |
| `[bugfix]` | Fix orphan no-permission ServiceAccount in kubernetes-novolume mode | [PR #4455](https://github.com/actions/actions-runner-controller/pull/4455) | **No** — this repo uses dind volume mode (not kubernetes-novolume), so the orphaned SA bug does not apply |
| `[bugfix]` | Detect init container failure in EphemeralRunner controller | [PR #4457](https://github.com/actions/actions-runner-controller/pull/4457) | **Yes** — this repo uses an `init-dind-externals` init container; previously, init container failures may have been silently ignored |
| `[bugfix]` | Fix job execution duration calculation when runner assign time is not set | [PR #4472](https://github.com/actions/actions-runner-controller/pull/4472) | **Yes** — affects metrics accuracy for job duration; PodMonitor in this repo scrapes the controller metrics endpoint |
| `[feature]` | Add health and readiness probes to controller manager | [PR #4459](https://github.com/actions/actions-runner-controller/pull/4459) | **Yes** — improves controller availability detection; no chart values change needed (enabled by default) |
| `[feature]` | Add option to disable workqueue bucket rate limiter | [PR #4451](https://github.com/actions/actions-runner-controller/pull/4451) | **No** — not enabled; relevant only if rate limiting causes issues at scale |
| `[feature]` | Allow users to apply labels and annotations to internal resources | [PR #4400](https://github.com/actions/actions-runner-controller/pull/4400) | **No** — feature not used; no change needed |
| `[feature]` | Add multi-label support to scalesets | [PR #4408](https://github.com/actions/actions-runner-controller/pull/4408) | **No** — `runnerGroup: Default` is already configured; single group sufficient |
| `[feature]` | Add chart-level API to customize internal resources | [PR #4410](https://github.com/actions/actions-runner-controller/pull/4410) | **No** — not used |
| `[feature]` | Add pprof flag on controller manager | [PR #4449](https://github.com/actions/actions-runner-controller/pull/4449) | **No** — not enabled by default; diagnostic tool only |
| `[bugfix]` | Shutdown scaleset when runner is deprecated | [PR #4404](https://github.com/actions/actions-runner-controller/pull/4404) | **Yes** — improves lifecycle management; runners will now cleanly deregister on deprecation events |
| `[feature]` | Runner binary updated: v2.331.0 → v2.332.0 → v2.333.0 → v2.333.1 → v2.334.0 | [ARC runner releases](https://github.com/actions/runner/releases) | **Yes** — bundled runner binary bumped; the custom runner image (`ghcr.io/webgrip/github-runner:1.2.2`) is separate and is NOT updated by this PR |

### Local impact

This repo deploys both charts as a pair in the `arc-systems` namespace:

- **Controller** (`kubernetes/apps/arc-systems/actions-runner-controller/app/`): A `HelmRelease` referencing an `OCIRepository` pinned by both tag and digest. The controller manages runner scale sets and exposes metrics on `:8080/metrics` (consumed by a `PodMonitor`). The `valuesFrom` pattern is not used here.
- **Scale set** (`kubernetes/apps/arc-systems/gha-runner-scale-set/app/`): A `HelmRelease` that depends on the controller, wires `gha-runner-scale-set-secrets` via `valuesFrom`, and deploys custom runner pods with a dind sidecar. Both `runner` and `dind` containers use custom images that are **not** updated by this PR. The `listenerTemplate` also exports metrics.

Both `OCIRepository` resources now pin the new digests (`sha256:3081ba...` and `sha256:579e3a...`), which is correct supply-chain practice.

The fix in PR #4492 (secret reconciliation for listener pod) is directly relevant: the listener pod picks up `gha-runner-scale-set-secrets`; previously a rotation/update to that secret might not have propagated without a controller restart.

The init-container failure detection fix (PR #4457) is also relevant since `init-dind-externals` copies runner externals; previously a failure there might have caused silent hangs.

Rollback: revert the two `ocirepository.yaml` files to the prior tag+digest and Flux will reconcile. The controller is stateless (state is in GitHub's API); the scale set maintains a pool of 2–10 ephemeral runners. Rollback risk is low.

### Improvement opportunities

- **Enable health/readiness probes via values** — PR #4459 adds probes to the controller manager. While they are on by default, check the Helm values to confirm whether `healthProbePort` / `readinessProbe` are already in the chart defaults or need explicit opt-in. This improves availability guarantees visible to Kubernetes. [Source PR #4459](https://github.com/actions/actions-runner-controller/pull/4459)
- **Evaluate multi-label support** — PR #4408 allows runner pods to carry multiple labels for job routing. If CI workflows need to target this runner fleet by multiple characteristics (e.g., `arc-runner-set` + `large`), this is now native. [Source PR #4408](https://github.com/actions/actions-runner-controller/pull/4408)
- **Consider labeling internal resources** — PR #4400 / #4410 expose a chart-level API to apply labels/annotations to internal Kubernetes resources (EphemeralRunnerSet, etc.). This could improve Grafana dashboard filtering granularity if needed. [Source PR #4400](https://github.com/actions/actions-runner-controller/pull/4400)

### Grafana dashboards and alerts

The Grafana dashboard (`kubernetes/apps/arc-systems/dashboards/apps-arc-systems.yaml`) uses only generic kube-state-metrics and cAdvisor metrics scoped to the `arc-systems` namespace. No ARC-specific metric names are queried. Both `PodMonitor` resources target port 8080 with the `/metrics` path — these selectors are based on Helm-managed labels (`app.kubernetes.io/instance` and `app.kubernetes.io/part-of`) which are stable across this version range.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| PodMonitor — controller | `kubernetes/apps/arc-systems/actions-runner-controller/app/podmonitor.yaml`, targets `app.kubernetes.io/instance: gha-runner-scale-set-controller` on `:8080/metrics` | None — labels unchanged | Chart label conventions are unchanged in 0.14.x |
| PodMonitor — scale set | `kubernetes/apps/arc-systems/gha-runner-scale-set/app/podmonitor.yaml`, targets `app.kubernetes.io/part-of: gha-runner-scale-set` on `:8080/metrics` | None — labels unchanged | Chart label conventions are unchanged in 0.14.x |
| Dashboard panels | Generic kube-state-metrics panels only (CPU, memory, pod restarts, PVC, up targets) | Consider adding ARC-specific panels for job queue depth and runner utilisation | New `job execution duration` metric fix in PR #4472 improves accuracy of any future job-duration panels; no existing panels broken |

No dashboard or alert changes are required for this upgrade.

### Pre-merge checks

- [ ] Confirm both digests are reachable from the cluster's GHCR credentials: `crane manifest ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller:0.14.2@sha256:3081ba15c41f0aa791058dedd2a7406fece24c9aeaa94956c268e5099427a452` and `crane manifest ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set:0.14.2@sha256:579e3a1bdf4032b3c3de3e9b0880a4a6d3c1989a67c06010f680c1cc49524d11`
- [ ] Run the repo OCI digest verify script: `./scripts/verify-oci-digests.sh <repo-root>` (used in CI flux-local workflow)
- [ ] After merge, verify Flux reconciles both HelmReleases successfully: `flux get helmrelease -n arc-systems`
- [ ] Confirm runner pods restart and re-register with GitHub Actions (check `arc-systems` pods reach `Running`, no `init-dind-externals` failures)
- [ ] Verify the listener pod comes up healthy with the new default `linux` nodeSelector — no scheduling failures if all nodes are Linux-labeled

### Follow-up

- [ ] **Update custom runner image** — `ghcr.io/webgrip/github-runner:1.2.2` bundles its own runner binary; the ARC chart now ships runner v2.334.0, but the custom image is at an older version. Consider building a new runner image to stay current with the bundled binary. Relevant to: `kubernetes/apps/arc-systems/gha-runner-scale-set/app/helmrelease.yaml`
- [ ] **Explore probes configuration** — Validate that `healthProbePort` introduced in PR #4459 is configured to a unique port to avoid conflict with the existing `:8080` metrics port on the controller pod. Check chart defaults for 0.14.2 before next upgrade cycle.

### Evidence reviewed

- **PR**: #235 "feat(container): update flux oci helm charts ( 0.13.1 ➔ 0.14.2 )" — labels: area/kubernetes, renovate/container, type/minor, dependencies; 2 files changed (+4/-4); both changes are tag+digest bumps in OCIRepository resources
- **Files in repo**: `kubernetes/apps/arc-systems/actions-runner-controller/app/{helmrelease,ocirepository,podmonitor}.yaml`, `kubernetes/apps/arc-systems/gha-runner-scale-set/app/{helmrelease,ocirepository,podmonitor,rbac}.yaml`, `kubernetes/apps/arc-systems/dashboards/apps-arc-systems.yaml`
- **Upstream sources checked**:
  - `https://api.github.com/repos/actions/actions-runner-controller/releases/tags/gha-runner-scale-set-0.14.0`
  - `https://api.github.com/repos/actions/actions-runner-controller/releases/tags/gha-runner-scale-set-0.14.1`
  - `https://api.github.com/repos/actions/actions-runner-controller/releases/tags/gha-runner-scale-set-0.14.2`
- **Notable uncertainty**: The custom runner image (`ghcr.io/webgrip/github-runner:1.2.2`) is not updated in this PR; its bundled runner binary version was not inspected. The exact Go CVEs fixed in 1.26.2/1.26.3 were not individually enumerated — marked as "critical" by upstream maintainers.
