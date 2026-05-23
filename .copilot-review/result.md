pr: 165

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** High

### Executive summary

This PR bumps the Valkey image used as a SearXNG in-cluster cache from 8.1.7 to 9.0.4, a major-version upgrade crossing nine patch/minor releases. The update carries **six CVE security fixes** across 9.0.3 and 9.0.4 that are rated SECURITY urgency by the upstream project, making the upgrade compelling. The local deployment is a single-replica StatefulSet with persistence intentionally disabled (`--save ""`, `--appendonly no`), so there is no state-migration risk and rollback is a simple image revert. Major-version breaking changes (atomic slot migration, hash-field TTLs, cluster databases) are irrelevant to this standalone, non-clustered deployment.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/valkey/valkey` | Container image | `8.1.7 → 9.0.4` | major | Runtime — in-cluster cache for SearXNG rate-limiting/sessions | Yellow |

### Important upstream changes

**9.0.4 (SECURITY)**
- `[security]` CVE-2026-23479 — Use-After-Free in unblock client flow
- `[security]` CVE-2026-25243 — Invalid Memory Access in RESTORE command
- `[security]` CVE-2026-23631 — Use-after-free when full sync occurs during a yielding Lua/function execution

**9.0.3 (SECURITY)**
- `[security]` CVE-2025-67733 — RESP Protocol Injection via Lua error_reply
- `[security]` CVE-2026-21863 — Remote DoS with malformed Valkey Cluster bus message
- `[security]` CVE-2026-27623 — Reset request type after handling empty requests
- `[bugfix]` ACL LOAD crash when current user loses permission to channels
- `[bugfix]` No response flush sometimes when IO threads are busy

**9.0.2 (HIGH urgency)**
- `[bugfix]` Multiple hash field expiration (HEXPIRE/HSETEX) correctness fixes
- `[bugfix]` AOF slot-cache key duplication and data-corruption fix (not applicable — AOF disabled here)
- `[bugfix]` XREAD returning error on empty stream with `+` ID

**9.0.1 (MODERATE)**
- `[bugfix]` Sentinel failover ACL regression fix
- `[bugfix]` Cluster mixed-version meet-packet fix (not applicable — standalone)
- `[bugfix]` IO-thread shutdown deadlock during panic

**9.0.0 GA (LOW urgency — first stable 9.x release)**
- `[feature]` Atomic slot migration (cluster-only — not applicable)
- `[feature]` Hash field expiration via HSETEX/HEXPIRE commands
- `[feature]` Numbered databases in cluster mode (standalone — not applicable)
- `[feature]` ~40% pipeline throughput improvement, SIMD BITCOUNT/HyperLogLog optimizations
- `[breaking]` Potential behavioral change: HSETEX with FXX no longer creates non-existent objects — could affect callers using hash-field commands, but SearXNG does not use these advanced hash commands for its cache

Note: a pending `9.1.0` tag exists in Renovate's update table; this PR targets the current stable `9.0.4`.

### Local impact

**Single file changed:** `kubernetes/apps/searxng/searxng/app/valkey.yaml`

- Deployed as a `StatefulSet` (1 replica) in the `searxng` namespace, accessed by the SearXNG app at `redis://searxng-valkey.searxng.svc.cluster.local:6379/0`.
- **Persistence is fully disabled** — args `--save ""` and `--appendonly no` mean no RDB or AOF data survives a pod restart. Cache miss on restart is the intended behaviour. This eliminates all state-migration risk.
- Backed by a 1 Gi Longhorn PVC (`storageClassName: longhorn-general`). Although the PVC exists, it is only used for Valkey's working directory; no data is persisted to it under the current config.
- The container runs as non-root (UID 1000), with `readOnlyRootFilesystem: true` and no privilege escalation — security posture is good.
- The CVEs fixed in 9.0.3/9.0.4 (Use-After-Free, invalid memory access, RESP injection) are relevant to any running Valkey instance, including this cache, even though the blast radius here is limited to SearXNG session/rate-limit data.
- No other files in the repository reference `valkey/valkey` or depend on this image.

### Pre-merge checks

- [ ] Verify the new image digest `sha256:8436e10bc65c94886a91d4415b6a6dfa9cb5a306fb3b996e5bb67cd2b4854193` resolves correctly and matches `docker.io/valkey/valkey:9.0.4` on Docker Hub.
- [ ] After Flux reconciles, confirm the `searxng-valkey` pod reaches `Running` state and the SearXNG app connects successfully (check `SEARXNG_VALKEY__URL` connectivity).
- [ ] Confirm SearXNG's rate-limiting and search functions work end-to-end post-upgrade (a brief manual smoke test is sufficient given the cache-only role).
- [ ] Monitor pod logs immediately after rollout for any startup errors or connection-refused messages from SearXNG.

### Evidence reviewed

- **PR:** #165 — title `feat(container)!: Update image docker.io/valkey/valkey ( 8.1.7 ➔ 9.0.4 )`, labels `area/kubernetes`, `type/major`, `renovate/container`, `dependencies`, `major`. Diff: 1 file changed, image tag + digest replaced.
- **Files in repo:** `kubernetes/apps/searxng/searxng/app/valkey.yaml` (StatefulSet + Service), `kubernetes/apps/searxng/searxng/app/kustomization.yaml` (references valkey.yaml), `kubernetes/apps/searxng/searxng/app/helmrelease-app.yaml` (sets `SEARXNG_VALKEY__URL`), `docs/techdocs/docs/applications.md` and `docs/techdocs/docs/runtime-inventory.md` (documentation references).
- **Upstream sources checked:** Valkey GitHub release notes embedded in PR body (v9.0.0–v9.0.4); valkey.io blog post on Valkey 9.0 features; web search for Valkey 9.0 breaking changes and migration guide.
- **Notable uncertainty:** CVE severity scores (CVSS) were not individually retrieved; all three 9.0.4 CVEs are described as "Use-After-Free" or "Invalid Memory Access" class, which typically rate medium-to-high. The local exposure is low (internal cluster service, not internet-facing), but patching is still recommended promptly.
