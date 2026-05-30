pr: 302

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge after checks
**Confidence:** High

### Executive summary

This PR pins `docker.io/grafana/mcp-grafana` from a mutable tag (`0.14.0`) to an immutable digest (`0.14.0@sha256:42f541f...`). There is no version bump, so functional upstream change risk is low; the primary effect is better supply-chain reproducibility and rollback determinism. Local usage is limited to one deployment plus synthetic health checks. Merge is reasonable after confirming the deployed pod resolves to the expected digest.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/grafana/mcp-grafana` | Docker/OCI | `0.14.0` → `0.14.0@sha256:42f541f2206359ce7a40c8e19d96253cef4771bf00e707a760d3a7035c40e8f8` | digest pin | runtime (Kubernetes observability app) | Green |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[unknown]` | No upstream version delta in this PR (same tag `0.14.0`); change is immutability pinning to the current image index digest. | [Docker Hub tag metadata](https://hub.docker.com/v2/repositories/grafana/mcp-grafana/tags/0.14.0) | **No** — runtime behavior should be unchanged if cluster was already pulling this tag digest. |
| `[feature]` | `v0.14.0` release includes generic Grafana API request tool. | [#841](https://github.com/grafana/mcp-grafana/pull/841) | **Unknown** — repo enables many tools, but this PR does not move versions so this feature is already part of `0.14.0` baseline. |
| `[feature]` | `v0.14.0` adds OpenSearch datasource support. | [#669](https://github.com/grafana/mcp-grafana/pull/669) | **No** — no OpenSearch datasource usage found in this repo review scope. |
| `[feature]` | `v0.14.0` adds plugin info retrieval tool. | [#826](https://github.com/grafana/mcp-grafana/pull/826) | **Unknown** — potentially available via enabled tools, but unchanged by this digest-only PR. |
| `[behavior]` | `v0.14.0` server instructions dynamically reflect enabled tool categories. | [#829](https://github.com/grafana/mcp-grafana/pull/829) | **Yes** — deployment explicitly sets `--enabled-tools=...`; behavior is relevant to this app, but not newly introduced by this PR. |
| `[bugfix]` | `v0.14.0` fixes OnCall proxy auth, jq context/error handling, and Sift panic case. | [#842](https://github.com/grafana/mcp-grafana/pull/842), [#847](https://github.com/grafana/mcp-grafana/pull/847), [#834](https://github.com/grafana/mcp-grafana/pull/834) | **Unknown** — impacts only if those tools/paths are exercised; not a new change in this digest pin. |

### Local impact

- PR modifies one file: `kubernetes/apps/observability/mcp-grafana/app/deployment.yaml` (container image field only).
- Service exposure and health probes remain unchanged (`/healthz` on port 8000): `kubernetes/apps/observability/mcp-grafana/app/service.yaml`, `.../httproute.yaml`.
- This workload uses a Grafana service-account token (`mcp-grafana-token`) and has restricted pod/container security contexts; no privilege expansion is introduced by this PR.
- Operationally, pinning digest reduces drift risk from mutable tags and improves reproducibility for rollback/debugging.

### Improvement opportunities

- **`Pin by digest for similar directly-referenced runtime images`** — this PR improves immutability; applying the same pattern to any remaining mutable image tags would further reduce supply-chain drift risk ([Docker tag mutability context](https://hub.docker.com/v2/repositories/grafana/mcp-grafana/tags/0.14.0)).

### Grafana dashboards and alerts

No dashboard or alert changes identified: repo references for this dependency show deployment/service/route plus k6 synthetic endpoint check, but no dependency-specific Prometheus metrics, recording rules, or Grafana dashboard panels tied to mcp-grafana internals.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard / Alert / Metric / Scrape config | `kubernetes/apps/observability/k6-canaries/app/script-configmap.yaml` checks `mcp-grafana` `/healthz`; no ServiceMonitor/PodMonitor/dashboard references found for mcp-grafana | None | Digest pin does not introduce metric schema changes; no version change in dependency update ([PR diff](https://github.com/webgrip/homelab-cluster/pull/302/files)). |

### Pre-merge checks

- [ ] Confirm rendered manifest/image in PR branch resolves to `docker.io/grafana/mcp-grafana:0.14.0@sha256:42f541f2206359ce7a40c8e19d96253cef4771bf00e707a760d3a7035c40e8f8`.
- [ ] After deploy, verify pod comes up and readiness/liveness stay healthy (`/healthz`) for `mcp-grafana`.
- [ ] Confirm k6 ingress canary for `mcp-grafana` continues passing (`kubernetes/apps/observability/k6-canaries/app/script-configmap.yaml`).

### Follow-up

- [ ] Consider documenting an explicit policy to prefer digest-pinned images for directly-managed Deployments in `kubernetes/apps/**` — improves deterministic rollouts and incident forensics.

### Evidence reviewed

- PR: `chore(container): pin image docker.io/grafana/mcp-grafana to 42f541f`; labels `area/kubernetes`, `renovate/container`, `dependencies`; diff summary `1 file changed, +1/-1`.
- Files in repo: `kubernetes/apps/observability/mcp-grafana/app/deployment.yaml`, `.../service.yaml`, `.../httproute.yaml`, `kubernetes/apps/observability/grafana/app/service-accounts/mcp-grafana.yaml`, `kubernetes/apps/observability/k6-canaries/app/script-configmap.yaml`.
- Upstream sources checked: `https://hub.docker.com/v2/repositories/grafana/mcp-grafana/tags/0.14.0`, `https://github.com/grafana/mcp-grafana/releases/tag/v0.14.0`, PR links in release notes (`#669`, `#826`, `#829`, `#834`, `#839`, `#841`, `#842`, `#847`, `#756`).
- Notable uncertainty: prior runtime digest in-cluster before pinning is not visible from repository state alone.
