pr: 159

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates `docker.io/alpine/k8s` in two Renovate operator CronJobs from `1.34.3` to `1.36.0`, with digest pinning retained. The local blast radius is limited to Renovate maintenance jobs (`github-app-token` and `job-cleanup`), but this is still a cross-minor jump in a bundled Kubernetes tooling image. Upstream per-tag release notes for `alpine/k8s` are not published, which raises uncertainty about bundled tool changes between skipped versions. Recommended action is to merge after quick functional checks of the two jobs.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/alpine/k8s` | Docker/OCI image | `1.34.3@sha256:f7dbea...` → `1.36.0@sha256:c105e4...` | minor (cross-minor) | infra/operations runtime (CronJobs in `renovate` namespace) | Yellow |

### Important upstream changes

- [behavior] Docker Hub tags show all intermediate versions exist and this PR skips multiple tags (`1.34.4`, `1.34.5`, `1.35.0`-`1.35.4`) before landing on `1.36.0`.
- [behavior] Tag metadata confirms image remains multi-arch (`amd64`, `arm64`) and digest-pinned.
- [unknown] `alpine/k8s` does not publish structured per-tag release notes; upstream points to a generic repo/description only, so exact per-version tool deltas are not fully attributable from official tag notes.
- [feature] Upstream source repo commit history in the update window includes removal of `helm-push` plugin support (`#83 - remove helm-push`), indicating tool-bundle contents can change independently of Kubernetes version tag.
- [migration] Kubernetes upstream release pages for `v1.35.0` and `v1.36.0` point to large changelog documents; because this container bundles multiple CLIs, kubectl minor upgrades may include CLI/output behavior changes relevant to scripts.

### Local impact

This dependency is used directly in:

- `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml`
- `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml`

Both jobs execute `kubectl` in shell scripts and run with restricted security contexts (`runAsNonRoot`, dropped capabilities, read-only root filesystem) and namespaced service accounts. The update can impact Renovate operational automation (token secret refresh and stale job cleanup) rather than application data paths. Rollback is straightforward via Git revert, but a silent CLI behavior change could break job commands until observed in logs. Additional context: other repo CronJobs already run `alpine/k8s:1.36.1`, which lowers compatibility concern for cluster/runtime basics.

### Pre-merge checks

- [ ] Confirm CI passes for this PR (especially Flux Local test/diff workflow).
- [ ] After deploy, verify `CronJob/renovate-github-app-token` next run succeeds and refreshes `Secret/renovate-runtime-token` in namespace `renovate`.
- [ ] After deploy, verify `CronJob/renovate-job-cleanup` run completes successfully and can list/delete old jobs with current RBAC.
- [ ] Spot-check job logs for `kubectl` parsing/flag regressions (`kubectl get jobs ... -o go-template`, `kubectl create secret ... --dry-run=client -o yaml | kubectl apply -f -`).
- [ ] If failures occur, rollback to previous digest-pinned image (`1.34.3@sha256:f7dbea...`) and inspect upstream image/tooling delta.

### Evidence reviewed

- PR: `feat(container): update image docker.io/alpine/k8s ( 1.34.3 ➔ 1.36.0 )`; labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 2 files changed, 2 additions, 2 deletions.
- Files in repo: `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml`, `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml`, plus existing `alpine/k8s` usages in `kubernetes/apps/observability/k6-canaries/app/cronjob.yaml`, `kubernetes/components/cnpg-disaster-recovery/cronjob.yaml`, `kubernetes/components/cnpg-restore-test/cronjob.yaml`.
- Upstream sources checked: `https://hub.docker.com/v2/repositories/alpine/k8s`, `https://hub.docker.com/v2/repositories/alpine/k8s/tags?page_size=100`, `https://github.com/alpine-docker/k8s`, `https://github.com/alpine-docker/k8s/commits/main`, `https://github.com/kubernetes/kubernetes/releases/tag/v1.35.0`, `https://github.com/kubernetes/kubernetes/releases/tag/v1.36.0`, `https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.35.md`, `https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.36.md`.
- Notable uncertainty: No authoritative per-tag release notes from `alpine/k8s`; mapping exact image tag contents to specific upstream repo commits is incomplete.
