pr: 273

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge after checks
**Confidence:** High

### Executive summary

This PR bumps Talos Linux from v1.13.2 to v1.13.3 — a patch release containing bug fixes (scheduler config marshaling, mount propagation, `registry.k8s.io` image verification, hostname config validation, memory module reporting) and minor component updates (Linux kernel 6.18.33, containerd 2.2.4, Go 1.26.3). No breaking changes or API removals are present. The primary pre-merge check is verifying the custom factory schematic (used by all four nodes via `factory.talos.dev/installer/<hash>`) resolves correctly for v1.13.3 before executing the upgrade.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/siderolabs/installer` | Docker/OCI | `v1.13.2 → v1.13.3` | patch | infra (Talos node OS upgrade) | Green |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[bugfix]` | Guard `apply config` API call to prevent panics under certain race conditions | [commit 01b434870](https://github.com/siderolabs/talos/commit/01b434870) | **Yes** — all nodes run `talosctl apply-config`; this fix reduces risk of apply failures |
| `[bugfix]` | Fix memory module resource reporting | [commit d62d54ca7](https://github.com/siderolabs/talos/commit/d62d54ca7) | **Yes** — all nodes are physical hardware (soyo-1/2/3, fringe-workstation); memory SMBIOS data was mis-reported |
| `[bugfix]` | Relax hostname config validation (previously overly strict) | [commit 532bc6baa](https://github.com/siderolabs/talos/commit/532bc6baa) | **Yes** — nodes use static hostnames; validation was potentially rejecting valid configs |
| `[bugfix]` | Rework scheduler config marshaling (fixes edge-case serialization) | [commit 5633c7791](https://github.com/siderolabs/talos/commit/5633c7791) | **Yes** — control plane nodes run kube-scheduler; fixes potential config marshal issue |
| `[bugfix]` | Restore shared and lower-tier slave mount propagation (broken in earlier patch) | [commit 52f056084](https://github.com/siderolabs/talos/commit/52f056084) | **Yes** — nodes use iSCSI and other storage mounts; mount propagation regression is a reliability fix |
| `[bugfix]` | Fix image verification issue with `registry.k8s.io` | [commit 9de3c12d9](https://github.com/siderolabs/talos/commit/9de3c12d9) | **Yes** — Kubernetes control plane images pull from `registry.k8s.io`; this fix removes a potential upgrade blocker |
| `[feature]` | Redact more machine config secrets; expand audit redactors | [commit 7dc716d85](https://github.com/siderolabs/talos/commit/7dc716d85) | **Yes** — secrets are present (`talos/talsecret.sops.yaml`); improved redaction is a security improvement |
| `[feature]` | Add `bnxt_re` (Broadcom RDMA) kernel module | [commit 19755ad14](https://github.com/siderolabs/talos/commit/19755ad14) | **No** — not referenced in the custom extensions list (`binfmt-misc`, `iscsi-tools`, `util-linux-tools`) |
| `[feature]` | Support Akamai instance tags in `machined` | [commit a42c37f24](https://github.com/siderolabs/talos/commit/a42c37f24) | **No** — cluster runs on bare-metal (soyo-* and fringe-workstation), not Akamai/Linode |
| `[feature]` | Update default Kubernetes version to 1.36.1 | [commit 472b9d991](https://github.com/siderolabs/talos/commit/472b9d991) | **No** — `kubernetesVersion` in `talenv.yaml` is pinned to `v1.36.1` independently; no K8s version change in this PR |
| `[component]` | Linux kernel 6.18.33 (from 6.18.29 in v1.13.2) | [pkgs commit 82e70a0](https://github.com/siderolabs/pkgs/commit/82e70a0) | **Yes** — kernel update on all nodes; includes RP1/BCM2712 TX stall fix, PPP/INFINIBAND options |
| `[component]` | containerd updated to 2.2.4 | [pkgs commit 8bdd5e0](https://github.com/siderolabs/pkgs/commit/8bdd5e0) | **Yes** — all nodes run containerd as the container runtime; patch-level update |
| `[component]` | Go runtime updated to 1.26.3 | [release notes](https://github.com/siderolabs/talos/releases/tag/v1.13.3) | **No** — runtime detail; no action needed |

### Local impact

**Files referencing this dependency:**
- `talos/talenv.yaml` — single source of truth for `talosVersion`; consumed by `talhelper` to generate upgrade commands
- `talos/talconfig.yaml` — defines all four nodes with `talosImageURL: factory.talos.dev/installer/1da3394e6229e507d4e3d166b718cacff86435a61c4765feedd66b43ac237558`
- `.taskfiles/talos/Taskfile.yaml` — `upgrade-node` task reads `talosVersion` from `talenv.yaml` and `talosImageURL` from `talconfig.yaml` to construct the `talosctl upgrade` command

**Critical note on the custom factory schematic:**
All four nodes use `factory.talos.dev/installer/<schematic-hash>` rather than the vanilla `ghcr.io/siderolabs/installer`. The schematic hash `1da3394e6229e507d4e3d166b718cacff86435a61c4765feedd66b43ac237558` encodes the selected extensions (`binfmt-misc`, `iscsi-tools`, `util-linux-tools`). The factory.talos.dev service auto-builds schematic images for each Talos release, so the same hash should resolve for v1.13.3. However, this must be confirmed before running the upgrade.

**Upgrade procedure:** The actual node upgrade is performed manually via `task talos:upgrade-node IP=<node-ip>`. This PR only updates the version reference; the upgrade does not auto-apply via Flux.

**Rollback:** Rollback requires reverting this commit and re-running `talosctl upgrade` with v1.13.2. Talos node upgrades reboot the node; rollback is straightforward but requires access to the cluster.

**Stateful workloads:** The cluster runs stateful workloads (Longhorn storage based on the iSCSI extension). The mount propagation fix in this release is directly relevant to iSCSI stability.

### Improvement opportunities

- **Verify schematic hash for v1.13.3 at factory.talos.dev** — Before running `task talos:upgrade-node`, confirm `https://factory.talos.dev/image/1da3394e6229e507d4e3d166b718cacff86435a61c4765feedd66b43ac237558/v1.13.3/metal-amd64.iso` (or the installer variant) is available. If the extensions list changed, a new schematic may be needed.
- **Review expanded secret redaction** — v1.13.3 adds broader audit redactors ([commit 7dc716d85](https://github.com/siderolabs/talos/commit/7dc716d85)). Review the Talos audit logs after upgrade to confirm sensitive fields are properly redacted in your environment.

### Grafana dashboards and alerts

No dashboard or alert changes identified. The `talos/` and `kubernetes/` paths were scanned for PrometheusRule, ServiceMonitor, and dashboard JSON/YAML files referencing Talos-specific metrics. This update involves no metric name changes, no new exporters, and no scrape config changes. The containerd and kernel updates do not alter existing metric schemas.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Talos node metrics | No Talos-specific ServiceMonitor or PrometheusRule found in repo | None | Patch release; no metric changes in v1.13.3 release notes |

### Pre-merge checks

- [ ] Confirm `factory.talos.dev/installer/1da3394e6229e507d4e3d166b718cacff86435a61c4765feedd66b43ac237558` resolves for `v1.13.3` (visit `https://factory.talos.dev` or run `curl -sI https://factory.talos.dev/image/1da3394e6229e507d4e3d166b718cacff86435a61c4765feedd66b43ac237558/v1.13.3/metal-amd64.iso`)
- [ ] Merge this PR (updates `talos/talenv.yaml` only)
- [ ] Run `task talos:generate-config` to regenerate node configs with v1.13.3
- [ ] Run `task talos:upgrade-node IP=10.0.0.20` (soyo-1), wait for node to rejoin before proceeding
- [ ] Run `task talos:upgrade-node IP=10.0.0.21` (soyo-2), wait for node to rejoin
- [ ] Run `task talos:upgrade-node IP=10.0.0.22` (soyo-3), wait for node to rejoin
- [ ] Run `task talos:upgrade-node IP=10.0.0.23` (fringe-workstation, worker)
- [ ] Verify `kubectl get nodes` shows all nodes `Ready` at v1.13.3 post-upgrade
- [ ] Confirm iSCSI/Longhorn volumes remain healthy post-upgrade (mount propagation fix is relevant)

### Follow-up

- [ ] Verify `registry.k8s.io` image verification fix ([commit 9de3c12d9](https://github.com/siderolabs/talos/commit/9de3c12d9)) — run `talosctl health` post-upgrade to confirm no image pull errors remain
- [ ] Consider adding a ServiceMonitor for Talos node metrics (`/api/v1/metrics` on port 50000) now that the node metric surface is stable in 1.13.x

### Evidence reviewed

- **PR:** "fix(container): update image ghcr.io/siderolabs/installer ( v1.13.2 ➔ v1.13.3 )", labels: `area/talos`, `renovate/container`, `type/patch`, `dependencies`; diff: 1 line changed in `talos/talenv.yaml`
- **Files in repo:** `talos/talenv.yaml`, `talos/talconfig.yaml`, `.taskfiles/talos/Taskfile.yaml`
- **Upstream sources checked:**
  - https://github.com/siderolabs/talos/releases/tag/v1.13.3 (full release notes retrieved via GitHub API)
  - https://github.com/siderolabs/talos/releases/tag/v1.13.2 (prior release for context)
  - https://github.com/siderolabs/pkgs (Linux/containerd component update commits)
- **Notable uncertainty:** The custom factory.talos.dev schematic availability for v1.13.3 has not been live-verified (factory.talos.dev was not contacted); this is the only unconfirmed item.
