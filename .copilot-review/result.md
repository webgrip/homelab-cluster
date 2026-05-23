pr: 156

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates the `n8nio/n8n` container image from `2.22.0` to `2.22.2` and also updates the pinned digest in the n8n HelmRelease. Upstream notes for both intermediate patch versions are available and list bug fixes (not new major features), which lowers breakage risk. The main local risk driver is that n8n is a stateful, user-facing automation service with persistent storage and Postgres backing, so runtime behavior changes can still affect scheduled workflows. Merge is reasonable after quick functional checks focused on scheduled polls/webhooks and AI prompt flows.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `n8nio/n8n` | Docker/OCI image | `2.22.0@sha256:c501989f...` → `2.22.2@sha256:bf26d48e...` | patch + digest | runtime / infra (Flux HelmRelease) | Yellow |

### Important upstream changes

- [bugfix] `n8n@2.22.1`: populate manual user id on webhook execution data path.
- [bugfix] `n8n@2.22.1`: validate non-empty prompts in AI vendor nodes before API calls.
- [bugfix] `n8n@2.22.2`: scheduled poll expression isolate acquisition fix.
- [bugfix] `n8n@2.22.2`: report scheduled-poll isolate acquisition failures via `__emitError`.
- [bugfix] `n8n@2.22.2`: PostHog group identify call-site fix after init.

### Local impact

`n8nio/n8n` is referenced in `kubernetes/apps/n8n/n8n/app/helmrelease.yaml` and runs as the main app container in a Flux-managed HelmRelease. This workload is not stateless: it mounts persistent data at `/home/node/.n8n` (`existingClaim: n8n`) and uses a dedicated CloudNativePG Postgres cluster (`kubernetes/apps/n8n/n8n/app/database/cluster.yaml`) with credentials/config from secrets/configmaps (`configmap-env.yaml`, `n8n-secrets.sops.yaml`). The service is internet-facing through `httproute.yaml` and handles webhooks (`WEBHOOK_URL`), so regression impact could include failed triggers, scheduling issues, or execution behavior drift. Rollback is straightforward in GitOps terms (revert commit), but operationally this remains a production runtime change.

### Pre-merge checks

- [ ] Confirm Flux applies only the expected image tag+digest change for `kubernetes/apps/n8n/n8n/app/helmrelease.yaml`.
- [ ] After deploy, verify n8n pod readiness and no restart loop/crash (`n8n` namespace).
- [ ] Run/observe at least one scheduled workflow to validate scheduled-poll behavior.
- [ ] Trigger at least one webhook workflow and verify execution metadata/user mapping still looks correct.
- [ ] If AI vendor nodes are in active use, run a known-good AI workflow (including prompt validation path).
- [ ] Check recent n8n logs for new errors around scheduler isolates, webhooks, or prompt validation.

### Evidence reviewed

- PR: `fix(container): update image n8nio/n8n ( 2.22.0 ➔ 2.22.2 )`; labels: `area/kubernetes`, `renovate/container`, `type/patch`, `dependencies`; diff summary: 1 file changed, 1 insertion / 1 deletion in `kubernetes/apps/n8n/n8n/app/helmrelease.yaml`.
- Files in repo: `kubernetes/apps/n8n/n8n/app/helmrelease.yaml`, `kubernetes/apps/n8n/n8n/app/configmap-env.yaml`, `kubernetes/apps/n8n/n8n/app/database/cluster.yaml`, plus repository-wide grep hits under `kubernetes/apps/n8n/**`.
- Upstream sources checked: `https://github.com/n8n-io/n8n/releases/tag/n8n%402.22.1`, `https://github.com/n8n-io/n8n/releases/tag/n8n%402.22.2`, `https://api.github.com/repos/n8n-io/n8n/releases/tags/n8n@2.22.1`, `https://api.github.com/repos/n8n-io/n8n/releases/tags/n8n@2.22.2`, `https://hub.docker.com/v2/repositories/n8nio/n8n/tags?page_size=100&name=2.22.`.
- Notable uncertainty: The pinned digest in PR appears to be a manifest-list digest while quick Docker Hub API inspection returned platform image digests; digest-format differences are expected, but this was not independently revalidated against registry manifest-list digest in-cluster.
