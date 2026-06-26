# Consolidated Knowledge Set

**Executive summary:**
- The webgrip CI supply chain was rebuilt around an in-cluster **Forgejo Actions** runner that builds `ops/docker/*` images, dual-publishes to **Harbor** (LAN) and **GHCR**, and signs via **cosign + OpenBao Transit** (per-job OIDC), with Dependency-Track SBOMs and **Kyverno verifyImages** as the single admission gate — kept at **Audit**, never Enforce yet.
- Architecture is **"release once, publish many"**: Forgejo is the sole release authority (semantic-release tags, commits package.json back); GitHub is a pure mirror that runs **zero** Actions (`.github/` deleted on `infrastructure`). The shared `.releaserc.js` env-gates `@saithodev/semantic-release-gitea` (Forgejo, REST-only) vs `@semantic-release/github` (404s on Forgejo's missing GraphQL endpoint), gated on a **literal** env flag not an unset `vars.*`.
- Forgejo's young reusable-workflow **expansion** (v15.0.0) is the root of several footguns: it flattens inner jobs into the caller graph, **ignores the caller job's `if:`** (duplicate racing builds), **rejects a caller job id colliding with an inner job id**, and splits action resolution by call-site (job-level reusables → local instance; step-level composites → `DEFAULT_ACTIONS_URL` = `data.forgejo.org`, an incomplete mirror).
- The **biggest CI build cost is emulated arm64 (QEMU)**, not action clones — the amd64-default + gated-QEMU change (ADR-0036) is the single biggest, lowest-risk speedup; the action-clone wall is measure-first (offline mode does NOT exist in forgejo-runner 12.10.2 at any layer).
- Several **empty/wrong-context Forgejo values** bite: `github.repository_owner`/`github.sha` are empty in `workflow_dispatch` runs (hardcode `webgrip`); `semantic-release-monorepo` `outputs.version` is the full namespaced tag (don't re-prefix); CI-created releases don't fire a release event (dispatch explicitly).
- The Harbor pull-through mirror was a **silent no-op** until a Talos `extraHostEntries` let nodes DNS-resolve LAN-only `harbor.${secretDomain}`; Harbor 2.15's proxy returns the full upstream tag list so Renovate works through it. Harbor's native **SBOM column** is gated by `sbom:create` (NOT `scan:create`), fed only by Harbor's own scanner (NOT pushed cosign attestations), and the robot provisioner was non-idempotent (needed a convergence `PUT /robots/{id}`).
- A **Grafana threshold alert-rule schema bug** (missing top-level `expression:`) silently broke all 16 SLO rules for ~3 weeks — uncatchable by kubeconform/flux-local (preserve-unknown CRD); live MCP rule-health re-query is the only acceptance test. Multiple PromQL anti-patterns: `count()` over a boolean gauge counts nodes not pressured-nodes (use `sum()`); `count()`/`sum()` over an empty set returns NoData not 0 (append `or vector(0)`).
- All 5 Talos nodes are on **v1.13.4 / k8s v1.36.1**; the documented upgrade flow silently stalls on single-replica-PDB workloads (kyverno + CNPG) — force-`kubectl drain --disable-eviction` first. The **node-taxonomy migration is essentially complete**: soyos (control-plane/etcd) are Longhorn/app-free; storage + workloads run on the two workers. Capability labels (`node.webgrip.io/cpu|pool`) are the placement contract, never hostnames.
- Cross-cutting hazards: **RWX PVCs are Kyverno-blocked cluster-wide**; **safety hooks** block imperative kubectl/Longhorn/talosctl mutations (even `--help`/comments containing trigger words) — hand mutating steps to the human; **concurrent agents on unprotected `main`** revert each other's work — `git fetch` + verify-not-behind + stage explicit pathspecs before pushing.
- Git **worktrees** isolate working dirs (and `.worktreeinclude` copies this repo's gitignored bootstrap files into Claude-created worktrees) but do NOT solve push-to-`main` collisions — the rebase-before-push discipline still applies.

**Stats:** ~185 items in (across 21 unique source threads in 5 already-consolidated batches; "1 copy 9.md"≡"1 copy 10.md" duplicate counted once) → 96 consolidated out; conflicts: 3; low-confidence: 14

---

## Forgejo Actions engine behavior

### Reusable-workflow expansion flattens inner jobs and ignores the caller's `if:` → duplicate racing builds
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] in-repo as cause of a real prior incident + the `changed-images` naming case)
- **What:** Forgejo ≥15.0.0 expands reusable-workflow `uses:` calls into the caller's job graph (PR forgejo#10525). Consequences: (1) a caller job's `if:` does NOT gate the flattened inner jobs, so two mutually-exclusive `if:`-gated reusable calls (e.g. `distribute` vs `distribute-prerelease`, or `is_prerelease`-gated build splits) BOTH run their inner build, racing on the same registry tag + buildx `:cache` ref; (2) every `workflow_call` level appears as its own pass-through job (cosmetic, renders as a `0s` ⟳ row). Fix: use ONE call/job and push the conditional inside `inputs` (gate the `:latest` tag inline so it resolves to `''` on prereleases — the engine skips blank tags). GitHub namespaces inner jobs, so the same file is fine there.
- **Why it matters:** Caller-level `if:` gating silently fails to dedupe under flattening, producing concurrent racing builds (or build-plan rejection).
- **Snippet:** `${{ needs.parse-release-tag.outputs.is_prerelease != 'true' && format('webgrip/{0}:latest', needs.parse-release-tag.outputs.image) || '' }}`
- **Sources:** batches 1 (copy 13, copy 6), 3 (copy 4, copy 5)

### Caller job id must differ from every inner job id of the workflow it calls
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Under v15 expansion, if a calling job's id equals a job id inside the reusable workflow it calls, the flattened graph has no dependency-free job and Forgejo rejects it at detection: "the workflow must contain at least one job without dependencies." Example: caller `determine-changed-directories` calling `determine-changed-directories.yml` whose inner job was also `determine-changed-directories`; fix = rename the caller to `changed-images`. The error message points at `needs:`/cycles and misdirects you. (Corrects an in-thread false hypothesis that "Forgejo lacks reusable-workflow expansion" — it shipped in 15.0.0.)
- **Sources:** batches 1 (copy 13, copy 6), 3 (copy 5)

### Composite/reusable resolution splits by call-site; `data.forgejo.org` is an incomplete mirror
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Job-level reusable-workflow `uses:` (bare slug `webgrip/workflows/.forgejo/workflows/*.yml@main`) and the top-level call resolve against the LOCAL Forgejo instance (nested `workflow_call` supported). But step-level **composite-action** `uses:` resolve against `[actions] DEFAULT_ACTIONS_URL`, defaulting to `https://data.forgejo.org` — a curated/incomplete mirror that has `actions/checkout` + `docker/*` but 404s (`remote: Not found`) on `actions/github-script`, `sigstore/cosign-installer`, `anchore/sbom-action`, and all `webgrip/*`. Pin missing externals/internals to absolute URLs case-by-case (`https://github.com/...` or `https://forgejo.webgrip.dev/...`).
- **Why it matters:** A bare `uses:` silently hitting a stale mirror is a real failure mode for any library consumed by many repos.
- **Sources:** batches 3 (copy 4, copy 7), 1 (copy 13 — `DEFAULT_ACTIONS_URL` server-side lever)

### The cluster's Forgejo serves actions from `data.forgejo.org` because `DEFAULT_ACTIONS_URL` is unset
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** `forgejo/app/helmrelease.yaml` sets `gitea.config.actions: { ENABLED: true }` and does NOT set `DEFAULT_ACTIONS_URL`, so it defaults to `https://data.forgejo.org` — every CI action clones from the internet. Setting it globally would make in-cluster Forgejo authoritative for ALL actions (15+ used); un-mirrored ones would 404 (high blast radius). The only built-in lever for the action-clone wall is this global flip — rejected for blast radius; chosen fallback is a scoped per-action mirror.
- **Sources:** batch 1 (copy 13)

### Workflow-directory precedence is first-existing-dir-wins (not merged)
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** Forgejo's `ListWorkflows` checks, in order, `.forgejo/workflows` → `.gitea/workflows` → `.github/workflows`, using only the **first existing directory** — NOT additive; the trigger is the directory's existence even if empty. Once `.forgejo/workflows/` exists, Forgejo ignores `.github/`. GitHub only ever reads `.github/`. Resolution is per-commit/per-branch; no admin toggle to disable the `.github` fallback yet (forgejo#9203).
- **Why it matters:** Dispels the fear that Forgejo double-runs `.github`+`.forgejo`. An empty `.forgejo/workflows/.gitkeep` is a valid lever to stop Forgejo running a repo's `.github` workflows without porting them.
- **Sources:** batch 3 (copy 5)

### The `workflow_call: secrets:` parser warning is benign
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Forgejo's `DetectWorkflows` ignores any workflow whose `on.workflow_call` has a `secrets:` key (`[W] ignore invalid workflow "X": ... workflow_call only supports keys "inputs" and "outputs", but key "secrets" was found`). Affects ~30 webgrip/workflows reusables. Benign at runtime — when called via `uses:` they still execute correctly; it only blocks standalone detection and clutters logs.
- **Sources:** batch 3 (copy 4)

### `on_source_change` occasionally misses a push; amending does NOT re-trigger
- **Type:** GOTCHA · **Confidence:** MEDIUM ([ASSERTED])
- **What:** A valid push with matching `paths:` landed on main but created no run — a transient detection miss (confirmed via the actions/tasks run-number gap). To re-trigger you must change a file matching the `paths:` filter; `git commit --amend` + force-push does NOT trigger (tree identical → empty push diff → no path matches). A config-only change does NOT cut a release (matrix empty unless an `ops/docker/<image>` file changed).
- **Sources:** batches 3 (copy 4), 2 (copy 14)

### `github.repository_owner` and `github.sha` are EMPTY in `workflow_dispatch` runs — hardcode `webgrip`
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] — user-applied correction)
- **What:** In a Forgejo `workflow_dispatch`-triggered run, `github.repository_owner` and `github.sha` are empty (empty owner → `harbor.webgrip.dev//<image>` double-slash → "invalid reference format"; empty sha → blank `IMAGE_REVISION`). `github.repository` IS populated. The publish path hardcodes `webgrip`, so any derived cache ref must too (`BUILD_CACHE_REF=${{ inputs.registry }}/webgrip/${{ inputs.package-name }}:cache`) or you get a never-matching ref → permanent cold cache.
- **Snippet:** `docker-tags: | webgrip/${{ needs.parse-release-tag.outputs.image }}:${{ ...version }}`
- **Sources:** batches 3 (copy 4), 1 (copy 6)

