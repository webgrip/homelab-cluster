pr: 199

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR bumps the Talos installer image tag from `v1.12.4` to `v1.13.2`, which crosses multiple patch releases and one minor Talos release. Upstream includes meaningful lifecycle/API and bootstrap-behavior changes in `v1.13.0`, plus security-relevant hardening and container runtime updates. In this repo, that version pin directly drives node OS upgrade commands, so blast radius is cluster-wide when operators execute upgrades. Merge is reasonable, but only after confirming operator tooling/version compatibility and rollout runbook readiness.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/siderolabs/installer` | Docker/OCI (GHCR) | `v1.12.4 → v1.13.2` | minor (with skipped intermediate versions) | infra/runtime (Talos node OS upgrade image) | Yellow |

### Important upstream changes

- [migration] Talos `v1.13.0` introduces install/upgrade operations via `LifecycleService`; legacy upgrade API is deprecated (release note + implementing commit: [v1.13.0 notes](https://github.com/siderolabs/talos/releases/tag/v1.13.0), [siderolabs/talos@1e4cd20d2](https://github.com/siderolabs/talos/commit/1e4cd20d2)).
- [behavior] Talos `v1.13.0` switches bootstrap manifest application to inventory-backed server-side apply (release note + implementation commit: [v1.13.0 notes](https://github.com/siderolabs/talos/releases/tag/v1.13.0), [siderolabs/talos@c4f3f6d3e](https://github.com/siderolabs/talos/commit/c4f3f6d3e)).
- [security] Talos `v1.13.0` adds machine-wide image verification support (`ImageVerificationConfig`) (release note + endpoint commit: [v1.13.0 notes](https://github.com/siderolabs/talos/releases/tag/v1.13.0), [siderolabs/talos@7f2eb4856](https://github.com/siderolabs/talos/commit/7f2eb4856)).
- [security] Talos `v1.13.0` hardens `/proc/PID/mem` behavior by default (`proc_mem.force_override=never`) (release note + commit: [v1.13.0 notes](https://github.com/siderolabs/talos/releases/tag/v1.13.0), [siderolabs/talos@b95912e04](https://github.com/siderolabs/talos/commit/b95912e04)).
- [security] Talos `v1.12.8` explicitly updates containerd to `2.2.4` due to `2.1.x` EOL and CVE-2026-46680 context (release note + update commit: [v1.12.8 notes](https://github.com/siderolabs/talos/releases/tag/v1.12.8), [siderolabs/talos@faff61707](https://github.com/siderolabs/talos/commit/faff61707)).
- [unknown] No GitHub release notes were found for `v1.13.1` tag; compare data shows 27 commits between `v1.13.0...v1.13.1` including a Kubernetes manifest sync panic fix and other runtime/network fixes ([compare](https://github.com/siderolabs/talos/compare/v1.13.0...v1.13.1), [siderolabs/talos@549f3c0b4c](https://github.com/siderolabs/talos/commit/549f3c0b4c), [siderolabs/talos@ce89d67270](https://github.com/siderolabs/talos/commit/ce89d67270)).

### Local impact

The dependency is pinned in `talos/talenv.yaml` and consumed as `talosVersion` by Talos automation. Specifically, `.taskfiles/talos/Taskfile.yaml` reads `talosVersion` from `talos/talenv.yaml` and builds node upgrade commands (`talos:upgrade-node`) against that image tag. `talos/talconfig.yaml` templates `talosVersion` into generated cluster configs, and docs/runbook (`docs/techdocs/docs/runbooks/talos-rolling-upgrade.md`) treat this file as the authoritative rollout target. This means the change is not a passive image bump: once operators execute upgrade tasks, all control-plane/worker nodes can be affected. Rollback requires orchestrated node-by-node Talos downgrade/restore procedures, so operational risk is moderate.

### Pre-merge checks

- [ ] Confirm maintainers intend to skip intermediate versions (`v1.12.5`..`v1.13.1`) in one step and accept the wider change surface.
- [ ] Verify operator tooling compatibility before rollout (runbook step), especially Talos client/tooling pin alignment in `.mise.toml` versus target cluster version.
- [ ] Ensure Talos upgrade runbook is followed for phased rollout (one control-plane node at a time with health checks between nodes).
- [ ] After first node upgrade, verify etcd/member health and Kubernetes node readiness before continuing cluster-wide.

### Evidence reviewed

- PR: feat(container): update image ghcr.io/siderolabs/installer ( v1.12.4 ➔ v1.13.2 ); labels: `area/talos`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 1 insertion, 1 deletion in `talos/talenv.yaml`.
- Files in repo: `talos/talenv.yaml`, `talos/talconfig.yaml`, `.taskfiles/talos/Taskfile.yaml`, `docs/techdocs/docs/runbooks/talos-rolling-upgrade.md`, `docs/techdocs/docs/renovate.md`.
- Upstream sources checked: https://github.com/siderolabs/talos/releases/tag/v1.12.5 , https://github.com/siderolabs/talos/releases/tag/v1.12.6 , https://github.com/siderolabs/talos/releases/tag/v1.12.7 , https://github.com/siderolabs/talos/releases/tag/v1.12.8 , https://github.com/siderolabs/talos/releases/tag/v1.13.0 , https://github.com/siderolabs/talos/releases/tag/v1.13.2 , https://github.com/siderolabs/talos/compare/v1.13.0...v1.13.1 , https://github.com/siderolabs/talos/compare/v1.13.1...v1.13.2 .
- Notable uncertainty: `v1.13.1` has a tag but no corresponding GitHub release entry/changelog page found via release API.
