pr: 150

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

PR #150 updates the n8n runtime container from `n8nio/n8n:2.21.7` to `2.22.0` and rotates the pinned digest in a single HelmRelease value. Upstream 2.22.0 includes a large set of bugfixes and features (including security-related dependency fixes), but no explicit breaking-change section was published in the release notes. In this repo, n8n is a stateful, externally exposed workflow platform with persistent storage and a dedicated Postgres cluster, so behavior regressions can affect live automations. Merge is reasonable after focused runtime checks.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `n8nio/n8n` | Docker/OCI | `2.21.7@sha256:9f1f8e4c...` → `2.22.0@sha256:c501989f...` | minor | runtime / app workload (GitOps deploy) | Yellow |

### Important upstream changes

- [behavior] Upstream `n8n@2.22.0` release contains a broad set of workflow engine/editor/core behavior changes (AI builder, MCP tooling, expression handling, retries, autosave/UI behavior).
- [feature] `n8n@2.22.0` adds multiple new node and platform capabilities (for example AWS IRSA strategy support, OAuth additions in several nodes, crypto actions, and core telemetry/observability additions).
- [security] Release notes include security-related fixes: “Fix 13 critical issues in vm2, protobufjs, @daytonaio/sdk and 4 more” and “Fix security issue in langsmith via minor version upgrade from 0.5.19 to 0.6.0”.
- [bugfix] Release notes include “Restore /usr/local/bin/n8n compat symlink in production image”, relevant for self-hosted container runtime compatibility.
- [unknown] No dedicated “breaking changes” section was found in the release notes for `n8n@2.22.0`; risk remains from the breadth of change in a minor release.

### Local impact

`n8nio/n8n` is set directly in `kubernetes/apps/n8n/n8n/app/helmrelease.yaml` (single container under app-template), and this PR only changes that image tag+digest. The workload runs with `Recreate` strategy and mounts persistent data at `/home/node/.n8n` via PVC (`kubernetes/apps/n8n/n8n/app/pvc.yaml`), so startup/runtime regressions can impact stored workflow metadata/state and operator UX. The app is connected to a dedicated CloudNativePG database (`kubernetes/apps/n8n/n8n/app/database/cluster.yaml`) and is reachable via HTTPRoute on `n8n.${SECRET_DOMAIN}` (`kubernetes/apps/n8n/n8n/app/httproute.yaml`), increasing blast radius versus an internal-only stateless service. Rollback is straightforward via Git revert, but may still require pod restart/reconcile and post-rollback validation of workflow execution health.

### Pre-merge checks

- [ ] Verify Flux/CI passes for this PR (`verify-oci-digests` and flux-local checks).
- [ ] After deploy, confirm n8n pod starts cleanly and remains Ready in namespace `n8n` (no crash loops / migration failures).
- [ ] Run a smoke test in n8n UI/API: open editor, execute one representative existing workflow, and validate webhook-triggered workflow execution.
- [ ] Confirm DB connectivity remains healthy (`DB_POSTGRESDB_*` path) and no new errors appear in n8n logs around migrations/credential loading.
- [ ] If any regression appears, revert to previous pinned image digest (`2.21.7@sha256:9f1f8e4c...`) and reconcile.

### Evidence reviewed

- PR: `feat(container): update image n8nio/n8n ( 2.21.7 ➔ 2.22.0 )`; labels `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 1 insertion, 1 deletion in `kubernetes/apps/n8n/n8n/app/helmrelease.yaml`.
- Files in repo: `kubernetes/apps/n8n/n8n/app/helmrelease.yaml`, `kubernetes/apps/n8n/n8n/app/configmap-env.yaml`, `kubernetes/apps/n8n/n8n/app/pvc.yaml`, `kubernetes/apps/n8n/n8n/app/database/cluster.yaml`, `kubernetes/apps/n8n/n8n/app/httproute.yaml`, `kubernetes/apps/n8n/n8n/ks.yaml`.
- Upstream sources checked: `https://github.com/n8n-io/n8n/releases/tag/n8n%402.22.0`, `https://github.com/n8n-io/n8n/releases/tag/n8n%402.21.7`, `https://hub.docker.com/v2/repositories/n8nio/n8n/tags/2.22.0`, `https://hub.docker.com/v2/repositories/n8nio/n8n/tags/2.21.7`.
- Notable uncertainty: The update target in this PR is `2.22.0` while upstream has newer `2.22.1/2.22.2`; this review only assesses the exact proposed jump `2.21.7 → 2.22.0`.