### A CI-created release does NOT fire a release Actions event — dispatch explicitly
- **Type:** GOTCHA + DECISION · **Confidence:** HIGH ([VERIFIED] two ways — no release-event run in the entire Actions history; Forgejo server log shows no release dispatch)
- **What:** A release created inside a CI job does not fire a `release` Actions event (loop-prevention), even with a real user PAT (`draft:false`). GitHub avoids this with a GitHub App token (which DOES fire); Forgejo has no equivalent. The tag + Release object are created by `publish` *before* any later failure, so a red job still leaves a release behind. Resolution: keep `on_release_published.yml` as the single build/sign source, make it reachable via a `workflow_dispatch` trigger (inputs `tag`, `is_prerelease`), have `parse-release-tag` handle both events, and have the semantic-release composite POST a dispatch (gated on the version output). Per-image dispatch is precise (handles multi-image pushes a matrix-job output can't). Don't relocate/duplicate the build+sign jobs. A `workflow_dispatch` input WITHOUT explicit `type:` makes Forgejo render `Invalid input type ""` and reject the API dispatch — add `type: string` to every input (GitHub tolerates omission).
- **Snippet:** `curl -fsS -X POST -H "Authorization: token ${GITEA_TOKEN}" "${GITEA_URL%/}/api/v1/repos/${REPO}/actions/workflows/on_release_published.yml/dispatches" -d "{\"ref\":\"${REF}\",\"inputs\":{\"tag\":\"${TAG}\",\"is_prerelease\":\"${IS_PRERELEASE}\"}}"`
- **Sources:** batches 3 (copy 4), 2 (copy 14)

### `semantic-release-monorepo` `outputs.version` is the FULL namespaced tag, not bare semver
- **Type:** GOTCHA + FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** Under `extends: 'semantic-release-monorepo'`, the `exec` `successCmd echo "version=${nextRelease.version}"` emits the `tagFormat`-prefixed value (e.g. `techdocs-builder-v1.2.19`), NOT bare `1.2.19`. Pass it to the dispatch/parse verbatim (matches `^(.+)-v(.+)$`) — do NOT prepend `<package-name>-v` (a wrong "fix", commit ca732f2, doubled it → `techdocs-builder-vtechdocs-builder-v1.2.14`; the real original failure was the `data.forgejo.org` 404, misdiagnosed as a tag-format bug). Per-image `.releaserc.cjs` sets `tagFormat: '<image>-v${version}'`.
- **Sources:** batches 3 (copy 4), 2 (copy 14), 1 (copy 6)

### Forgejo runner pod logs show only the DinD sidecar, not job step output
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** `kubectl -n forgejo logs <runner-pod> --all-containers` shows only dockerd/containerd lifecycle (the DinD sidecar). Actual Actions step output streams to Forgejo, not pod stdout — you cannot diagnose a failed build from the runner pod. Runner pods are KEDA-scaled ephemeral Jobs (`scaledjob.keda.sh/name=forgejo-runner`), 2 containers, label `app.kubernetes.io/name=forgejo-runner`.
- **Why it matters:** Don't grep runner pods for build errors — get the job log from the authenticated Forgejo UI.
- **Sources:** batch 2 (copy 14)

### Verify a Forgejo release-pipeline run by its actual conclusion, not the tag/Release existing
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** Poll the tasks API and read `status`/`conclusion` for the named job. Do NOT infer success from the tag/Release existing — `publish` creates those even when the job later fails (the GraphQL-404 path); `git ls-remote --tags` is likewise insufficient. Readable unauthenticated against `https://forgejo.webgrip.dev`: `actions/tasks?limit=N`, `releases/tags/<tag>`, `actions/runs/<id>`. NOT readable unauthenticated (404): `actions/runs/<id>/jobs`, `actions/tasks/<id>/logs` — get failing logs from the UI/session.
- **Snippet:** `curl -fsS ".../actions/tasks?limit=30"` then read `status conclusion name head_sha`
- **Sources:** batch 2 (copy 14)

### KEDA warm-pool runner + `activeDeadlineSeconds` → false `KubeJobFailed` every ~2h
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] — Job reason `DeadlineExceeded` at exactly startTime+7200s)
- **What:** The ScaledJob keeps a warm pool blocked on `forgejo-runner one-job --wait`. With `jobTargetRef.activeDeadlineSeconds: 7200`, an idle waiting runner is killed as `DeadlineExceeded` every 2h; `failedJobsHistoryLimit: 5` → 5 permanent `KubeJobFailed` alerts. `activeDeadlineSeconds` caps wait+execute, so it kills intentionally-blocking warm runners. Fix: remove `activeDeadlineSeconds` (Forgejo's per-job timeout is the real runaway cap) and set `failedJobsHistoryLimit: 0`.
- **Sources:** batch 2 (copy 8)

---

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

## Dockerfile / dual-pipeline build wiring

### Parameterize base registries via ARGs defaulting upstream; in-cluster overrides to Harbor proxy paths
- **Type:** DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** Every base ref goes through `ARG REGISTRY_DOCKERHUB=docker.io`, `REGISTRY_GHCR=ghcr.io`, `REGISTRY_MCR=mcr.microsoft.com`, defaulting upstream so GitHub-hosted builds are byte-identical. The `.forgejo` build overrides them to `harbor.webgrip.dev/{dockerhub,ghcr,mcr}` proxy projects via `docker-build-args`/`--build-arg`. Each image consumes only the ARGs it declares (buildx warns harmlessly on unused). Renovate resolves ARG-default chains so the upstream ref stays trackable. Harbor proxy paths use a prefix (`dockerhub/library/alpine`), so a transparent buildkit registry-mirror does NOT cover them — the path must be explicit in `FROM`, which is exactly why hardcoding `harbor.webgrip.dev` would break LAN-unreachable GitHub builds.
- **Snippet:** `ARG BASE_IMAGE=${REGISTRY_DOCKERHUB}/library/alpine:3.23.4@sha256:5b10f432…` / `FROM ${BASE_IMAGE}`
- **Sources:** batch 3 (copy 4)

### Inter-image pin via the GHCR-proxy path so ONE digest works in both pipelines
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Native Harbor (`harbor.webgrip.dev/webgrip/techdocs-builder`) and GHCR builds have DIFFERENT digests, so a single `@sha256:` pin can't serve both. Pin the inter-image base via `REGISTRY_GHCR` (default `ghcr.io`, Forgejo overrides to `harbor.webgrip.dev/ghcr`) — the Harbor GHCR pull-through proxy preserves GHCR's digest, so one ref `webgrip/techdocs-builder:<ver>@sha256:<ghcr-digest>` is valid on ghcr.io AND via the proxy, and Renovate tracks it. (Verified identical digest `sha256:ac891…`.)
- **Snippet:** `ARG REGISTRY_GHCR=ghcr.io` then `ARG TECHDOCS_BUILDER=${REGISTRY_GHCR}/webgrip/techdocs-builder:1.2.7@sha256:ac891abd…`
- **Sources:** batch 3 (copy 4)

---

## CI library structure & semantic-release on Forgejo

### Two-tree layout: frozen `.github/` + adapted `.forgejo/`, enforced by a parity check
- **Type:** DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** Keep `.github/workflows` + `.github/composite-actions` byte-for-byte frozen and add a parallel `.forgejo/` mirror with all Forgejo adaptations (self-refs rewritten `.github→.forgejo`). Rejected: one dual-purpose tree (impossible — checkout v6 vs v5) and a flag-day move (breaks every GitHub consumer). A parity check (`scripts/forgejo-parity-check.sh`, ADR `docs/adrs/0002-forgejo-actions-parity.md`) FAILS if anything under `.forgejo/` mentions `ghcr.io`, `actions/checkout@v6`, `create-github-app-token`, or `@semantic-release/github` (comments included), enforces no orphan `.forgejo` workflow lacking a `.github` sibling (except a `FORGEJO_ONLY` allowlist), fatal under `STRICT=1`. `generate-forgejo-workflows.sh` idempotently regenerates mechanical T1 copies, skipping a hand-owned `MANUAL[]` list. Two-repo split: `webgrip/workflows` = reusables only (canonical templates); `webgrip/infrastructure` = consuming pipeline + per-image build images + `.releaserc.js` + an infra-local hand-maintained mirror of the monorepo composite — editing the workflows copy alone does NOT affect the live release path.
- **Why it matters:** Both ecosystems run independently during migration; "depending on GitHub to run the CI that frees you from GitHub" is caught by a linter; a CI log mentioning `release-per-image` is not debuggable from the workflows repo alone.
- **Sources:** batches 3 (copy 7, copy 5), 1 (copy 6 — two-repo split)

### Tiered port of a GitHub workflow to `.forgejo/`
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** Classify each workflow: **T1 mechanical** (copy + rewrite `.github/`→`.forgejo/` self-refs) — `scripts/generate-forgejo-workflows.sh`; **T2 action swap/pin** (checkout v6→v5, setup-node v6→v4, cache v5→v4; ghcr→configurable registry); **T3 reimplementation** (`actions/github-script` octokit → Forgejo REST curl; `actions/ai-inference` GitHub Models → direct OpenAI; `softprops/action-gh-release` → Forgejo Releases API; `peaceiris/actions-gh-pages` → branch-push). `actions/github-script` steps using only `core.summary` can be kept (forgejo-runner provides the summary API); only `github.rest.*`/`github.graphql` calls must be rewritten.
- **Sources:** batch 3 (copy 7)

### Per-registry build/push = one engine + thin wrappers (the `-ghcr` action was a misnamed generic engine)
- **Type:** DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** Build/push lives in ONE composite `docker-build-push-registry` (login + tag-normalize + buildx + summary) wrapped by ONE reusable `docker-build-and-push-registry.yml`; thin `docker-build-and-push-{harbor,ghcr}.yml` `uses:` the engine, pinning the registry + mapping named secrets (`HARBOR_ROBOT_*` → `REGISTRY_USERNAME/TOKEN`, `runs-on: docker`). The original `docker-build-push-ghcr` was actually the generic engine (display name "(Registry)", "Harbor by default") — a misnomer; `docker-build-push` (no suffix) is Docker-Hub-only. All `.forgejo/workflows/` jobs with direct steps pin `runs-on: docker` (the only label reaching LAN-only Harbor); orchestrator jobs that only `uses:` a reusable correctly omit `runs-on`.
- **Sources:** batches 3 (copy 4, copy 7), 1 (copy 6)

### semantic-release on Forgejo: `@saithodev/semantic-release-gitea`, env-gated on a LITERAL flag
- **Type:** GOTCHA + REFERENCE · **Confidence:** HIGH ([VERIFIED]; matches existing memory `forgejo-semantic-release-gitea-plugin.md`)
- **What:** On Forgejo the GitHub plugin's `verifyConditions`/`publish` succeed (REST `…/api/v1`) but the `success` step `POST …/api/v1/graphql` (getAssociatedPRs) → `404 page not found` → job exits 1 (tag+Release already created by `publish`). The shared `.releaserc.js` selects the publish plugin at require-time. Critical (first fix failed here): gate on a *literal* `SEMANTIC_RELEASE_GITEA: "true"` exported by the action, NOT on `process.env.GITEA_URL` derived from `${{ vars.FORGEJO_INSTANCE_URL }}` — that repo variable was unset, so `GITEA_URL=""` and the gate silently fell back to GitHub. Let `GITEA_URL` fall back to `github.server_url`. Also: `npx semantic-release --config <file>` silently ignores `--config` (not a real flag — config resolves via cosmiconfig from cwd, so each image's `ops/docker/<image>/.releaserc.cjs` wins); plugin selection MUST live in config, not a CLI flag. Drop `semantic-release-github-actions-tags` + `id-token: write` unless needed.
- **Snippet:** `const publishPlugin = process.env.SEMANTIC_RELEASE_GITEA ? '@saithodev/semantic-release-gitea' : '@semantic-release/github';`
- **Sources:** batches 2 (copy 14), 3 (copy 7, copy 4)

