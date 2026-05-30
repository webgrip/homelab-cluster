pr: 332

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

PR #332 updates the Trivy CLI container used by the Dependency-Track SBOM uploader CronJob from `0.69.3` to `0.70.0` and pins an image digest. Upstream 0.70.0 includes output/behavior changes that can affect SBOM content and vulnerability counting, especially CycloneDX data and detection behavior. In this repo, that can alter what gets uploaded to Dependency-Track and potentially shift security trend baselines. Merge is reasonable after a one-run functional check of the CronJob and a quick comparison of resulting findings volume.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/aquasecurity/trivy` | Docker/OCI (GHCR) | `0.69.3` → `0.70.0` (+ digest pin) | minor | runtime (security SBOM generation job) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[behavior]` | CycloneDX output now includes CVSS v4 vulnerability ratings. | [source](https://github.com/aquasecurity/trivy/issues/10313) | **Yes** — this repo runs `trivy image --format cyclonedx` in the SBOM uploader and uploads the generated SBOM to Dependency-Track (`kubernetes/apps/security/dependency-track/app/sbom-uploader/configmap.yaml`). |
| `[behavior]` | SBOM output sets `NOASSERTION` for SPDX non-library package license fields. | [source](https://github.com/aquasecurity/trivy/issues/10368) | **Yes** — repo consumes Trivy SBOM output for downstream processing in Dependency-Track/GUAC path; schema/content shifts can change downstream interpretation. |
| `[behavior]` | Vulnerability detector change: skip third-party packages in common detect function. | [source](https://github.com/aquasecurity/trivy/issues/10129) | **Yes** — likely to influence reported vulnerability totals used in Trivy-related dashboards/alerts and operational triage. |
| `[feature]` | Server JSON output includes server version metadata (client/server mode). | [source](https://github.com/aquasecurity/trivy/issues/10075) | **No** — local job executes CLI `trivy image` directly, not Trivy client/server mode. |
| `[unknown]` | 0.70.0 changelog compares `v0.69.0...v0.70.0`; exact delta from `0.69.3` is not separately summarized in release body. | [source](https://github.com/aquasecurity/trivy/blob/main/CHANGELOG.md#0700-2026-04-16) | **Unknown** — release notes are available, but the release-page summary does not provide a dedicated `0.69.3 → 0.70.0` curated migration section. |

### Local impact

The PR changes only `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml` (image tag/digest for container `upload`). That container runs `/scripts/upload.sh`, which executes `trivy image --format cyclonedx` and uploads results to Dependency-Track (`.../sbom-uploader/configmap.yaml`).

This is a security pipeline component with moderate blast radius: it is not cluster-critical runtime traffic, but it influences vulnerability inventory and policy/triage data quality. Rollback is straightforward (revert image tag), but behavior changes in generated SBOMs can affect trend continuity and downstream ingestion semantics.

### Improvement opportunities

- **`Track CVSS v4 influence in Dependency-Track policy outcomes`** — Trivy now emits CVSS v4 ratings in CycloneDX output; validate whether Dependency-Track policies can leverage these fields and tune policy thresholds if useful. [source](https://github.com/aquasecurity/trivy/issues/10313)
- **`Document expected vulnerability count shift after upgrade`** — detector behavior changed to skip third-party packages, so historical count comparisons may need a note in security runbooks/dashboard annotations. [source](https://github.com/aquasecurity/trivy/issues/10129)

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | `kubernetes/apps/observability/grafana/app/dashboards/security-trivy-sbom.yaml` and `security-trivy-compliance.yaml` visualize Trivy metrics from Trivy Operator exporters | None (immediate) | This PR updates the standalone Trivy CLI image in SBOM uploader CronJob, not Trivy Operator metric schema; no documented metric rename/removal in 0.70.0 release notes. [source](https://github.com/aquasecurity/trivy/blob/main/CHANGELOG.md#0700-2026-04-16) |
| Alert | `kubernetes/apps/security/trivy-operator/app/prometheusrule.yaml` alerts on `trivy_*` metrics | None (immediate) | Alerts target Trivy Operator metrics, while this update targets Dependency-Track SBOM uploader job image. |
| Metric / Scrape config | No scrape config tied specifically to `trivy-sbom-uploader` found; dashboards mostly query operator-generated `trivy_*` series | None | No upstream note found indicating metric cardinality/name changes for the operator path in this container bump. |

### Pre-merge checks

- [ ] Run one manual job execution of `trivy-sbom-uploader` in a non-critical window and confirm `=== Done:` summary shows expected upload success ratio (`kubernetes/apps/security/dependency-track/app/sbom-uploader/configmap.yaml`).
- [ ] Compare pre/post-upgrade vulnerability totals for a representative image set to identify expected shifts from detector behavior changes (especially third-party package handling).
- [ ] Confirm Dependency-Track accepts uploaded CycloneDX documents from Trivy 0.70.0 without parsing/policy errors.

### Follow-up

- [ ] Add a short runbook note under security supply-chain docs describing possible trend discontinuity after Trivy 0.70.0 detection/output changes. — Helps SOC/on-call interpret dashboard changes correctly. [source](https://github.com/aquasecurity/trivy/issues/10129)
- [ ] Evaluate whether to expose CVSS v4-oriented views in security reporting once Dependency-Track ingestion behavior is confirmed. — New data is present in CycloneDX output from Trivy 0.70.0. [source](https://github.com/aquasecurity/trivy/issues/10313)

### Evidence reviewed

- PR: `feat(container): update image ghcr.io/aquasecurity/trivy ( 0.69.3 ➔ 0.70.0 )`; labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 1 insertion, 1 deletion (`kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml`).
- Files in repo: `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml`, `kubernetes/apps/security/dependency-track/app/sbom-uploader/configmap.yaml`, `kubernetes/apps/security/trivy-operator/app/prometheusrule.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/security-trivy-sbom.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/security-trivy-compliance.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/security-overview.yaml`.
- Upstream sources checked: `https://github.com/aquasecurity/trivy/releases/tag/v0.70.0`, `https://github.com/aquasecurity/trivy/releases/tag/v0.69.3`, `https://github.com/aquasecurity/trivy/blob/main/CHANGELOG.md#0700-2026-04-16`, plus linked upstream issue references in that changelog section.
- Notable uncertainty: upstream release body does not provide a dedicated curated migration note specifically for `0.69.3 → 0.70.0`; assessment is based on the 0.70.0 changelog and local usage analysis.
