pr: 193

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates one digest-pinned init container image used to mint GitHub App installation tokens for Renovate. Upstream changes between `2026.01.15` and `2026.05.22` are mostly build/CI maintenance, with the only runtime-relevant change being Node base image patch upgrades in the container. Because this image runs in the token-minting path and writes Renovate credentials into a Kubernetes Secret, the blast radius is operationally sensitive even though upstream changes appear low-impact. Merge is reasonable after validating one successful CronJob run and token refresh.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `ghcr.io/mshekow/github-app-installation-token` | Docker/OCI (GHCR) | `2026.01.15@sha256:cd651456...` → `2026.05.22@sha256:7babcf82...` | minor (date-tag series, digest-pinned) | infra / deploy (Renovate auth bootstrap CronJob initContainer) | Yellow |

### Important upstream changes

- [behavior] Runtime base image bumped from `node:24.13.0-alpine` to `node:24.16.0-alpine` in Dockerfile, via incremental updates (`24.13.1`, `24.14.0`, `24.15.0`, `24.16.0`) ([commit](https://github.com/MShekow/github-app-installation-token/commit/ae9cbc5fd6979ae2df06b45242c41f5f4afdf133), [PR #108](https://github.com/MShekow/github-app-installation-token/pull/108), [compare range](https://github.com/MShekow/github-app-installation-token/compare/c3ab2a7b94839189ec2fd366eee520a885562688...ae9cbc5fd6979ae2df06b45242c41f5f4afdf133)).
- [feature] Multi-arch image tags in this range are published and traceable to source revisions through OCI labels for intermediate tags (`2026.02.13`, `2026.03.04`, `2026.03.05`, `2026.03.06`, `2026.04.16`) and target tag `2026.05.22` ([GHCR tags API](https://ghcr.io/v2/mshekow/github-app-installation-token/tags/list), [repo source](https://github.com/MShekow/github-app-installation-token)).
- [unknown] No GitHub Releases/CHANGELOG entries were found for this project, so assessment relied on commit-level analysis and image metadata ([releases endpoint result](https://api.github.com/repos/MShekow/github-app-installation-token/releases), [tags endpoint result](https://api.github.com/repos/MShekow/github-app-installation-token/tags)).
- [bugfix] Remaining upstream commits in range are CI/build pipeline dependency updates (actions and Renovate config) rather than application logic changes ([commit list in compare](https://github.com/MShekow/github-app-installation-token/compare/c3ab2a7b94839189ec2fd366eee520a885562688...ae9cbc5fd6979ae2df06b45242c41f5f4afdf133)).

### Local impact

The dependency is used only in `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml` as the `mint-token` initContainer image. That initContainer reads `RENOVATE_GITHUB_APP_PRIVATE_KEY` from Secret `renovate-secrets`, calls GitHub API to mint an installation token, and writes/refreshes Secret `renovate-runtime-token` consumed by Renovate jobs. Related docs and usage context are in `kubernetes/apps/renovate/renovate-operator/jobs/README.md`, and RBAC allowing Secret writes is in `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.rbac.yaml`. Because this sits in auth/token issuance, rollback is straightforward (revert digest) but failure would block Renovate updates until corrected.

### Pre-merge checks

- [ ] Confirm the new digest resolves correctly in registry (already pinned in manifest) and image pull succeeds in cluster.
- [ ] After merge/reconcile, verify CronJob `renovate-github-app-token` completes successfully at least once.
- [ ] Confirm Secret `renovate-runtime-token` is updated and contains non-empty `token` and `RENOVATE_HOST_RULES` keys.
- [ ] Verify a Renovate executor run can authenticate to GitHub (and GHCR/Docker Hub if configured) using refreshed token.

### Evidence reviewed

- PR: `feat(container): update image ghcr.io/mshekow/github-app-installation-token ( 2026.01.15 ➔ 2026.05.22 )`; labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 1 insertion, 1 deletion (`kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml`).
- Files in repo: `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml`, `kubernetes/apps/renovate/renovate-operator/jobs/README.md`, `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.rbac.yaml`.
- Upstream sources checked: `https://github.com/MShekow/github-app-installation-token`, compare API/range for `c3ab2a7...ae9cbc5`, GHCR tags/manifest metadata (`https://ghcr.io/v2/mshekow/github-app-installation-token/tags/list` and manifest/config endpoints), GitHub releases/tags API endpoints.
- Notable uncertainty: No formal release notes/changelog per tag; risk judgment is based on commit/file diff + OCI metadata rather than curated release notes.