### Architecture: "release once, publish many" — Forgejo sole authority, GitHub pure mirror + version commit-back
- **Type:** DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** Exactly one system decides a version (semantic-release, tags, changelog, package.json bump). GitHub runs zero Actions (`.github/` tree deleted on `infrastructure`); Forgejo's runner fans out to BOTH Harbor (LAN) and GHCR (internet). GitHub Release objects are recreated via a best-effort step (not an inline plugin, so a GitHub/PAT hiccup can't abort the Forgejo release). Forgejo-gated `@semantic-release/npm` (`npmPublish:false`) + `@semantic-release/git` version-bump commit-back (`chore(release): ${nextRelease.gitTag} [skip ci]`, identity `webgrip-ci <ci@webgrip.nl>`); both forges honor `[skip ci]` so the mirror push re-triggers nothing. GHCR/GitHub parity for the cached verify build was deliberately skipped (GitHub-hosted runners aren't the pain point). `infrastructure` is NOT double-publishing — verified all GitHub releases ≤2026-06-18 (pre-migration); the GitHub gap is a missing push-mirror, not double-publishing.
- **Sources:** batches 3 (copy 4, copy 9/10), 1 (copy 6)

### Pinned semantic-release toolchain + npm cache; `actions/checkout@v6` broken on non-GitHub runners
- **Type:** REFERENCE + FACT · **Confidence:** HIGH ([VERIFIED]; cache effectiveness [ASSERTED])
- **What:** The monorepo action installs a pinned, lockfile-less set via `npm install --no-save --no-audit --no-fund` (Node 24, checkout@v5 — v6 hardcodes GitHub paths in `includeIf` and fails on Forgejo); an `actions/cache@v4` step caches `~/.npm` keyed on pinned versions (bump key suffix on change). Pins: `semantic-release@24.2.7`, `semantic-release-monorepo@8.0.2`, `@semantic-release/commit-analyzer@13.0.0`, `@semantic-release/exec@7.0.3`, `@semantic-release/npm@12.0.1`, `@semantic-release/git@10.0.1`, `@saithodev/semantic-release-gitea`, `@semantic-release/release-notes-generator@14.0.0`, `conventional-changelog-conventionalcommits@7.0.2`.
- **Sources:** batches 1 (copy 6), 2 (copy 14), 3 (copy 7, copy 4, copy 5)

### Forgejo auth model + Releases/Issues REST shapes (replacing GitHub actions)
- **Type:** REFERENCE · **Confidence:** MEDIUM ([ASSERTED] — designed/implemented, many T3 shapes not run live)
- **What:** `actions/create-github-app-token` has no Forgejo analog — use a dedicated CI bot user with a repo/org-scoped secret; API is Gitea-compatible REST at `${URL}/api/v1` with `Authorization: token <TOKEN>` (curl, not octokit). Issues: `POST/GET/PATCH …/issues`; Releases (replacing `softprops/action-gh-release`): `GET …/releases/tags/{tag}` → `POST …/releases`, assets `POST …/releases/{id}/assets?name=<file>` multipart `-F "attachment=@<file>"`; template repos `POST …/repos/{template_owner}/{template_repo}/generate`; topics `PUT …/repos/{o}/{r}/topics {"topics":[...]}` (Gitea field, not GitHub's). No native Forgejo Pages (`peaceiris/actions-gh-pages` → branch-push); GitHub Advanced Security / Models have no analog (dropped with `# Forgejo: dropped <X>` comments).
- **Sources:** batch 3 (copy 7)

### Forgejo flux/topology coordinates, run-inspection API & local tooling
- **Type:** REFERENCE · **Confidence:** HIGH ([VERIFIED])
- **What:** `on_source_change.yml` (changed-images via `determine-changed-directories.yml` scoped `inside-dir: ops/docker` → matrix release-per-image) → `semantic-release-monorepo` composite → dispatch. Forgejo internal `http://forgejo-http.forgejo.svc.cluster.local:3000`; public `https://forgejo.webgrip.dev`. `origin` = `ssh://git@forgejo-ssh.webgrip.dev/webgrip/infrastructure.git`. Inspect runs: `GET …/repos/webgrip/infrastructure/actions/tasks?limit=N` (`.workflow_runs[].run_number/status/conclusion/name/head_sha`); status-filter UI `…/actions?status=<int>` (5=Waiting,6=Running,7=Blocked). `actionlint`/`yamllint`/PyYAML NOT installed locally — validate structurally + parity-greps; `forgejo-runner exec` is higher-fidelity than `act`. Sibling checkouts under `/home/ryan/projects/webgrip/` (homelab-cluster, infrastructure, workflows). EditorConfig: LF, final newline, 4-space (2 for YAML/JSON/MD), 150-char.
- **Sources:** batches 2 (copy 14), 3 (copy 4, copy 7)

---

## Signing, verification & registry policy

### cosign signing via OpenBao Transit, authorized by Forgejo Actions OIDC, key-only Kyverno verify (no Rekor)
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** Harbor (and GHCR) images are signed **keyed, not keyless**: `cosign sign --tlog-upload=false --key hashivault://cosign-webgrip` calls OpenBao's Transit engine (ECDSA-P256); the private key never leaves OpenBao. Authorization is per-job: the release job enables OIDC, Forgejo mints a token (issuer `https://forgejo.webgrip.dev/api/actions`), OpenBao's JWT auth (`auth/forgejo`, role `cosign-signer`) exchanges it for a sign-only Transit token only when bound claims match (OIDC disabled for fork PRs). The public key is published to a `cosign-webgrip-pub` ConfigMap by a CronJob; Kyverno `image-verify-harbor-audit` verifies against it **key-only** (no rekor block → no tlog lookup; the GHCR keyless policy explicitly sets `rekor.url`). `--tlog-upload=false` avoids leaking digests/timestamps to public Rekor and any internet dependency. Requires a one-time `generate-root` break-glass to enable Transit + the forgejo jwt auth. The sign-attest action signs BY DIGEST (`docker buildx imagetools inspect … --format '{{.Manifest.Digest}}'`) and is generalized to `REGISTRY_USERNAME`/`REGISTRY_TOKEN` so one key signs both registries.
- **Why it matters:** Keyless/Fulcio won't trust a private Authentik; this is the keyed equivalent with per-workflow identity; explains the Harbor-vs-GHCR policy difference.
- **Sources:** batches 3 (copy 5, copy 4), 2 (copy 3, copy 2)

### OpenBao `cosign-signer` JWT role must bind the Forgejo `workflow_dispatch`/branch claim shape
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** The `auth/forgejo` JWT role originally bound `event_name=release` + `ref=refs/tags/*` (GitHub shape) → OpenBao 400'd the login because the Forgejo flow triggers via `workflow_dispatch` on a branch. Rebind `bound_claims` to `{"repository":"webgrip/infrastructure","event_name":"workflow_dispatch","ref":"refs/heads/*"}` (verified: `aud=openbao-cosign`, `event_name=workflow_dispatch`, `ref=refs/heads/main`). The Forgejo OIDC token request URL may lack a query string, so append `audience=` with `?` vs `&` correctly (malformed URL → default audience → 400).
- **Snippet:** `case "$ACTIONS_ID_TOKEN_REQUEST_URL" in *\?*) sep='&';; *) sep='?';; esac`
- **Sources:** batch 3 (copy 4 — refines copy 5's old `event_name=release`/`refs/tags/*` binding)

### The Harbor SBOM trigger lives only in the Forgejo action; the two cosign actions are NOT symmetric
- **Type:** DECISION + FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** The Harbor-native-SBOM step lives ONLY in `.forgejo/actions/cosign-sign-attest` (gated `if: contains(inputs.registry, 'harbor')`); GHCR has no server-side SBOM API, so the step there is meaningless. The Forgejo/Harbor path signs key-based via OpenBao Transit (`--tlog-upload=false`), while the `.github` mirror pushes to GHCR via keyless OIDC/Fulcio/Rekor — changes must be evaluated per-target, not blindly mirrored. The SBOM step is fail-soft (logs `::warning::` on non-2xx; the cosign attestation already proves provenance + Trivy Operator covers analysis). Tokens passed via a `0600` curl config file (`-K`), not `-u`, to keep the robot token out of the process list (the literal `$`/`+` in `robot$webgrip+ci` survive inside the quoted `user = "..."`). The action installs cosign v2.4.3 + Syft v1.21.0 (pinned to absolute github.com URLs because `data.forgejo.org` 404s), generates CycloneDX+SPDX, signs+attests via Forgejo OIDC → OpenBao Transit, uploads SBOM to in-cluster Dependency-Track (fail-soft). OpenBao role `cosign-signer`, JWT path `/v1/auth/forgejo/login`, audience `openbao-cosign`. DT `http://dependency-track-api-server.security.svc.cluster.local:8080/api/v1/bom`.
- **Sources:** batches 2 (copy 3, copy 2), 3 (copy 4)

### Kyverno policies are Audit-only; Harbor "Deployment security" stays OFF
- **Type:** DECISION · **Confidence:** HIGH (Audit [VERIFIED]; Harbor-off [ASSERTED] single-source)
- **What:** Kyverno policies `kubernetes/apps/kyverno/policies/app/{image-verify-audit,image-attestations-audit,image-verify-harbor-audit}.yaml` are all `validationFailureAction: Audit` — flip Audit→Enforce only once a release is green with zero false positives (explicitly NOT done). Leave Harbor project Deployment-security OFF: Harbor's cosign check only verifies a signature exists (not against your key) and blocks pulls of unsigned artifacts including the buildx `:cache` tag (breaking cache-from); "Prevent vulnerable images" can make a running image unpullable on a new CVE. Enforce only at Kyverno admission.
- **Sources:** batches 3 (copy 4, copy 5)

---

## Harbor operations & supply-chain

### Harbor's native SBOM column is gated by `sbom:create` (NOT `scan:create`), fed only by Harbor's own scanner
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED] from Harbor source at the deployed tag)
- **What:** Triggering Harbor's native SBOM accessory via `POST .../artifacts/{ref}/scan {"scan_type":"sbom"}` is authorized by RBAC resource `sbom` + action `create` (in `scan.go`: `if scanType == ScanTypeSbom { res = ResourceSBOM }`) — a DIFFERENT resource from the vuln scan's `scan:create`. Granting `scan:create` (the intuitive guess) does NOT fix the 403. The "SBOM" UI column is populated EXCLUSIVELY by Harbor's own native (Trivy-backed) `.sbom` accessory — a `cosign attest --type cyclonedx` produces a `.att` accessory shown under "Signed" but never in the SBOM column (different media types: attestation → Kyverno + DT; `.sbom` → Harbor UI/policies). Needs Harbor ≥2.11 + an SBOM-capable scanner. The CI robot lacked the grant → release SBOM step 403'd (fixed least-privilege, commit 9938e09, live-verified). Harbor's auto-scan-on-push also scans the `sha256-<digest>` signature/attestation accessory rows (~5 MiB, "Signed") emitting spurious warnings — expected noise; the rows that matter are full image manifests.
- **Snippet:** RBAC `{resource:sbom, action:create}`; access list `{"resource":"sbom","action":"create"}` alongside repository push/pull.
- **Sources:** batches 2 (copy 2, copy 3), 3 (copy 4)

### The robot provisioner set permissions only on FIRST creation — fix = convergence PUT reusing the stored full name
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] by code path + live job behavior)
- **What:** `robot$webgrip+ci` (project-level, id=2) is created/converged by `configure.sh` in `harbor-proxy-config.configmap.yaml` (CronJob `harbor-proxy-config`, ns `harbor`, `17 * * * *`). `ensure_webgrip_robot()` POSTed permissions only when the robot didn't exist; for an existing robot it merely PATCHed the secret, so editing the create-body's permissions array is a no-op against the live robot. Fix: a convergence `PUT /robots/{id}` resending the desired spec every run. Caveats: `UpdateRobot` rejects a changed name/level; `GET /robots/{id}` returns the full name `robot$webgrip+ci` (create used bare `ci`) — the PUT must reuse the exact stored name. `GET /robots` lists only SYSTEM robots — find a project robot via `q=Level%3Dproject%2CProjectID%3D<id>`. There is NO Harbor robot/project/scanner IaC in `webgrip/infrastructure` — only this homelab-cluster file touches Harbor RBAC.
- **Why it matters:** Classic idempotency footgun: "I updated the IaC" ≠ "the running resource changed."
- **Snippet:** `_rname="$(hc GET "/robots/$_rid" | jq -r '.name')"; hc PUT "/robots/$_rid" "{\"name\":\"$_rname\",...,\"permissions\":$_perms}"`
- **Sources:** batches 2 (copy 2), 3 (copy 4)

### Talos registry mirror is a silent no-op unless nodes can DNS-resolve the Harbor hostname
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED]; `extraHostEntries` confirmed in `talos/patches/global/machine-network.yaml`)
- **What:** The mirror endpoints point at `https://harbor.${secretDomain}/v2/…`, but nodes resolve via `1.1.1.1/1.0.0.1` and `harbor.webgrip.dev` is LAN-only → containerd got `dial tcp: lookup harbor.webgrip.dev on 127.0.0.53:53: no such host` and silently fell back to upstream on every pull. The fail-open drill passed trivially (fallback was the only working path) and all proxy projects stayed empty. Image pulls use **node DNS** (kubelet/containerd), not pod/cluster DNS. Fix: a static Talos `extraHostEntries` mapping `harbor.${secretDomain}` → `10.0.0.27` (envoy-internal LAN VIP).
- **Why it matters:** A mirror can be fully configured and verified-present on every node yet route nothing, with zero errors. Always verify a node can resolve the mirror host before declaring success.
- **Snippet:** `mise exec -- talosctl -n <ip> read /etc/hosts | grep harbor` → `10.0.0.27 harbor.webgrip.dev`
- **Sources:** batch 1 (copy 11)

### Route images via transparent Talos mirror (fail-open); apply with no drain/reboot
- **Type:** DECISION + PROCEDURE · **Confidence:** HIGH ([VERIFIED]; `overridePath: true` confirmed)
- **What:** Per-registry `machine.registries.mirrors` with `overridePath: true`, composed with Spegel `prependExisting: true` (Spegel peers → Harbor proxy → upstream). Manifests keep upstream refs. `skipFallback` default `false` → Harbor down ⇒ fall back to upstream (fail-open), never ImagePullBackOff. Six upstreams: `docker.io→dockerhub, ghcr.io→ghcr, quay.io→quay, mirror.gcr.io→gcrmirror, registry.k8s.io→k8s, code.forgejo.org→forgejo`. `overridePath: true` is mandatory or containerd appends its own `/v2/`. `machine.registries.mirrors` + `extraHostEntries` are containerd/`/etc/hosts` reloads — no reboot/drain: `task talos:apply-node IP=… MODE=no-reboot` (NOT `apply-node-safe`, which drains; avoiding the drain matters because draining soyo triggers Longhorn/CNPG incidents); one node at a time, control-plane last. Inspect via `talosctl get mc v1alpha1` (NOT `registriesconfig`, which isn't a registered resource → false "not applied").
- **Sources:** batch 1 (copy 11, copy 16)

### Harbor 2.15 proxy returns the FULL upstream tag list → Renovate works; `registryAliases` keys on host only
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED] — app-template 15/15 tags identical to ghcr.io on a cold repo; matches MEMORY)
- **What:** The old "Harbor only returns cached tags, breaks Renovate" limitation is gone in 2.15 — a proxy-cache `tags/list` proxies the complete upstream list even for uncached repos. `registryAliases` cannot disambiguate multiple upstreams behind one Harbor host (`/ghcr`, `/quay`) because it keys on the host alone (and is applied at extraction, before packageRules, so it can't be set in a packageRule). The working lever for Harbor-proxied OCI charts is to widen the `ghcr.io` packageRules to also match the Harbor path.
- **Snippet:** `matchPackageNames: ["/^ghcr\\.io\\//", "/^harbor\\.webgrip\\.dev\\//"]`
- **Sources:** batch 1 (copy 11)

### Charts go through Harbor by URL-rewrite; only non-bootstrap OCI; NOT fail-open
- **Type:** DECISION · **Confidence:** HIGH ([VERIFIED] — rewritten OCIRepositories Ready)
- **What:** Flux source-controller fetches charts directly (no containerd), so the Talos mirror does nothing for charts — the only lever is the OCIRepository `url:`. Rewrote 25 non-bootstrap OCI chart sources `oci://ghcr.io/… → oci://harbor.webgrip.dev/ghcr/…`. Unlike images this is NOT fail-open: while Harbor is down, affected apps can't install/upgrade (running releases keep running). Keep upstream (bootstrap/reach-Harbor path): flux-operator, flux-instance, cilium, coredns, cert-manager, external-secrets, kyverno, k8s-gateway, envoy-gateway, spegel, trust-manager. HTTP HelmRepository sources stay upstream (Harbor's proxy is OCI-only; ChartMuseum removed in 2.8). OCIRepository bumps come from a `custom.regex` manager in the shared preset; pinned `@sha256:` digests stay valid through the proxy (content-addressable).
- **Sources:** batch 1 (copy 11)

### A manifest GET through the proxy doesn't register/persist; only a full pull does — warm via skopeo Job, not respawn
- **Type:** FACT + PROCEDURE · **Confidence:** HIGH (mechanism [VERIFIED]; full warm run pending)
- **What:** Fetching only the manifest (`crane manifest`, a bare `/v2/.../manifests/<ref>` GET) is proxied but not stored as a catalog artifact, doesn't cache blobs, and doesn't enable Trivy scanning — killed the "warm just the manifests" idea. To get an image into Harbor (registered, cached, scannable) you must do a real pull. A digest-pinned running image is byte-identical to what Harbor would serve (content-addressable + Kyverno verify), so "image in Harbor == image running" is guaranteed by the digest pin WITHOUT forcing pulls through Harbor; forcing all running images through Harbor only adds cache-of-record + Trivy coverage at real Garage cost — not worth a risky mass-respawn ("batched rollouts → storage collapse"). To warm without restart: an in-cluster skopeo Job enumerating running images, `skopeo copy docker://<harborref> dir:/scratch/_w` one at a time (on worker-1, emptyDir scratch, digest-pinned skopeo base). skopeo rejects refs with BOTH tag and digest (`sed -E 's#:[^/@]*@sha256:#@sha256:#'`); the image-ref→proxy-path mapping must normalize bare/implicit docker.io names (first segment is a registry only if it contains `.`/`:` or is `localhost`; `library/` prepended for single-segment).
- **Sources:** batch 1 (copy 11)

