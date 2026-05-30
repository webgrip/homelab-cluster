pr: 293

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR adds an OCI digest pin to the `docker.io/alpine:3.21` image reference in the Dependency Track policy-bootstrap Kubernetes Job, locking it to `sha256:48b0309...` — which is the current multi-arch manifest digest for `alpine:3.21` / `alpine:3.21.7` (pushed 2026-04-17). No version change occurs; the tag `3.21` continues to be used and the digest simply ensures immutable, reproducible pulls. Alpine 3.21.7 includes security patches for musl, openssl, and zlib, so any node that had previously cached an older 3.21.x image will pull the patched version on the next job run. The change is minimal, confined to a one-shot Job, and carries no risk of breaking functionality.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/alpine` | Docker/OCI | `3.21` (no digest) → `3.21@sha256:48b0309...` (= 3.21.7) | digest pin | build/bootstrap (one-shot Job) | Green |

### Important upstream changes

The digest `sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d` resolves to **Alpine Linux 3.21.7**, released 2026-04-15. It consolidates security fixes shipped across minor patch releases 3.21.4 → 3.21.7. Notable security fixes for the versions between the previously unpinned `3.21` state (which resolved to ≤ 3.21.6) and 3.21.7:

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[security]` | **musl CVE-2026-6042** — security fix in musl libc | [Alpine 3.21.7 release](https://alpinelinux.org/posts/Alpine-3.20.10-3.21.7-3.22.4-3.23.4-released.html) | **Yes** — the Job container runs musl-based Alpine and installs/runs packages at job time. Patched digest is preferable. |
| `[security]` | **musl CVE-2026-40200** — security fix in musl libc | [Alpine 3.21.7 release](https://alpinelinux.org/posts/Alpine-3.20.10-3.21.7-3.22.4-3.23.4-released.html) | **Yes** — same as above. |
| `[security]` | **openssl CVE-2026-31790, CVE-2026-28387, CVE-2026-28388, CVE-2026-28389, CVE-2026-28390, CVE-2026-31789** — multiple OpenSSL security fixes | [Alpine 3.21.7 release](https://alpinelinux.org/posts/Alpine-3.20.10-3.21.7-3.22.4-3.23.4-released.html) | **Yes** — the bootstrap script invokes `curl` which links against OpenSSL; running the patched image is safer. |
| `[security]` | **zlib CVE-2026-22184, CVE-2026-27171** — security fixes in zlib | [Alpine 3.21.7 release](https://alpinelinux.org/posts/Alpine-3.20.10-3.21.7-3.22.4-3.23.4-released.html) | **Yes** — zlib is present in the Alpine base image; patched digest is preferable. |
| `[feature]` | Digest pinning itself — supply chain integrity: the image reference is now immutable and cannot be silently replaced by a different image pushed under the same `3.21` tag | N/A | **Yes** — direct improvement to this repo's supply chain security posture. |

> No breaking changes or behavior changes introduced between Alpine 3.21.x patch releases. Alpine's stable branch policy only backports security fixes and critical bugfixes; no API or CLI changes are expected.

### Local impact

- **File changed:** `kubernetes/apps/security/dependency-track/app/policy-bootstrap/job.yaml`
- **Role:** One-shot Kubernetes `batch/v1` Job (`restartPolicy: OnFailure`, `backoffLimit: 3`, `ttlSecondsAfterFinished: 86400`). Re-triggered manually by bumping `policy-revision` annotation. Not part of any steady-state deployment.
- **What alpine does here:** Provides the shell environment; the startup command is `apk add --no-cache curl python3 && /bin/sh /scripts/bootstrap.sh`. Alpine is used only for its shell, `curl`, and `python3` — no Alpine-specific version-sensitive features are relied upon.
- **Security context:** The container does not specify a `securityContext` (runs as root inside the container), which is necessary for `apk add`. The privilege boundary is the pod security policy / namespace security profile, not the image version.
- **Rollback:** Trivial — revert the `@sha256:` suffix. The Job is idempotent; re-running it after a rollback carries no risk of duplicating Dependency Track policies (the script checks for existence before creating).
- **Blast radius:** Narrow — a single bootstrap Job in the `security` namespace. No persistent state is stored in the alpine container; all side effects occur via authenticated REST API calls to the Dependency Track API server.
- **Other alpine image references:** The repository also uses `alpine/k8s`, `alpine/git`, `postgres:...-alpine`, `python:...-alpine`, and `nginxinc/nginx-unprivileged:...-alpine` in other workloads — these are different images and are not affected by this PR.

### Improvement opportunities

- **Add a `securityContext` to the bootstrap Job container** — Alpine 3.21+ supports running as a non-root user with `--no-cache` apk installs via pre-seeded package indexes. Given the bootstrap script only needs curl/python3 and a network call, consider pre-baking a minimal image or using `runAsNonRoot: true` with a non-root variant. This is a hardening opportunity independent of the alpine version but worth noting while touching this file. No upstream release note directly mandates this, but it aligns with supply-chain best practices.
- **Pin the `alpine:3.21` reference to `alpine:3.21.7` (explicit version tag) in addition to the digest** — currently the tag remains `3.21` with a digest. Using `alpine:3.21.7@sha256:48b0309...` makes it immediately obvious which patch release is running without needing to look up the digest. This is a minor readability improvement. [Alpine versioning](https://alpinelinux.org/releases/)

### Grafana dashboards and alerts

No dashboard or alert changes identified. The changed file is a one-shot bootstrap Job that runs shell scripts against the Dependency Track API. No metrics, exporters, or scrape targets are defined in the `policy-bootstrap` directory. The `metrics-exporter` sub-chart (`kubernetes/apps/security/dependency-track/app/metrics-exporter/`) has its own `ServiceMonitor` and does not reference the alpine image.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Metrics / alerts | `metrics-exporter/servicemonitor.yaml` (Dependency Track metrics exporter) | None | The bootstrap Job is ephemeral; no metrics are scraped from the alpine container. |

### Pre-merge checks

- [ ] Confirm that the running cluster's node architecture (amd64, arm64) can pull the multi-arch manifest digest `sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d`. Docker Hub confirms amd64 and arm64 images are present in this manifest; verify if any nodes use a different architecture.
- [ ] If you need to re-trigger the bootstrap Job after merging (to pick up the pinned image), bump `policy-revision` in `job.yaml` as documented in the annotation comment.
- [ ] Run `./scripts/verify-oci-digests.sh <repo-root>` (per CI workflow) to confirm the digest is resolvable from your registry.

### Follow-up

- [ ] **Pin `docker.io/alpine:3.21` in `sbom-uploader/cronjob.yaml`** — `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml` references `docker.io/alpine/k8s:1.36.1` without a digest on the init container named `get-images`. Although that is a different image (`alpine/k8s` vs `alpine`), it is in the same app tree and worth reviewing for digest pinning consistency.
- [ ] **Consider migrating to `alpine:3.22` or `alpine:3.23`** when the policy-bootstrap script is next updated — Alpine 3.21 reaches end-of-life in November 2026. No action needed now, but worth tracking. [Alpine release schedule](https://alpinelinux.org/releases/)

### Evidence reviewed

- **PR:** "chore(container): pin image docker.io/alpine to 48b0309", labels: `area/kubernetes`, `renovate/container`, `dependencies`. Diff: 1 file, 1 line changed (`alpine:3.21` → `alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d`).
- **Files in repo:** `kubernetes/apps/security/dependency-track/app/policy-bootstrap/job.yaml`, `kubernetes/apps/security/dependency-track/app/policy-bootstrap/configmap.yaml`, `kubernetes/apps/security/dependency-track/app/policy-bootstrap/kustomization.yaml`.
- **Upstream sources checked:**
  - Docker Hub tags API: `https://hub.docker.com/v2/repositories/library/alpine/tags?page_size=20&name=3.21` — confirmed `48b0309...` is the manifest digest for `alpine:3.21` and `alpine:3.21.7`, pushed 2026-04-17.
  - Alpine Linux release notes: `https://alpinelinux.org/posts/Alpine-3.20.10-3.21.7-3.22.4-3.23.4-released.html` — confirmed security fixes for musl, openssl, zlib.
  - Alpine release schedule: `https://alpinelinux.org/releases/`
- **Notable uncertainty:** Alpine does not publish a detailed per-package changelog in the release post; the list of CVEs is taken from the release announcement. Intermediate patch releases 3.21.4, 3.21.5 may have contained additional security fixes not enumerated in the 3.21.7 announcement, but no changelog entries were withheld — only the final security summary was available.
