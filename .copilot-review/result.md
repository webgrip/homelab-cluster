pr: 187

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR updates the busybox container image from `1.37.0` to `1.38.0` (minor version bump, released 13 May 2026). The images are used exclusively as init containers performing simple config-sync operations (`sh`, `mkdir -p`, `cp -f`). The update includes a CVE-2023-39810 path-traversal fix in archival tools (tar/cpio), which are not exercised by these init containers. Digest pinning is maintained, the scope is narrow, and no breaking changes affect the command set in use. Safe to merge.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/library/busybox` | Docker/OCI | `1.37.0@sha256:1487d0af…` → `1.38.0@sha256:b6762ddf…` | minor | init container (config-sync) | Green |

### Important upstream changes

Full changelog: [busybox.net/news.html](https://busybox.net/news.html) — 1.38.0 released 2026-05-13, labelled "unstable" per busybox's standard release naming.

- **[security]** `archival: disallow path traversals (CVE-2023-39810)` — tar/cpio path-traversal vulnerability now blocked. Not exercised in this repo (no archival applets used). ([busybox.net news](https://busybox.net/news.html))
- **[security]** `archival/libarchive: sanitize filenames on output (prevent control sequence attacks)` — related hardening of archive output. Again, not used by these containers.
- **[bugfix]** `cp: fix cp -aT overwriting symlink to directories` — behaviour fix for `cp -aT` flag combination. This repo's init containers use `cp -f` (not `-aT`), so no impact.
- **[bugfix]** `ash,hush: fix race between signal handlers setting bb_got_signal and poll()` — shell signal-handling race fix. Low impact for short-lived init containers.
- **[bugfix]** `ash,hush: fix corner cases with backslash-newlines in heredocs` — heredoc edge-case fix; not used in these scripts.
- **[bugfix]** `ash: parser: Invalid redirections are run-time, not syntax errors` — minor parser semantic change; does not affect the `set -eu` / `cp` / `mkdir` pattern in use.
- **[feature]** `sha384sum: new applet`, `procps: new applet: vmstat`, `ssl_server: new applet` — new applets not used by any init container here.
- **[feature]** `busybox: optional --version support` — cosmetic.

No release notes were found that introduce breaking changes to `sh`, `mkdir`, or `cp -f` as used by these init containers.

### Local impact

Busybox is used in **three** workloads as an init container for config-sync:

1. **`kubernetes/apps/minecraft/minecraft/app/helmrelease.yaml`** — two init containers (`geyser-config-sync`, `bluemap-config-sync`) that run `sh -c 'set -eu; mkdir -p …; cp -f …'` to copy ConfigMap-mounted YAML files into the game server's `/data` directory before startup.
2. **`kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml`** — one init container (`config-sync`) that runs `sh -c 'set -eu; … for file in … cp -f …'` to seed the Zomboid server config directory from a ConfigMap.

Both workloads use `Recreate` strategy and have `existingClaim` persistent storage. The init containers are stateless (read-only ConfigMap source → writable PVC destination) and do not manage state themselves, so rollback risk is low.

**⚠️ Two other busybox references in this repo are NOT updated by this PR:**
- `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` — still pinned to `busybox:1.37.0@sha256:1487d0af…`
- `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml` — still references `busybox` (1.37.0 digest)

These are not blocking, but a follow-up PR to keep all busybox references consistent would be worthwhile.

### Pre-merge checks

- [x] Digest is pinned in all changed files — provenance is verifiable.
- [ ] Confirm Flux reconciles both `minecraft` and `zomboid` HelmReleases successfully after merge (watch `flux get helmreleases -A`).
- [ ] Verify Minecraft init containers (`geyser-config-sync`, `bluemap-config-sync`) complete without error in pod events / logs post-deploy.
- [ ] Verify Zomboid `config-sync` init container completes without error post-deploy.
- [ ] Optional: open a follow-up PR to update `invoiceninja` and `renovate-operator` busybox references to `1.38.0` for consistency.

### Evidence reviewed

- **PR:** `feat(container): update image docker.io/library/busybox ( 1.37.0 ➔ 1.38.0 )` — labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; 2 files changed, 3 additions, 3 deletions; automerge disabled.
- **Files in repo:** `kubernetes/apps/minecraft/minecraft/app/helmrelease.yaml`, `kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml` (changed); `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml`, `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml` (unchanged, still on 1.37.0).
- **Upstream sources checked:** [busybox.net/news.html](https://busybox.net/news.html) (full 1.38.0 changelog retrieved); [hub.docker.com/v2/repositories/library/busybox/tags](https://hub.docker.com/v2/repositories/library/busybox/tags) (confirmed `1.38.0` tag exists and was pushed 2026-05-22).
- **Notable uncertainty:** Busybox labels all major releases "unstable" as part of its standard naming convention — this does not indicate instability relative to 1.37.0; both carry the same quality tier.