### Harbor proxy-cache provisioner originally skipped credential-less (anonymous) registries; GC + retention + scan-on-push
- **Type:** GOTCHA + PROCEDURE · **Confidence:** HIGH ([VERIFIED] — code fix; flux-local passed)
- **What:** `ensure_registry()` did `return 0` (skipped creation) when no user/pass was supplied — fine for dockerhub/ghcr (creds lift rate limits) but it blocked anonymous upstreams (quay/gcrmirror/k8s/forgejo). Fixed to always create the endpoint, including the credential block only when both user and pass are present. Proxy projects: `dockerhub→docker.io, ghcr→ghcr.io, quay→quay.io, gcrmirror→mirror.gcr.io, k8s→registry.k8s.io, forgejo→code.forgejo.org` (generic docker-registry, public, `storage_limit: -1`). GC + retention are complementary: retention (`POST /retentions`, template `latestPushedK`, exclude tag `cache`) untags old versions; GC (`POST/PUT /system/gc/schedule`, `delete_untagged:true`, cron `0 30 3 * * 0`) reclaims bytes incl. orphaned `:cache` manifests; per-project `auto_scan`/`auto_sbom_generation` (≥2.11) via `PUT /projects/{id}`. Shell `$` doubled to `$$` for Flux post-build substitution (so an un-doubled `${var}` referencing an undefined var doesn't get blanked); build jq programs by interpolating doubled shell vars into the program string, NOT `jq --arg` (a jq `$var` looks like a Flux `$VAR`). The sibling `forgejo-actions-secrets` ks deliberately has NO `postBuild.substituteFrom`, so its script uses single `$`. Never `kubectl apply` the raw git file (`$$` would land live; reproduce Flux's render with `sed 's/\$\$/\$/g'`, syntax-check `sh -n`).
- **Sources:** batches 1 (copy 11), 2 (copy 2), 3 (copy 4)

