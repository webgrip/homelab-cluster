pr: 168

## Dependency Update Review

**Verdict:** Yellow — Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates two CLI tools in `.mise.toml`: `helm/helm` from v3.19.2 to v4.1.4 (major version jump with documented breaking changes) and `cloudflare/cloudflared` from `2025.11.1` to `2026.3.0` (calendar-versioned tool update). The cloudflared update is low risk — it bumps the local dev CLI while the container image is already pinned to `2026.5.0` in the cluster. The Helm 3→4 upgrade is the primary risk driver: Helm 4 carries backward-incompatible CLI flag and SDK changes, and the bootstrap helmfile (`00-crds.yaml`) uses a `postRenderer: bash` whose behavior could change. Since the repo uses `helmfile` (v1.2.2) for bootstrapping — which bundles its own Helm binary — and `flux-local` for CI, direct exposure of the mise `helm` CLI is limited to ad-hoc operator tasks. Recommended action: verify ad-hoc helm workflows and bootstrap sequence against Helm 4 before merging.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `aqua:helm/helm` | Aqua / GitHub releases | `3.19.2 → 4.1.4` | major | dev-tool / infra bootstrap CLI | Yellow |
| `aqua:cloudflare/cloudflared` | Aqua / GitHub releases | `2025.11.1 → 2026.3.0` | major (calendar versioning) | dev-tool / tunnel CLI | Green |

### Important upstream changes

**helm/helm 3.19.2 → 4.1.4**

- `[breaking]` Helm 4 is documented as backward-incompatible with Helm 3 for CLI flags and output formats (ref: v4.0.0 release notes: *"backward incompatible changes including to the flags and output of the Helm CLI"*).
- `[feature]` Redesigned plugin system using WebAssembly — existing Helm v3 plugins may not work without updates.
- `[behavior]` Post-renderers are now plugins in Helm 4 (different from the helmfile-level `postRenderer: bash` feature in this repo).
- `[feature]` Server-side apply is now the default in Helm 4, which changes how resources are applied and can affect field ownership in existing cluster resources.
- `[security]` v4.1.4 is a security patch release fixing three CVEs: GHSA-hr2v-4r36-88hr (Chart.yaml dot-segment path collapse), GHSA-q5jf-9vfq-h4h7 (unsigned plugin install when `.prov` missing), GHSA-vmx8-mqv2-9gmg (path traversal in plugin metadata for arbitrary file write). These security fixes motivate upgrading, but they apply to the CLI tool itself.
- `[behavior]` Chart `apiVersion: v2` (used by virtually all modern charts) continues to be supported — existing cluster HelmRelease objects should remain compatible.
- Note: v4.1.2 was skipped due to a build automation issue; the jump is v4.1.1 → v4.1.3 → v4.1.4.

**cloudflare/cloudflared 2025.11.1 → 2026.3.0**

- `[unknown]` Intermediate releases (2026.1.1, 2026.1.2, 2026.2.0) contain only SHA256 checksums in their release bodies — no changelog entries were published. No breaking changes or notable features identified.
- The cloudflared container image in the cluster HelmRelease is already pinned to `2026.5.0@sha256:59bab8d…` (newer than this PR's target), confirming the runtime component is independently managed.

### Local impact

**helm/helm**

- Defined in `.mise.toml` as `"aqua:helm/helm" = "3.19.2"` → `4.1.4`. This installs the `helm` binary for local operator use via `mise exec`.
- The **bootstrap scripts** (`scripts/bootstrap-apps.sh`) call `helmfile`, not `helm` directly. `helmfile` v1.2.2 (currently pinned) already bundles a Helm v4 SDK (`helm.sh/helm/v4 4.0.1`) — so bootstrap should use helmfile's embedded helm, not the mise CLI binary.
- The `bootstrap/helmfile.d/00-crds.yaml` uses `postRenderer: bash` + `postRendererArgs` to filter CRDs via `yq`. This is a helmfile-level feature (not the Helm 4 plugin-based post-renderer); its behavior is governed by helmfile's implementation and is unlikely to be broken by the helm CLI version.
- **CI pipeline** (`.github/workflows/flux-local.yaml`) uses the `ghcr.io/allenporter/flux-local:v8.0.1` Docker image — no direct invocation of the mise `helm` CLI in CI.
- **Ad-hoc operator workflows** (e.g., `helm list`, `helm upgrade --install`, `helm template`) that operators run locally are the only direct Helm CLI consumers. If any custom scripts or runbooks use Helm 3 CLI flags that changed in v4, they will break.
- Server-side apply becoming default in Helm 4 could affect any direct `helm install`/`helm upgrade` commands that operators run against the cluster — field ownership conflicts are possible for resources previously managed with client-side apply.

**cloudflare/cloudflared**

- Defined in `.mise.toml` as the CLI tool; used for tunnel management operations (e.g., `cloudflared tunnel login`, `cloudflared tunnel route`).
- The running container in `kubernetes/apps/network/cloudflare-tunnel/` is already at `2026.5.0` — this PR does not touch it.
- No risk to cluster runtime from this update.

### Pre-merge checks

- [ ] Run `helm version` after updating mise and confirm `v4.1.4` is picked up correctly.
- [ ] Run `mise exec -- helm list -A` against a test context and confirm output format is acceptable for any scripts or runbooks that parse `helm` output.
- [ ] Verify `helmfile --file bootstrap/helmfile.d/00-crds.yaml template --quiet` still renders CRDs correctly with helmfile v1.2.2 (it bundles its own Helm binary; the mise `helm` upgrade should not affect this, but worth confirming).
- [ ] Check whether any Helm plugins are in use locally (`helm plugin list`); Helm 4 redesigned the plugin system and existing v3 plugins may need updates.
- [ ] If server-side apply is now the default in Helm 4, verify any ad-hoc `helm upgrade` commands on existing cluster resources don't produce field-ownership conflicts.
- [ ] Consider upgrading `helmfile` from v1.2.2 to ≥ v1.4.2 in a follow-up PR to get explicit Helm 4 compatibility fixes (helmfile v1.4.2 added `helm-legacy` track mode for Helm v4 compatibility).
- [ ] No special pre-merge checks needed for cloudflared CLI beyond confirming `cloudflared version` reports `2026.3.0`.

### Evidence reviewed

- PR: "feat(mise)!: Update Mise tools (major)" — `.mise.toml` only, 2 additions / 2 deletions. No CI workflow or script changes included.
- Files in repo: `.mise.toml`, `scripts/bootstrap-apps.sh`, `bootstrap/helmfile.d/00-crds.yaml`, `.taskfiles/bootstrap/Taskfile.yaml`, `.github/workflows/flux-local.yaml`, `kubernetes/apps/network/cloudflare-tunnel/app/helmrelease.yaml`
- Upstream sources checked:
  - `https://api.github.com/repos/helm/helm/releases` — confirmed v4.0.0 breaking changes, v4.1.4 security fixes
  - `https://api.github.com/repos/cloudflare/cloudflared/releases` — release bodies contain checksums only; no changelog for intermediate versions
  - `https://api.github.com/repos/helmfile/helmfile/releases` — confirmed v1.2.2 bundles Helm v4 SDK; v1.4.2+ adds explicit Helm 4 CLI compatibility fixes
- Notable uncertainty: Helm 4 breaking changes to CLI flags are documented at a high level but the exact flags affected are not enumerated in release notes — the Helm team links to `https://helm.sh/docs/overview/` for full details. Any operator runbooks or external CI jobs (outside this repo) that invoke the mise `helm` binary should be reviewed independently.
