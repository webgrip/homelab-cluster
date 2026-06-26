## Forgejo runner topology & resources

### forgejo-runner is a KEDA ScaledJob with a 3-container ephemeral cold-start pod (host-mode)
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED] manifests + live `pods_top`)
- **What:** `kubernetes/apps/forgejo/forgejo-runner/` (ns `forgejo`), a `keda.sh/v1alpha1` ScaledJob (no HelmRelease). Each ephemeral pod = init `runner-bin` (copies the static `forgejo-runner` binary out of `code.forgejo.org/forgejo/runner:12.10.2` into a shared emptyDir) + native-sidecar init `dind` (`docker:29.5.3-dind`, privileged) + main `runner` (`ghcr.io/webgrip/github-runner`: docker CLI+buildx, git, php 8.3, dotnet 9, CodeQL, composer, gh). Steps run host-mode inside the main runner (config label `docker:host`), reaching dind at `DOCKER_HOST=tcp://localhost:2376` over the shared pod netns. `capacity: 1`; all volumes emptyDir → nothing persists between jobs ("Topology A, host-mode", ADR-0008). Every job is a cold start. Container-job mode (`docker://image`) is avoided — the spawned container is NOT in the pod netns, so `localhost:2376` doesn't reach the daemon.
- **Why it matters:** Orients any runner change; explains cold-start cost, why an in-pod action/BuildKit cache can't persist, and resolves the whole `localhost:2376` reachability bug class.
- **Snippet:** init `args: ['cp "$(command -v forgejo-runner)" /dist/forgejo-runner; chmod 0755 /dist/forgejo-runner']`; config `runner.labels: [ "docker:host" ]`
- **Sources:** batches 1 (copy 16, copy 13), 3 (copy 5)

### `agent_labels` are fixed at registration; runner advertises ONE honest label `docker`; it's `forgejo-runner` not `act_runner`
- **Type:** GOTCHA + DECISION + FACT · **Confidence:** HIGH ([VERIFIED] by DB query)
- **What:** A runner advertises only the labels stored server-side in `action_runner.agent_labels`, set at registration — adding labels to `config.yaml` does NOT update the server (Forgejo's "no matching online runner with label X" UI warning is a static check against `agent_labels`). The in-cluster runner advertises only `docker` (truthful), not `arc-runner-set`/`ubuntu-latest`/`default` (GitHub-ARC/compat masks); all `.forgejo/workflows` were swept `arc-runner-set`/`[homelab, heavy]` → `docker`; `.github` stays on `arc-runner-set` (real GitHub ARC). The runner is **forgejo-runner** (Forgejo's fork) — do NOT reason from `act_runner`/`act` semantics (user corrected this 3×). `one-job` supports `--label name:backend` (repeatable) and `--handle` (Forgejo ≥15). Query `action_runner` Postgres to check; an empty `version` column means the runner never actually ran a job.
- **Conflict (resolved):** Earlier (copy 7) read the config as advertising `docker, default, ubuntu-latest`; later DB-verified post-sweep state (copy 5) is single `docker` — more credible (verified against the live DB + post-sweep config).
- **Snippet:** `psql ... -tAc "select id, name, version, agent_labels from action_runner order by id;"`
- **Sources:** batch 3 (copy 5, copy 7)

### `github-runner` image contents (and what it lacks)
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** `ghcr.io/webgrip/github-runner` is `FROM ghcr.io/actions/actions-runner` + tooling. Has: `docker`, `dockerd`, the buildx plugin, `git`, `jq`, `gh`, `php` 8.3, `dotnet` 9, `composer`, CodeQL; runs as non-root `runner` (uid 1001). Lacks: `node` on PATH (base bundles it under `externals/`), `cosign`, `syft`, `forgejo-runner`. So in host-mode: docker build/buildx work; JS-action node resolution and cosign/syft must be installed by the action. Source `infrastructure/ops/docker/github-runner/Dockerfile`. (Corrects an in-thread assumption that the image had no docker CLI — it does.)
- **Sources:** batches 3 (copy 5), 1 (copy 13)