### Harbor coordinates, version, private project & break-glass
- **Type:** REFERENCE · **Confidence:** HIGH ([VERIFIED])
- **What:** Harbor `goharbor/harbor-core:v2.15.1` (Helm chart 1.19.1). OCI registry `harbor.webgrip.dev`, LAN-only (HTTPRoute on envoy-internal `10.0.0.27`, split-DNS, valid TLS). In-cluster plain HTTP at `harbor.harbor.svc.cluster.local:80` (nginx front-end serves `/v2/` + `/api/`; forgejo→harbor:80 already open — sidesteps TLS/DNS/`${SECRET_DOMAIN}`). Private project `webgrip` (pushed images invisible to anon/non-member views) — OIDC (`oidc_admin_group: harbor-admins`); local break-glass `admin` (NOT `harbor-admin`, the secret name), password from the `harbor-admin` secret, login at `/account/sign-in`. Robot token in OpenBao `secret/harbor/robot-webgrip`. Storage growth via `harbor_statistics_total_storage_consumption` / `harbor_project_quota_usage_byte` (Garage's own capacity is NOT scraped — external `10.0.0.110:3900`, confirm headroom out-of-band). Verify an RBAC requirement credential-free by reading Harbor source at the deployed tag (`src/server/v2.0/handler/*.go`, `src/common/rbac/const.go`).
- **Sources:** batches 1 (copy 11, copy 16), 3 (copy 4, copy 7), 2 (copy 2)

---

## Provisioning org secrets & OpenBao access

### Provision Forgejo org Actions secrets via OpenBao + a CronJob; reserved prefixes
- **Type:** PROCEDURE + GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Add an ExternalSecret reading e.g. `secret/github/ci-pat`; add env vars + `put_secret` calls to `forgejo-actions-secrets.cronjob.yaml`. The Forgejo Actions secrets API is **write-only** — verify by the cronjob log (`created org secret webgrip/GHCR_TOKEN`), not by reading back; the provisioner PUTs every tick (create-or-update). No ESO push-provider for Forgejo Actions secrets exists. The org API **rejects** secret/variable names beginning with `FORGEJO_`, `GITHUB_`, or `GITEA_` (secret PUT 400; var POST/PUT 400/404) — use a `WEBGRIP_` prefix (token `WEBGRIP_CI_TOKEN`, URL `WEBGRIP_FORGEJO_URL`/`WEBGRIP_CI_BOT_NAME`). `GHCR_*`, `CODEBERG_TOKEN`, `HARBOR_ROBOT_*`, `DT_API_KEY` are fine. (`secrets.FORGEJO_TOKEN` inside a workflow is the built-in per-job token, distinct from the org bot token.) Trigger now: `kubectl -n forgejo create job fas-manual --from=cronjob/forgejo-actions-secrets`.
- **Sources:** batches 3 (copy 4, copy 5), 2 (copy 8)

### Write to OpenBao as admin via OIDC (root token is revoked)
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** OpenBao revokes the initial root token and persists only the unseal key (Secret `openbao-keys`). Admin is OIDC via Authentik: the `admins` policy (path `"*"`) is granted to identity group `openbao-admins` ← Authentik `homelab-admins`. `kubectl exec` into the pod gives a non-admin token → 403 on `sys/internal/ui/mounts`. Correct: OpenBao Web UI OIDC login or CLI `bao login -method=oidc role=default`, then `bao kv put`. Break-glass: `bao operator generate-root` using the unseal key. Mount `secret` (KV v2); ESO policy grants `secret/data/*`. `VAULT_ADDR=http://openbao.security.svc.cluster.local:8200` (in-cluster) or `https://openbao.webgrip.dev` (CLI).
- **Snippet:** `bao login -method=oidc role=default; bao kv put secret/github/ci-pat username='<gh-user>' token='<REDACTED>'`
- **Sources:** batch 3 (copy 4)

---

## Forgejo-leading repo migration (off gitea-mirror)

### Forgejo-leading repo cutover (order is load-bearing; un-mirror is Danger-Zone "Convert")
- **Type:** PROCEDURE + GOTCHA · **Confidence:** HIGH ([VERIFIED] on Forgejo 15.0.2)
- **What:** Per repo, in order (un-mirroring before stopping gitea-mirror lets the next sync re-assert read-only): (1) in gitea-mirror UI disable/remove the repo; (2) Forgejo Settings → `Synchronize now` (final pull) → **Danger Zone → "Convert to a regular repository"** (type repo name; flips `is_mirror=false`) — the Mirror-settings panel has NO un-mirror button (only Synchronize/interval/prune; interval 0 only stops periodic sync, stays read-only); (3) re-point local git remotes. gitea-mirror disable alone does NOT stop Forgejo's own scheduled pull — the convert does. Without this, push returns `403 remote: mirror repository is read-only`. Two shapes: convert-mirror (exists as pull-mirror) vs create-and-push (404 → create empty repo, `git push --all && --tags`, re-point).
- **Snippet:** `git remote rename origin github; git remote set-url github git@github.com:webgrip/<repo>.git; git remote add origin ssh://git@forgejo-ssh.webgrip.dev/webgrip/<repo>.git; git rev-parse origin/main github/main  # MUST match`
- **Sources:** batch 3 (copy 9/10)

### Verify un-mirror via the `.mirror` flag, NOT anon `permissions.push`
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** `GET /api/v1/repos/<o>/<r>` field `permissions.push` reflects the **anonymous caller**, so it reads `false` even for converted writable repos. The reliable signal is the top-level `.mirror` boolean (or `git push` succeeding).
- **Snippet:** `curl -fsS .../repos/webgrip/<r> | python3 -c 'import sys,json;print(json.load(sys.stdin)["mirror"])'`
- **Sources:** batch 3 (copy 9/10)

### GitHub push-mirror PAT needs the `workflow` scope, not just `repo`
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** A Forgejo→GitHub push-mirror pushes all refs. GitHub rejects any ref creating/updating `.github/workflows/` unless the PAT has the `workflow` scope. Tags/releases don't touch workflow files so they sync ("the release appears on GitHub"), but a commit changing a workflow file is rejected → code/branch doesn't land — the literal cause of "release mirrors but code doesn't." Fix: add `workflow` to the existing classic PAT (same value → Forgejo's stored creds gain the scope).
- **Snippet:** `last_error: ! [remote rejected] ... refusing to allow a Personal Access Token to create or update workflow .github/workflows/<file> without 'workflow' scope`
- **Sources:** batch 3 (copy 9/10)

### Converting a pull-mirror leaves Actions AND Pull-Requests units OFF; library repos keep Actions OFF
- **Type:** GOTCHA + DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** gitea-mirror creates the Forgejo repo with `has_actions=false`, and converting leaves `has_pull_requests=false`. PRs-disabled makes Renovate skip the repo ("pull requests are disabled") and blocks normal PRs. Re-enable both via `PATCH /repos/{o}/{r}` `{"has_actions":true}`/`{"has_pull_requests":true}`. EXCEPTION: reusable-workflow library repos (webgrip/workflows) force Actions OFF — their workflows are `on: workflow_call` and run in the caller's runner, so disabling the unit doesn't break `uses:` consumers but prevents stray in-repo runs (encoded as `ACTIONS_OFF_REPOS="workflows"`; commit `feat(forgejo): force Actions unit OFF for reusable-workflow library repos`).
- **Sources:** batch 3 (copy 9/10)

### Don't copy GitHub `status_check_contexts` into Forgejo branch protection
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Copying GitHub's `required_status_checks.contexts` (e.g. `validate (default.json)`) deadlocks every Forgejo merge — those are GitHub job names; Forgejo's checks are named differently and never report them. Keep only structural rules (require PR + approvals, block force-push/deletion); re-add status checks later under actual Forgejo check names.
- **Snippet:** baseline `{"rule_name":"main","enable_push":true}`; strict `{"rule_name":"main","enable_push":false,"required_approvals":1}`
- **Sources:** batch 3 (copy 9/10)

### Forgejo PAT granular scopes — `/user` 403s, org-list needs `read:organization`
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** A Forgejo PAT scoped only `write:repository` (correct for repo ops) 403s on `GET /api/v1/user` (needs `read:user`). Don't validate the token via `/user` — probe a repo endpoint. `GET /orgs/{org}/repos` (for `--all` sweeps) needs `read:organization`. A 403 (not 401) = valid-token-but-missing-scope.
- **Sources:** batch 3 (copy 9/10)

### `gitea-mirror` config/state is in its own SQLite DB — no API, UI-only; `.profile`/`.profile-private`
- **Type:** FACT · **Confidence:** MEDIUM ([ASSERTED])
- **What:** `ghcr.io/raylabshq/gitea-mirror:v3.8.4` (ns `forgejo`, data `/app/data/gitea-mirror.db`, mem 2Gi) stores its repo list + sync settings in a private SQLite DB — no REST API/CLI to disable a repo (web-UI action only, or unsupported direct SQLite edits); a per-repo disable can re-appear on the next discovery pass (exclude instead). Forgejo org profile README = a repo named `.profile` with root `README.md` (NOT `profile/README.md`); members-only = `.profile-private`. There is NO Forgejo equivalent of GitHub's `.github` org-wide defaults repo — shared CI is `uses: webgrip/workflows/.forgejo/workflows/<name>@<ref>`.
- **Sources:** batch 3 (copy 9/10)

### `forgejo-sync.sh` + migration API shapes; migrate webgrip/workflows first
- **Type:** REFERENCE + DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** `scripts/forgejo-sync.sh` brings a Forgejo repo to GitHub parity: `actions` (enable, except `ACTIONS_OFF_REPOS`), `prs`, `mirror` (Forgejo→GitHub push-mirror), `protect`. Dry-run by default; `--apply`; idempotent. Push-mirror `remote_username` must be the **token owner** (from `https://api.github.com/user`), not the org. API base `https://forgejo.webgrip.dev/api/v1`, `Authorization: token $FORGEJO_TOKEN`: push-mirror `POST /repos/{o}/{r}/push_mirrors` (+ `-sync`), protection `GET/POST .../branch_protections`, units `PATCH /repos/{o}/{r}`, status `push_mirrors[].last_error`. Origin SSH `ssh://git@forgejo-ssh.webgrip.dev/webgrip/<repo>.git` (host key trusted); tokens in `~/.config/webgrip/forgejo.env` (`FORGEJO_TOKEN` + `GH_MIRROR_TOKEN`, never echoed). The `webgrip-ci` bot has org-wide write via the `webgrip/ci` team. **Migrate webgrip/workflows first** (the library every repo consumes via `uses:`; 0 tags) so consumers' Forgejo CI resolves it before they migrate.
- **Sources:** batch 3 (copy 9/10)

### `gh api` prints error body to stdout on 404 — fallback must be outside `$(...)`
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** On HTTP error, `gh api` writes error JSON to stdout and exits non-zero. `x=$(gh api ... || echo '{}')` concatenates error JSON with `{}` → a "two JSON docs" parse crash. Put the fallback outside the substitution: `ghp=$(gh api "..." 2>/dev/null) || ghp='{}'`.
- **Sources:** batch 3 (copy 9/10)

---

## Talos node operations & upgrades

### `task talos:upgrade-node` built-in drain STALLS on single-replica-PDB workloads — force-drain first
- **Type:** GOTCHA + PROCEDURE · **Confidence:** HIGH ([VERIFIED]; all 5 nodes reached v1.13.4)
- **What:** `talosctl upgrade`'s internal cordon+drain cannot evict single-replica workloads with PDBs (`allowedDisruptions: 0`): kyverno-background/reports-controller on every node + ~7 single-instance CNPG DBs on worker-1. The drain hits a 5m global timeout, errors, and aborts — leaving the node cordoned, new image staged to the inactive partition, but NEVER rebooted (still old version) even though "upgrade completed" prints. Fix: `kubectl drain <name> --disable-eviction --force --ignore-daemonsets --delete-emptydir-data --timeout=600s` → `task talos:upgrade-node IP=<ip>` → `kubectl uncordon` → verify Server Tag. CNPG DBs (longhorn SC, Immediate, no PV node-lock) reschedule; etcd/kubelet are Talos static pods unaffected by kubectl drain so CP quorum is safe. A stalled upgrade is safe to Ctrl+C (`talosctl get machinestatus`: STAGE=running READY=true = stable, only the cordon to undo; a plain reboot won't switch partitions — re-run the upgrade after a clean force-drain).
- **Snippet:** `error draining node "soyo-1": [error when evicting pods/"kyverno-background-controller-..." ... global timeout reached: 5m0s]`
- **Sources:** batch 4 (Talos upgrade digest)

### Two distinct Talos node operations with different drain behavior; use the recipes
- **Type:** FACT + PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** (1) **Config changes** → `task talos:apply-node-safe IP=<ip> HOSTNAME=<name>` (explicit `kubectl drain --timeout=120s` then apply). (2) **Version upgrades** → `task talos:upgrade-node IP=<ip>` (relies on Talos's OWN internal drain — do NOT pre-drain in the documented flow, do NOT hand-roll the `--image` string; the recipe looks up `talosImageURL`+`talosVersion`). Exception: a label-only no-reboot change uses `task talos:apply-node ... MODE=no-reboot`. Recipes in `.taskfiles/talos/Taskfile.yaml`: apply-node-safe, upgrade-node, upgrade-k8s, generate-config. Read hardware via read-only COSI: `get systeminformation/processors/memorymodules/disks` (`get disks` is mostly Longhorn iSCSI virtual disks — only `transport: sata` is physical; runtime `/dev/sdX` letters unstable; `meminfo` not a valid resource). `talhelper` must recognize the target version or genconfig warns — bump it (v3.1.11 added v1.13.4) as an adjacent pin.
- **Sources:** batch 4 (both Talos digests)

### Version pins live in two files; generated clusterconfig is gitignored
- **Type:** REFERENCE + FACT · **Confidence:** HIGH ([VERIFIED] against repo)
- **What:** `talos/talenv.yaml` holds `talosVersion` + `kubernetesVersion` (Renovate datasource comments); `.mise.toml` holds client tool pins. Current: **Talos v1.13.4** (kernel 6.18.34, etcd v2.6.12, Go 1.26.4), **Kubernetes v1.36.1** (newest stable — 1.37 doesn't exist), kubectl 1.36.1, talosctl 1.13.4, talhelper 3.1.11. `talos/clusterconfig/kubernetes-*.yaml` + `talosconfig` are NOT tracked (only `.gitignore`) — a version-bump commit is just `.mise.toml` + `talos/talenv.yaml`; per-node configs regenerated locally via `task talos:generate-config`, never committed. A node is added by an entry in `talos/talconfig.yaml` `nodes:` (hostname, ipAddress, installDisk, `controlPlane:`, MAC deviceSelector).
- **Sources:** batch 4 (both Talos digests)

### Node inventory & hardware (5 nodes)
- **Type:** REFERENCE + FACT · **Confidence:** HIGH ([VERIFIED]; cross-confirmed across batches)
- **What:** soyo-1 `10.0.0.20`, soyo-2 `.21`, soyo-3 `.22` = control-plane/etcd, `pool=soyo`, `allowScheduling=false` for Longhorn (ADR-0026); Intel N150 4C/4T, 12 GiB (4×3 GiB Samsung LPDDR5 soldered), 512 GB **SATA** SSD (earlier docs wrongly said NVMe); soyo-1 holds the VIP; address soyo-3 by IP (hostname flaky). fringe-workstation `.23` = worker, **only `cpu=high` node**, HP Z230 i7-4770 4C/8T, 16 GiB DDR3, 256 GB SSD + 1 TB HDD, Longhorn-schedulable. worker-1 `.24` (added 2026-06-19) = worker, high-RAM (Gigabyte Z87X-D3H, i5-4670K, 24 GiB DDR3 — most in cluster, 960 GB SSD, `installDisk: /dev/sda`), Longhorn-schedulable, **hosts the CNPG DB fleet**. All on Talos v1.13.4 / k8s v1.36.1. Capability label `node.webgrip.io/pool|cpu`. `secretDomain: webgrip.dev` lives in plaintext `talos/talenv.yaml` (owner confirmed not sensitive). Garage S3 external `10.0.0.110:3900`. Totals: 5 nodes, 24 vCPU / ~76 GiB.
- **Sources:** batches 4 (both Talos digests), 1 (copy 11, copy 16)

---

## etcd / control-plane HA & node placement

### etcd quorum / HA — corrects the "go to 1 control-plane" intuition
- **Type:** FACT + DECISION · **Confidence:** HIGH (quorum math textbook-correct; failover not exercised in-thread)
- **What:** etcd Raft needs majority (quorum = ⌊N/2⌋+1), tolerated failures = N−quorum (3→1, 5→2). Odd counts only. **3 CP nodes is the HA minimum; dropping to 1 is strictly less resilient** and there's no automated etcd backup yet (roadmap #52), so a single-CP disk loss is unrecoverable.
- **Conflict (resolved):** The intuition "3 soyos feel fragile → go to 1" is WRONG — the fragility is **correlated failure** (3 identical RAM-starved shared-disk boxes fail together) + etcd's fsync sensitivity when Longhorn saturates the shared SSD (→ leader-election flapping), not node count. Fix = isolate etcd, keep heavy workloads off CP nodes (now done — soyos app/Longhorn-free), add etcd backups; NOT fewer nodes. (Corroborated by memory `tenant-db-on-etcd-node-leader-change.md`.) "All storage on one node" trades correlated-failure for a SPOF; worker-1 is the second independent worker enabling cross-node Longhorn replicas.
- **Sources:** batch 4 (Talos hardware digest)

### Capability labels are the placement contract — and Cilium L2 CRDs consume node labels too
- **Type:** GOTCHA + DECISION · **Confidence:** HIGH ([VERIFIED] against repo)
- **What:** Placement uses capability labels (`node.webgrip.io/cpu`, `node.webgrip.io/pool`), never hostnames or legacy `nodegroup`/`workload-tier`. `kubernetes/apps/kube-system/cilium/app/networks.yaml` holds a `CiliumL2AnnouncementPolicy` whose `nodeSelector.matchLabels` was on `nodegroup: fringe` — a REAL dependency (dropping the label breaks LB-IP announcement); swapped to `pool: worker` before retiring legacy labels. So before retiring any node label, `grep -rn "nodegroup\|workload-tier" kubernetes/apps/` for ALL consumers including Cilium CRDs. gitops-critical apps (forgejo/openbao/gitea-mirror) are pinned to `pool=worker` like any app; DR is external-Garage-S3 backups + a GitHub fallback Flux GitRepository, NOT a soyo Longhorn replica (the `longhorn-gitops` SC was retired). Post-migration: 0 Longhorn replicas / 0 app pods on soyos (42 replicas each on fringe + worker-1); CP RAM 80–83% → 65–73% (residual = CP + BestEffort-DaemonSet overhead, structural to 12 GiB nodes).
- **Sources:** batch 4 (node-taxonomy migration digest)

### Pin a single-node RWO-shared app via a node-unique capability label (RWX is blocked)
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** When several pods share one RWO volume (can't spread) and RWX is blocked, pin to a single node using a capability label that resolves to exactly one node — never a hostname. authentik (2 server + 1 worker share `/data` media) → `node.webgrip.io/cpu: high` (fringe is the only high-CPU node), set as both nodeSelector and hard nodeAffinity. Node-level HA later requires moving the shared data off RWO first (media → S3).
- **Sources:** batch 4 (node-taxonomy migration digest)

---

## Workload placement & RWO/HelmRelease tactics

### Kyverno blocks all RWX PVCs cluster-wide
- **Type:** GOTCHA + FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** Any ReadWriteMany PVC is denied at admission by `storage-cnpg-governance/disallow-rwx-pvcs` (also `require-approved-pvc-storageclass`); there are zero RWX PVCs in the repo. A `longhorn-rwx` StorageClass exists (NFS share-manager) but is blocked cluster-wide. Denial is at dry-run/admission, so a Flux Kustomization referencing an RWX PVC goes `ReconciliationFailed` without disrupting the running app. Rules out RWX as the "share a volume across nodes for HA" solution and as a shared CI cache (NFS SPOF on RAM-tight nodes); shapes any "shared cache" design toward bake/hostPath/object-storage, RWX only behind a PolicyException.
- **Snippet:** `admission webhook "validate.kyverno.svc-fail" denied... disallow-rwx-pvcs: ReadWriteMany PVCs are not allowed...`
- **Sources:** batches 4 (node-taxonomy migration digest), 2 (copy 8), 1 (copy 13)

### Break a goharbor RWO RollingUpdate Multi-Attach deadlock by deleting the old ReplicaSet
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** The goharbor chart hardcodes RollingUpdate (renders both strategy blocks, so Recreate-via-values is impossible). Pinning a single-replica RWO Deployment to move nodes deadlocks: old pod holds the volume, new pinned pod sits ContainerCreating (Multi-Attach). Deleting just the old *pod* isn't enough (the RS recreates it). Fix: delete the old ReplicaSet — the Deployment won't recreate a superseded revision, the volume frees, HR goes UpgradeSucceeded. Must beat the HR timeout (20m for harbor).
- **Sources:** batch 4 (node-taxonomy migration digest)

### Convert a chart that hardcodes RollingUpdate to StatefulSet (dependency-track api-server); VCT storageClass is immutable
- **Type:** FACT + PROCEDURE · **Confidence:** HIGH (conversion [VERIFIED] against repo; immutability [ASSERTED] from K8s semantics)
- **What:** DT's api-server was converted to `apiServer.deploymentType: StatefulSet` (native nodeSelector, no postRenderer) — an ordered STS recreate frees the RWO volume, sidestepping the Multi-Attach deadlock. (Older skill docs claiming "DT uses `strategy: Recreate` via its postRenderer" were stale and corrected.) Note a StatefulSet's `volumeClaimTemplates.storageClassName` is immutable — repointing a chart-rendered STS PVC to a different SC is API-rejected and breaks the HR until STS+PVC are deleted/recreated (acceptable for DT only because `/data` is a rebuildable NVD/OSV cache; the encryption key lives in `dependency-track-secret`, not `/data`). CNPG `storageClass` changes are similarly disruptive — present the trade-off; don't unilaterally swap.
- **Sources:** batches 4 (node-taxonomy migration digest), 2 (copy 8)

### helm-controller cache-sync rollback is driven by a loaded control-plane API
- **Type:** GOTCHA · **Confidence:** LOW ([ASSERTED] — hypothesis, causation not proven)
- **What:** RWO-move/postRenderer HR upgrades had failed with `failed to wait for object to sync in-cache after patching: context deadline exceeded` → `remediateLastFailure` rolling the release back in a loop. After the soyo control-planes were emptied of apps (idle API), the same harbor move succeeded with no rollback. Hypothesis: the cache-sync timeout was caused by the slow/loaded soyo apiserver — operations previously "impossible via GitOps" may become safe once the control-plane is unloaded. **Needs verification** as a repeatable cause.
- **Snippet:** `kubectl get hr <app> -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}'` → want `UpgradeSucceeded`
- **Sources:** batch 4 (node-taxonomy migration digest)

---

## Longhorn storage

### All Longhorn StorageClasses are now `Immediate`; `longhorn-gitops` SC was deleted
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED] against repo)
- **What:** Every Longhorn SC is `volumeBindingMode: Immediate` now. WFFC was eliminated because with `dataLocality: disabled` volumes are network-attached, so WFFC's PV-node-locking is pure downside (it permanently excluded the later-added worker-1). The `longhorn-gitops` SC (soyo-replica DR design) was retired 2026-06-21; soyos stay 100% Longhorn-free. Legacy WFFC-era PVs keep their baked nodeAffinity until recreated. The storageclass Flux ks uses `force: true` so the immutable binding-mode change recreates the SC.
- **Snippet:** `kubectl get pv <pv> -o jsonpath='{.spec.nodeAffinity}'` (empty = free)
- **Sources:** batch 4 (node-taxonomy migration digest)

### The default longhorn SC still provisions 3 replicas on a 2-storage-node cluster (deliberate deferral)
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** The chart-created default `longhorn` SC carries `numberOfReplicas: 3` (immutable SC param, from `persistence.defaultClassReplicaCount`), but only 2 Longhorn-schedulable nodes exist with hard replica anti-affinity → a 3-replica volume can never be healthy (recurring "volume degraded", e.g. dependency-track-api-server). Existing volumes were reduced to 2 at runtime (not durable; any reprovision returns to 3). The chart's `defaultSettings.defaultReplicaCount: "2"` does NOT override an explicit SC param. Maintainers deliberately left it at 3 ("to avoid breaking the HR upgrade"); convergence to 2 is deferred (ADR-0029 Stage 2 / ADR-0027). Treat as a deliberate decision.
- **Sources:** batch 2 (copy 8)

### Longhorn 1.11 ignores `defaultSettings.backupTarget` — use a `BackupTarget` CR
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED]; target available=true)
- **What:** Setting `backupTarget`/`backupTargetCredentialSecret` in HelmRelease `defaultSettings` is silently ignored in Longhorn 1.11 (deprecated). The working mechanism is a `BackupTarget` CR named `default`. Creds from the `longhorn-backup-s3` ExternalSecret (OpenBao `s3/cnpg-backup` → AWS_*). A `gitops-backup` RecurringJob (cron `0 2 * * *`) backs up volumes labeled `recurring-job-group.longhorn.io/gitops-backup=enabled` (forgejo-data, gitea-mirror).
- **Snippet:** `kubectl get backuptarget default -n longhorn-system -o jsonpath='available={.status.available}'`
- **Sources:** batch 4 (node-taxonomy migration digest)

