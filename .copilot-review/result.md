pr: 295

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR pins the existing `docker.io/alpine/git:2.49.1` image to its immutable manifest-index digest (`sha256:c0280cf…`). There is no version change — the same Git 2.49.1 binary is used before and after the merge. Digest pinning is a supply-chain security best practice that prevents tag mutation attacks. The digest has been verified against Docker Hub and matches the current `2.49.1` manifest index. Safe to merge immediately.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/alpine/git` | Docker/OCI | `2.49.1` → `2.49.1@sha256:c0280cf9572316299b08544065d3bf35db65043d5e3963982ec50647d2746e26` | digest-pin (no version change) | init-container (one-shot job) | Green |

### Important upstream changes

No version change — this is a digest pinning operation only. The image tag `2.49.1` (Git 2.49.1 on Alpine) is unchanged; only an immutable digest reference is added.

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[unknown]` | No upstream release notes apply — this is a digest pin, not an upgrade. The `2.49.1` tag was pushed to Docker Hub on 2025-11-30. | [Docker Hub tag](https://hub.docker.com/r/alpine/git/tags?name=2.49.1) | **No** — no code change, same image content |

### Local impact

The image is used exclusively in `kubernetes/apps/security/guac/app/sample-data-job.yaml` as an **init-container** (`clone-sample-data`) in a Kubernetes `Job` (`guac-sample-data`). Its sole function is a shallow `git clone` of the public `guac-data` repository into a shared `emptyDir` volume. The container is:

- Short-lived and stateless (no persistent storage).
- Already hardened: `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `runAsNonRoot: true`, `seccompProfile: RuntimeDefault`, `fsGroup` set.
- Not network-exposed.

Rolling back is trivial: remove the digest suffix from the image field and re-apply.

The verified digest `sha256:c0280cf9572316299b08544065d3bf35db65043d5e3963982ec50647d2746e26` is the **manifest-index (multi-arch) digest** for `alpine/git:2.49.1` on Docker Hub, confirmed via the Docker Hub v2 API. Architecture-specific digests: amd64 → `sha256:53a62393…`, arm64 → `sha256:03f28637…`.

### Improvement opportunities

- **Consider upgrading to `alpine/git:2.52.0`** — Docker Hub shows `2.52.0` as the latest tag (also available as `latest`). After pinning `2.49.1` with a digest, it may be worth scheduling a follow-up PR to evaluate the newer version. Note: this is advisory only; `2.49.1` has no known blocking CVEs surfaced in this review.

### Grafana dashboards and alerts

No dashboard or alert changes identified. The `alpine/git` image is used only as a one-shot init-container for data ingestion (`guac-sample-data` Job). It exposes no metrics, has no long-running processes, and is not referenced by any ServiceMonitor, PrometheusRule, or Grafana dashboard found in the repository.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Metrics / Dashboards | None found | None | `alpine/git` exposes no metrics; used only as a one-shot git clone init-container |

### Pre-merge checks

- [ ] Confirm CI passes (flux-local validation and `verify-oci-digests.sh` if applicable).
- [ ] Optionally manually verify: `docker manifest inspect docker.io/alpine/git:2.49.1@sha256:c0280cf9572316299b08544065d3bf35db65043d5e3963982ec50647d2746e26` resolves without error.

### Follow-up

- [ ] Consider upgrading `alpine/git` from `2.49.1` to `2.52.0` (latest on Docker Hub) in a separate PR — newer Git versions include bug fixes and minor improvements. Link: [Docker Hub alpine/git tags](https://hub.docker.com/r/alpine/git/tags).

### Evidence reviewed

- PR: "chore(container): pin image docker.io/alpine/git to c0280cf" — labels: `area/kubernetes`, `renovate/container`, `dependencies` — diff: 1 file changed, tag `2.49.1` → `2.49.1@sha256:c0280cf…` in `kubernetes/apps/security/guac/app/sample-data-job.yaml`.
- Files in repo: `kubernetes/apps/security/guac/app/sample-data-job.yaml` (only occurrence of `alpine/git`).
- Upstream sources checked: [Docker Hub v2 API — alpine/git:2.49.1](https://hub.docker.com/v2/repositories/alpine/git/tags/2.49.1) — digest confirmed; [alpine-docker/git GitHub repo](https://github.com/alpine-docker/git) — no GitHub releases published.
- Notable uncertainty: Alpine-docker/git publishes no formal changelog or release notes; the image simply tracks official Git releases on Alpine Linux. No CVE data was checked against the `2.49.1` Alpine/Git combination — standard practice would be to rely on Trivy/Grype scanning in CI if present.
