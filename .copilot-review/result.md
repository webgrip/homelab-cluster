pr: 308

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR adds a SHA-256 digest pin to an already-deployed `ghcr.io/aquasecurity/trivy:0.69.3` image reference. The software version is unchanged; only immutability is added. No new code, no behaviour change, and no breaking changes are introduced. This is a supply-chain hardening improvement and is safe to merge.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/aquasecurity/trivy` | Docker/OCI | `0.69.3` → `0.69.3@sha256:bcc376de…` (digest pin only) | digest | runtime (CronJob container) | Green |

### Important upstream changes

No version change is being made — the tag remains `0.69.3`. A digest pin does not update the software; it locks the pull to an immutable layer hash.

For completeness, `v0.69.3` was released on 2026-03-03 and contains only one notable change:

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[bugfix]` | Bump `github.com/go-git/go-git/v5` from 5.16.4 → 5.16.5 (security backport) | [#10291](https://github.com/aquasecurity/trivy/pull/10291) | **No** — this repo does not use the go-git code path; Trivy is invoked via the `trivy image` CLI to scan OCI images, not git repositories. |

No breaking changes, no migration steps, and no config changes are needed.

### Local impact

Trivy is used in a single file:

- **`kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml`** — a `batch/v1` CronJob scheduled `0 2 * * *` (daily at 02:00 UTC). It runs `trivy image --format cyclonedx` on every running cluster image (gathered by an `alpine/k8s` initContainer), then uploads the CycloneDX SBOMs to Dependency Track and optionally to an S3 bucket for GUAC.

The digest pin means Kubernetes will refuse to run a tag-overwritten image (e.g., if `0.69.3` were repointed to a different layer on `ghcr.io`). The workload is a non-privileged batch job with no persistent state; rollback is trivial by reverting the manifest. There is no elevated privilege or network exposure introduced by this change.

### Improvement opportunities

- **Adopt digest pinning for `docker.io/alpine/k8s:1.36.1`** — the initContainer in the same CronJob uses a floating tag without a digest. Applying the same pinning strategy to this image would make the entire job supply-chain-immutable. Renovate can manage this automatically once the image is added to the `pinDigests` policy.

### Grafana dashboards and alerts

The PR does not change metrics, metrics labels, or Trivy Operator configuration. The dashboards and recording rules in this repo that reference Trivy metrics are for the separate **trivy-operator** Helm release, not for the direct `ghcr.io/aquasecurity/trivy` CLI image used in this CronJob.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard — `security-trivy-compliance.yaml` | Trivy Operator metrics | None | Not affected by this PR; image version unchanged |
| Dashboard — `security-trivy-sbom.yaml` | SBOM upload metrics | None | Not affected by this PR |
| PrometheusRule — `trivy-operator/app/prometheusrule.yaml` | Trivy Operator alerts | None | Not affected by this PR |

No dashboard or alert changes are needed.

### Pre-merge checks

- [ ] Confirm that `sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c` resolves successfully from `ghcr.io` (e.g., `docker manifest inspect ghcr.io/aquasecurity/trivy:0.69.3@sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c`). Renovate fetches this at PR creation time, so it should be valid, but a quick sanity check eliminates any transient registry issue.
- [ ] Verify CI / flux-local checks pass (OCI digest verification script `./scripts/verify-oci-digests.sh`).

### Follow-up

- [ ] Pin `docker.io/alpine/k8s:1.36.1` in the same CronJob with a SHA-256 digest — `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml` line 40. This makes the entire job supply-chain-immutable, consistent with what this PR does for the `trivy` container.

### Evidence reviewed

- **PR**: "chore(container): pin image ghcr.io/aquasecurity/trivy to bcc376d" — labels: `area/kubernetes`, `renovate/container`, `dependencies`. Diff: 1 file, 1 addition, 1 deletion (digest appended to existing tag).
- **Files in repo**: `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml` (only occurrence of this image).
- **Upstream sources checked**: GitHub Releases API `https://api.github.com/repos/aquasecurity/trivy/releases/tags/v0.69.3` — confirms v0.69.3 release notes (one dependency-bump bugfix).
- **Notable uncertainty**: None. Digest pinning carries no semantic risk; this is a mechanical supply-chain hardening change.