### Runner builds via a privileged DinD sidecar today; rootless BuildKit is the roadmap (ADR-0008)
- **Type:** DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** Each ephemeral pod runs a privileged `docker:dind` sidecar; `docker/setup-buildx-action` + multi-arch `build-push-action` work as-is. ADR-0008 plans to separate three roles — agent (orchestrates), toolchain/job (node/git/buildx/cosign/syft + secrets + checkout), build engine (dockerd→buildkitd) — invariant: **privilege and secrets never share a container**. Sequence: prove on privileged DinD host-mode (A) → long-lived rootless `buildkitd` Service with a Harbor registry cache (C), dropping privileged. Topology B (rootless sidecar per-pod) rejected (rootless tax + cold cache). ARC "Kubernetes mode" is a non-starter (no container runtime → can't build OCI). File `docs/techdocs/docs/adr/adr-0008-rootless-ci-image-builds.md`.
- **Sources:** batch 3 (copy 5, copy 7)

### Worker-pool node shape & runner placement (pool=worker; retired fringe taint)
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED] — Prometheus allocatable + manifest `nodeSelector node.webgrip.io/pool: worker`)
- **What:** Allocatable CPU: `fringe-workstation`=7.95 cores (~15.96 GB), `worker-1`=3.95, `soyo-1/2/3`=3.95 each (control-plane/etcd, not worker pool). Runner `nodeSelector node.webgrip.io/pool: worker` selects fringe + worker-1; pods land on fringe (the only 8-core node). The ScaledJob still carries a dormant `tolerations: dedicated=fringe:NoSchedule` block, but that taint was retired 2026-06-19 — docs saying "pinned to the fringe nodegroup" are stale; the toleration is dead weight kept "for safety."
- **Sources:** batches 1 (copy 16, copy 11), 3 (copy 5 — KEDA pins nodegroup `fringe`, now stale)

### Runners have NO CPU limit → never throttled; speed lever is requests + cold start, not a CPU cap
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED] — live runner=973m; 7d p95 runner ~0.24 / dind ~0.70 core)
- **What:** Neither runner nor dind sets a CPU limit (only memory limits). The speed constraint is tiny CPU *requests* under contention, not throttling. Generous-burst posture: keep CPU limitless so a lone job uses the whole idle node. Don't "fix speed" by raising a nonexistent CPU limit.
- **Sources:** batch 1 (copy 16)

### Resource + scaling rightsize values (shipped in 04c6151)
- **Type:** DECISION · **Confidence:** HIGH ([VERIFIED] via flux-local; committed + pushed)
- **What:** `scaledjob.yaml`, justified by 7-day Prometheus data: dind mem limit `4Gi → 1536Mi` (peak ~649Mi = 16%); runner mem request `256Mi → 512Mi`, limit `1Gi → 1280Mi` (peak ~796Mi = 78%, zero OOM); both CPU requests `100m → 250m` (no CPU limit); `pollingInterval 30 → 15`; `minReplicaCount 1 → 2` (warm pool, freed by the dind-limit cut); `maxReplicaCount` kept 6 (peak concurrency 3/6 over 7d). The 2nd-warm-runner "Insufficient memory" was the dind 4Gi mem LIMIT, not its request — scheduling uses requests (768Mi/pod, fit easily on 16GB); the oversized limit (+ node RAM pressure) blocked scale-out indirectly. Cutting the limit to 1.5Gi unblocked warm pool = 2.
- **Why it matters:** Reusable template for "rightsize from metrics, not guesses"; distinguishes request-vs-limit effects on scheduling.
- **Sources:** batch 1 (copy 16)

---

## CI speed: build chain, caching & decisions

