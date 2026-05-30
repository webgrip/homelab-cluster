pr: 309

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR adds a SHA-256 digest pin to the existing `ghcr.io/guacsec/guac:v1.0.1` image tag used in two Kubernetes Jobs/CronJobs. The image version does not change; only supply-chain provenance is strengthened. No new code is executed, no configuration changes, and no behavioral differences are introduced. This is a safe, recommended security hardening change.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/guacsec/guac` | Docker/OCI (GHCR) | `v1.0.1` → `v1.0.1@sha256:34ca3dc7d5a21340904f753fd2483b1a4305e8223a6969f315b6bf7e2fb27d3e` | digest pin (no version change) | runtime (batch job / cronjob) | Green |

### Important upstream changes

No upstream changes — this is a digest pin of the already-deployed `v1.0.1` tag. No new application code is introduced.

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[unknown]` | v1.0.1 release notes consist entirely of CI/dependency bumps and minor fixes; no application-level behavioral changes were noted | [v1.0.1 release](https://github.com/guacsec/guac/releases/tag/v1.0.1) | **No** — no version change, digest pin only |

### Local impact

The image `ghcr.io/guacsec/guac:v1.0.1` is used in exactly two places in this repository:

- **`kubernetes/apps/security/guac/app/s3-collector.yaml`** — A `CronJob` running daily at 05:00 UTC that executes `guaccollect s3` to scan the Garage S3 bucket for Trivy-generated CycloneDX SBOMs and ingest them into the GUAC dependency graph. Credentials are sourced from the `security-s3` Secret.
- **`kubernetes/apps/security/guac/app/sample-data-job.yaml`** — A one-shot `Job` that ingests sample GUAC data from `guacsec/guac-data` into the GraphQL server for bootstrapping/demo purposes.

Both workloads are **batch** (not long-running services), stateless with respect to local disk, and access only the GUAC GraphQL API and S3 — no persistent volumes are mounted by these containers. Rollback is trivial: revert the digest suffix from the image field.

Note: The GUAC HelmRelease (`helmrelease.yaml`, chart `guac` v0.8.0) deploys the main GUAC services (GraphQL server, REST API, collectors, visualizer) and is **not** covered by this PR — its image is managed by the Helm chart directly. Only the two supplemental batch workloads are pinned here.

### Improvement opportunities

- **Pin the Helm chart image tags too** — The `guac` HelmRelease (chart 0.8.0) likely pulls `ghcr.io/guacsec/guac` for its main service containers. Those image references are controlled by the chart and are not digest-pinned. Consider using Renovate's `pinDigests` strategy for the HelmRelease as well, or tracking the chart's bundled image digest via a post-render patch.

### Grafana dashboards and alerts

The GUAC HelmRelease enables `deployServiceMonitor: true`, meaning Prometheus scrapes GUAC metrics. No Grafana dashboard JSON files or PrometheusRule manifests referencing GUAC metrics were found in this repository.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| ServiceMonitor | `guac.observability.deployServiceMonitor: true` in helmrelease.yaml | None required by this PR | Digest pin does not affect metrics endpoints or label cardinality |

No dashboard or alert changes identified for this digest-pin update.

### Pre-merge checks

- [ ] Confirm the digest `sha256:34ca3dc7d5a21340904f753fd2483b1a4305e8223a6969f315b6bf7e2fb27d3e` resolves to the `v1.0.1` tag on GHCR: `docker manifest inspect ghcr.io/guacsec/guac:v1.0.1` and verify the digest matches.
- [ ] Verify `./scripts/verify-oci-digests.sh` (the repo's standard OCI digest check, also run in the `flux-local` CI workflow) passes against the updated manifests.

### Follow-up

- [ ] Consider pinning images for the main GUAC HelmRelease components — the supplemental batch Jobs are now pinned but the primary Helm-managed deployments are not. — improves supply-chain security parity across all GUAC workloads.
- [ ] Consider upgrading from GUAC v1.0.1 to v1.1.0 (released 2026-03-13) — includes a Kubescape collector, REST spec improvements, and various dependency security bumps. [v1.1.0 release notes](https://github.com/guacsec/guac/releases/tag/v1.1.0)

### Evidence reviewed

- **PR:** "chore(container): pin image ghcr.io/guacsec/guac to 34ca3dc" — labels: `area/kubernetes`, `renovate/container`, `dependencies` — diff: +2/-2 lines across 2 files, adding `@sha256:` suffix to existing `v1.0.1` tag references.
- **Files in repo:** `kubernetes/apps/security/guac/app/s3-collector.yaml`, `kubernetes/apps/security/guac/app/sample-data-job.yaml`, `kubernetes/apps/security/guac/app/helmrelease.yaml`, `kubernetes/apps/security/guac/ks.yaml`
- **Upstream sources checked:** [GUAC GitHub releases API](https://api.github.com/repos/guacsec/guac/releases), [v1.0.1 release](https://github.com/guacsec/guac/releases/tag/v1.0.1)
- **Notable uncertainty:** The full SHA-256 digest was not independently verified against a live GHCR API call (network access to ghcr.io not available in this environment); the pre-merge check above addresses this.
