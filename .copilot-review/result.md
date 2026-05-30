pr: 326

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates one runtime image in the Dependency-Track policy bootstrap Job from `docker.io/alpine:3.21` to `docker.io/alpine:3.23` and adds a pinned manifest digest. Upstream Alpine 3.23 introduces `apk-tools` v3 and several distro-level behavior changes; this repo’s affected path is the bootstrap container’s `apk add --no-cache curl python3` step. The blast radius is limited to a one-shot security policy bootstrap Job in `security`, but if package-manager behavior changes unexpectedly, policy bootstrapping can fail. Merge is reasonable after a focused runtime smoke check of the Job.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/alpine` | Docker/OCI | `3.21 → 3.23@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11` | minor (skips 3.22) + digest pin | runtime (Kubernetes Job init image) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[behavior]` | Alpine 3.23 transitions stable branch to `apk-tools` v3 (with compatibility notes and changed package-manager internals). | [source](https://wiki.alpinelinux.org/wiki/Release_Notes_for_Alpine_3.23.0#apk-tools), [apk v3 release notes](https://gitlab.alpinelinux.org/alpine/apk-tools/-/releases/v3.0.0) | **Yes** — this Job installs packages at runtime via `apk add --no-cache curl python3` in `policy-bootstrap/job.yaml`. |
| `[migration]` | Alpine 3.22 flagged upcoming `apk-tools` v3 in 3.23 as a notable transition. | [source](https://wiki.alpinelinux.org/wiki/Release_Notes_for_Alpine_3.22.0#apk-tools) | **Yes** — confirms this update crosses the planned package-manager transition boundary used by the Job startup command. |
| `[behavior]` | Alpine 3.23 introduces optional `/usr`-merge workflows and related migration guidance. | [source](https://wiki.alpinelinux.org/wiki/Release_Notes_for_Alpine_3.23.0#/usr_merge), [announcement](https://alpinelinux.org/posts/2025-10-01-usr-merge.html) | **No** — this repo consumes the stock container image for short-lived Job execution and does not perform in-image OS migration workflows. |
| `[feature]` | Alpine 3.23 significant changes include curl HTTP/3 support from aports packaging updates. | [source](https://wiki.alpinelinux.org/wiki/Release_Notes_for_Alpine_3.23.0#curl_HTTP/3), [MR 89382](https://gitlab.alpinelinux.org/alpine/aports/-/merge_requests/89382) | **No** — bootstrap script uses standard HTTP calls to an internal service and does not rely on HTTP/3 behavior. |
| `[unknown]` | Alpine announcement pages summarize many upgraded components but do not provide complete per-package break/fix mapping specific to `curl`/`python3` installation path used here. | [3.22 announcement](https://alpinelinux.org/posts/Alpine-3.22.0-released.html), [3.23 announcement](https://alpinelinux.org/posts/Alpine-3.23.0-released.html) | **Unknown** — no upstream note explicitly ties this update to breakage for the exact `apk add curl python3` bootstrap path. |

### Local impact

- PR touches one file: `kubernetes/apps/security/dependency-track/app/policy-bootstrap/job.yaml`.
- Container command is `apk add --no-cache curl python3 && /bin/sh /scripts/bootstrap.sh`; so image-level package-manager behavior directly controls whether policy bootstrap starts.
- Job uses `dependency-track-api-key` secret and writes security policies via API (ConfigMap script at `.../policy-bootstrap/configmap.yaml`), so failure means policy baseline drift rather than app downtime.
- Workload is short-lived (`Job`, `restartPolicy: OnFailure`, `backoffLimit: 3`) and not stateful; rollback is straightforward by reverting image tag/digest.

### Improvement opportunities

- **Pin all Alpine image usages to immutable digests consistently** — this PR pins digest for `policy-bootstrap`; other Alpine-derived images in repo include both pinned and unpinned forms. Extending digest pinning reduces supply-chain drift and aligns with reproducibility goals. ([Docker Hub tag metadata for 3.23 digest](https://hub.docker.com/v2/repositories/library/alpine/tags/3.23))

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard / Alert / Metric / Scrape config | Dependency-Track observability exists (`kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-security-dt.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/security-dependency-track.yaml`, `kubernetes/apps/observability/grafana/app/alerting/slo-security.yaml`) but tracks Dependency-Track metrics, not the Alpine bootstrap container | None | Alpine base-image update changes bootstrap runtime only; no upstream metric schema change or exporter contract change identified for this path. |

### Pre-merge checks

- [ ] Reconcile/run `dt-policy-bootstrap` Job in a non-prod or controlled window and confirm `apk add --no-cache curl python3` succeeds on Alpine 3.23.
- [ ] Confirm Job logs end with successful policy creation/existence checks (`P1..P10`) and no API/auth errors.
- [ ] Verify no unexpected drift in security alerts after bootstrap run (Dependency-Track rules/dashboard remain populated as before).

### Follow-up

- [ ] Consider replacing runtime `apk add` with a prebuilt minimal bootstrap image containing `curl` + `python3` — reduces startup variability from package-manager/repository changes across Alpine releases.
- [ ] Review other `docker.io/alpine` references for consistent digest pinning policy (`kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml`, `kubernetes/apps/security/guac/app/sample-data-job.yaml`).

### Evidence reviewed

- PR: `feat(container): update image docker.io/alpine ( 3.21 ➔ 3.23 )`; labels `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 1 insertion, 1 deletion.
- Files in repo: `kubernetes/apps/security/dependency-track/app/policy-bootstrap/job.yaml`, `kubernetes/apps/security/dependency-track/app/policy-bootstrap/configmap.yaml`, `kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml`, `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-security-dt.yaml`, `kubernetes/apps/observability/grafana/app/dashboards/security-dependency-track.yaml`, `kubernetes/apps/observability/grafana/app/alerting/slo-security.yaml`.
- Upstream sources checked: `https://hub.docker.com/v2/repositories/library/alpine/tags/3.21`, `https://hub.docker.com/v2/repositories/library/alpine/tags/3.22`, `https://hub.docker.com/v2/repositories/library/alpine/tags/3.23`, `https://alpinelinux.org/posts/Alpine-3.22.0-released.html`, `https://alpinelinux.org/posts/Alpine-3.23.0-released.html`, `https://wiki.alpinelinux.org/wiki/Release_Notes_for_Alpine_3.22.0`, `https://wiki.alpinelinux.org/wiki/Release_Notes_for_Alpine_3.23.0`, `https://gitlab.alpinelinux.org/alpine/apk-tools/-/releases/v3.0.0`.
- Notable uncertainty: Alpine release notes are distro-wide summaries; no explicit upstream issue/commit was found that directly validates or breaks this repo’s exact `apk add curl python3` bootstrap invocation.
