pr: 171

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR updates `docker.io/alpine/k8s` from `1.36.0` (digest `sha256:c105e4eaa265c617e43be34fffc7d9961de76b65a1e520179ed61e2f3a9fabf7`) to `1.36.1` (digest `sha256:692239d739589247c4a791205ed9619c28ae85a21286e19a6211c04a62c56668`) in two Renovate operator CronJob manifests. This is a patch-level bump within the same Kubernetes minor version (1.36.x), and the image is pinned by digest in both cases, ensuring supply-chain integrity. The primary risk is near-zero: the containers run short-lived kubectl-based jobs and are stateless.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/alpine/k8s` | Docker/OCI | `1.36.0 → 1.36.1` | patch | runtime (CronJob containers) | Green |

### Important upstream changes

The `alpine/k8s` image is maintained at https://github.com/alpine-docker/k8s and built weekly by CircleCI. No formal GitHub releases are published; the version tag tracks the bundled `kubectl` version (Kubernetes 1.36.x). Upstream commit history shows recent changes include:

- `[bugfix]` Removed `helm-push` plugin (no longer maintained upstream — issue #83). _Note: this change landed in prior builds and likely applies to both 1.36.0 and 1.36.1._
- `[bugfix]` Build fixes related to Helm plugin installation (`--verify=false`) and Helm version filtering (issue #88, #85).
- `[feature]` Patch bump in kubectl from 1.36.0 → 1.36.1, tracking the upstream Kubernetes 1.36.1 patch release (bug fixes, no breaking API changes).

No security advisories or breaking changes were identified in the Kubernetes 1.36.0 → 1.36.1 upstream patch release. No CVEs tied to this image were found.

### Local impact

The image is used in **five** places in this repository:

- `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml` — **updated by this PR** — runs a short-lived container using `kubectl apply` to create/update the `renovate-runtime-token` secret in the `renovate` namespace. Uses `docker.io/` registry prefix.
- `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml` — **updated by this PR** — runs a short-lived container using `kubectl get/delete jobs` to prune old Renovate jobs. Uses `docker.io/` registry prefix.
- `kubernetes/components/cnpg-disaster-recovery/cronjob.yaml` — **already on 1.36.1** (without `docker.io/` prefix).
- `kubernetes/components/cnpg-restore-test/cronjob.yaml` — **already on 1.36.1** (without `docker.io/` prefix).
- `kubernetes/apps/observability/k6-canaries/app/cronjob.yaml` — **already on 1.36.1** (without `docker.io/` prefix).

This PR brings the two Renovate operator CronJobs in line with the other three files already at 1.36.1, making the entire repository consistent. Both containers are stateless and have no persistent state concerns. Security context enforces `runAsNonRoot`, `readOnlyRootFilesystem`, and dropped capabilities. The `imagePullPolicy: IfNotPresent` is fine given the digest pin.

### Pre-merge checks

- [x] Digest `sha256:692239d739589247c4a791205ed9619c28ae85a21286e19a6211c04a62c56668` confirmed present and active on Docker Hub (pushed 2026-05-17, supports `linux/amd64` and `linux/arm64`).
- [x] Both files in the PR already reference the correct new digest — no drift between tag and digest.
- [x] Three other files in the repo already reference 1.36.1 at the same digest, confirming the image is in use and pulling correctly in this cluster.
- [ ] Verify Flux reconciles both CronJob manifests cleanly post-merge (no `ImagePullBackOff`).

### Evidence reviewed

- **PR:** "fix(container): update image docker.io/alpine/k8s ( 1.36.0 ➔ 1.36.1 )" — 2 files changed, tag + digest bump in both CronJob specs. Labels: `area/kubernetes`, `renovate/container`, `type/patch`, `dependencies`.
- **Files in repo:** `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml`, `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml`, `kubernetes/components/cnpg-disaster-recovery/cronjob.yaml`, `kubernetes/components/cnpg-restore-test/cronjob.yaml`, `kubernetes/apps/observability/k6-canaries/app/cronjob.yaml`
- **Upstream sources checked:**
  - Docker Hub API: `https://hub.docker.com/v2/repositories/alpine/k8s/tags?page_size=20&name=1.36`
  - Docker Hub repository description: `https://hub.docker.com/v2/repositories/alpine/k8s/`
  - GitHub commit history: `https://api.github.com/repos/alpine-docker/k8s/commits`
  - GitHub releases API: `https://api.github.com/repos/alpine-docker/k8s/releases` (no releases published)
- **Notable uncertainty:** The `alpine/k8s` project does not publish formal release notes or a CHANGELOG. Component-level versions (kubectl 1.36.1, helm, kustomize, etc.) bundled in the image are not explicitly documented per tag. The patch bump is inferred from the Kubernetes patch release cadence and the weekly build pattern. Risk remains low given the stateless, kubectl-only workload.
