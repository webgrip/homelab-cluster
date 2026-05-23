pr: 174

## Dependency Update Review

**Verdict:** Yellow Caution  
**Recommendation:** Merge after checks  
**Confidence:** High

### Executive summary

This PR updates the `docker.io/valkey/valkey` container image from `9.0.4` to `9.1.0` (minor bump) for the SearXNG cache sidecar. The release patches three memory-safety CVEs (two use-after-free, one invalid memory access), all requiring authenticated access to exploit. No breaking changes are present. The workload is stateless by configuration (`--save ""`, `--appendonly no`), which reduces rollback friction. The security fixes make merging clearly beneficial.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/valkey/valkey` | Docker/OCI | `9.0.4@sha256:8436…` → `9.1.0@sha256:4963…` | minor | runtime cache (SearXNG session/rate-limit backend) | Yellow |

### Important upstream changes

- **[security]** CVE-2026-23479 (CVSS ~7.7–8.8): Use-after-free in unblock client flow — authenticated RCE vector
- **[security]** CVE-2026-25243 (CVSS ~7.7): Invalid memory access in `RESTORE` command via crafted payload — authenticated RCE vector
- **[security]** CVE-2026-23631 (CVSS ~6.1–7.7): Use-after-free during full sync while Lua/function yields — authenticated RCE vector
- **[feature]** Cluster bus network traffic metric added (bytes)
- **[feature]** Incremental page release during rehashing reduces latency spikes
- **[bugfix]** GEOSEARCH BYPOLYGON memory leak on invalid COUNT
- **[bugfix]** streamTrim listpack delta NULL pointer crash
- **[bugfix]** Server crash on RDMA benchmark client disconnect
- **[bugfix]** Memory leak in valkey-benchmark tool

No breaking changes or migration steps noted; upstream declares upgrade urgency **LOW**.

### Local impact

Valkey is deployed as a `StatefulSet` (`searxng-valkey`) in the `searxng` namespace, serving as the in-memory cache backend for SearXNG (`redis://searxng-valkey.searxng.svc.cluster.local:6379/0`). It handles session data and rate-limit state.

**Key configuration details (from `kubernetes/apps/searxng/searxng/app/valkey.yaml`):**
- Persistence is **disabled** (`--save ""`, `--appendonly no`) — data is ephemeral; pod restart loses nothing important
- Image is digest-pinned (good supply-chain hygiene; digest matches new `9.1.0` tag)
- Runs non-root (`runAsUser: 1000`, `runAsGroup: 1000`), read-only root filesystem, no privilege escalation
- Resource limits: 200m CPU / 256Mi memory — well within cache workload expectations
- PVC (`1Gi`, `longhorn-general`) exists but holds no persistent Valkey data given the no-save/no-AOF config

The CVEs involve authenticated attack vectors. In this deployment, Valkey listens only on a cluster-internal service (no external exposure via Gateway/HTTPRoute), and no password auth is configured (as is standard for an internal ephemeral cache). Cluster-internal exposure means the blast radius is limited to workloads in the cluster that can reach the service — but the security fixes are still worthwhile.

**Files affected in this repo:**
- `kubernetes/apps/searxng/searxng/app/valkey.yaml` — sole file changed; updates image tag + digest
- `kubernetes/apps/searxng/searxng/app/helmrelease-app.yaml` — not changed; references Valkey URL via env var
- `kubernetes/apps/searxng/searxng/app/kustomization.yaml` — not changed; includes valkey.yaml

### Pre-merge checks

- [ ] Verify the new digest `sha256:4963247afc4cd33c7d3b2d2816b9f7f8eeebab148d29056c2ca4d7cbc966f2d9` is the correct `9.1.0` amd64 manifest on Docker Hub / GHCR before merging.
- [ ] Confirm CI (flux-local / OCI digest verification via `./scripts/verify-oci-digests.sh`) passes on this PR.
- [ ] After Flux reconciles, verify `searxng-valkey` pod restarts cleanly and SearXNG health check (`/healthz`) continues to pass.
- [ ] No special data migration needed (persistence is disabled; rolling restart is safe).

### Evidence reviewed

- **PR:** `feat(container): update image docker.io/valkey/valkey ( 9.0.4 ➔ 9.1.0 )` — labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; 1 file changed, 1 addition, 1 deletion
- **Files in repo:** `kubernetes/apps/searxng/searxng/app/valkey.yaml`, `kubernetes/apps/searxng/searxng/app/helmrelease-app.yaml`, `kubernetes/apps/searxng/searxng/app/kustomization.yaml`
- **Upstream sources checked:** Valkey GitHub releases (v9.1.0 release notes in PR body); security advisory for CVE-2026-23479, CVE-2026-25243, CVE-2026-23631 via web search
- **Notable uncertainty:** CVE CVSS scores are from third-party sources; official NVD entries may differ slightly. No intermediate versions were skipped (direct 9.0.4 → 9.1.0).