### Post-reboot Longhorn churn self-heals serially; detect rebuilds via JSON `rebuildStatus`, not table grep
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Rolling-rebooting all nodes left ~25 volumes degraded; they self-healed to ~0 over ~1–2h (expected — don't reboot another node until converged, each degraded volume is momentarily single-replica). Each volume wants 2 replicas (one per worker); after a worker reboot its replica shows `currentState=stopped, healthyAt=NEVER` and rebuilds from the other worker, throttled by `concurrent-replica-rebuild-per-node-limit=1` (serial by design) + `replica-auto-balance=disabled`. `kubectl get replicas.longhorn.io ... | grep -ci rebuild` always returns 0 — rebuild state isn't a table column, it's `.status.rebuildStatus` (JSON only); the "0 healthy replica" safety check must be computed from replica `healthyAt`/`failedAt`. `node-down-pod-deletion-policy=delete-both-statefulset-and-deployment-pod`.
- **Snippet:** `kubectl get replicas.longhorn.io -n longhorn-system -o json | jq -r '[.items[]|select(.status.rebuildStatus.state=="in_progress")]|length'`
- **Sources:** batch 4 (Talos upgrade digest)

---

## Flux / HelmRelease drift

### spegel is the only HR that perpetually shows DriftDetected — root cause + fix (not yet applied)
- **Type:** FACT · **Confidence:** HIGH (cause [VERIFIED]; fix still unapplied — repo confirms no per-HR ignore block in spegel yet)
- **What:** A global Flux patch sets `driftDetection.mode: warn` on EVERY HelmRelease (`kubernetes/flux/cluster/ks.yaml:~42`) — detect+log only, never remediate (avoids fighting Kyverno mutate webhooks). spegel is the only HR that drifts: its chart renders a DaemonSet omitting fields the API server then defaults — `spec.revisionHistoryLimit: 10`, `spec.updateStrategy.rollingUpdate.maxSurge: 0`, plus a third server-default — logged every reconcile, never converges. Benign noise on the FluxResourceDriftDetected alert.
- **Snippet (proposed per-HR fix):** `driftDetection: { mode: warn, ignore: [{ target: {kind: DaemonSet}, paths: [/spec/revisionHistoryLimit, /spec/updateStrategy] }] }`
- **Sources:** batch 4 (Talos upgrade digest)

---

## Grafana / observability / alerting

### Grafana threshold alert rules silently error without a top-level `expression:` — broke all 16 SLO rules for ~3 weeks
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] via throwaway MCP rule)
- **What:** A `GrafanaAlertRuleGroup` SSE chain (Prometheus query node + a `type: threshold` node) errors every evaluation (`[sse.parseError] failed to parse expression [threshold]: no variable specified to reference for refId threshold`) unless the threshold node's model includes `expression: <input-refId>` (the bare refId string, e.g. `query` — NOT `$query`, NOT `A`). The legacy `conditions[].query.params:[query]` is not sufficient. `kubeconform` and `flux-local build` do NOT catch it (the operator CRD is preserve-unknown-fields). Two rules with `execErrState: Alerting` produced false critical pages; the other 14 errored silently. Now guarded by `scripts/validate_grafana_alert_expr.py` (stdlib text linter) wired into `e2e.yaml` + `run-flux-local-test.sh` + ADR-0030.
- **Snippet:** `model: { refId: threshold, type: threshold, expression: query, datasource: {uid: "-100", type: __expr__} }`
- **Sources:** batch 2 (copy 8)

### Pre-flight a Grafana alert-rule shape with a throwaway MCP rule before mass-editing
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** Before editing many rules, `alerting_manage_rules` (op `create`) one throwaway rule, confirm `health != error`, delete it — validates exact SSE syntax against the live Grafana version without touching GitOps rules. After committing, verify via list `states:["error"]` (expect empty). Render-time validation (kubeconform/flux-local) cannot catch SSE model errors; live rule-health re-query is the only acceptance test.
- **Sources:** batch 2 (copy 8)

### PromQL anti-patterns: `count()` over a boolean gauge counts nodes; empty filtered set returns NoData not 0
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] — fixed across ~13 rules; flux-local passed)
- **What:** (1) `kube_node_status_condition{condition="MemoryPressure",status="true"}` emits one 0/1 series per node, so `count(...)` returns ~5 (node count) regardless of actual pressure → permanent false critical; use `sum(...)` (sums the 0/1 values). Same for any `kube_*_status_condition`/boolean gauge. (2) `count(up == 0)`, `count(flux_resource_info{ready="False"})`, etc. return an empty vector when healthy → the rule sits `health: nodata` (indistinguishable from a broken pipeline) instead of 0/Normal; append `or vector(0)` — EXCEPT rules whose `noDataState: Alerting` is intentional (a "metrics-stale" detector / "watch-the-watchers" meta-rule, where NoData must page).
- **Snippet:** `sum(kube_node_status_condition{condition="MemoryPressure",status="true"})`; `count(up == 0) or vector(0)`
- **Sources:** batch 2 (copy 8)

### Operator-managed Grafana ServiceMonitor needs the `release` label AND the operator's actual selector labels
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** For kube-prometheus-stack to scrape the grafana-operator-managed Grafana, the ServiceMonitor must (1) carry `metadata.labels.release: kube-prometheus-stack`, and (2) `spec.selector.matchLabels` must match the operator's actual Service labels: `app.kubernetes.io/managed-by: grafana-operator` + `grafana.internal/instance: grafana` (NOT `app.kubernetes.io/name: grafana`). Missing either → `grafana_alerting_*` never scraped → a "watch-the-watchers" rule sits NoData forever (the blind spot that hid the 3-week outage).
- **Sources:** batch 2 (copy 8)

### The cluster runs TWO independent alert engines with no unified view
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** (1) Grafana-managed SLO rules (`GrafanaAlertRuleGroup` CRDs under `grafana/app/alerting/{slo-platform,slo-security,slo-observability}.yaml`) — `grafana.${SECRET_DOMAIN}/alerting/list`. (2) Prometheus-native (kube-prometheus-stack + Sloth `PrometheusServiceLevel` + custom `PrometheusRule`) — `alertmanager.${SECRET_DOMAIN}` / `prometheus.${SECRET_DOMAIN}/alerts`. Some conditions were alerted by BOTH (DT critical/policy/risk rules); resolved by keeping the Grafana SLO rules and dropping the `PrometheusRule` dupes. No dashboard unifies both engines.
- **Snippet:** `ALERTS{alertstate="firing"}` (Prom) vs `alerting_manage_rules list states:["firing"]` (Grafana)
- **Sources:** batch 2 (copy 8)

### Trivy/Dependency-Track "supply-chain" numbers are whole-fleet third-party scans, NOT your images
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] — live `dt_portfolio_projects{state="total"}=159`)
- **What:** A `trivy-sbom-uploader` CronJob (Sundays 02:00) Trivy-scans all running cluster images and uploads CycloneDX SBOMs to DT, auto-populating 159 projects = every upstream third-party image (postgres, cilium, longhorn, grafana, alpine…); `trivy-operator` scans all running pod images registry-agnostically (no Harbor, no first-party SBOM). So "63 critical CVEs / 2332 policy fails / risk 5961" are about upstream images (fixed by version bumps/Renovate), NOT the user's build artifacts (only `ghcr.io/webgrip/github-runner` is genuinely first-party). Relatedly, `TrivyExposedSecretsDetected` matches `severity=~"Critical|High|Medium"` but carries `labels.severity: critical` — a Medium/High base-image finding pages as critical (the 2 firing were High in stock postgres/backup images, near-certain false positives). Verify the `ExposedSecretReport` CR before treating as a real leak.
- **Sources:** batch 2 (copy 8)

### Sloth burn-rate / synthetic alerts linger after recovery; disable alerts/SLOs in lock-step with their workload
- **Type:** FACT + DECISION · **Confidence:** HIGH ([VERIFIED])
- **What:** Multi-window burn-rate SLO alerts (Sloth `PrometheusServiceLevel`, fed by blackbox `probe_success`) keep firing after the endpoint recovers because the burned error budget is still in the long window — check `probe_success` current value before treating as a live outage. k6-operator/k6-canaries were suspended but `K6CanaryMetricsMissing` + `slo-synthetic-k6-canary` were left active and fired forever — comment them out too (with a note pointing back to the k6 suspension so re-enabling re-enables both); kept `slo-synthetic-availability` (independent of k6).
- **Sources:** batch 2 (copy 8)

### Bootstrap Jobs/CronJobs need explicit worker pinning; etcd fragmentation is double-alerted
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** `AppsTierWorkloadSpilledToControlPlane` excludes `.*-(runner|metrics-exporter|sbom-uploader|policy-bootstrap)-.*` but NOT provisioner/CronJob bootstrap pods — stateless forgejo bootstrap Jobs had no nodeSelector and scheduled onto a soyo (fired on `forgejo-ci-provisioner-*` + `forgejo-actions-secrets-*`). Fix = add `nodeSelector: { node.webgrip.io/pool: worker }` to their pod specs (ADR-0028; the `components/placement/worker-pool` component patches Deployments/StatefulSets/CNPG, NOT bare Jobs). Separately, etcd boltdb fragmentation is double-alerted (`EtcdDbHighFragmentationRatio` custom + stock `etcdDatabaseHighFragmentationRatio`) ×3 members — remediation is owner-run `talosctl etcd defrag` (one member at a time, leader last; gating prerequisite for re-enabling pyroscope).
- **Sources:** batch 2 (copy 8)

### Live alert/SLO read surfaces, dashboard UIDs, validators
- **Type:** REFERENCE · **Confidence:** HIGH ([VERIFIED])
- **What:** Aggregate views: `grafana.${SECRET_DOMAIN}/alerting/list`, `alertmanager.${SECRET_DOMAIN}`, `prometheus.${SECRET_DOMAIN}/alerts`. Dashboards (`/d/<uid>`): security-overview, security-trivy-sbom, dt-supply-chain-001, kyverno-violations, kyverno-policy-insights, platform-etcd, obs-stack-overview, talos-node-health. New validators: `scripts/validate_grafana_alert_expr.py`, `scripts/check-kyverno-test-coverage.sh`, both wired into `e2e.yaml` (mirror the dependency-free `scripts/validate_alert_annotations.py` pattern).
- **Sources:** batch 2 (copy 8)

---

## Observability — Forgejo/CI metrics & logs; MCP

### Forgejo exports NO Actions/CI metrics; runner logs are NOT in Loki
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED] — queried live)
- **What:** `/metrics` exposes only `gitea_*` count gauges (accesses, attachments, issues, repositories, releases, users, webhooks…) — no run-duration/job-timing/task-status. A CI build-duration/cache-hit dashboard is NOT possible from native metrics — it needs a custom Forgejo-Actions-API exporter. Loki here uses OTel-style labels (`service_name, service_namespace, deployment_environment, …`), not `namespace/pod/container`, so runner job logs don't appear in Loki — "where does the job time go" must come from Prometheus container metrics or the Forgejo UI, not LogQL.
- **Sources:** batches 1 (copy 13, copy 16)

### Query per-job resource peaks without a Prometheus series explosion; MCP UIDs
- **Type:** PROCEDURE + REFERENCE · **Confidence:** HIGH ([VERIFIED])
- **What:** Ephemeral pods create one series per pod, so a 7-day un-aggregated subquery over `forgejo-runner.*` overflows the MCP result — collapse with an outer aggregator (`quantile`/`max` over a `max_over_time(rate(...)[7d:3m])` subquery); a 3-min rate window smooths sub-minute bursts. Grafana MCP datasource UIDs are literally `prometheus` (default) + `loki`; `query_prometheus` requires `datasourceUid`. The in-cluster kubernetes MCP runs as `system:serviceaccount:observability:k8s-mcp-kubernetes-mcp-server` (view-scoped — listing nodes is forbidden; get node data via Prometheus `kube_node_status_allocatable`). When the grafana + kubernetes MCP servers (in-cluster, LAN-only) time out together (a brief LAN/ingress blip — ≠ cluster down), confirm via `kubectl get --raw '/readyz'` and read Prometheus alerts directly (`kubectl exec ... prometheus -- wget -qO- 'http://localhost:9090/api/v1/alerts'`; Grafana-managed SLO rule states are NOT in Prometheus and unavailable this way).
- **Snippet:** `quantile(0.95, max_over_time(rate(container_cpu_usage_seconds_total{namespace="forgejo",pod=~"forgejo-runner.*",container="runner"}[3m])[7d:3m]))`
- **Sources:** batches 1 (copy 16), 2 (copy 8)

---

## Kyverno / policy

### Enforce mechanics + the test-harness allowlist that hid untested enforced policies
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Policies set spec-level `validationFailureAction: Audit|Enforce`; rules can override with `failureAction: Audit` inside an Enforce policy (effective = rule's if set, else spec-level). No per-rule "action" knob beyond `failureAction`. Promotion levers: whole-policy flip, `validationFailureActionOverrides` (per-namespace), or split (clean rules → `-enforce.yaml`). Autogen duality: every Pod policy emits `<rule>` (Pod/background) AND `autogen-<rule>` (controller/admission) findings — a `PolicyException` must waive both. The CLI test harness (`scripts/lib/kyverno-tests.sh` `prepare_kyverno_test_workspace()`) hardcoded a policy allowlist that silently omitted 6 enforced-capable policies (`workload-hardening-audit`, `workload-advanced-hardening-audit`, `secrets-observability-ops-audit`, `image-hygiene-audit`, `image-verify-harbor-audit`, `storage-cnpg-governance`) — so those could be promoted to Enforce with zero CLI coverage and CI stayed green; replaced with discovery by kind over `policies/app/*.yaml`. New guard `scripts/check-kyverno-test-coverage.sh` fails if an enforcing ClusterPolicy lacks a `result: fail` CLI test.
- **Snippet:** `grep -rlZ -E '^kind: (ClusterPolicy|Policy|PolicyException|ClusterCleanupPolicy)$' "${policy_dir}"/*.yaml`
- **Sources:** batch 2 (copy 8)

---

## Safety hooks & agent constraints

### Safety hooks block kubectl/Longhorn/talosctl mutations (string-match — even `--help`/comments)
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] across batches)
- **What:** `.claude/hooks/guard-destructive.sh` blocks any `kubectl patch/delete/edit/apply/scale/uncordon` and Longhorn volume/replica/node mutations and destructive talosctl ops — regardless of in-chat user approval (even a one-off maintenance Job). The match is **string-based**: `talosctl upgrade --help` and even a read-only diagnostic merely *containing* "upgrade" in an echo comment got blocked. Read-only `kubectl get/describe/logs`, `exec wget`, `get --raw /readyz`, `talosctl get/read/version/etcd members` are fine. The agent must make changes in Git (GitOps) or hand the exact command to the human, and strip trigger words from benign diagnostics. (The auto-mode classifier also blocks extracting cluster secrets — plan live-verification via in-cluster jobs with their own mounted secrets + read-only reads + source inspection.)
- **Sources:** batches 4 (Talos upgrade digest), 2 (copy 8, copy 2), 1 (copy 11)

