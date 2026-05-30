pr: 315

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates the `jgraph/drawio` container image from digest `63ba7ec` to `3fbc301` (Docker Hub `latest`, corresponding to tag `30.0.4`, published 2026-05-27). The update spans the `29.7.x` → `30.0.x` major version boundary and includes a patched **medium-severity XSS vulnerability** (GHSA-wj8x-4c77-v8v3) that allows arbitrary JavaScript execution when a user opens a crafted `.drawio` file. That security fix alone justifies applying the update promptly. The v30 line is additive (new stencils, DOMPurify upgrades, UI polish) with no confirmed breaking changes for a self-hosted, self-contained deployment.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `jgraph/drawio` | Docker/OCI | `latest@sha256:63ba7ec…` → `latest@sha256:3fbc301…` (v30.0.4) | digest / crosses major boundary (~29.7.x → 30.0.4) | runtime (user-facing diagram editor) | Yellow |

### Important upstream changes

The jgraph/drawio project publishes releases with empty GitHub Release bodies. All change detail was sourced from the upstream `ChangeLog` file at `https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog`.

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[security]` | **XSS via crafted cell label** (GHSA-wj8x-4c77-v8v3, severity: medium). DOM-based XSS via mutation XSS (mXSS) in `<math>` / MathML parsing; allows exfiltration of diagram XML and IP, and open redirect. Fixed by adding label sanitization (v29.7.12). | [GHSA-wj8x-4c77-v8v3](https://github.com/jgraph/docker-drawio/security/advisories/GHSA-wj8x-4c77-v8v3) | **Yes** — draw.io is exposed to end-users who can open external `.drawio` files; any user who opens a malicious diagram file would be impacted. |
| `[feature]` | DOMPurify upgraded from 3.3.3 → 3.4.0 (v29.7.7), then → 3.4.2 (v30.0.0), then → 3.4.5 (v30.0.3). | [ChangeLog](https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog) | **Yes** — DOMPurify is the XSS sanitizer; these upgrades strengthen the security posture of the self-hosted instance. |
| `[feature]` | Mermaid updated to v11.14.0 (v29.7.11). | [ChangeLog](https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog) | **No** — runtime improvement inside the container; no external config change needed. |
| `[feature]` | MathJax updated from 4.1.1 → 4.1.2 (v29.7.11). | [ChangeLog](https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog) | **No** — internal runtime improvement; no config change needed. |
| `[feature]` | v30.0.0: Adds mermaid shapes from native-ports branch, new Mindmap/Git/Smiley shapes in Basic sidebar, lockedGroup cell style, configurable `tooltipFontSize`/`tooltipMaxWidth`, adaptive colors moved to page setup. | [ChangeLog](https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog) | **No** — additive UI features; no deployment config change required. |
| `[behavior]` | v30.0.0: "Default adaptive colours no longer simple in desktop." | [ChangeLog](https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog) | **Unknown** — this is primarily a desktop app behaviour change; impact on the web/self-hosted variant is unclear from changelog text. |
| `[feature]` | v30.0.2–30.0.4: Extensive multicolor support added for GCP2, GCP3 (new stencil set), IBM, Atlassian, Citrix, MS Office, Rack, Salesforce, VVD, EIP, GMDL, Floorplan stencil libraries. | [ChangeLog](https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog) | **No** — additive stencil additions; no breaking change. |
| `[feature]` | v30.0.0: Upgrades JDK to JDK 21 (also present in v29.7.11). | [ChangeLog](https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog) | **No** — internal runtime; no Kubernetes resource change needed. |
| `[bugfix]` | v29.7.x: Extensive NPE and TypeError hardening in graph handlers, cell editors, and geometry functions. | [ChangeLog](https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog) | **No** — defensive fixes; reduces crash likelihood in the running pod. |
| `[unknown]` | The exact version corresponding to the old digest `sha256:63ba7ec…` could not be resolved. Docker Hub no longer exposes historical `latest` manifest pointers. The old version is likely in the `29.7.9`–`30.0.2` range based on push timestamps. | Docker Hub API | **Unknown** — if the old version was already ≥ 29.7.12, the security fix is already present. If not, this update is security-relevant. |

### Local impact

**Files referencing `jgraph/drawio`:**
- `kubernetes/apps/drawio/drawio/app/helmrelease.yaml` — sole container image reference; the only changed file in this PR.

**Deployment characteristics:**
- The draw.io container is pinned to `tag: latest` with a digest lock and deployed via Flux + bjw-s app-template Helm chart.
- It is exposed only on an internal HTTPS route (`drawio.${SECRET_DOMAIN}` via `envoy-internal` gateway), so the XSS attack surface is limited to internal users.
- `DRAWIO_SELF_CONTAINED: "1"` is set, meaning the instance runs without external calls — this limits some XSS exfiltration vectors but does not eliminate the risk from crafted files loaded by users.
- Companion `jgraph/plantuml-server` container is **not** changed by this PR (its digest is unaffected).
- The app is deployed to the `fringe` nodegroup with tolerations; the rollout is non-stateful (no persistent volumes identified in the helm release).
- Rollback difficulty: **Low** — stateless workload; reverting is a one-line digest change in git.

### Improvement opportunities

- **Pin to a versioned tag instead of `latest`** — The current `tag: latest@sha256:…` pattern relies on digest locking for reproducibility, but it makes it hard to reason about which application version is running. Switching to `tag: 30.0.4@sha256:3fbc301…` would make audits and rollbacks clearer. Renovate would still update it automatically.

### Grafana dashboards and alerts

No observability files in this repository reference `jgraph/drawio` metrics, dashboards, or alert rules. The draw.io app does not expose Prometheus metrics and does not have a ServiceMonitor or PodMonitor. The `monitoring.webgrip.io/synthetic-check: k6-ingress-canary` annotation on the HTTPRoute suggests a synthetic canary check is configured; verify it exercises the `/` health endpoint after the rollout.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Synthetic canary | `kubernetes/apps/drawio/drawio/app/httproute.yaml` annotation | None | Health check already configured via `k6-ingress-canary`; confirm check passes post-rollout |

### Pre-merge checks

- [ ] Confirm CI (flux-local / OCI digest verification via `./scripts/verify-oci-digests.sh`) passes on the PR branch.
- [ ] Verify the new digest `sha256:3fbc301ab4cbb5ae02d47a5586b95ee287cb90c6b6385876fa44947ed99548b9` matches the `30.0.4` tag on Docker Hub — confirmed in research (Docker Hub amd64 manifest index digest matches).
- [ ] After merge and rollout, confirm the draw.io web UI loads correctly at `drawio.${SECRET_DOMAIN}` and the synthetic canary check (`k6-ingress-canary`) reports healthy.
- [ ] Confirm the `jgraph/plantuml-server` companion container is still functional after the drawio upgrade (the helmrelease deploys both; plantuml-server digest is unchanged).

### Follow-up

- [ ] **Consider switching from `latest` to a versioned tag** (e.g., `30.0.4`) — reduces ambiguity during incident review and makes changelog-to-deployment mapping explicit. This is a config change in `kubernetes/apps/drawio/drawio/app/helmrelease.yaml`.
- [ ] **Review the XSS security advisory GHSA-wj8x-4c77-v8v3** and assess whether internal users should be reminded not to open untrusted `.drawio` files from external sources, as a defence-in-depth measure even after patching. See [advisory](https://github.com/jgraph/docker-drawio/security/advisories/GHSA-wj8x-4c77-v8v3).

### Evidence reviewed

- **PR**: "chore(container): update image jgraph/drawio ( 63ba7ec ➔ 3fbc301 )", labels: `area/kubernetes`, `renovate/container`, `type/digest`, `dependencies`. Single file changed: `kubernetes/apps/drawio/drawio/app/helmrelease.yaml` (+1/-1 digest line).
- **Files in repo**: `kubernetes/apps/drawio/drawio/app/helmrelease.yaml`, `httproute.yaml`, `ocirepository.yaml`, `namespace.yaml`, `kustomization.yaml`; `kubernetes/apps/kyverno/policies/app/exception-third-party-workloads.yaml`, `exception-third-party-images.yaml`.
- **Upstream sources checked**:
  - Docker Hub tags API: `https://hub.docker.com/v2/repositories/jgraph/drawio/tags?page_size=50`
  - GitHub releases API: `https://api.github.com/repos/jgraph/drawio/releases?per_page=20`
  - Upstream ChangeLog: `https://raw.githubusercontent.com/jgraph/drawio/dev/ChangeLog`
  - Security advisory: `https://api.github.com/repos/jgraph/docker-drawio/security-advisories`
  - GitHub commit compare: `v29.7.12...v30.0.4`
- **Notable uncertainty**: The exact application version corresponding to the old digest `sha256:63ba7ec…` could not be confirmed — Docker Hub does not expose historical `latest` manifest history. All changes from approximately `v29.7.9` through `v30.0.4` are covered above as a conservative range.
