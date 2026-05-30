pr: 299

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR does not change the `alpine/k8s` version used by the repository; it only converts `docker.io/alpine/k8s:1.36.1` into the immutable multi-arch manifest digest `sha256:692239d739589247c4a791205ed9619c28ae85a21286e19a6211c04a62c56668`. Locally, that image is only used as a short-lived initContainer that runs `kubectl get pods -A` to build an image list for the Dependency-Track SBOM uploader, so the functional blast radius is limited. The main caveat is upstream transparency: `alpine/k8s` is a community-maintained toolbox image with no image-specific release notes, and its build script pulls several auxiliary tools at their latest versions at build time. Because this PR pins an already-selected tag to an exact digest, it improves reproducibility and supply-chain control, but I still recommend one manual CronJob verification because the workload runs on a weekly schedule.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/alpine/k8s` | Docker/OCI image | `1.36.1` → `1.36.1@sha256:692239d739589247c4a791205ed9619c28ae85a21286e19a6211c04a62c56668` | digest | runtime / security automation | Green |

### Important upstream changes

No image-specific release notes were found for `alpine/k8s:1.36.1`. I checked the Docker Hub tag metadata, the upstream GitHub repository releases/tags, and the upstream source README/build script.

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[behavior]` | Docker Hub currently publishes `alpine/k8s:1.36.1` as manifest-list digest `sha256:692239d739589247c4a791205ed9619c28ae85a21286e19a6211c04a62c56668` with `linux/amd64` and `linux/arm64` images underneath. This PR pins that exact manifest instead of relying on the mutable tag. | [source](https://hub.docker.com/v2/repositories/alpine/k8s/tags/1.36.1) | **Yes** — `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml` currently uses the unpinned tag for the `get-images` initContainer. |
| `[unknown]` | The image itself has no published changelog for the `1.36.1` build. The upstream repository exposes no GitHub releases or tags for image builds. | [source](https://hub.docker.com/r/alpine/k8s/tags), [source](https://github.com/alpine-docker/k8s) | **Unknown** — lack of image-specific release notes means the exact contents beyond the tag are not transparently documented. |
| `[behavior]` | Upstream documents `alpine/k8s` as an “all-in-one Kubernetes tools” image, and its build script assembles the image from `kubectl` plus several other tools (`helm`, `kustomize`, `kubeseal`, `krew`, `vals`, `kubeconform`, etc.), with multiple components resolved to the latest available release at build time. Pinning the digest freezes that full bundle. | [source](https://raw.githubusercontent.com/alpine-docker/k8s/master/README.md), [source](https://raw.githubusercontent.com/alpine-docker/k8s/master/build.sh) | **Yes** — even though this repo’s `get-images.sh` only needs `kubectl` and shell utilities, the digest pin now locks the full tool bundle that ships inside the helper image. |
| `[bugfix]` | Kubernetes `v1.36.1` includes a kube-proxy large-cluster full-sync regression fix. | [source](https://github.com/kubernetes/kubernetes/pull/138635) | **No** — this repository uses `alpine/k8s` only as a helper `kubectl` image in CronJobs, not to run kube-proxy. |
| `[bugfix]` | Kubernetes `v1.36.1` fixes kubelet startup on ZFS when the cadvisor plugin is missing. | [source](https://github.com/kubernetes/kubernetes/pull/138590) | **No** — this repo is not using the image for kubelet or node components. |
| `[bugfix]` | Kubernetes `v1.36.1` changes DRA metadata decode handling to error on malformed objects/files instead of silently skipping them. | [source](https://github.com/kubernetes/kubernetes/pull/138859) | **No** — the repo usage is limited to `kubectl get pods -A -o json` in an initContainer script; no DRA metadata workflow is present locally. |

### Local impact

The PR changes only `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml`, where the `get-images` initContainer runs `docker.io/alpine/k8s:1.36.1` before the main Trivy upload container starts. The paired script in `kubernetes/apps/security/dependency-track/app/sbom-uploader/configmap.yaml` uses `kubectl get pods -A -o json`, `grep`, `sed`, and `sort` to enumerate running images into `/work/images.txt`; it does not use Helm, kustomize, or other bundled tools from the image. RBAC in `kubernetes/apps/security/dependency-track/app/sbom-uploader/rbac.yaml` grants only `get`/`list` on pods and namespaces, so the workload is privileged enough to see cluster-wide runtime inventory but not to mutate cluster state. Rollback difficulty is low because this is a scheduled CronJob helper, not a stateful service, but failure would delay SBOM collection and downstream Dependency-Track uploads until the next successful run or a manual job execution.

The repository also uses the same image family in other helper CronJobs (`kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml`, `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml`, `kubernetes/apps/observability/k6-canaries/app/cronjob.yaml`, `kubernetes/components/cnpg-disaster-recovery/cronjob.yaml`, and `kubernetes/components/cnpg-restore-test/cronjob.yaml`), and those references are already digest-pinned. That makes this PR consistent with the prevailing local hardening pattern.

### Improvement opportunities

None identified.

### Grafana dashboards and alerts

No dashboard or alert changes identified. The observability files I found for Dependency-Track (`kubernetes/apps/security/dependency-track/app/metrics-exporter/servicemonitor.yaml` and `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-security-dt.yaml`) monitor Dependency-Track exporter metrics such as `dt_portfolio_*` and `dt_exporter_last_scrape_timestamp`; they do not scrape or alert on `alpine/k8s`, `kubectl`, or sbom-uploader-specific metrics. The upstream sources reviewed also did not document any metric name, label, or scrape-path changes for this image.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard / Alert / Metric / Scrape config | `kubernetes/apps/security/dependency-track/app/metrics-exporter/servicemonitor.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-security-dt.yaml` | None | Existing observability targets Dependency-Track exporter metrics, not the `alpine/k8s` helper image; no upstream metric changes were published for this image. |

### Pre-merge checks

- [ ] Confirm the rendered manifest for `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml` now resolves to `docker.io/alpine/k8s:1.36.1@sha256:692239d739589247c4a791205ed9619c28ae85a21286e19a6211c04a62c56668`.
- [ ] Manually trigger or observe one `trivy-sbom-uploader` job run after deployment and verify the `get-images` initContainer still produces `/work/images.txt` successfully before the Trivy upload container starts.

### Follow-up

- [ ] Consider documenting in Renovate policy or ops docs that `alpine/k8s` is a community-maintained multi-tool image with sparse per-build release notes, so future upgrades should keep receiving manual review.

### Evidence reviewed

- PR: `chore(container): pin image docker.io/alpine/k8s to 692239d`; labels `area/kubernetes`, `renovate/container`, `dependencies`; diff summary: 1 file changed, 1 addition, 1 deletion in `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml`.
- Files in repo: `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml`, `kubernetes/apps/security/dependency-track/app/sbom-uploader/configmap.yaml`, `kubernetes/apps/security/dependency-track/app/sbom-uploader/rbac.yaml`, `kubernetes/apps/security/dependency-track/app/metrics-exporter/servicemonitor.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-security-dt.yaml`, plus other `alpine/k8s` references in `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml`, `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml`, `kubernetes/apps/observability/k6-canaries/app/cronjob.yaml`, `kubernetes/components/cnpg-disaster-recovery/cronjob.yaml`, and `kubernetes/components/cnpg-restore-test/cronjob.yaml`.
- Upstream sources checked: https://hub.docker.com/v2/repositories/alpine/k8s/tags/1.36.1, https://hub.docker.com/r/alpine/k8s/tags, https://hub.docker.com/v2/repositories/alpine/k8s, https://github.com/alpine-docker/k8s, https://raw.githubusercontent.com/alpine-docker/k8s/master/README.md, https://raw.githubusercontent.com/alpine-docker/k8s/master/build.sh, https://raw.githubusercontent.com/kubernetes/kubernetes/master/CHANGELOG/CHANGELOG-1.36.md, https://github.com/kubernetes/kubernetes/pull/138635, https://github.com/kubernetes/kubernetes/pull/138590, https://github.com/kubernetes/kubernetes/pull/138859.
- Notable uncertainty: `alpine/k8s` does not publish image-specific release notes or git tags for the exact Docker Hub build, so the full contents of the `1.36.1` image are inferred from Docker Hub metadata and the upstream source repository rather than from a formal release artifact.
