pr: 341

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates the runtime container image for n8n from `2.22.2` to `2.23.0`, including a digest change, in a single HelmRelease value. Upstream notes show many fixes/features in `2.23.0` plus intermediate `2.22.3` and `2.22.4` bugfixes; no explicit breaking/migration notes were published in this range. Risk is mainly operational: this repo runs n8n as a stateful workload (PVC + external Postgres) and exposes it via HTTPRoute, so behavior regressions can impact active automations and webhooks. Merge is reasonable with targeted smoke checks after rollout.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `n8nio/n8n` | Docker/OCI | `2.22.2@sha256:bf26d48...` → `2.23.0@sha256:8978cc9...` | minor | runtime (app workload) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[security]` | urllib3 upgraded to address security issue (`2.6.3` → `2.7.0` in packages). | [source](https://github.com/n8n-io/n8n/commit/6eb6628ea1aa61ccd6884df5dc786e8764096f89) | **Yes** — runtime image contains this dependency update. |
| `[behavior]` | Binary-data temp directory cleanup behavior changed (fix to avoid aggressive cleanup). | [source](https://github.com/n8n-io/n8n/commit/978840db54cb6c27596b661fafe6af8bb734180b) | **Unknown** — impact depends on whether workflows process/rename binary data. |
| `[behavior]` | Scheduled poll expression isolate handling/failure reporting updates in this release range. | [source](https://github.com/n8n-io/n8n/releases/tag/n8n%402.22.3) | **Unknown** — repo does not track workflow definitions here; cannot confirm scheduled poll usage. |
| `[behavior]` | Dynamic credential OAuth callback behavior adjusted (no skip-auth env var requirement). | [source](https://github.com/n8n-io/n8n/commit/cf1a6fa18cc96ea2b1be8307edce8f00b28b6163) | **Unknown** — may matter if OAuth credential flows are used in this n8n instance. |
| `[behavior]` | Webhook CORS preflight now uses active workflow version. | [source](https://github.com/n8n-io/n8n/commit/979a53baa43b0b7b2031c21763eee44d09e831ab) | **Yes** — this deployment exposes webhook/editor URLs via `HTTPRoute`. |
| `[feature]` | New API/editor/core features in 2.23.0 (workflow groups, redaction controls, AI/agent improvements, etc.). | [source](https://github.com/n8n-io/n8n/releases/tag/n8n%402.23.0) | **Unknown** — feature usage depends on enabled n8n capabilities and existing workflows. |

### Local impact

`n8nio/n8n` is referenced in one runtime path: `kubernetes/apps/n8n/n8n/app/helmrelease.yaml` (container image tag). n8n is deployed with `strategy: Recreate`, persistent storage (`kubernetes/apps/n8n/n8n/app/pvc.yaml`), and an external Postgres cluster (`kubernetes/apps/n8n/n8n/app/database/cluster.yaml`), so upgrade failures can cause downtime and workflow interruption even without data loss. The service is externally routed (`kubernetes/apps/n8n/n8n/app/httproute.yaml`) and has secure-cookie/proxy settings in `kubernetes/apps/n8n/n8n/app/configmap-env.yaml`; regressions in auth/webhook/OAuth behavior have immediate user-facing impact. Kyverno policy exceptions for this deployment (`kubernetes/apps/kyverno/policies/app/exception-third-party-images.yaml`, `.../exception-third-party-workloads.yaml`) indicate reduced hardening constraints versus first-party workloads.

### Improvement opportunities

- **Enable targeted post-upgrade checks for webhook and OAuth credential flows** — 2.23.0 includes webhook/CORS and dynamic OAuth callback behavior changes that are easy to regress in real workflows ([source](https://github.com/n8n-io/n8n/commit/979a53baa43b0b7b2031c21763eee44d09e831ab), [source](https://github.com/n8n-io/n8n/commit/cf1a6fa18cc96ea2b1be8307edce8f00b28b6163)).
- **Review binary-data-heavy workflows after upgrade** — upstream explicitly changed temp-file cleanup/rename behavior in this range ([source](https://github.com/n8n-io/n8n/commit/978840db54cb6c27596b661fafe6af8bb734180b)).

### Grafana dashboards and alerts

No dashboard or alert changes identified. I found no n8n-specific references in `kubernetes/apps/observability/**`, and upstream release notes for this range do not call out n8n metric name/label changes.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard / Alert / Metric / Scrape config | none found for n8n in `kubernetes/apps/observability/**` | None | No n8n observability objects in-repo; no metric schema change called out in upstream notes ([release](https://github.com/n8n-io/n8n/releases/tag/n8n%402.23.0)). |

### Pre-merge checks

- [ ] Confirm rendered manifest updates only the n8n image tag/digest (`kubernetes/apps/n8n/n8n/app/helmrelease.yaml`).
- [ ] After deploy, run a smoke test for one webhook-triggered workflow and one scheduled workflow execution.
- [ ] Validate login/editor access and at least one OAuth-backed credential flow in the n8n UI.
- [ ] Check pod logs for binary-data temp-file/rename warnings or new execution errors during first hours after rollout.

### Follow-up

- [ ] Add/confirm n8n-specific availability/error observability (dashboard panel and/or alert) — current observability tree contains no explicit n8n monitoring objects (`kubernetes/apps/observability/**`).
- [ ] Track removal of broad third-party workload/image exceptions for n8n when upstream chart allows stricter security controls (`kubernetes/apps/kyverno/policies/app/exception-third-party-images.yaml`, `kubernetes/apps/kyverno/policies/app/exception-third-party-workloads.yaml`).

### Evidence reviewed

- PR: `feat(container): update image n8nio/n8n ( 2.22.2 ➔ 2.23.0 )`; labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 1 addition, 1 deletion.
- Files in repo: `kubernetes/apps/n8n/n8n/app/helmrelease.yaml`, `kubernetes/apps/n8n/n8n/app/configmap-env.yaml`, `kubernetes/apps/n8n/n8n/app/httproute.yaml`, `kubernetes/apps/n8n/n8n/app/pvc.yaml`, `kubernetes/apps/n8n/n8n/app/database/cluster.yaml`, `kubernetes/apps/kyverno/policies/app/exception-third-party-images.yaml`, `kubernetes/apps/kyverno/policies/app/exception-third-party-workloads.yaml`.
- Upstream sources checked: `https://github.com/n8n-io/n8n/releases/tag/n8n%402.22.3`, `https://github.com/n8n-io/n8n/releases/tag/n8n%402.22.4`, `https://github.com/n8n-io/n8n/releases/tag/n8n%402.23.0`, `https://api.github.com/repos/n8n-io/n8n/releases/tags/n8n%402.22.3`, `https://api.github.com/repos/n8n-io/n8n/releases/tags/n8n%402.22.4`, `https://api.github.com/repos/n8n-io/n8n/releases/tags/n8n%402.23.0`, `https://hub.docker.com/v2/repositories/n8nio/n8n/tags/2.22.2`, `https://hub.docker.com/v2/repositories/n8nio/n8n/tags/2.23.0`.
- Notable uncertainty: `2.23.0` release notes are cumulative from `2.22.0`, so not every listed item is guaranteed to be newly introduced after `2.22.2` without deeper commit-by-commit filtering.