### The dominant CI build cost is emulated arm64 (QEMU), not action clones → amd64-default + gated QEMU (ADR-0036)
- **Type:** DECISION · **Confidence:** HIGH (decision [VERIFIED]; "biggest cost" [ASSERTED], first fast run 10m43s not yet A/B-confirmed)
- **What:** The shared build composite defaulted to `platforms: linux/amd64,linux/arm64`; the homelab is amd64-only Talos, so arm64 was built under QEMU on every image for an artifact nothing runs. ADR-0036 (`adr-0036-amd64-default-constrictor-build.md`) defaults builds to `linux/amd64` and runs `docker/setup-qemu-action` only when a non-amd64 arch is requested: `if: ${{ inputs.platforms != 'linux/amd64' }}`. Owned by Accepted `rfc-ci-pipeline-performance.md`. A caller passing explicit `platforms: "linux/amd64,linux/arm64"` defeats the fast wrapper's default — the QEMU gate sees the comma'd value and still emulates; you must also set the caller's `platforms` to `linux/amd64`.
- **Why it matters:** Single biggest, lowest-risk speedup; reframes action-cache work as secondary ("measure first").
- **Sources:** batches 1 (copy 13, copy 16), 3 (copy 5)

### forgejo-runner 12.10.2 has NO action offline mode at any layer → action-clone wall is measure-first / scoped LAN mirror (ADR-0035)
- **Type:** DECISION + FACT · **Confidence:** HIGH ([VERIFIED] — image inspected 3 ways)
- **What:** `code.forgejo.org/forgejo/runner:12.10.2` exposes no way to skip re-fetching already-cached actions: `generate-config`'s `cache:` block is ONLY the actions/cache server; the `one-job` daemon path exposes only `--url/--uuid/--token-url/--wait/--fetch-interval/--handle/--label`; `exec` has **stripped** upstream act's `--action-offline-mode`/`--action-cache-path`, leaving only `--default-actions-url`. Even a warm baked `~/.cache/act` `git fetch`es every job. `exec -n` (dryrun) does NOT clone actions (so can't prime the cache at build time) and rejects `-P/--platform` (use `-i/--image`). Decision: ship the amd64 fix first and re-time before building cache infra; if clones still dominate, mirror only the ~6 docker-build action repos into in-cluster Forgejo by explicit LAN URLs in the `-fast` composite only. **Rejected:** pre-baking `~/.cache/act` (no offline mode), global `DEFAULT_ACTIONS_URL` (blast radius), an RWX shared cache PVC (policy forbids RWX).
- **Conflict (resolved):** copy 16's earlier digest described ADR-0035 as "pre-bakes the docker-build action set + runner offline mode"; copy 13 supersedes it (offline mode proven impossible; ADR repointed to a scoped mirror, file renamed `adr-0035-prebaked-action-cache.md` → `adr-0035-action-clone-wall.md`). copy 13 is authoritative.
- **Sources:** batch 1 (copy 13 authoritative, copy 16)

### Constrictor (strangler) migration for the build-workflow chain
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED] — files created/committed/pushed; first caller flipped)
- **What:** Build call graph: app-repo job → per-registry wrapper (`docker-build-and-push-harbor.yml`) → engine (`docker-build-and-push-registry.yml`) → composite (`docker-build-push-registry`). To change behavior without a flag-day, create parallel `-fast` files at each layer, leave originals untouched, migrate callers one at a time by flipping `uses:`, then delete the old chain once unreferenced. Each migration independently revertible.
- **Snippet:** `uses: webgrip/workflows/.forgejo/workflows/docker-build-and-push-harbor-fast.yml@main` + `platforms: "linux/amd64"`
- **Sources:** batch 1 (copy 13)

### buildx must stay even for amd64-only builds — registry cache export needs its driver
- **Type:** FACT · **Confidence:** HIGH (well-established buildx behavior; corroborated across 3 threads)
- **What:** `docker/setup-buildx-action` cannot be dropped from the fast path: `cache-to/cache-from type=registry` requires buildx's `docker-container` driver to import/export (the default `docker` driver can't). Only `docker/setup-qemu-action` is safe to skip for pure-amd64. The Harbor `:cache` repo also needs `docker/login-action` to pull, even for read-only `cache-from`. A multi-platform buildx `--push` build leaves no local image, so a follow-up `docker push` won't work — dual-publish via one build with multiple registry-qualified tags + logins, not a second push.
- **Snippet:** `cache-to: type=registry,ref=<reg>/<owner>/<image>:cache,mode=max,compression=zstd`
- **Sources:** batches 1 (copy 13, copy 6, copy 16), 3 (copy 7)

