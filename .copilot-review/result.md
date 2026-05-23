pr: 184

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge after checks
**Confidence:** High

### Executive summary

This PR bumps the `busybox` init container image in the InvoiceNinja deployment from `1.37.0` to `1.38.0`, with an updated digest pin. BusyBox 1.38.0 was released on 13 May 2026 and contains a notable security fix (CVE-2023-39810 — path traversal in archival) along with new applets and general improvements. The init container's sole function is to `mkdir` and `chown` storage directories, which does not exercise the changed archival code. Risk is low; the main follow-up is ensuring consistency — three other places in this repo still reference the old 1.37.0 image.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `busybox` | Docker/OCI | `1.37.0@sha256:1487d0af…` → `1.38.0@sha256:b6762ddf…` | minor | init container (runtime) | 🟢 Low |

### Important upstream changes

Release notes sourced from [busybox.net/news.html](https://busybox.net/news.html) (released 13 May 2026):

- **[security]** `archival: disallow path traversals (CVE-2023-39810)` — fixes a path-traversal vulnerability in archive extraction. The `prepare-storage` init container in this repo does **not** extract archives, so there is no direct exposure, but it is good hygiene to take this fix.
- **[feature]** `sha384sum`: new applet added.
- **[feature]** `vmstat`: new `procps` applet added.
- **[feature]** `ssl_server`: new applet added; TLS server-side code implemented.
- **[feature]** `libbb: add yescrypt password hashing support` — new hash algorithm support.
- **[bugfix]** Multiple shell (`ash`/`hush`) fixes including heredoc handling, backslash-newline corner cases, and signal-race fixes.
- **[bugfix]** `cut: fix "-s" flag to omit blank lines`.
- **[bugfix]** `libbb: fix too-narrow variable in procps_read_smaps() causing incorrect sizes`.
- **[bugfix]** `lineedit: fix printing lines during tab completion` and `fix left-over print to stdout`.
- **[behavior]** `libbb: make read_cmdline() replace chars 1..31 with '?'` — control character sanitization in command-line reading.
- **[behavior]** `archival/libarchive: sanitize filenames on output (prevent control sequence attacks)`.

No direct links to individual commits are available from busybox.net, but the full git log for the 1.38 stable branch is at [git.busybox.net/busybox/log/?h=1_38_stable](https://git.busybox.net/busybox/log/?h=1_38_stable).

> **Note:** BusyBox labels its releases as "unstable" on its website — this is a long-standing convention for their development branch/release process and does **not** indicate a pre-release or beta status for the Docker image. The `1.38.0` tag on Docker Hub is an official release.

### Local impact

The busybox image is used as an **init container** (`prepare-storage`) in:

- `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` (this PR) — runs:
  ```sh
  mkdir -p /storage/storage/app/public /storage/logo
  chown -R 1500:1500 /storage
  ```
  This is a minimal, stateless filesystem-setup operation. The container completes and exits before the main workload starts. No archival, network, or TLS operations are performed, so none of the security-relevant new code paths are exercised.

**Consistency gap — not covered by this PR:** The same `1.37.0` image (same digest) is also referenced in:
- `kubernetes/apps/minecraft/minecraft/app/helmrelease.yaml` — two init containers (`geyser-config-sync`, `bluemap-config-sync`)
- `kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml` — one init container (`config-sync`)

These will remain on `1.37.0` after this PR merges. Consider opening or checking for follow-up Renovate PRs to update those.

**Digest pin:** Both old and new images are pinned with SHA-256 digests, which is best practice for supply-chain integrity. The digest change from `sha256:1487d0af…` to `sha256:b6762ddf…` is expected and correct for a version bump.

### Pre-merge checks

- [ ] Confirm `busybox:1.38.0@sha256:b6762ddf4a50aabb5f4d21aa6f447d05d5633fb09f09c08b33f22356a2f98be0` resolves correctly (e.g., `docker manifest inspect busybox:1.38.0@sha256:b6762ddf4a50aabb5f4d21aa6f447d05d5633fb09f09c08b33f22356a2f98be0`).
- [ ] Verify Flux reconciles the InvoiceNinja deployment successfully after merge (watch for init container failures or `ImagePullBackOff`).
- [ ] Check that the `prepare-storage` init container completes successfully post-deploy (storage directories created, ownership set correctly).
- [ ] Track consistency: ensure Renovate also opens PRs for `busybox` in `kubernetes/apps/minecraft/` and `kubernetes/apps/zomboid/` — or manually update them.

### Evidence reviewed

- **PR:** `feat(container): update image busybox ( 1.37.0 ➔ 1.38.0 )`, labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`. Diff: 1 file changed, 1 addition, 1 deletion — only the image tag+digest in the init container.
- **Files in repo referencing busybox:**
  - `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` (this PR)
  - `kubernetes/apps/minecraft/minecraft/app/helmrelease.yaml` (still on 1.37.0)
  - `kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml` (still on 1.37.0)
  - `kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml` (references `busybox`-style date syntax in shell script, not an image)
- **Upstream sources checked:**
  - [busybox.net/news.html](https://busybox.net/news.html) — full changelog for 1.38.0
  - [hub.docker.com/v2/repositories/library/busybox/tags?name=1.38](https://hub.docker.com/v2/repositories/library/busybox/tags?name=1.38) — confirmed 1.38.0 tag exists and was recently pushed (2026-05-22)
- **Notable uncertainty:** The multi-arch manifest list digest in the PR (`sha256:b6762ddf…`) could not be independently verified via Docker Hub API (which returns platform-specific digests separately); Renovate's digest should be treated as authoritative.
