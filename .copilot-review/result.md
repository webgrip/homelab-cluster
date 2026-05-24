pr: 247

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

PR #247 updates the Invoice Ninja web sidecar image from `nginxinc/nginx-unprivileged:1.29.1-alpine` to `1.31.0-alpine` (digest-pinned). This is a multi-version jump that includes multiple upstream security fixes and HTTP behavior changes in NGINX mainline, but local usage is limited to a single unprivileged nginx container serving FastCGI in one namespace. The primary risk is request-handling behavior drift (header/request validation and keepalive/proxy defaults in newer NGINX), not broad platform blast radius. Merge is reasonable after a focused runtime smoke test and log check.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `nginxinc/nginx-unprivileged` | Docker/OCI | `1.29.1-alpine@sha256:27985295...` → `1.31.0-alpine@sha256:3707417e...` | minor (multi-version jump) | runtime/infra | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[security]` | NGINX 1.31.0 includes multiple CVE fixes (HTTP/2 proxy body injection, rewrite/scgi/uwsgi/charset overread/overflow, QUIC migration, OCSP DNS response processing). | [source](https://nginx.org/en/CHANGES) | **Unknown** — local config does not obviously enable all affected directives/modules; changelog does not map each CVE to exact config prerequisites in this repo. |
| `[behavior]` | NGINX now rejects HTTP/2/HTTP/3 requests carrying forbidden connection headers or invalid `TE` values. | [source](https://nginx.org/en/CHANGES) | **Yes** — this nginx serves client traffic for Invoice Ninja; stricter request validation can change client/proxy compatibility behavior. |
| `[behavior]` | Host/port validation changed to RFC 3986 semantics (1.29.4). | [source](https://nginx.org/en/CHANGES) | **Yes** — this deployment handles external HTTP traffic, so stricter host validation may reject previously-tolerated malformed requests. |
| `[feature]` | `ngx_http_proxy_module` HTTP/2 support added (1.29.4). | [source](https://nginx.org/en/CHANGES) | **No** — local `nginx-configmap.yaml` uses FastCGI to `127.0.0.1:9000`, not proxying upstream HTTP backends. |
| `[behavior]` | Keepalive defaults changed (`upstream keepalive`/proxy keepalive defaults adjusted in 1.29.7). | [source](https://nginx.org/en/CHANGES) | **No** — local nginx site config does not define `upstream` blocks or proxy directives for app traffic. |
| `[unknown]` | `nginx/docker-nginx-unprivileged` GitHub releases are visible only through 1.29.4, while Docker Hub carries 1.31.0 tags; image-layer release notes for the full jump are not fully published in one place. | [source](https://github.com/nginx/docker-nginx-unprivileged/releases) | **Unknown** — missing image-specific changelog detail lowers confidence for base-image/package-level changes. |


### Local impact

`nginxinc/nginx-unprivileged` is referenced once in this repo: `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` (`web` container). It serves Invoice Ninja static/PHP front-end traffic on port 8080 with a custom config from `kubernetes/apps/invoiceninja/invoiceninja/app/nginx-configmap.yaml` and FastCGI passthrough to local php-fpm (`127.0.0.1:9000`).

This workload is stateless at the nginx layer (PVC-backed storage is for app data, shared with app containers), runs unprivileged image defaults, and rollback is straightforward by reverting the image tag/digest in Git. Blast radius is constrained to the `invoiceninja` namespace and the Invoice Ninja HTTP route.

### Improvement opportunities

- **None identified.**

### Grafana dashboards and alerts

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | `kubernetes/apps/invoiceninja/invoiceninja/app/dashboards/apps-invoiceninja.yaml` (pod health/restarts/cpu/memory/PVC only) | None | No nginx-version-specific metric rename/removal documented for this image update; dashboard is Kubernetes resource-level, not nginx internals. [source](https://nginx.org/en/CHANGES) |
| Alert / Metric / Scrape config | No Invoice Ninja-specific `PrometheusRule`, `ServiceMonitor`, or `PodMonitor` for nginx internals found | None | This update changes nginx runtime image version only; repo does not currently scrape nginx exporter metrics for this workload. |

### Pre-merge checks

- [ ] Reconcile PR branch manifests in a test cluster and confirm `invoiceninja` deployment rollout succeeds with `web` container Ready on `/health`.
- [ ] Smoke-test Invoice Ninja UI/API path via `invoice.webgrip.dev` (login + one normal page load) to catch request/header validation regressions.
- [ ] Check nginx container logs after rollout for new request parsing/invalid-header errors.
- [ ] Confirm rollback path by keeping prior digest (`1.29.1-alpine@sha256:27985295...`) ready if issues appear.

### Follow-up

- [ ] Track upstream image metadata continuity for `nginxinc/nginx-unprivileged` 1.30/1.31 tags (missing corresponding GitHub release entries at review time) to improve future review confidence — https://github.com/nginx/docker-nginx-unprivileged/releases

### Evidence reviewed

- PR: `feat(container): update image nginxinc/nginx-unprivileged ( 1.29.1 ➔ 1.31.0 )`; labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff: 1 file, 1-line image+digest update in `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml`.
- Files in repo: `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml`, `kubernetes/apps/invoiceninja/invoiceninja/app/nginx-configmap.yaml`, `kubernetes/apps/invoiceninja/invoiceninja/app/dashboards/apps-invoiceninja.yaml`, plus repo-wide string search results for `nginxinc/nginx-unprivileged` and `invoiceninja`.
- Upstream sources checked: https://github.com/nginx/docker-nginx-unprivileged/releases, https://api.github.com/repos/nginx/docker-nginx-unprivileged/tags, https://hub.docker.com/v2/repositories/nginxinc/nginx-unprivileged/tags/1.29.1-alpine, https://hub.docker.com/v2/repositories/nginxinc/nginx-unprivileged/tags/1.31.0-alpine, https://nginx.org/en/CHANGES
- Notable uncertainty: Docker image release notes for the full 1.29.1 → 1.31.0 jump are not centrally published in `docker-nginx-unprivileged` releases (only through 1.29.x visible), so image-layer change attribution is partial.