### Apply + live-verify a Flux change immediately; verify by real status, not a proxy artifact
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** After committing+pushing to `main`, Flux reconciles within ~minutes — confirm via the Kustomization status (`Applied revision: ...@sha1:<your-sha>`); to exercise a CronJob's script now, spawn a one-off job from it, read its logs, clean up. The `hc()` curl wrapper uses `curl -fsS` (non-zero on HTTP ≥400), so a logged success branch with no WARN is direct evidence of a 2xx. Verify by REAL status, not a proxy artifact: a published tag/Release object is NOT proof of a green CI run (publish creates them before a later-failing step), and "I updated the IaC" ≠ "the running resource changed."
- **Snippet:** `kubectl -n harbor create job --from=cronjob/harbor-proxy-config harbor-proxy-config-verify; kubectl -n harbor logs job/... | grep -iE 'robot|sbom|converged|WARN'; kubectl -n harbor delete job ...`
- **Sources:** batches 2 (copy 2, copy 14), 1 (copy 11)

---

## Git worktrees for parallel work

### Fresh git worktrees lack this repo's gitignored bootstrap files; `.worktreeinclude` copies them (Claude-created only)
- **Type:** GOTCHA + PROCEDURE · **Confidence:** HIGH (gap [VERIFIED]; `.worktreeinclude` [ASSERTED] — not yet exercised)
- **What:** A new worktree is a clean checkout of tracked files only, so it silently lacks the gitignored toolchain files and breaks SOPS/kubectl/talosctl/mise/validation the moment it touches secrets or the cluster: `age.key`, `kubeconfig`, `.mise.local.toml`, `.claude/settings.local.json`, `talos/talosconfig`, `talos/clusterconfig/` (per-node `kubernetes-*.yaml` + `talosconfig`). A root-level `.worktreeinclude` (`.gitignore` syntax) makes Claude Code COPY matching gitignored files into worktrees IT creates (`claude --worktree`, `EnterWorktree`, `isolation: worktree` subagents, desktop parallel sessions) — the native fix, safe to commit (filenames only). It copies (not symlinks), so rotated files (kubeconfig/tokens) can drift in long-lived worktrees; static key material (age key) is fine. It does NOT fire for hand-run `git worktree add`, third-party TUIs (Claude Squad), or the VSCode-extension "Open in New Tab" — those need a post-checkout git hook or a copy-env/copy-configs/git-worktreeinclude tool. The age key resolves per-worktree via `.mise.toml: SOPS_AGE_KEY_FILE = "{{config_root}}/age.key"`, which is exactly why a copied `age.key` at each worktree root works.
- **Snippet:** `git config --global core.hooksPath ~/.git-hooks` (universal post-checkout fallback)
- **Sources:** batch 5 (worktrees digest)

### Claude Code `--worktree` defaults; true parallel+isolated in VSCode = integrated-terminal `claude --worktree`
- **Type:** REFERENCE + PROCEDURE · **Confidence:** HIGH ([VERIFIED] from docs)
- **What:** `claude --worktree <name>` creates a worktree at `.claude/worktrees/<name>/` on branch `worktree-<name>` (auto-generated name if omitted), branching from `origin/HEAD` (matches remote `main` in a trunk-based repo — set `worktree.baseRef: "head"` to carry unpushed commits). `claude --worktree "#1234"` branches from a PR. Add `.claude/worktrees/` to `.gitignore`; `--worktree` ones are never auto-swept. The VSCode extension's "Open in New Tab/Window" gives parallel chats but SHARES one working directory (no isolation — the exact collision worktrees prevent). Real in-window parallel+isolated work = integrated terminal split panes each running `claude --worktree <name>`; or `EnterWorktree` relocates one session mid-conversation (no parallelism).
- **Sources:** batch 5 (worktrees digest)

### Worktrees solve working-dir collisions but NOT push-to-main collisions
- **Type:** DECISION · **Confidence:** HIGH ([ASSERTED]; reinforces existing `concurrent-agents-main-collisions` memory documenting real reverts)
- **What:** This repo is trunk-based on `main` (no feature branches/PRs by policy) with a history of parallel streams reverting each other's pushed work. Worktrees isolate the working directory but do not serialize merges — parallel worktree work must still `git fetch && git rebase origin/main` before each push.
- **Sources:** batch 5 (worktrees digest); corroborates memory `concurrent-agents-main-collisions.md`

### Parallel-AI-agent worktree tooling landscape (mid-2026)
- **Type:** REFERENCE · **Confidence:** LOW ([ASSERTED] — web research, not hands-on)
- **What:** Git worktrees became the de-facto isolation primitive for parallel AI agents ~Q1 2026. Native: Claude Code built-in (~v2.1.49); Cursor 2.0; Zed Parallel Agents; JetBrains 2026.1; VS Code. TUI: Claude Squad (tmux+worktrees), workmux, parallel-code, Conduit, agent-deck. GUI/kanban: Vibe Kanban, Crystal, Conductor (predicts cross-worktree merge conflicts). For non-Claude worktree creation: a global post-checkout git hook, copy-env, copy-configs, git-worktreeinclude (reuses `.worktreeinclude`), or per-worktree `.git/worktrees/<name>/info/exclude`.
- **Sources:** batch 5 (worktrees digest)

---

## Forge choice (Forgejo vs GitLab)

### Forgejo chosen over GitLab for the homelab forge — rationale + counter-case
- **Type:** DECISION · **Confidence:** MEDIUM ([ASSERTED]; footprint/OOM rationale corroborated by soyo-OOM memories; conceptual Q&A — no tooling run)
- **What:** Forgejo preferred over GitLab on four grounds: (1) **footprint** — single Go binary (~100–300 MB RAM) vs GitLab's multi-service stack (Puma/Gitaly/Sidekiq/Workhorse + bundled Postgres/Redis), 4 GB floor / ~8 GB realistic, untenable on RAM-tight OOM-prone soyo nodes; (2) **FOSS ethos** — nonprofit, fully copyleft GPL, no open-core (vs GitLab's open-core), consistent with prior OSS pivots (off Infisical, off SOPS); (3) **GitHub interop** — Forgejo Actions is GitHub-Actions-compatible, enabling workflow reuse where GitLab CI would force a rewrite; (4) **best-of-breed already assembled** — Harbor/Renovate/Grafana already run, so GitLab's bundling is redundant. **Counter-case (GitLab wins):** you need the integrated DevOps suite AND matching hardware — complex multi-stage CI (DAG/child pipelines, environments, approval gates), built-in SAST/DAST/dependency/container scanning, compliance/audit, or a larger team wanting one vendor-supported platform. The conceded trade-off is Forgejo's weaker CI maturity, acceptable because cluster CI is GitOps-light (semantic-release cuts releases; Flux deploys).
- **Sources:** batch 5 (Forgejo vs GitLab digest)

---

## Repo conventions, tooling & cross-cutting

