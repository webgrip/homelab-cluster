pr: 267

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR updates the Stakater Reloader Helm chart from `2.2.11` to `2.2.12` (patch release) and also bumps the digest for the CoreDNS chart at the same tag `1.45.2`. The primary driver for the Reloader update is a **vulnerable Go dependency fix** (supply-chain security improvement), a hardened UBI9 base image, and a CI/CD supply-chain hardening change upstream. No breaking changes, API changes, or configuration changes were found. This is safe to merge.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/stakater/charts/reloader` | OCI Helm chart | `2.2.11 → 2.2.12` (digest pinned) | patch | runtime / kube-system cluster operator | 🟢 Green |
| `ghcr.io/coredns/charts/coredns` | OCI Helm chart | `1.45.2` digest refresh only | digest | runtime / kube-system DNS | 🟢 Green |

### Important upstream changes

Changes in `chart-v2.2.11 → chart-v2.2.12` (app version `v1.4.16 → v1.4.17`):

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[security]` | Bump vulnerable Go dependency | [PR #1151](https://github.com/stakater/Reloader/pull/1151) | **Yes** — the runtime binary ships in the chart image; this fix is applied by accepting this update |
| `[security]` | Harden GitHub Actions workflows against cache poisoning | [PR #1149](https://github.com/stakater/Reloader/pull/1149) | **No** — this is an upstream CI/build hygiene change; affects supply-chain integrity of the released artifact, not local cluster config |
| `[feature]` | Update UBI9 base image to `v9.8-1779374378` | [PR #1152](https://github.com/stakater/Reloader/pull/1152) | **Yes** — base image refreshed; reduces exposure to OS-level CVEs in the running container |
| `[bugfix]` | README revisions and doc cleanups | [PR #1136](https://github.com/stakater/Reloader/pull/1136), [PR #1138](https://github.com/stakater/Reloader/pull/1138), [PR #1140](https://github.com/stakater/Reloader/pull/1140) | **No** — documentation only |
| `[bugfix]` | Update `pull_request.yaml` CI config | [PR #1142](https://github.com/stakater/Reloader/pull/1142) | **No** — upstream CI change only |

No breaking changes, removed flags, API changes, or chart value schema changes were found between `2.2.11` and `2.2.12`.

### Local impact

Reloader is deployed into `kube-system` via a Flux `OCIRepository` + `HelmRelease`. It is configured with:
- `reloader.readOnlyRootFileSystem: true` — hardened pod security; no change needed.
- `reloader.podMonitor.enabled: true` — a `PodMonitor` is created for scraping metrics.

Relevant files:
- `kubernetes/apps/kube-system/reloader/app/ocirepository.yaml` — tag and digest pinned (updated in this PR).
- `kubernetes/apps/kube-system/reloader/app/helmrelease.yaml` — chart values; unchanged and no action needed.
- `kubernetes/apps/kube-system/reloader/ks.yaml` — Flux Kustomization targeting `kube-system`.

Reloader watches for `ConfigMap`/`Secret` annotation changes and triggers rolling restarts of referencing `Deployment`/`DaemonSet`/`StatefulSet` resources. It is a lightweight, non-stateful operator with no persistent storage. Rollback is trivial: revert the tag and digest in `ocirepository.yaml`.

The CoreDNS digest refresh is a no-op for the running workload — same chart version `1.45.2`, only the OCI digest was updated (likely a layer rebuild). This carries zero application risk.

### Improvement opportunities

- **Review the specific vulnerable Go dependency fixed in PR #1151** — the release notes do not name the CVE or package. If you run container image scanning (e.g., Trivy/Grype), confirm that the new image resolves the finding before merging if a known CVE is tracked. [PR #1151](https://github.com/stakater/Reloader/pull/1151)

### Grafana dashboards and alerts

The HelmRelease enables `podMonitor.enabled: true`, so Reloader exposes a `PodMonitor` in `kube-system`. No Grafana dashboards or Prometheus alert rules referencing Reloader metrics were found in the repository.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| PodMonitor (Reloader metrics) | `reloader.podMonitor.enabled: true` in `helmrelease.yaml` | None | No metrics schema changes in this patch release |

No dashboard or alert changes identified for this update.

### Pre-merge checks

- [ ] Confirm Flux reconciliation of the `reloader` HelmRelease succeeds after merge (`flux get helmreleases -n kube-system`).
- [ ] Optionally verify the new image digest resolves the Go vulnerability flagged in [PR #1151](https://github.com/stakater/Reloader/pull/1151) if you maintain a CVE tracking process.

### Follow-up

- [ ] **Identify the specific Go vulnerability fixed** — [PR #1151](https://github.com/stakater/Reloader/pull/1151) does not name the CVE; check `ghcr.io/stakater/reloader:v1.4.17` with Trivy/Grype for confirmation this resolves any tracked findings.

### Evidence reviewed

- **PR:** `fix(container): update image ghcr.io/stakater/charts/reloader ( 2.2.11 ➔ 2.2.12 )` — labels: `area/kubernetes`, `renovate/container`, `type/patch`, `dependencies`; diff: 2 files, 4 changed lines (tag + digest in reloader OCI, digest in coredns OCI)
- **Files in repo:** `kubernetes/apps/kube-system/reloader/app/ocirepository.yaml`, `kubernetes/apps/kube-system/reloader/app/helmrelease.yaml`, `kubernetes/apps/kube-system/reloader/app/kustomization.yaml`, `kubernetes/apps/kube-system/reloader/ks.yaml`, `kubernetes/apps/kube-system/coredns/app/ocirepository.yaml`
- **Upstream sources checked:** `https://api.github.com/repos/stakater/Reloader/releases` — release `chart-v2.2.12` full changelog; individual upstream PRs #1136, #1138, #1140, #1142, #1149, #1151, #1152, #1155 at `github.com/stakater/Reloader`
- **Notable uncertainty:** The exact Go package and CVE resolved by [PR #1151](https://github.com/stakater/Reloader/pull/1151) was not disclosed in the release notes. The risk assessment treats this as a security fix that is worth shipping but low in blast radius given the narrow scope of the operator.
