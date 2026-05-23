pr: 147

## Dependency Update Review

**Verdict:** Orange High risk
**Recommendation:** Hold
**Confidence:** High

### Executive summary

PR #147 updates `alpine/k8s` from `1.34.3` to `1.36.1` and adds a digest pin in two CNPG CronJob manifests. Upstream Kubernetes releases exist for all intermediate versions (`1.34.4` through `1.36.1`), and 1.35+ includes kubectl behavior/API-support changes. The main local risk is version skew: this repo indicates a Kubernetes control plane on `v1.34.x`, while `kubectl` `1.36.1` is two minors newer, outside the documented supported skew window. Recommend holding this PR until cluster version catches up, or reducing the image to a supported kubectl minor.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `alpine/k8s` | Docker/OCI container image | `1.34.3` → `1.36.1` (+ digest pin) | minor (crosses 1.35 and 1.36) | infra/ops runtime (kubectl-based CronJobs) | Orange |

### Important upstream changes

- [behavior] Docker Hub shows intermediate tags published between current and target: `1.34.4`, `1.34.5`, `1.34.6`, `1.34.7`, `1.34.8`, `1.35.0`, `1.35.1`, `1.35.2`, `1.35.3`, `1.35.4`, `1.35.5`, `1.36.0`, `1.36.1`.
- [breaking] Kubernetes 1.35 changelog includes kubectl API support removals for deprecated beta APIs (for example `networking/v1beta1` Ingress/IngressClass, `certificates/v1beta1` CSR, `policy/v1beta1` PDB, `discovery/v1beta1` EndpointSlice).
- [behavior] Kubernetes 1.36 changelog includes multiple kubectl behavior/output changes (for example `kubectl describe` event-display defaults changed; `kubectl diff` added `--show-secret`; additional output fields in describe/get).
- [bugfix] Kubernetes 1.35/1.36 include kubectl CLI bugfixes (for example exec panic fixes, apply/logs/describe corrections).
- [unknown] No dedicated upstream changelog was found for the `alpine/k8s` image packaging itself; assessment is based on Docker Hub tag metadata and Kubernetes upstream release/changelog notes.

### Local impact

`alpine/k8s` is used in five CronJob manifests:

- `kubernetes/components/cnpg-disaster-recovery/cronjob.yaml` (updated by this PR)
- `kubernetes/components/cnpg-restore-test/cronjob.yaml` (updated by this PR)
- `kubernetes/apps/observability/k6-canaries/app/cronjob.yaml` (already on `1.36.1`)
- `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml` (still `1.34.3`)
- `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml` (still `1.34.3`)

The two changed CronJobs run `kubectl` heavily (`get`, `wait`, `exec`, `apply`, `delete`) against CNPG resources. Repo indicators show cluster tooling/version anchored around 1.34 (`talos/talenv.yaml` sets `kubernetesVersion: v1.34.4`; `.mise.toml` pins `kubectl` `1.34.0`). Kubernetes version-skew policy states kubectl is supported within one minor version of kube-apiserver; moving these jobs to `1.36.1` against a `1.34.x` cluster creates an unsupported skew with increased chance of subtle CLI/API behavior issues. Rollback is easy (manifest revert), but failed jobs can impact DR validation signal quality.

### Pre-merge checks

- [ ] Verify actual control-plane version in-cluster; if still `1.34.x`, do **not** merge `kubectl 1.36.1` (unsupported +2 minor skew).
- [ ] If merge is desired now, retarget image to a supported kubectl minor (for `1.34.x` API server: use `1.33.x` to `1.35.x` client range).
- [ ] Run the two jobs manually in a staging/safe window and confirm `kubectl wait/get/exec/apply/delete` paths still succeed for CNPG resources.
- [ ] Decide whether to align the other `alpine/k8s` CronJobs (renovate jobs) to a consistent supported minor to reduce drift.

### Evidence reviewed

- PR: `feat(container): update image alpine/k8s ( 1.34.3 ➔ 1.36.1 )`; labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff: 2 files changed, 2 additions, 2 deletions (image tag+digest update).
- Files in repo: `kubernetes/components/cnpg-disaster-recovery/cronjob.yaml`, `kubernetes/components/cnpg-restore-test/cronjob.yaml`, `kubernetes/apps/observability/k6-canaries/app/cronjob.yaml`, `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml`, `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml`, `talos/talenv.yaml`, `.mise.toml`, `README.md`.
- Upstream sources checked: `https://hub.docker.com/v2/repositories/alpine/k8s/tags?page_size=100`, `https://hub.docker.com/v2/repositories/alpine/k8s/tags/<version>`, `https://api.github.com/repos/kubernetes/kubernetes/releases/tags/v1.34.4` ... `v1.36.1`, `https://raw.githubusercontent.com/kubernetes/kubernetes/master/CHANGELOG/CHANGELOG-1.35.md`, `https://raw.githubusercontent.com/kubernetes/kubernetes/master/CHANGELOG/CHANGELOG-1.36.md`, `https://kubernetes.io/releases/version-skew-policy/`.
- Notable uncertainty: No image-maintainer changelog for `alpine/k8s` packaging was located; behavior assessment relies on upstream Kubernetes release/changelog data.