### Harbor registry layer cache (`:cache`) already ships in the composite; ref = `<registry>/<owner>/<image>:cache`
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED] — read the composite)
- **What:** `webgrip/workflows/.forgejo/composite-actions/docker-build-push-registry/action.yml` derives the cache tag from the first normalized tag, strips the tag, appends `:cache`, then `cache-from` + `cache-to type=registry,ref=…:cache,mode=max,compression=zstd`. For Harbor: `harbor.webgrip.dev/webgrip/<image>:cache`. The `-fast` variant inherits it verbatim. Runtime cache-hit effectiveness (CACHED layers on a 2nd build) not yet confirmed. Each `cache-to mode=max` overwrites the cache tag and orphans the prior ~2.6 GiB manifest (GC reclaims it).
- **Why it matters:** "Build the Harbor cache" was already done — the task is to verify it; any other build wanting reuse must reconstruct this exact ref.
- **Sources:** batches 1 (copy 13, copy 6, copy 16), 3 (copy 4)

### Make `verifyRelease` a buildx build that READS the publish path's `:cache` (no `cache-to`)
- **Type:** DECISION · **Confidence:** HIGH (logic [VERIFIED]; cache-hit speedup [ASSERTED] until run in CI)
- **What:** The ~9-min per-image release cost was an uncached `docker build` inside semantic-release's `verifyReleaseCmd` (rebuilt the heavy image — multiple bases + ~194 apk pkgs incl. chromium/graphviz — cold, before the tag was cut). Fix: env-gate so when `BUILD_CACHE_REF` is set, run `docker buildx build … --cache-from type=registry,ref=<ref> --output=type=cacheonly`; else plain `docker build`. **Deliberately NO `cache-to`** — verify is amd64-only while publish is amd64+arm64 into the SAME `:cache` ref; an amd64-only `cache-to` would clobber the arm64 layers. Verify reads "one release behind" (full hit for the common no-Dockerfile-change bump). Plain-build fallback keeps GitHub unchanged.
- **Snippet:** `const cacheRef = process.env.BUILD_CACHE_REF; const verifyReleaseCmd = cacheRef ? ['docker buildx build --file Dockerfile --platform linux/amd64', `--cache-from type=registry,ref=${cacheRef}`, '--output=type=cacheonly .'].join(' ') : 'docker build --file Dockerfile .';`
- **Sources:** batch 1 (copy 6)

### `@semantic-release/exec` `verifyReleaseCmd` is Lodash-templated — build dynamic strings in JS, not the command
- **Type:** GOTCHA · **Confidence:** MEDIUM ([ASSERTED])
- **What:** semantic-release expands `${...}` in exec commands as Lodash templates against its release context (`${nextRelease.version}`), NOT as shell — you cannot put `${process.env.FOO}` in the command string. Since `.releaserc.js` is real JS, read `process.env` and interpolate at config-load time (`const cacheRef = process.env.BUILD_CACHE_REF`). `successCmd: 'echo "version=${nextRelease.version}" >> $GITHUB_OUTPUT'` is the intended Lodash use.
- **Sources:** batch 1 (copy 6)

### Mirroring CI base-image pulls belongs in the buildx builder's buildkitd config, NOT a dind ConfigMap
- **Type:** GOTCHA · **Confidence:** MEDIUM ([ASSERTED] — design analysis; dind-ConfigMap approach built then backed out unshipped)
- **What:** Routing `docker build` base-image (`FROM`) pulls through Harbor by mounting `daemon.json`/`buildkitd.toml` into the dind sidecar is the wrong layer: `daemon.json registry-mirrors` only mirrors Docker Hub (classic/embedded driver); `buildkitd.toml` is read by a standalone `buildkitd` — i.e. only a `docker-container`-driver builder, whose `--config` is resolved from the **runner** container's filesystem, not dind's. The node mirror only accelerates kubelet/containerd pod-image pulls — the dind daemon (separate Docker engine) does NOT use the node mirror for build-time pulls. So per-registry base-image mirrors must live in that builder's buildkitd config, configured in `webgrip/workflows`. (The shipped alternative is parameterized base-registry ARGs — see Dockerfile wiring below.)
- **Sources:** batches 1 (copy 16, reinforced by copy 6's base-image-proxy `--build-arg` approach), 3 (copy 4)

---
