pr: 131

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates the bootstrap Helm chart source for cert-manager from `v1.19.3` to `v1.20.2` in a single file. Upstream releases between these versions include security-related dependency bumps (notably in `v1.19.4`/`v1.19.5`) plus feature and behavior changes introduced in `v1.20.0`. The primary local risk driver is that cert-manager is a critical PKI component, but in this repository the changed pin is in bootstrap Helmfile logic while Flux-managed runtime manifests currently pin `v1.19.5` separately. Merge is reasonable after confirming bootstrap behavior is still valid for recovery/bootstrap workflows.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `quay.io/jetstack/charts/cert-manager` | OCI Helm chart | `v1.19.3 → v1.20.2` | minor | infra / deploy (bootstrap PKI installation) | Yellow |

### Important upstream changes

- [security] `v1.19.4` is described upstream as a patch release fixing reported vulnerabilities, including CVE-2026-24051 and CVE-2025-68121.
- [security] `v1.19.5` is described as a patch release with additional vulnerability-related Go/dependency bumps.
- [feature] `v1.20.0` introduces new functionality (e.g., ListenerSet alpha support, Azure Private DNS support, Gateway API-related changes) and Helm chart value additions.
- [behavior] `v1.20.1` fixes a duplicate `parentRef` bug and OpenShift-related upgrade issue tied to finalizer RBAC.
- [bugfix] `v1.20.2` fixes invalid Helm chart YAML generation when both `webhook.config` and `webhook.volumes` are set.

### Local impact

The PR changes only `bootstrap/helmfile.d/01-apps.yaml` (`cert-manager` chart version pin). This affects bootstrap/restore installation flow rather than the ongoing Flux-managed runtime deployment path. Runtime cert-manager in-cluster is sourced from `kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml`, which is currently pinned to `v1.19.5` with digest, and consumed by `kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml` via Flux. cert-manager is still high-importance because it underpins certificate issuance and is referenced by ingress/networking and observability runbooks, but blast radius of this exact PR is mostly bootstrap-time unless additional Flux pins are updated separately.

### Pre-merge checks

- [ ] Confirm maintainers intend this PR to update bootstrap-only cert-manager and not the Flux runtime pin (`kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml`).
- [ ] Validate bootstrap rendering/install path for cert-manager with this chart version (at minimum: Helmfile/template success for `bootstrap/helmfile.d/01-apps.yaml`).
- [ ] If doing full bootstrap rehearsal, verify cert-manager pods become Ready and ClusterIssuer health checks pass post-install.

### Evidence reviewed

- PR: `feat(container): update image quay.io/jetstack/charts/cert-manager ( v1.19.3 ➔ v1.20.2 )`; labels: `area/bootstrap`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 1 line version bump in bootstrap Helmfile.
- Files in repo: `bootstrap/helmfile.d/01-apps.yaml`, `bootstrap/helmfile.d/templates/values.yaml.gotmpl`, `kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml`, `kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml`, `kubernetes/apps/cert-manager/cert-manager/ks.yaml`.
- Upstream sources checked: `https://github.com/cert-manager/cert-manager/releases/tag/v1.19.4`, `https://github.com/cert-manager/cert-manager/releases/tag/v1.19.5`, `https://github.com/cert-manager/cert-manager/releases/tag/v1.20.0`, `https://github.com/cert-manager/cert-manager/releases/tag/v1.20.1`, `https://github.com/cert-manager/cert-manager/releases/tag/v1.20.2`, plus GitHub API PR endpoints for `webgrip/homelab-cluster#131`.
- Notable uncertainty: Release notes were reviewed at cert-manager project-release level; no separate chart-only changelog was identified for this exact OCI chart path beyond those release notes.
