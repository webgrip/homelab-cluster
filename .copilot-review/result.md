pr: 131

---
## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** High

### Executive summary

This PR bumps the **bootstrap Helmfile** copy of the cert-manager Helm chart from `v1.19.3` to `v1.20.2`. Upstream release notes are clear and include multiple security fixes plus a few behavior changes, but the main repo-specific risk is that bootstrap now points at `v1.20.2` while the Flux-managed OCI source in `kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml` is still pinned to `v1.19.5`. Merge is reasonable if maintainers confirm that bootstrap/runtime drift is intentional and that a fresh bootstrap still produces a healthy cert-manager + ClusterIssuer.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `quay.io/jetstack/charts/cert-manager` | Helm OCI chart | `v1.19.3` → `v1.20.2` | minor | bootstrap / infra / PKI | Yellow |

### Important upstream changes

- [security] `v1.19.4` is a patch release explicitly fixing reported vulnerabilities, notably **CVE-2026-24051** and **CVE-2025-68121**.
- [security] `v1.20.0` fixes a potential cert-manager controller panic / denial-of-service path when malformed DNS responses are cached, and also updates Go to address reported CVEs.
- [behavior] `v1.20.0` changes the default container user/group from `1000:0` to `65532:65532`; that can matter if a deployment relies on writable mounted paths or custom security context assumptions.
- [behavior] `v1.20.0` normalizes the Prometheus metrics label to `cert-manager` when monitoring is enabled.
- [feature] `v1.20.0` adds several chart features (for example `extraContainers`, `startupapicheck-job.imagePullSecrets`, broader NetworkPolicy controls), but I found no local use of those new values in this repo.
- [bugfix] `v1.20.1` fixes an OpenShift upgrade/RBAC issue and a Gateway API duplicate `parentRef` bug; the OpenShift-specific fix does not appear directly relevant to this Talos-based cluster.
- [bugfix] `v1.20.2` fixes invalid Helm chart YAML when both `webhook.config` and `webhook.volumes` are set. I did not find those values in local cert-manager configuration, so that specific bugfix does not look like a direct driver here.

### Local impact

The changed file is `bootstrap/helmfile.d/01-apps.yaml`, which Helmfile uses during cluster bootstrap via `scripts/bootstrap-apps.sh` and `.taskfiles/bootstrap/Taskfile.yaml`. That bootstrap flow does **not** maintain its own cert-manager values; `bootstrap/helmfile.d/templates/values.yaml.gotmpl` imports the live values from `kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml`, where this repo enables CRDs, a single replica, DNS01 recursive nameservers, and Prometheus ServiceMonitor support.

Operationally, cert-manager is a cluster-wide PKI component here: `kubernetes/apps/cert-manager/cert-manager/app/clusterissuer.yaml` defines the `letsencrypt-production` `ClusterIssuer`, and `kubernetes/apps/network/envoy-gateway/app/certificate.yaml` consumes that issuer for the wildcard/domain certificate used by Envoy. That makes bootstrap breakage noticeable even though the PR is labeled `area/bootstrap` and does not directly change the steady-state Flux manifests.

The biggest repo-local concern is version alignment: the Flux-managed source in `kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml` is still pinned to `tag: v1.19.5` with a digest. If bootstrap installs `v1.20.2` but Flux later reconciles `v1.19.5`, a newly bootstrapped cluster could see cert-manager version drift or an immediate downgrade once Flux takes over. I did not find local use of `webhook.config`, `webhook.volumes`, extra sidecars, or custom writable volume settings that would make the new chart behavior an obvious incompatibility.

### Pre-merge checks

- [ ] Confirm whether bootstrap is intentionally allowed to diverge from `kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml` (`v1.19.5`). If not, align the Flux OCIRepository tag/digest in a follow-up or split the change.
- [ ] Render or dry-run the bootstrap path with the existing imported values (`bootstrap/helmfile.d/01-apps.yaml` + `bootstrap/helmfile.d/templates/values.yaml.gotmpl`) to ensure cert-manager `v1.20.2` still templates cleanly.
- [ ] After bootstrap/reconcile in a test or real cluster, verify `kubectl -n cert-manager get pods` shows healthy controller/webhook/startup jobs and `kubectl get clusterissuer letsencrypt-production` remains `Ready=True`.
- [ ] Verify at least one cert issuance/renewal path still works for the Envoy wildcard certificate defined in `kubernetes/apps/network/envoy-gateway/app/certificate.yaml`.
- [ ] Check observability after rollout to make sure cert-manager metrics and alerts still appear as expected, since upstream changed metrics label behavior in `v1.20.0`.

### Evidence reviewed

- PR: `feat(container): update image quay.io/jetstack/charts/cert-manager ( v1.19.3 ➔ v1.20.2 )`; labels `area/bootstrap`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, +1/-1.
- Files in repo: `bootstrap/helmfile.d/01-apps.yaml`, `bootstrap/helmfile.d/templates/values.yaml.gotmpl`, `scripts/bootstrap-apps.sh`, `.taskfiles/bootstrap/Taskfile.yaml`, `kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml`, `kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml`, `kubernetes/apps/cert-manager/cert-manager/app/clusterissuer.yaml`, `kubernetes/apps/network/envoy-gateway/app/certificate.yaml`, `docs/techdocs/docs/runbooks/cert-manager.md`, `README.md`.
- Upstream sources checked: https://github.com/cert-manager/cert-manager/releases/tag/v1.19.4, https://github.com/cert-manager/cert-manager/releases/tag/v1.20.0, https://github.com/cert-manager/cert-manager/releases/tag/v1.20.1, https://github.com/cert-manager/cert-manager/releases/tag/v1.20.2
- Notable uncertainty: I could not execute the repo's documented `task verify-oci-digests` target because the `task` CLI is not installed in this sandbox, and `helmfile` is also unavailable here, so I could not render the bootstrap Helmfile locally.
---