### Concurrent agents on unprotected `main` — fetch, verify survival, stage explicit paths
- **Type:** GOTCHA + PROCEDURE · **Confidence:** HIGH ([VERIFIED] across many threads; matches `concurrent-agents-main-collisions.md`)
- **What:** Another actor (or a parallel agent in the same working tree) commits to `main` mid-session — files you never touched appear staged (e.g. `scaledjob.yaml`, RFC/ADRs, `mkdocs.yml`; an ADR was renamed live; commit `04c6151` appeared during a session; HEAD advanced via others' commits). A reflexive `git add -A` sweeps them in. Defenses: stage only your own files by explicit pathspec (never `git add -A`); leave pre-existing uncommitted files (`.mise.toml`, `talos/talenv.yaml`) untouched; before pushing `git fetch origin main` + verify `git rev-list --count HEAD..origin/main == 0` (clean fast-forward). Recovery: `git reset -q HEAD .` then stage own paths; if a prior `add -A` may have run before a commit, `git reset --soft HEAD~N && git reset -q` then stage per-commit.
- **Snippet:** `git fetch -q origin main && [ "$(git rev-list --count HEAD..origin/main)" = "0" ] && git push -q origin main && echo PUSHED || echo DIVERGED`
- **Sources:** batches 1 (copy 13, copy 16), 2 (copy 8), 3 (copy 9/10, copy 5), 4 (all)

### Repo validate/commit conventions
- **Type:** REFERENCE · **Confidence:** HIGH ([VERIFIED] across threads)
- **What:** Validate manifests with `./scripts/run-flux-local-test.sh` (builds ~72 kustomizations; ~3–4 min; docs-only changes skip it). Commit via mise so lefthook's zizmor resolves: `mise exec -- git -c commit.gpgsign=false commit` (pinentry hangs non-interactively); a lefthook pre-commit (`format-yaml`/yamlfmt `stage_fixed=true`, format-mise/format-just, `zizmor --offline` on `.github/workflows/`) may reformat + stage into the same commit (`git add -A` + recommit). `zizmor` is NOT pre-installed — `python3 -m pip install zizmor` into the repo `.venv`. Trunk-based directly on `main` (unprotected); no feature branches/PRs (PR/review path explicitly declined for these homelab repos). Co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Renovate: `npx --yes --package renovate@latest renovate-config-validator .renovaterc.json5`; isolated lookup `npx renovate@latest --platform=local --dry-run=lookup`.
- **Sources:** batches 1 (copy 16, copy 11, copy 13), 2 (copy 8, copy 2, copy 14), 4 (all)

### Per-app Flux Kustomizations live in the APP namespace; `${SECRET_DOMAIN}` won't expand without substituteFrom
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Each per-app Kustomization is created in the app's own namespace (`flux suspend ks harbor -n flux-system` → "not found"; correct is `-n harbor`). And a ks with no `postBuild.substituteFrom` (e.g. `forgejo-runner/ks.yaml`) won't expand `${SECRET_DOMAIN}` in its `app/` manifests — it renders blank, a silent breakage flux-local won't flag; either add `substituteFrom: cluster-secrets` or use cluster-internal service names.
- **Sources:** batch 1 (copy 11, copy 16)

### Bash/git tool gotchas (cwd reset, zsh globs, `commit -- pathspec` ordering)
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Each Bash call resets cwd to project root — use `git -C <path>` per command. The shell is zsh: unquoted globs with no match hard-error (`ls ops/docker/*/` → "no matches found") — quote glob args or use `find`. To commit only specific files, put `-m` BEFORE the `--` pathspec: `git commit -m "msg" -- path1 path2` (`-m` after `--` makes git treat it as a pathspec). Validate YAML without pyyaml/ruby via `npx --yes js-yaml@4 <file>`; for `.releaserc.js` use `node --check` + exercise the env-gated branch (`BUILD_CACHE_REF=… node -e "…require('./.releaserc.js')…"`).
- **Sources:** batches 1 (copy 6, copy 13), 2 (copy 14)

### Documentation conventions: ADRs + RFCs in this repo
- **Type:** REFERENCE · **Confidence:** MEDIUM (mechanics [VERIFIED] in-thread; exact next-ADR-number claims vary by batch — verify against the live index)
- **What:** ADRs at `docs/techdocs/docs/adr/adr-NNNN-<kebab>.md` (zero-padded, monotonic, never reused; a reversal gets a superseding ADR). RFCs at `docs/techdocs/docs/rfc/rfc-<topic>.md` (no number). No front-matter; open with `# H1` then a `> Status: **Accepted** · Date: YYYY-MM-DD · Part of [RFC: …]` banner. ADR sections: Context / Decision / Consequences / Alternatives. Must ALSO register in the ADR/RFC tables in `adr/index.md` AND the explicit `nav:` in `mkdocs.yml` (a rename touches both); RFC wiring is a 3-edit convention (nav block + `redirect_maps` + `adr/index.md` "### RFCs" table). Decisions get an ADR number only when ratified — list pending ones as unnumbered "candidate ADRs". (The `adr/index.md` Conventions text still says files live under `docs/techdocs/docs/architecture/` — stale; actual files live in `adr/` + `rfc/` with redirects.) markdownlint: MD031 blank lines around fences (incl. in `>` blockquotes), MD049 wants `_emphasis_` (existing RFCs use `*` — don't "fix" repo-wide style), MD060 long-row table warnings cosmetic. The github-script build-summary step uses `String(content).replace(/```/g, '\u200b``')` — keep the `\u200b` **escape**, not a literal zero-width space.
- **Sources:** batches 1 (copy 13), 2 (copy 8), 4 (both Talos digests)

### TechDocs / mkdocs build: in-cluster only; plugins must be pinned in the image before enabling
- **Type:** GOTCHA + PROCEDURE · **Confidence:** MEDIUM ([VERIFIED] mechanics; some [ASSERTED])
- **What:** `mise exec -- mkdocs build` fails (no local mkdocs) — TechDocs is built by Backstage in-cluster, so `mkdocs build --strict` is unavailable locally; fall back to a relative-link existence check. The TechDocs image installs `mkdocs-techdocs-core==1.5.3` (+mermaid2, macros, dracula) but NOT `mkdocs-redirects`/`awesome-pages` — declaring `plugins: [- redirects]` while the deployed image lacks the package fails `unknown plugin "redirects"`; correct order = add the pin to the image Dockerfile (`mkdocs-redirects==1.2.2` in `infrastructure/ops/docker/techdocs-builder/Dockerfile`), rebuild+publish, THEN enable. Mermaid (via `pymdownx.superfences`): flat node-chains render; subgraph-chaining + commas-in-unquoted-labels + `&` break it (use `<br/>`, `·` separators, simple labels). When moving docs into a new taxonomy, rewrite links **file-relative** (mkdocs convention even with `use_directory_urls: true`); neutralize genuinely-missing targets (`[text](dead)` → `text`) rather than invent. Docs taxonomy: `adr/ rfc/ blogs/ incidents/ runbooks/ general/`; nest a repo's coherent topical IA under `general/`, don't flatten ("don't bulldoze good IA").
- **Sources:** batches 3 (copy 5), 4 (Talos hardware digest)

### roadmap-topup maintains roadmap.md at exactly 100 items via posture-counts.sh
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** `docs/techdocs/docs/general/roadmap.md` is a living backlog held at exactly 100 open items (roadmap-topup skill). Ground truth via `./scripts/posture-counts.sh` (PDB / NetworkPolicy / CiliumNetworkPolicy / ResourceQuota / SecurityPolicy counts + Kyverno Audit-vs-Enforce split + namespaces-with-a-NetworkPolicy). Move shipped work to the Done log, reframe partials, add findings to hold at 100. Don't manually renumber it. Snapshot (2026-06-21): PDB 2 · NetworkPolicy 17/11 ns · CiliumNetworkPolicy 1 · ResourceQuota 4 · SecurityPolicy 0 · Kyverno 11 Audit / 6 Enforce.
- **Sources:** batch 2 (copy 8)

### Skill authoring (skillsmith): loader executes bang-backtick injection; substitutes `${CLAUDE_SKILL_DIR}`/`$ARGUMENTS`
- **Type:** GOTCHA + FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** The Claude Code skill loader executes the bang-backtick dynamic-injection pattern found in a SKILL.md body at load time — skillsmith/SKILL.md documented that very syntax with the live token, so invoking `/skillsmith` ran the literal example (`zsh: command not found: cmd`), blocking the skill. Only SKILL.md is scanned (sibling reference.md is not). Fix: never write the literal bang-backtick token in a SKILL.md body — name the feature, put the literal syntax in reference.md. On load, `${CLAUDE_SKILL_DIR}` expands to the absolute skill path and `$ARGUMENTS` to invocation args; the command name derives from the **directory name**, not frontmatter `name:`.
- **Sources:** batch 4 (node-taxonomy migration digest)

---

## Conflicts (cross-batch)

### Was the cosign-sign-attest Harbor SBOM step committed/exercised?
- **Conflict:** Batch 2's copy 3 (earlier "column not populated" thread) said the code change was made but not yet committed or run; copy 2 (later "403 fix" thread, same date) treats the step as live and resolves the permission via the robot grant (commit 9938e09). Batch 3's copy 4 independently confirms the grant via recent commit `fix(harbor): grant CI robot sbom:create`.
- **More credible:** The later state — the SBOM step exists, `sbom:create` is granted+verified (commit 9938e09 is in the repo's recent-commits list) — supersedes the earlier `[OPEN]` permission concern. The only genuinely-unexercised piece is the next real release turning the `::warning:: HTTP 403` into a populated Harbor SBOM column.
- **Sources:** batches 2 (copy 2, copy 3), 3 (copy 4)

### Runner advertised labels: `docker` only vs `docker, default, ubuntu-latest`
- **Conflict:** Batch 3 copy 7 read the config as advertising three labels; copy 5 established (by live `action_runner` DB query, post-sweep) that it advertises only `docker`.
- **More credible:** Single `docker` — verified against the live DB and the post-sweep config, and matches the explicit "labels must be TRUE" preference. copy 7's reading predates the sweep.
- **Sources:** batch 3 (copy 5 authoritative, copy 7)

### ADR-0035 scope: "pre-baked action cache + offline mode" vs "scoped LAN action mirror"
- **Conflict:** Batch 1 copy 16 described ADR-0035 as pre-baking the action set + runner offline mode; copy 13 proved offline mode impossible and repointed the ADR (file renamed to `adr-0035-action-clone-wall.md`).
- **More credible:** copy 13 — it inspected the exact runner image three ways and the file rename is in-tree. Treat the scoped-mirror framing as authoritative.
- **Sources:** batch 1 (copy 13 authoritative, copy 16)

---

## Preferences / feedback (→ memory)

- **Enforce nothing yet — Audit only.** Standing reminder: flip Kyverno `image-verify-harbor-audit` + the GHCR policies Audit→Enforce only once a release is green with zero false positives. Explicitly NOT done. (batches 1, 3)
- **Verify by REAL status, not a proxy artifact / "make sure it works" = end-to-end against the real cluster/source.** A published tag/Release is NOT proof of a green run; "I updated the IaC" ≠ "the running resource changed". The user repeatedly asked "so it all works now?", pushed back when a pipeline was prematurely called "verified green", and self-corrects ("I was wrong, continue") — diagnoses should quote concrete evidence (exact `.releaserc.js` line + log) over assertion. (batches 1, 2)
- **Challenge/verify framing before reporting** — the user correctly pushed back that the "supply-chain" alerts don't reflect their images/Harbor/SBOMs; verify what a metric actually *measures*. (batch 2)
- **GitOps-first, statelessly rebuildable, one change at a time.** "I want my cluster to be statelessly rebuildable" / "can we get around my having to actually run commands?" — separate scoped commits per fix, validate, push to `main` directly; prefer reconciled-from-git mechanisms (provisioner Jobs/CronJobs reading OpenBao, ESO, publisher CronJobs); surface irreducible manual prerequisites as explicit handoffs. Acceptable exception: one-time OpenBao `generate-root` break-glass. (batches 1, 2, 3, 4)
- **Labels must be TRUE, not masks.** "The labels should be TRUE, and not masking something else." It's `forgejo-runner`, not `act_runner` — don't reason from `act` docs (corrected 3×). (batch 3)
- **Author RFC(s)/ADR(s) BEFORE implementation; constrictor/strangler & additive pattern** — new `-fast`/dedicated files, migrate callers incrementally, don't repurpose an existing workflow ("ghcr should be ghcr, harbor should be harbor", DRY as far as possible). Don't RFC a trivial change — a scratch plan suffices. (batches 1, 3)
- **Pin missing external actions to github.com case-by-case** (greppable/findable), NOT a global `DEFAULT_ACTIONS_URL` flip. (batch 3)
- **Forgejo is leading; GitHub mirrors Forgejo; both cannot cut separate releases.** Want `package.json` bumped on release; inter-image base pinned by version+digest with Renovate keeping it bumped. Want a migration *skill* (skillsmith house standard) with automation + "all the coolest Forgejo features", Actions-parity, push-mirror back, branch protection. (batches 3)
- **Respect deliberate deferrals** (longhorn SC at 3) — a decision, not a bug to silently override; don't break a HelmRelease (immutable-VCT swap) without a coordinated owner recreate — present the trade-off. (batches 2, 4)
- **Skills must be token-conscious — only date incident-derived rules** (no ship-dates); state present-state in present tense. **Use the actual skill, not a manual re-implementation** (single-source-of-truth across skills). Use the repo's documented flows/recipes, not hand-rolled raw commands. (batch 4)
- **Triage-then-handover:** lead with a read-only state assessment, then hand a complete, ordered, copy-pasteable command set for the hook-blocked mutating steps. The user verifies via pasted CI logs from the IDE and expects concrete root-cause over speculation. (batches 2, 4)
- **NL-based fast-learning hardware beginner; EU sourcing; power-cost-weighted** (1 W ≈ ~€3/yr; favor perf-per-watt; quiet matters) — teach jargon, still aim high-end; don't over-emphasize NL location in deliverables (note it once). Prefers OSS-first / established-upstream fixes over bespoke. (batches 4, 5; matches `user-nl-hardware-learner.md`)
- **`webgrip.dev` is not sensitive** — fine in plaintext `talenv.yaml`. **Node-touching Talos applies are human-gated**; stage GitOps-side first. (batches 1, 4)
- **Wants a genuinely better CI view than the Forgejo Actions run UI** (which they dislike). **Open to a constraint if the rationale is justified** (asked *why* RWX is avoided). (batch 1)
- **Working style:** casual/collaborative; comfortable doing manual UI steps while the assistant scripts the deterministic parts and verifies; resets/re-scopes tokens himself; scripts must NEVER print token values (length/HTTP-code/masked only). Plan-mode discipline (Explore → Plan → AskUserQuestion → plan file → ExitPlanMode). Don't commit until told during a long review phase. (batches 3, 2)

---

## Open questions / TODO (not for docs)

- **[CI] Real-job A/B of the amd64-fast path** + verifyRelease ≤2-min target — confirm `-fast` files synced to the Forgejo mirror, trigger a release, compare wall-clock (no setup-qemu) + cache hit on run #2/#3; first fast run 10m43s not A/B-confirmed; verifyRelease changes left uncommitted in both repos. (batch 1)
- **[CI] Action-clone wall still significant once QEMU is gone?** If yes, execute ADR-0035's scoped LAN mirror (~6 docker-build action repos). (batch 1)
- **[CI] Forgejo `actions/cache@v4` persistence of `~/.npm`** across ephemeral runs unverified; external Garage-S3 cache backend deferred phase-2. (batches 1)
- **[CI] Per-registry base-image mirroring in the webgrip/workflows docker-container buildkitd config** — offered, not started. (batch 1)
- **[CI] Forgejo-Actions-API → Prometheus exporter + Grafana "CI overview" dashboard** — only viable trends/better-UI path. (batch 1)
- **[CI] Harbor "Docker Build and Push (Harbor)" job fails on first-ever execution** — candidates: robot login, harbor reachability/TLS from runner, push perms, multi-arch buildx. Needs the authenticated run log. (batch 2)
- **[CI] Forgejo may not honor job-level `if:` on reusable (`uses:`) jobs** — both the `is_prerelease != 'true'` and `== 'true'` distribute jobs executed (matches the flattening gotcha; needs confirmation as the gating mechanism). (batch 2)
- **[CI] Final controlled release (run #33)** — confirm image+signature landed in BOTH Harbor and GHCR, the `chore(release) [skip ci]` commit-back occurred, and GitHub Releases populated. (batches 3, 1)
- **[CI] Flip Kyverno Audit→Enforce** once a release is green with zero false positives. (batches 1, 3)
- **[Harbor] Final visual confirmation of Harbor SBOM column** pending the next real release; and whether the explicit pipeline SBOM POST is redundant given `auto_sbom_generation` is enabled. (batches 2, 3)
- **[Harbor] Full warm Job run (116 refs, digest-normalized)** not yet completed; ADR-0016/0017 + rfc-harbor-proxy-cache flipped Proposed→Accepted before the cutover was functional (drill non-representative pre-DNS-fix) — needs a correction noting the `extraHostEntries` prerequisite. 6 images can't be routed (`reg.kyverno.io/*` + `oci.external-secrets.io/*`). Proxy retention/TTL + Trivy "block vulnerable" gates deferred. (batch 1)
- **[Forge migration] Mirror token fix not applied** (`GH_MIRROR_TOKEN` still `x-oauth-scopes: repo`, no `workflow` → workflows push-mirror broken); **infrastructure mirror divergence** (GitHub main stale + GitHub-only tags a blind mirror would force-delete — needs a decision); **GitHub Actions still enabled on migrated repos**; `--all` sweep needs `read:organization`; `.profile-private` rendering unverified; claude-config private-on-Forgejo/public-on-GitHub; ~65 repos remain. (batch 3)
- **[Docs] mkdocs `--strict` not run locally** ("0 dead links" via custom resolver only); `techdocs-builder` image must be rebuilt+published with `mkdocs-redirects==1.2.2` before the next docs build (plugin already enabled on main → build fails until rebuilt); Codeberg Pages / Backstage TechDocs external-storage not live; homelab-cluster has no `on_docs_change.yml`. (batch 3)
- **[Storage/HA] etcd backups don't exist (roadmap #52)**; spegel `driftDetection.ignore` not applied (third drifted field never pinned); Longhorn volume backups never actually ran (BackupTarget Available but `kubectl get backups.longhorn.io` empty; restore unproven, roadmap #58); Garage S3 single external host = SPOF for ALL backups + CNPG WAL (roadmap #63); DT 2-replica durability decision; whether to rebalance Longhorn to use worker-1 as a second replica home. (batches 4, 2)
- **[Talos/placement] Label-drop (`nodegroup`/`workload-tier`) not yet run on live nodes** (`MODE=no-reboot`, roadmap #34); authentik node-level HA needs media→S3 then `cpu=high`→`pool=worker` (roadmap #47); whether worker-1's CNPG DBs landed on a soyo during its force-drain (fsync/leader-change risk) — flagged, unverified. (batches 4, 2)
- **[Observability] Kyverno audit→enforce campaign (Workstreams D)** framework shipped (ADR-0033/0034 + CI gate); flips deliberately NOT executed. Owner-gated: seed Codeberg PAT into OpenBao, `talosctl etcd defrag`, re-enable pyroscope after defrag. Re-frame supply-chain CVE triage as third-party hygiene; downgrade upstream-CVE alerts; fix `TrivyExposedSecretsDetected` severity labeling. `harbor-jobservice` flapping CrashLoopBackOff (pre-existing). (batch 2)
- **[Worktrees] `.worktreeinclude` left untracked/uncommitted** for review (safe to commit — filenames only); whether to add a universal post-checkout git hook + a `scripts/new-worktree.sh` + CLAUDE.md docs; copy-vs-symlink drift for rotated files unresolved. (batch 5)
- **[Runner] never proven on a real job** (version empty in DB); host-mode + label declaration unverified end-to-end pending OpenBao break-glass. Stale `feat/forgejo-harbor-ci` branch deletable. GHCR `webgrip/*` package visibility unknown (private → needs ghcr-pull secret in the keyless policies); `infrastructure/ops/kyverno/.../verify-webgrip-images.yaml` keyless-Enforce policy should be removed/converted; GHCR images create a 2nd DT project per image. (batches 3, 1)
