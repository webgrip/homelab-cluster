pr: 223

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR adds a SHA-256 digest pin (`@sha256:27985295...`) to an already-pinned `nginxinc/nginx-unprivileged:1.29.1-alpine` tag used as the nginx sidecar in the InvoiceNinja deployment. There is **no version change** — it is a `pinDigest` operation only. The pinned digest matches the current digest that Docker Hub reports for `1.29.1-alpine` (last pushed 2025-10-10). This is a pure supply-chain-security improvement with zero functional risk.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `nginxinc/nginx-unprivileged` | Docker/OCI | `1.29.1-alpine` → `1.29.1-alpine@sha256:2798529…` | digest pin (no version bump) | runtime sidecar (InvoiceNinja web container) | Green |

### Important upstream changes

No upstream version change. This PR only adds a digest pin to the existing `1.29.1-alpine` tag — it does not upgrade the image. No changelog entries apply.

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[feature]` | Digest pinning: image will be pulled by immutable content address | [Docker Hub tag](https://hub.docker.com/r/nginxinc/nginx-unprivileged/tags?name=1.29.1-alpine) | **Yes** — prevents silent tag-mutable pulls; no behavior change |

> **Note:** Newer versions (`1.29.2`, `1.29.3`, `1.29.4`) exist on Docker Hub, but they are out-of-scope for this pinDigest PR. A separate version-bump PR should be expected from Renovate.

### Local impact

`nginxinc/nginx-unprivileged` is used exclusively as the `web` container in the InvoiceNinja deployment:

- **File:** `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` (container `web`, line ~190)
- **Role:** Serves static InvoiceNinja PHP-FPM output via nginx on port 8080. Mounts an nginx configmap (`invoiceninja-nginx`), the app-data emptyDir, and the storage PVC (read-only).
- **Privilege:** Runs as non-root (nginx-unprivileged). No special capabilities or host-path mounts.
- **State:** Stateless reverse-proxy sidecar; no persistent state of its own.
- **Rollback:** Simple — revert one line in the deployment manifest and let Flux reconcile.

Pinning by digest eliminates the risk of pulling a different binary if the mutable tag were ever overwritten on Docker Hub. The actual running container is **identical** before and after this merge.

### Improvement opportunities

- **Consider upgrading to `1.29.4-alpine`** — Three patch releases (`1.29.2`, `1.29.3`, `1.29.4`) have shipped since `1.29.1` (released 2025-10-10). Renovate should propose a separate version-bump PR; if it has not, check the Renovate config to ensure version updates for this image are enabled alongside digest pinning. [Docker Hub tag listing](https://hub.docker.com/r/nginxinc/nginx-unprivileged/tags?name=1.29)

### Grafana dashboards and alerts

No dashboard or alert changes identified. No Prometheus metrics, ServiceMonitors, PrometheusRules, or Grafana dashboard files referencing `nginx-unprivileged` (or its metrics) were found in this repository. The container is a pure sidecar with no metrics exporter configured.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Metrics / Dashboards | None found | None | nginx-unprivileged sidecar has no metrics endpoint configured in this repo |

### Pre-merge checks

- [ ] Confirm the pinned digest `sha256:27985295bdb22a1ef8f712863210bd5877c0f3006494a593e86b3fe0fa55467e` matches the multi-arch manifest index for `1.29.1-alpine` on Docker Hub (verified: matches as of 2026-05-24).
- [ ] Verify InvoiceNinja pod rolls over cleanly after merge (readiness probe on `/health:8080` will confirm).

### Follow-up

- [ ] Track Renovate version-bump PR for `nginxinc/nginx-unprivileged 1.29.1 → 1.29.4` (three patch releases available) — [Docker Hub](https://hub.docker.com/r/nginxinc/nginx-unprivileged/tags?name=1.29)

### Evidence reviewed

- **PR:** "chore(container): pin image nginxinc/nginx-unprivileged to 2798529" — labels: `area/kubernetes`, `renovate/container`, `dependencies` — 1 file changed, 1 insertion/1 deletion
- **Files in repo:** `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` (only reference to `nginx-unprivileged` in the repo)
- **Upstream sources checked:**
  - Docker Hub API: `https://hub.docker.com/v2/repositories/nginxinc/nginx-unprivileged/tags/1.29.1-alpine` — confirmed digest `sha256:27985295bdb22a1ef8f712863210bd5877c0f3006494a593e86b3fe0fa55467e`, last pushed 2025-10-10
  - GitHub releases: `https://api.github.com/repos/nginx/docker-nginx-unprivileged/releases` — confirmed `1.29.1` released 2025-10-10; newer releases exist up to `1.29.4`
- **Notable uncertainty:** None — digest pinning is deterministic and low risk.
