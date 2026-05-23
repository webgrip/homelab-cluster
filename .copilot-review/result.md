pr: 190

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** High

### Executive summary

This PR updates the external-dns Helm chart artifact used during bootstrap CRD extraction from `1.20.0` to `1.21.1`. Upstream chart changes are mostly additive/fixes, but this chart version also updates the bundled ExternalDNS app image to `v0.21.0`, which includes several upstream breaking changes in the controller release train. In this repo, external-dns is a production DNS controller (Cloudflare + Gateway API + CRD sources), so behavior drift has high operational impact even if chart values are unchanged. I recommend merging after targeted runtime checks focused on Gateway API source behavior and Cloudflare reconciliation.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/home-operations/charts-mirror/external-dns` | Helm OCI chart | `1.20.0 → 1.21.1` | minor | infra / deploy / runtime DNS automation | Yellow |

### Important upstream changes

- [feature] Chart `v1.21.1` adds `.sourceNamespace` for namespaced installs, useful for scoped source watching ([kubernetes-sigs/external-dns#6297](https://github.com/kubernetes-sigs/external-dns/pull/6297)).
- [feature] Chart `v1.21.1` adds Gateway API ListenerSet support ([kubernetes-sigs/external-dns#6381](https://github.com/kubernetes-sigs/external-dns/pull/6381)).
- [bugfix] Chart `v1.21.1` fixes namespaced RBAC behavior for Gateway API sources when `gatewayNamespace` is set ([kubernetes-sigs/external-dns#5843](https://github.com/kubernetes-sigs/external-dns/pull/5843)).
- [bugfix] Chart `v1.21.1` fixes container args string handling (relevant because this repo passes multiple `extraArgs`) ([kubernetes-sigs/external-dns#6264](https://github.com/kubernetes-sigs/external-dns/pull/6264), [kubernetes-sigs/external-dns#6284](https://github.com/kubernetes-sigs/external-dns/pull/6284)).
- [behavior] Chart `v1.21.1` updates the app image to ExternalDNS `v0.21.0` ([kubernetes-sigs/external-dns#6354](https://github.com/kubernetes-sigs/external-dns/pull/6354), [release v0.21.0](https://github.com/kubernetes-sigs/external-dns/releases/tag/v0.21.0)).
- [breaking] ExternalDNS `v0.21.0` migrates Gateway/HTTPRoute source handling to Gateway API `v1` ([kubernetes-sigs/external-dns#6291](https://github.com/kubernetes-sigs/external-dns/pull/6291)).
- [behavior] ExternalDNS `v0.21.0` adds Cloudflare batch API support and includes Cloudflare pagination fixes, which can change request/reconciliation patterns ([kubernetes-sigs/external-dns#6208](https://github.com/kubernetes-sigs/external-dns/pull/6208), [kubernetes-sigs/external-dns#5986](https://github.com/kubernetes-sigs/external-dns/pull/5986)).
- [unknown] No `1.21.0` chart release is published in ArtifactHub version history (sequence goes `1.20.0` → `1.21.1`), so there is no separate intermediate chart release note to review ([ArtifactHub package metadata](https://artifacthub.io/packages/helm/external-dns/external-dns)).

### Local impact

- PR diff updates only `bootstrap/helmfile.d/00-crds.yaml` chart version for CRD extraction.
- Active runtime deployment is wired via `kubernetes/apps/network/cloudflare-dns/app/ocirepository.yaml` (already pinned to `tag: 1.21.1` + digest) and `kubernetes/apps/network/cloudflare-dns/app/helmrelease.yaml`.
- Local external-dns config uses:
  - provider: `cloudflare`
  - sources: `crd`, `gateway-httproute`
  - explicit `extraArgs` including `--gateway-name=envoy-external`
- Because this component controls public DNS records, rollback is straightforward via Git revert but operational blast radius is high (record drift or missed updates can impact ingress reachability).

### Pre-merge checks

- [ ] Confirm cluster Gateway API resources are served at `gateway.networking.k8s.io/v1` (required by upstream `v0.21.0` gateway source migration).
- [ ] Reconcile in a controlled window and watch `cloudflare-dns` logs for RBAC/list/watch errors on Gateway/HTTPRoute and DNSEndpoint resources.
- [ ] Verify at least one expected DNS update path (HTTPRoute or DNSEndpoint change) still produces correct Cloudflare records.
- [ ] Verify no spike in Cloudflare API errors/rate-limit responses after upgrade (batch API behavior changed upstream).
- [ ] Keep rollback ready: revert this version bump if reconciliation errors persist.

### Evidence reviewed

- PR: `feat(container): update image ghcr.io/home-operations/charts-mirror/external-dns ( 1.20.0 ➔ 1.21.1 )`; labels: `area/bootstrap`, `renovate/container`, `type/minor`, `dependencies`; diff: 1 file / 1-line version bump.
- Files in repo: `bootstrap/helmfile.d/00-crds.yaml`, `kubernetes/apps/network/cloudflare-dns/app/ocirepository.yaml`, `kubernetes/apps/network/cloudflare-dns/app/helmrelease.yaml`, plus repo-wide `external-dns` references via `git grep`.
- Upstream sources checked: 
  - https://github.com/webgrip/homelab-cluster/pull/190
  - https://raw.githubusercontent.com/kubernetes-sigs/external-dns/master/charts/external-dns/CHANGELOG.md
  - https://github.com/kubernetes-sigs/external-dns/releases/tag/v0.21.0
  - https://artifacthub.io/api/v1/packages/helm/external-dns/external-dns
- Notable uncertainty: chart changelog is current and complete for `v1.21.1`; no standalone `v1.21.0` artifact/release found.
