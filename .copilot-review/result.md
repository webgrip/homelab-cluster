pr: 162

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR updates the Renovate self-hosted runner image from `43.104.11-full` to `43.181.1-full` — 77 patch/minor releases over approximately three weeks. No breaking changes were found across any intermediate release. The update is digest-pinned, providing strong provenance assurance. The primary risk is the large number of skipped versions, but the Renovate project follows strict semantic versioning with explicit `[breaking]` tagging and none appear in this range.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/renovate/renovate` | Docker/OCI | `43.104.11-full → 43.181.1-full` | minor (77 releases) | deploy/infra — self-hosted Renovate runner in Kubernetes CronJob | Green |

### Important upstream changes

Notable changes across the 77 intermediate versions (no breaking changes found):

- `[feature]` **43.105.0** — New Apache Ant manager for inline version extraction
- `[feature]` **43.107.0** — Onboarding: "Add your custom config" made more prominent in PR descriptions
- `[feature]` **43.108.0** — GitHub Actions: Zizmor version auto-extraction
- `[feature]` **43.111.0** — npm: Trim response data before caching (reduces cache size)
- `[feature]` **43.112.0** — Maven: `writeSchema` added to cache provider
- `[feature]` **43.115.0** — `packageRules.bumpVersions.type` sync support
- `[feature]` **43.116.0** — OSV: Malicious packages now marked with `skipReason`
- `[feature]` **43.117.0** — In-memory expiry map added to package file cache; Bitbucket Pipelines shared config support
- `[feature]` **43.120.0** — Vulnerability: severity and CVSS details added to GitHub Dependabot alerts
- `[feature]` **43.123.0** — New XcodeGen manager for Swift package dependencies
- `[behavior]` **43.124.0** — `manager/github-actions`: default versioning changed to `semver-partial` (may generate new PRs for GitHub Actions pins already in the repo)
- `[feature]` **43.128.0** — Vulnerability PRs now include GHSA ID, summary, and references
- `[feature]` **43.129.0** — New `github-actions` versioning scheme added
- `[feature]` **43.173.0** — Renovate now logs the resolved configuration (without internal presets) — useful for debugging
- `[bugfix]` **43.170.2** — GitHub: retry assigning reviewers after a delay (reduces assignment failures)
- `[bugfix]` **43.170.3** — Revert of git rebase/amend commit detection (stability fix)
- `[bugfix]` **43.177.0** — Cache: SQLite busy timeout increased 100ms → 5000ms (reduces lock contention on busy runners)
- `[bugfix]` **43.177.1** — Vulnerability: `datasource` now correctly set when overriding `allowedVersions`
- `[bugfix]` **43.177.5** — GitHub: commit message set explicitly for platform automerge
- `[bugfix]` **43.177.7** — Config validator: warnings now flush before `process.exit`
- `[bugfix]` **43.180.2** — `GlobalConfig.get` now returns default values correctly (fixes issue #39949)
- `[feature]` **43.181.0** — Swift: SSH URLs now supported in `Package.swift`

### Local impact

The dependency is used in exactly one file:

**`kubernetes/apps/renovate/renovate-operator/jobs/webgrip-gitops.yaml`**

- Defines a `RenovateJob` CRD (managed by `renovate-operator`) that runs Renovate as a Kubernetes CronJob every 2 hours.
- The image is digest-pinned (`@sha256:c8c590aba5ed196603205bfe690ee84dfc70eccfc49e4f0fd4aa974e6e384ea4`), confirming image integrity.
- Renovate runs as non-root (`runAsUser: 12021`), with `allowPrivilegeEscalation: false` — strong security posture.
- Targets all `webgrip/*` GitHub repos for dependency scanning.
- Config file mounted from `renovate-config-gitops` ConfigMap; secrets via `renovate-runtime-token` and `renovate-webhook-auth`.
- The `NODE_OPTIONS: --max-old-space-size=3000` and memory limit of 4Gi remain appropriate; no memory model changes found in the update.
- The **`semver-partial` default versioning change for `manager/github-actions`** (43.124.0) is the most impactful behavioral change: if this repo or managed repos rely on the old versioning scheme for Actions pins, new PRs may be generated on next run. This is additive, not destructive.
- The **resolved-config logging** (43.173.0) will produce slightly more verbose logs; no operational impact.
- The **SQLite busy timeout increase** (43.177.0) is a positive reliability improvement for the multi-repo scanning pattern used here.
- **Pending:** The Renovate PR notes `43.195.0-full (+34)` is already available, so another update PR will follow shortly.

### Pre-merge checks

- [x] Image digest is pinned in the PR — provenance verified.
- [ ] After merge, confirm the next Renovate CronJob run completes without errors (check pod logs via `kubectl logs` in the `renovate` namespace).
- [ ] If GitHub Actions version PRs start appearing with unexpected changes (due to `semver-partial` default), verify this is intentional behavior for the managed repos.
- [ ] No config migration steps required — all changes are additive or bugfix-only.

### Evidence reviewed

- **PR:** "feat(container): update image docker.io/renovate/renovate ( 43.104.11 ➔ 43.181.1 )" — 1 file changed, digest-pinned image update in `RenovateJob` manifest
- **Files in repo:** `kubernetes/apps/renovate/renovate-operator/jobs/webgrip-gitops.yaml` (sole consumer)
- **Upstream sources checked:**
  - `https://api.github.com/repos/renovatebot/renovate/releases?per_page=100` (pages 1–3, covering all 77 intermediate versions)
  - Full release bodies reviewed for `### Breaking Changes` and `### Features` sections across all 77 releases
- **Notable uncertainty:** None — release notes were complete and available for all intermediate versions; no breaking changes found.
