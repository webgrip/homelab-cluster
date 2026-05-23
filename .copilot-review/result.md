pr: 181

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR updates both `flux-operator` and `flux-instance` Helm charts from `0.49.0` to `0.50.0` (minor version bump) in `bootstrap/helmfile.d/01-apps.yaml`. The v0.50.0 release contains no breaking changes — it extends OpenShift v4.21 compatibility, hardens the CI release pipeline, swaps the OLM base image to `ubi8-micro`, bumps dependencies, and sets a 2-week npm min release age for the web component. None of these changes affect non-OpenShift Kubernetes deployments. Notably, the GitOps-managed OCIRepository manifests in `kubernetes/apps/flux-system/` already reference `0.50.0` with pinned digests, so the cluster may already be running this version via the Flux reconciliation path.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/controlplaneio-fluxcd/charts/flux-operator` | OCI Helm chart | `0.49.0 → 0.50.0` | minor | bootstrap + GitOps infra (manages Flux controllers) | 🟢 Low |
| `ghcr.io/controlplaneio-fluxcd/charts/flux-instance` | OCI Helm chart | `0.49.0 → 0.50.0` | minor | bootstrap + GitOps infra (deploys Flux components) | 🟢 Low |

### Important upstream changes

All changes are from the [v0.50.0 release](https://github.com/controlplaneio-fluxcd/flux-operator/releases/tag/v0.50.0):

- [feature] Extend OLM compatibility to OpenShift v4.21 — no impact on vanilla Kubernetes ([#861](https://github.com/controlplaneio-fluxcd/flux-operator/pull/861))
- [feature] CI release pipeline hardening — supply-chain improvement, no operational impact ([#870](https://github.com/controlplaneio-fluxcd/flux-operator/pull/870))
- [behavior] Change OLM base image to `ubi8-micro` — smaller attack surface for the OLM-flavoured image; does not affect standard Kubernetes deployments ([#864](https://github.com/controlplaneio-fluxcd/flux-operator/pull/864))
- [bugfix] Set npm minimum release age to 2 weeks for web component — dependency hygiene improvement ([#869](https://github.com/controlplaneio-fluxcd/flux-operator/pull/869))
- [feature] Dependency bumps (Go modules, CLI tools, GitHub Actions) — no user-facing behavioral changes ([#873](https://github.com/controlplaneio-fluxcd/flux-operator/pull/873), [#866](https://github.com/controlplaneio-fluxcd/flux-operator/pull/866), [#872](https://github.com/controlplaneio-fluxcd/flux-operator/pull/872))

No breaking changes, no CRD schema changes, no API removals, and no migration steps were mentioned in the release notes.

### Local impact

**Files referencing these charts:**

- `bootstrap/helmfile.d/01-apps.yaml` — the only file changed in this PR; used to bootstrap the cluster before Flux takes over. Both `flux-operator` (depends on `cert-manager/cert-manager`) and `flux-instance` (depends on `flux-system/flux-operator`) are installed here.
- `kubernetes/apps/flux-system/flux-operator/app/ocirepository.yaml` — already pinned to `0.50.0` with digest `sha256:901a00064286b446e723bc145f015470424551ea2ddd8714058eb56fc53d4939`
- `kubernetes/apps/flux-system/flux-instance/app/ocirepository.yaml` — already pinned to `0.50.0` with digest `sha256:30693bb721871eaf9ca35bd7c9364b774783e5cf564c55450e8cf0552721a618`
- `kubernetes/apps/flux-system/flux-operator/app/helmrelease.yaml` — HelmRelease with `serviceMonitor.create: true`
- `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml` — HelmRelease with detailed FluxInstance configuration including custom kustomize patches, SOPS age integration, and tuned resource limits

**Assessment:** The OCIRepository manifests in the GitOps path are already targeting `0.50.0` with pinned digest references, indicating this version has already been vetted or is already running in the cluster. This PR only aligns the bootstrap helmfile to match. The `flux-instance` HelmRelease uses several custom kustomize patches and the `--sops-age-secret=sops-age` flag — none of these are affected by v0.50.0 changes. Rollback is straightforward: revert the version bump in `bootstrap/helmfile.d/01-apps.yaml` and re-run the bootstrap procedure.

### Pre-merge checks

- [ ] Confirm that `kubernetes/apps/flux-system/flux-operator/app/ocirepository.yaml` and `flux-instance/app/ocirepository.yaml` are already reconciled successfully at `0.50.0` (i.e. the GitOps path is already healthy at this version).
- [ ] Verify that `flux-operator` and `flux-instance` pods are Running and Ready in the cluster before merging (since the GitOps path may have already applied the update).
- [ ] If re-bootstrapping the cluster from scratch is planned, confirm the `0.50.0` chart OCI images are reachable from `ghcr.io`.

### Evidence reviewed

- **PR:** "feat(container): update flux-operator group ( 0.49.0 ➔ 0.50.0 )" — labels: `area/bootstrap`, `renovate/container`, `type/minor`, `dependencies`; 2 additions, 2 deletions in 1 file
- **Files in repo:** `bootstrap/helmfile.d/01-apps.yaml`, `kubernetes/apps/flux-system/flux-operator/app/{ocirepository,helmrelease}.yaml`, `kubernetes/apps/flux-system/flux-instance/app/{ocirepository,helmrelease}.yaml`
- **Upstream sources checked:** [GitHub Releases API for v0.50.0](https://api.github.com/repos/controlplaneio-fluxcd/flux-operator/releases/tags/v0.50.0), [GitHub compare v0.49.0...v0.50.0](https://github.com/controlplaneio-fluxcd/flux-operator/compare/v0.49.0...v0.50.0)
- **Notable uncertainty:** None — release notes are complete and clearly enumerate all changes; no breaking changes identified.
