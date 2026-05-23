pr: 202

## Dependency Update Review

**Verdict:** 🔴 Red — Blocking risk  
**Recommendation:** Hold — do NOT merge without first upgrading Talos to v1.13.x  
**Confidence:** High

---

### Executive summary

This PR bumps `kubernetesVersion` in `talos/talenv.yaml` from `v1.34.4` to `v1.36.1`, skipping the entire v1.35 minor series. **Critical blocker**: the cluster currently runs Talos Linux `v1.12.4`, whose latest patch (`v1.12.8`, 2026-05-22) still ships Kubernetes `v1.35.4` as its bundled default and does not support Kubernetes v1.36.x. Kubernetes v1.36 support was only introduced in Talos v1.13.x (released 2026-04-27). Merging this PR without first upgrading Talos to ≥v1.13.x will likely cause `talosctl upgrade-k8s` to fail or the kubelet to run in an unsupported configuration. There are also two noteworthy breaking changes across the skipped versions (cgroup v1 removal in v1.35, `gitRepo` volume removal in v1.36) that must be verified before merging.

---

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/siderolabs/kubelet` | Container image | `v1.34.4 → v1.36.1` | 2 minor versions | infra/node agent | 🔴 High |

---

### Important upstream changes

**v1.35 (skipped entirely)**

- **[breaking]** **cgroup v1 support removed from kubelet.** Kubernetes v1.35 drops cgroup v1; the kubelet will refuse to start on cgroup v1 nodes by default. Talos Linux uses cgroup v2 by default, so this cluster is almost certainly unaffected, but verify via node OS configuration. ([kubernetes/kubernetes CHANGELOG-1.35.md](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.35.md))

- **[breaking]** **Last release supporting containerd 1.x.** v1.35 is the final Kubernetes release that works with containerd 1.x. v1.36 requires containerd 2.0+. Talos provides its own containerd, but double-check the Talos v1.13 release notes for the bundled containerd version. ([CHANGELOG-1.35.md](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.35.md))

- **[feature]** In-place Pod Resource Updates reaches GA (CPU/memory updates without pod restart). ([kubernetes/enhancements#1287](https://github.com/kubernetes/enhancements/issues/1287))

**v1.36**

- **[breaking]** **`gitRepo` volume type fully removed.** Any workloads using the `gitRepo` volume type (deprecated since v1.11) will fail to schedule. Audit cluster workloads for this pattern. ([kubernetes/kubernetes CHANGELOG-1.36.md](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.36.md))

- **[breaking]** **Portworx in-tree storage driver removed.** If any workloads use the in-tree Portworx driver, they must be migrated to the CSI driver. ([CHANGELOG-1.36.md](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.36.md))

- **[breaking]** **Talos v1.12.x does not support Kubernetes v1.36.x.** Confirmed: Talos v1.12.8 (latest 1.12 patch, released 2026-05-22) bundles `ghcr.io/siderolabs/kubelet:v1.35.4` and `kube-apiserver:v1.35.4`. Talos v1.13.0 (released 2026-04-27) is the first Talos release to bundle Kubernetes v1.36. Running Kubernetes v1.36 under Talos v1.12 is an unsupported combination. ([siderolabs/talos releases](https://github.com/siderolabs/talos/releases))

- **[feature]** Dynamic Resource Allocation (DRA) reaches GA — relevant if GPU/hardware accelerators are used. ([dev.to Kubernetes 1.36 guide](https://dev.to/x4nent/complete-guide-to-kubernetes-136-dra-ga-oci-volumesource-mutatingadmissionpolicy-and-2h8b))

- **[feature]** OCI VolumeSource GA — mount OCI registry artifacts directly as volumes. ([CHANGELOG-1.36.md](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.36.md))

- **[feature]** MutatingAdmissionPolicy GA — declarative mutations via CEL, without custom webhook servers. ([CHANGELOG-1.36.md](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.36.md))

- **[feature]** Fine-grained kubelet API authorization GA — per-endpoint RBAC for the kubelet API. ([CHANGELOG-1.36.md](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.36.md))

> **Release notes completeness note:** The PR body contains only compare-links with no inline summaries. All breaking changes above were sourced from official Kubernetes CHANGELOG files and third-party upgrade guides; no fabricated entries.

---

### Local impact

**File changed:** `talos/talenv.yaml` (single line: `kubernetesVersion: v1.34.4 → v1.36.1`)

**How it propagates:**
- `talos/talconfig.yaml` reads `${kubernetesVersion}` and passes it to `talhelper genconfig`, which generates node machine configs for all four nodes (soyo-1, soyo-2, soyo-3, fringe-workstation).
- `.taskfiles/talos/Taskfile.yaml` task `upgrade-k8s` runs `talhelper gencommand upgrade-k8s --to <kubernetesVersion>` sourcing the value from this file. This is the live upgrade path.
- `talos/patches/global/machine-kubelet.yaml` configures the kubelet globally (`serializeImagePulls: false`, `nodeIP.validSubnets`). No version-specific flags present — no immediate conflict, but must be validated against v1.36 kubelet flag removals.

**Cluster topology:** 3 control-plane nodes (soyo-1/2/3) + 1 worker (fringe-workstation), all bare-metal Talos nodes with a VIP at 10.0.0.25.

**Stateful risk:** This is a Kubernetes minor-version upgrade applied via `talosctl upgrade-k8s`. It is an in-place rolling upgrade of all cluster components (apiserver, controller-manager, scheduler, kubelet on all nodes). Rollback requires reverting the config and running the upgrade-k8s command in reverse — non-trivial on a bare-metal cluster.

**Privilege/exposure:** The kubelet runs at the highest privilege level on each node; version mismatches between the control plane and kubelet have historically caused subtle failures.

**Skipped minor version:** v1.35 is being skipped entirely. The Kubernetes project recommends upgrading one minor version at a time. While Talos `upgrade-k8s` may handle multi-step upgrades internally, skipping v1.35 should be explicitly validated.

---

### Pre-merge checks

- [ ] **[BLOCKER] Upgrade Talos to v1.13.x first.** Talos v1.12.4 (current) only supports Kubernetes ≤ v1.35. Kubernetes v1.36 requires Talos ≥ v1.13. Open a separate PR to bump `talosVersion` in `talos/talenv.yaml` from `v1.12.4` to at least `v1.13.2` (latest stable as of 2026-05-12), then upgrade all nodes before merging this PR.
- [ ] **Verify no `gitRepo` volumes in cluster workloads.** Run `kubectl get pods -A -o json | jq '.items[].spec.volumes[]? | select(.gitRepo)` to confirm zero uses before upgrading to v1.36.
- [ ] **Verify no Portworx in-tree volumes.** Run `kubectl get pv -o json | jq '.items[] | select(.spec.portworxVolume)'` to confirm zero.
- [ ] **Validate kubelet flags.** Check that `talos/patches/global/machine-kubelet.yaml` does not use any kubelet flags removed in v1.35 or v1.36.
- [ ] **Check cgroup v2.** Confirm all nodes run with cgroup v2 (Talos default): `talosctl get kubernetesnode -o yaml | grep cgroup` or inspect node conditions. This should pass automatically on Talos.
- [ ] **Consider upgrading in two steps (v1.34 → v1.35 → v1.36)** rather than skipping v1.35, to adhere to Kubernetes upgrade best practices and catch any v1.35-specific issues early.
- [ ] **Test on non-production first** if a staging cluster exists.
- [ ] **Monitor Flux reconciliation** immediately after applying — confirm all HelmReleases and Kustomizations return to Ready state.

