pr: 178

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This is a patch update of the `docker.io/renovate/renovate` container image from `43.181.1-full` to `43.181.2-full`, with the image digest updated to the corresponding SHA256. Upstream changes consist entirely of internal dependency bumps (lint-staged, a GitHub Action, and protobufjs) with no functional or behavioral changes to Renovate itself. The update is safe to merge.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/renovate/renovate` | Docker/OCI | `43.181.1-full → 43.181.2-full` | patch | deploy/infra (Renovate self-hosting via renovate-operator) | Green |

### Important upstream changes

From [v43.181.2 release notes](https://github.com/renovatebot/renovate/releases/tag/43.181.2):

- [bugfix/chore] **deps:** update `lint-staged` to v17.0.4 — internal dev tooling, no runtime impact ([renovatebot/renovate#43396](https://github.com/renovatebot/renovate/issues/43396))
- [bugfix/chore] **deps:** update `zizmorcore/zizmor-action` to v0.5.6 — CI action update, no runtime impact ([renovatebot/renovate#43395](https://github.com/renovatebot/renovate/issues/43395))
- [build] **deps:** update `protobufjs` to v8.2.0 — build-time dependency, no behavioral change expected ([renovatebot/renovate#43397](https://github.com/renovatebot/renovate/issues/43397))

No breaking changes, security advisories, behavior changes, or migration notes were found between `43.181.1` and `43.181.2`.

### Local impact

The image is referenced in exactly one file:

- **`kubernetes/apps/renovate/renovate-operator/jobs/webgrip-gitops.yaml`** — a `RenovateJob` custom resource managed by the renovate-operator. The job runs on a cron schedule (`0 */2 * * *`) with parallelism 1, scanning `webgrip/*` GitHub repositories. It runs as a non-root user (UID/GID 12021), with privilege escalation disabled. Resources are bounded (requests: 250m CPU / 1Gi RAM; limit: 4Gi RAM). The digest is pinned, so this PR replaces the old digest with the new one — supply-chain provenance is maintained.

Rollback is straightforward: revert the commit to restore the prior tag and digest.

### Pre-merge checks

- [ ] Confirm the new digest `sha256:c2c979ecb2bed799de56a57035887509f1ec7b3e39f08d244f0b4e0706b1783b` is present and healthy on Docker Hub (it is — verified via Docker Hub API, pushed 2026-05-16).
- [ ] No special pre-merge checks beyond normal CI.

### Evidence reviewed

- **PR:** "fix(container): update image docker.io/renovate/renovate ( 43.181.1 ➔ 43.181.2 )" — labels: `area/kubernetes`, `renovate/container`, `type/patch`, `dependencies`; 1 file changed, +1/-1
- **Files in repo referencing the image:** `kubernetes/apps/renovate/renovate-operator/jobs/webgrip-gitops.yaml` (sole reference)
- **Upstream sources checked:** PR body release notes (renovatebot/renovate v43.181.2), Docker Hub API (`hub.docker.com/v2/repositories/renovate/renovate/tags`)
- **Notable uncertainty:** GitHub API was rate-limited for unauthenticated release lookups; release notes were sourced from the PR body itself (provided by Renovate bot, which pulls directly from the upstream GitHub release).
