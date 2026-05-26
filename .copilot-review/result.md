pr: 270

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

PR #270 updates the token-minter init container image in the Renovate token CronJob from `ghcr.io/mshekow/github-app-installation-token:2026.05.22` to `:2026.05.26` with a new digest. Upstream GitHub release notes/tags for these version strings are not published; however, GHCR image metadata shows both tags were built from the same source revision (`ae9cbc5`). The main risk driver is that this container mints and writes Renovate runtime credentials, so even a rebuild-only image change has meaningful blast radius if behavior regresses. Merge is reasonable after a focused in-cluster token-mint smoke check.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/mshekow/github-app-installation-token` | Docker/OCI (GHCR) | `2026.05.22@sha256:7babcf...` → `2026.05.26@sha256:68b14a...` | patch/date-tag + digest | runtime/infra (Renovate auth bootstrap) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[unknown]` | No upstream GitHub Release entry exists for either `2026.05.22` or `2026.05.26` tags (release lookup returns 404). | [2026.05.22 release lookup](https://api.github.com/repos/MShekow/github-app-installation-token/releases/tags/2026.05.22), [2026.05.26 release lookup](https://api.github.com/repos/MShekow/github-app-installation-token/releases/tags/2026.05.26) | **Unknown** — no formal release notes/changelog entry for this exact range. |
| `[behavior]` | GHCR metadata indicates both image tags resolve to the same source revision `ae9cbc5` (the commit from `chore(deps): update node.js to v24.16.0 (#108)`), implying a rebuild/republish rather than a source-code delta between these two tags. | [commit ae9cbc5](https://github.com/MShekow/github-app-installation-token/commit/ae9cbc5fd6979ae2df06b45242c41f5f4afdf133), [workflow tagging logic](https://github.com/MShekow/github-app-installation-token/blob/ae9cbc5fd6979ae2df06b45242c41f5f4afdf133/.github/workflows/ci-cd.yaml#L52-L57), [GHCR tags endpoint](https://ghcr.io/v2/mshekow/github-app-installation-token/tags/list) | **Yes** — local manifest pins this image digest directly in the Renovate token-mint CronJob. |
| `[unknown]` | Layer digests differ between the two tags despite identical source revision, so artifact-level drift exists (likely rebuild-time changes), but upstream does not publish a human-readable changelog for this republish. | [manifest endpoint (old)](https://ghcr.io/v2/mshekow/github-app-installation-token/manifests/2026.05.22), [manifest endpoint (new)](https://ghcr.io/v2/mshekow/github-app-installation-token/manifests/2026.05.26) | **Yes** — this repo executes that artifact in-cluster to mint credentials; operational verification is warranted. |


No release notes/changelog entries for these date tags were found. I checked GitHub Releases tag endpoints, repository tags/CHANGELOG presence, and container registry tag/manifest metadata.

### Local impact

The dependency is used in exactly one runtime path: `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml` (`initContainers[].name: mint-token`). This job reads GitHub App credentials from `renovate-secrets`, runs `node index.js` in the updated container, and writes a short-lived token plus `RENOVATE_HOST_RULES` into `renovate-runtime-token` consumed by Renovate runs. Documentation also references this image in `kubernetes/apps/renovate/renovate-operator/jobs/README.md`. This is security-sensitive but scoped (non-root, dropped capabilities, read-only root filesystem, isolated to `renovate` namespace); rollback is straightforward by reverting the pinned tag+digest.

### Improvement opportunities

None identified.

### Grafana dashboards and alerts

No dashboard or alert changes identified for this image bump. Existing Renovate observability (`kubernetes/apps/observability/grafana/app/dashboards/platform-renovate-operator.yaml` and `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml`) tracks operator/deployment/run metrics, not internals of the token-minter container image.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | `kubernetes/apps/observability/grafana/app/dashboards/platform-renovate-operator.yaml` (operator-level metrics) | None | Upstream change is an image republish with no published metric/schema changes. |
| Alert | `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml` (operator/run health alerts) | None | No evidence of renamed/removed metrics tied to this token-minter image update. |
| Metric / Scrape config | none found for `github-app-installation-token` | None | This helper container does not expose a dedicated metrics endpoint in local manifests. |

### Pre-merge checks

- [ ] Reconcile/apply PR branch in a test environment and run one-off job from `cronjob/renovate-github-app-token`.
- [ ] Confirm job logs show successful token mint + secret apply (no `failed to mint installation token`, no `set both RENOVATE_DOCKERHUB_*` errors).
- [ ] Verify `renovate-runtime-token` Secret is refreshed and contains `token`, `RENOVATE_TOKEN`, and `RENOVATE_HOST_RULES` keys.
- [ ] Trigger one Renovate run and confirm dependency lookups to GHCR still succeed.

### Follow-up

- [ ] Add lightweight runtime SLI/alert for token-refresh freshness (age of `renovate-runtime-token`) to detect silent token-minter regressions earlier — current rules focus on operator/run outcomes, not token secret staleness. (`kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml`)

### Evidence reviewed

- PR: `fix(container): update image ghcr.io/mshekow/github-app-installation-token ( 2026.05.22 ➔ 2026.05.26 )`; labels: `area/kubernetes`, `renovate/container`, `type/patch`, `dependencies`; diff summary: 1 file changed, 1 insertion / 1 deletion.
- Files in repo: `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml`, `kubernetes/apps/renovate/renovate-operator/jobs/README.md`, `kubernetes/apps/observability/grafana/app/dashboards/platform-renovate-operator.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml`.
- Upstream sources checked: https://github.com/MShekow/github-app-installation-token, https://api.github.com/repos/MShekow/github-app-installation-token/releases/tags/2026.05.22, https://api.github.com/repos/MShekow/github-app-installation-token/releases/tags/2026.05.26, https://github.com/MShekow/github-app-installation-token/commit/ae9cbc5fd6979ae2df06b45242c41f5f4afdf133, https://github.com/MShekow/github-app-installation-token/blob/ae9cbc5fd6979ae2df06b45242c41f5f4afdf133/.github/workflows/ci-cd.yaml, https://ghcr.io/v2/mshekow/github-app-installation-token/tags/list, https://ghcr.io/v2/mshekow/github-app-installation-token/manifests/2026.05.22, https://ghcr.io/v2/mshekow/github-app-installation-token/manifests/2026.05.26.
- Notable uncertainty: Upstream does not publish explicit release notes/changelog per date-tagged image, so image-layer drift cause between these two tags is inferred from registry metadata rather than maintainer-authored notes.