---

### Evidence reviewed

- **PR:** `feat(container): update image ghcr.io/siderolabs/kubelet (v1.34.4 → v1.36.1)`, labels: `area/talos`, `renovate/container`, `type/minor`, `dependencies`. Single-file diff: `talos/talenv.yaml`, +1/-1.
- **Files in repo:** `talos/talenv.yaml`, `talos/talconfig.yaml`, `talos/patches/global/machine-kubelet.yaml`, `.taskfiles/talos/Taskfile.yaml`
- **Upstream sources checked:**
  - `https://api.github.com/repos/siderolabs/talos/releases/tags/v1.12.4` — Talos v1.12.4 bundles Kubernetes v1.35.0
  - `https://api.github.com/repos/siderolabs/talos/releases/tags/v1.12.8` — Talos v1.12.8 (latest 1.12 patch) bundles Kubernetes v1.35.4, confirms v1.36 not supported
  - `https://api.github.com/repos/siderolabs/talos/releases/tags/v1.13.2` — Talos v1.13.2 bundles Kubernetes v1.36.0, confirms v1.36 requires Talos v1.13+
  - `https://api.github.com/repos/siderolabs/kubelet/releases` — v1.36.1 image exists and is published
  - `https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.35.md` — breaking changes
  - `https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.36.md` — breaking changes
- **Notable uncertainty:** The upstream `siderolabs/kubelet` repository has no per-release changelogs beyond compare links; all breaking-change data was sourced from the upstream `kubernetes/kubernetes` CHANGELOG. The Talos v1.12 official support matrix page was not directly accessible (JavaScript-rendered), but the conclusion is drawn from inspecting actual release bundles.
