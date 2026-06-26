Thread Digest: Speeding up Forgejo CI (amd64-default builds, action-clone wall)
One-line summary: Diagnosed slow Forgejo Actions CI ("setup takes minutes"), found the two real costs (per-job action re-clones + emulated arm64), shipped an amd64-default "fast" build-workflow stack via a constrictor pattern, and discovered the planned action-cache fix (offline mode) is impossible in this runner.
Approx date / status: 2026-06-25/26 — in progress (fast workflows pushed; awaiting a real release run to measure; action-cache work deferred behind measurement).

Items
[FACT] forgejo-runner 12.10.2 has NO action offline mode at any layer
Type: FACT
Verification: [VERIFIED] (inspected the exact image locally three ways)
What: code.forgejo.org/forgejo/runner:12.10.2 exposes no way to skip re-fetching already-cached actions. generate-config → the cache: block is ONLY the actions/cache server (ACTIONS_CACHE_URL), not the action-repo cache. one-job --help (the daemon path used in-pod) exposes only --url/--uuid/--token-url/--wait/--fetch-interval/--handle/--label. exec --help — this Forgejo act fork has stripped --action-offline-mode and --action-cache-path that upstream nektos/act has; the only action lever left is --default-actions-url (default https://code.forgejo.org).
Why it matters: Kills the common "pre-bake actions into the image + enable offline mode" plan. Without offline mode, even a warm/baked ~/.cache/act still git fetches upstream every job (only converts clone→fetch). The lever that actually controls action source is the server-side DEFAULT_ACTIONS_URL.
Snippet:

docker run --rm --entrypoint forgejo-runner code.forgejo.org/forgejo/runner:12.10.2 generate-config
docker run --rm --entrypoint forgejo-runner code.forgejo.org/forgejo/runner:12.10.2 one-job --help
docker run --rm --entrypoint forgejo-runner code.forgejo.org/forgejo/runner:12.10.2 exec --help
Suggested home: memory + doc (ADR on the action-clone wall)
[FACT] forgejo-runner config schema (12.10.2) — the cache block is the actions/cache server only
Type: REFERENCE
Verification: [VERIFIED]
What: cache: keys = enabled, port, dir (defaults to $HOME/.cache/actcache), external_server, secret, secret_url, host, proxy_port, actions_cache_url_override. The runner: block has fetch_timeout, fetch_interval, report_interval, timeout, shutdown_timeout, capacity, labels, envs, env_file. The container: block has network, privileged, options, workdir_parent, valid_volumes, docker_host, force_pull, force_rebuild. No key controls action re-fetch or sets an action-repo cache dir.
Why it matters: Confirms there is no config-level knob for the action-clone wall; rules out a quick config fix.
Snippet: forgejo-runner generate-config > config.yaml
Suggested home: doc
[GOTCHA] act --dryrun does NOT fetch actions; ~/.cache/act is only written during real execution
Type: GOTCHA
Verification: [VERIFIED] (ran exec -n; it created only ~/.cache/actcache/bolt.db, never ~/.cache/act)
What: Running forgejo-runner exec -n (dryrun) does not clone/fetch the workflow's actions, so it cannot be used to pre-populate the action cache at image-build time. Also: this fork's exec rejects upstream act flags like -P/--platform ("unknown shorthand flag: 'P'"); use -i/--image (default node:20-bullseye) instead.
Why it matters: Invalidated the "prime the cache cheaply with a Docker-less dryrun at image build" idea; correct priming would need a real run (Docker), and the cache path stability is unverified anyway.
Snippet: docker run --rm --user 0 -e HOME=/h -v $T/h:/h -v $T/repo:/repo -w /repo --entrypoint forgejo-runner code.forgejo.org/forgejo/runner:12.10.2 exec -n --default-actions-url https://data.forgejo.org -W .forgejo/workflows/t.yml
Suggested home: memory
[FACT] The cluster's Forgejo serves actions from data.forgejo.org because DEFAULT_ACTIONS_URL is unset
Type: FACT
Verification: [VERIFIED] (helmrelease [actions] block has only ENABLED: true; runner log clones from data.forgejo.org)
What: kubernetes/apps/forgejo/forgejo/app/helmrelease.yaml configures Forgejo gitea.config.actions: { ENABLED: true } and does NOT set DEFAULT_ACTIONS_URL, so it defaults to https://data.forgejo.org. That is why every CI action clones from the internet. Setting it globally would make the in-cluster Forgejo authoritative for ALL actions (15+ used across workflows) — un-mirrored ones would 404/break.
Why it matters: The only built-in lever for the action-clone wall is DEFAULT_ACTIONS_URL; a global flip has high blast radius, so the chosen fallback is a scoped per-action mirror referenced by explicit URLs in one composite.
Snippet: kubernetes/apps/forgejo/forgejo/app/helmrelease.yaml (gitea.config.actions)
Suggested home: doc
[DECISION] The dominant CI build cost is emulated arm64 (QEMU), not the action clones
Type: DECISION
Verification: [ASSERTED] (reasoned from the composite default + amd64-only cluster; first real run was 10m43s, not yet A/B-confirmed)
What: The shared build composite defaulted to platforms: linux/amd64,linux/arm64; the homelab is amd64-only Talos, so the arm64 image was built under QEMU emulation — slower than the entire action-clone wall, on every image, for an artifact nothing runs. Decision: default builds to linux/amd64 and run docker/setup-qemu-action only when a non-amd64 arch is requested.
Why it matters: Removing emulated arm64 is the single biggest, lowest-risk speedup; it also reframed the action-cache work as secondary ("measure first").
Snippet: QEMU gate in the fast composite: if: ${{ inputs.platforms != 'linux/amd64' }}
Suggested home: doc (ADR-0036)
[DECISION] Action-clone wall: measure-first, then scoped LAN mirror; reject pre-bake / global DEFAULT_ACTIONS_URL / RWX
Type: DECISION
Verification: [VERIFIED] (decision made; offline-mode impossibility verified)
What: Because offline mode does not exist, ship the amd64 fix first and re-time a real job before building any action-cache infra. If clones still dominate, mirror only the docker-build action repos into in-cluster Forgejo and reference them by explicit LAN URLs in the -fast composite only (e.g. uses: https://forgejo.webgrip.dev/<mirror>/checkout@v4). Rejected: pre-baking ~/.cache/act (no offline mode ⇒ still fetches; unverified path stability), global DEFAULT_ACTIONS_URL (blast radius), and an RWX shared cache PVC (cluster policy).
Why it matters: Avoids building disproven/fragile infrastructure; keeps the fix scoped and low-risk.
Snippet: none
Suggested home: doc (ADR-0035)
[FACT] buildx must stay even for amd64-only builds — registry cache export needs its driver
Type: FACT
Verification: [ASSERTED] (well-established buildx behavior; not re-tested here)
What: docker/setup-buildx-action cannot be dropped from the fast build path: cache-to: type=registry requires buildx's docker-container driver to export. Only docker/setup-qemu-action is safe to skip for pure-amd64 builds. Dropping buildx would silently disable the Harbor layer cache.
Why it matters: Prevents a "simplification" that quietly breaks layer caching.
Snippet: cache-to: type=registry,ref=<reg>/<owner>/<image>:cache,mode=max,compression=zstd
Suggested home: doc
[FACT] The Harbor registry layer cache (#4) already exists in the build composite
Type: FACT
Verification: [VERIFIED] (read the composite)
What: webgrip/workflows/.forgejo/composite-actions/docker-build-push-registry/action.yml already computes a :cache tag from the primary image tag and uses cache-from: type=registry,ref=…:cache + cache-to: type=registry,ref=…:cache,mode=max,compression=zstd. The -fast variant inherits it verbatim. Runtime effectiveness (cache import → CACHED layers on a second build) was not yet confirmed.
Why it matters: No new work was needed for layer caching; "build the Harbor cache" was already done — the task is to verify it, not add it.
Snippet: webgrip/workflows/.forgejo/composite-actions/docker-build-push-registry/action.yml
Suggested home: doc
[PROCEDURE] Constrictor (strangler) migration for the build workflow chain
Type: PROCEDURE
Verification: [VERIFIED] (files created, committed, pushed; first caller flipped)
What: Build-workflow call graph is: app repo job → per-registry wrapper (docker-build-and-push-harbor.yml) → engine (docker-build-and-push-registry.yml) → composite (docker-build-push-registry). To change behavior without a flag-day, create parallel -fast files at each layer (composite docker-build-push-registry-fast, engine docker-build-and-push-registry-fast.yml, wrapper docker-build-and-push-harbor-fast.yml), leave the originals untouched, migrate callers one at a time by flipping their uses: to the -fast wrapper, and delete the old chain once unreferenced.
Why it matters: Each migration is independently revertible; nothing breaks until a caller opts in.
Snippet: caller flip — uses: webgrip/workflows/.forgejo/workflows/docker-build-and-push-harbor-fast.yml@main + platforms: "linux/amd64"
Suggested home: existing-skill (a build/CI workflows skill) or doc
[GOTCHA] A caller passing explicit platforms: "linux/amd64,linux/arm64" defeats the fast wrapper's default
Type: GOTCHA
Verification: [VERIFIED] (saw the explicit value at on_release_published.yml:91; edited it to linux/amd64)
What: Switching a caller to the -fast wrapper is NOT enough if the caller still passes a multi-arch platforms input — the QEMU gate (inputs.platforms != 'linux/amd64') sees the comma'd value and still emulates arm64. You must also change the caller's platforms to linux/amd64 (or remove the override to inherit the fast default).
Why it matters: Easy to think you migrated to "fast" while still paying full arm64-emulation cost.
Snippet: webgrip/infrastructure/.forgejo/workflows/on_release_published.yml job release-distribute-harbor, platforms: "linux/amd64"
Suggested home: doc / skill
[GOTCHA] Forgejo flattens reusable-workflow inner jobs into the caller graph and ignores the caller job's if:
Type: GOTCHA
Verification: [ASSERTED] (documented in-repo as the cause of a real prior incident; not re-reproduced this thread)
What: Per the comment in on_release_published.yml: do NOT split a build into two is_prerelease-gated reusable-workflow jobs — Forgejo flattens the reusable workflow's inner jobs into the caller's graph and does NOT apply the caller job's if: to those flattened jobs, so a "skipped" job still runs its flattened build → two concurrent builds racing on the same Harbor tag + buildx :cache ref. Use ONE job and gate differences inline (e.g. the :latest tag via a docker-tags expression).
Why it matters: Reusable-workflow + conditional jobs behave differently on Forgejo than on GitHub; can cause duplicate concurrent builds.
Snippet: none
Suggested home: doc / skill
[GOTCHA] Forgejo Actions reusable-workflow nesting renders each workflow_call as a 0s ⟳ row
Type: GOTCHA
Verification: [VERIFIED] (observed in the run UI)
What: In the Forgejo run view, each reusable-workflow layer shows as its own caller row with 0s and a ⟳ icon; only the deepest job shows real duration. A 3-layer chain (release → harbor-fast → registry-fast → composite) renders one logical build as 3 rows. This is inherent to reusable workflows, not a config issue.
Why it matters: Explains the "messy" run UI; flattening a workflow_call layer is the only way to reduce the row count.
Snippet: none
Suggested home: memory
[FACT] Forgejo exports NO Actions/CI metrics to Prometheus — only object-count gauges
Type: FACT
Verification: [VERIFIED] (queried live Prometheus, datasource uid prometheus)
What: Forgejo's /metrics exposes only gitea_* count gauges: gitea_accesses, gitea_attachments, gitea_build_info, gitea_comments, gitea_follows, gitea_hooktasks, gitea_issues, gitea_issues_closed, gitea_issues_open, gitea_labels, gitea_loginsources, gitea_milestones, gitea_mirrors, gitea_oauths, gitea_organizations, gitea_projects, gitea_projects_boards, gitea_publickeys, gitea_releases, gitea_repositories, gitea_stars, gitea_teams, gitea_updatetasks, gitea_users, gitea_watches, gitea_webhooks. There are no run-duration, job-timing, or task-status metrics.
Why it matters: A Grafana CI dashboard for build durations/trends/cache-hit is NOT possible from native Forgejo metrics; it requires a custom Forgejo-Actions-API exporter. Don't promise a metrics dashboard without that exporter.
Snippet: Grafana MCP list_prometheus_metric_names datasourceUid=prometheus regex=(?i)(forgejo|gitea)_.*
Suggested home: memory
[REFERENCE] Repo locations, versions, and the build call graph (webgrip)
Type: REFERENCE
Verification: [VERIFIED]
What: Local checkouts: homelab GitOps /home/ryan/projects/webgrip/homelab-cluster; reusable workflows /home/ryan/projects/webgrip/workflows (origin = git@github.com:/webgrip/workflows.git, Forgejo serves it as a mirror; runner clones it from https://forgejo.webgrip.dev/webgrip/workflows); runner image source /home/ryan/projects/webgrip/infrastructure/ops/docker/github-runner/Dockerfile (image ghcr.io/webgrip/github-runner, FROM ghcr.io/actions/actions-runner, adds PHP 8.3 + .NET 9 + CodeQL + composer + gh). Forgejo helm chart 17.1.0 (OCI oci://harbor.webgrip.dev/forgejo/forgejo-helm/forgejo). Runner image pinned in kubernetes/apps/forgejo/forgejo-runner/app/scaledjob.yaml; injected forgejo-runner binary from code.forgejo.org/forgejo/runner:12.10.2.
Why it matters: Knowing which of the 3 repos owns which change (and that workflows pushes to GitHub origin but is consumed via the Forgejo mirror) is essential for any CI change here.
Snippet: Harbor robot creds reach CI as Forgejo org secrets HARBOR_ROBOT_USER/HARBOR_ROBOT_TOKEN (from OpenBao secret/harbor/robot-webgrip, robot username form robot$webgrip+ci).
Suggested home: doc / CLAUDE.md
[GOTCHA] git commit -- <paths> -m "msg" fails — -m after -- is treated as a pathspec
Type: GOTCHA
Verification: [VERIFIED] (failed once, then fixed by reordering)
What: To commit ONLY specific files while leaving other staged files out of the commit, put -m BEFORE the -- pathspec separator: git commit -m "msg" -- path1 path2. Putting -m after -- makes git interpret -m and the message text as pathspecs ("pathspec '-m' did not match"). For new/untracked files, git add them first.
Why it matters: Needed to scope a commit when unrelated changes are already staged in the index.
Snippet: git -c commit.gpgsign=false commit -m "msg" -- <files>
Suggested home: memory
[GOTCHA] Parallel agents commit on main mid-session; SessionStart "clean" snapshot goes stale
Type: GOTCHA
Verification: [VERIFIED] (files I never touched appeared staged; a perf(forgejo-runner): rightsize CPU/mem + warm pool commit 04c6151 appeared during the session)
What: Files unexpectedly appeared staged (scaledjob.yaml, forgejo-runner.md) despite a clean session-start; a concurrent workstream committed them to main during the session. Before committing/pushing: re-check git status, git log, and git fetch; scope your commit with explicit pathspecs so you don't sweep in someone else's staged work; and inspect any "unexpected" staged change rather than committing it.
Why it matters: Concurrent agents on the unprotected main can collide; this matches the known "concurrent-agents-main-collisions" hazard.
Snippet: none
Suggested home: memory (reinforces existing concurrent-agents memory)
[FACT] webgrip/workflows is GitHub-origin, consumed via the Forgejo mirror (so pushes have sync lag)
Type: FACT
Verification: [VERIFIED] (only remote is origin = GitHub; runner clones from forgejo.webgrip.dev)
What: webgrip/workflows local checkout has a single remote origin → git@github.com:/webgrip/workflows.git; @main reusable-workflow refs are consumed from forgejo.webgrip.dev/webgrip/workflows. After pushing to GitHub origin, the Forgejo mirror may lag — confirm the new files exist on forgejo.webgrip.dev/webgrip/workflows before triggering a release, or it fails "workflow not found." (NB: a forgejo-leading skill exists and lists workflows as the first migration candidate, so this may change to Forgejo-leading.)
Why it matters: Push location ≠ consumption location; the mirror lag is a real ordering dependency for CI changes.
Snippet: none
Suggested home: doc / memory
[REFERENCE] Documentation conventions: RFCs + ADRs in this repo
Type: REFERENCE
Verification: [VERIFIED] (followed them; files build into nav)
What: ADRs live at docs/techdocs/docs/adr/adr-NNNN-<kebab>.md (zero-padded, monotonic, never reused; this thread added 0035, 0036 — last prior was 0034). RFCs at docs/techdocs/docs/rfc/rfc-<topic>.md. Each doc opens with # H1 then a > Status: **Accepted** · Date: YYYY-MM-DD · Part of [RFC: …](../rfc/rfc-….md) banner (no front-matter). ADR sections: Context / Decision / Consequences / Alternatives considered. An RFC is the umbrella; ADRs link back. Must also update: docs/techdocs/docs/adr/index.md (RFC table + ADR table) AND docs/techdocs/mkdocs.yml nav: (explicit nav, not auto). Status legend: Proposed/Accepted/Superseded/Deprecated.
Why it matters: New ADRs/RFCs won't appear unless registered in both index.md and mkdocs.yml nav; numbering is an invariant.
Snippet: rename also requires updating index.md row + the mkdocs.yml nav line (renamed adr-0035-prebaked-action-cache.md → adr-0035-action-clone-wall.md here).
Suggested home: existing-skill (an ADR/RFC authoring skill) or CLAUDE.md
[GOTCHA] markdownlint MD060 (table style) and the github-script \u200b fence escape
Type: GOTCHA
Verification: [VERIFIED]
What: Two doc/lint footguns seen: (1) this repo's markdown tables trip MD060 "compact"/"aligned" warnings on long-content rows — they're cosmetic and consistent with existing tables, safe to leave. (2) The build-summary github-script step uses a literal in String(content).replace(/```/g, '\u200b``'); when copying it, keep the \u200b*escape*, not a literal zero-width space (a literal ZWSP is an invisible-char smell). Converted viaperl -CSD -i -pe 's/\x{200b}/\u200b/g' <file>`.
Why it matters: Avoids churn on cosmetic lints and avoids smuggling invisible Unicode into YAML when duplicating the composite.
Snippet: perl -CSD -i -pe 's/\x{200b}/\\u200b/g' .forgejo/composite-actions/docker-build-push-registry-fast/action.yml
Suggested home: memory
[FACT] Longhorn RWX is policy-forbidden; there are zero RWX PVCs in the repo
Type: FACT
Verification: [VERIFIED] (explored StorageClasses, policy, and existing PVCs)
What: longhorn-rwx StorageClass exists (NFS share-manager, numberOfReplicas: "2") but Kyverno storage-cnpg-governance.disallow-rwx-pvcs blocks all ReadWriteMany PVCs cluster-wide; there are no RWX PVCs in the repo (pattern is RWO + node-pinning, or push shared state to S3/Garage). A per-node hostPath cache is the lower-risk step if a shared cache is ever needed; RWX only beyond that, behind a PolicyException.
Why it matters: Rules out a shared RWX cache for CI (NFS SPOF on RAM-tight nodes); shapes any "shared cache" design toward bake/hostPath/object-storage.
Snippet: policy kubernetes/apps/kyverno/policies/app/storage-cnpg-governance.yaml; SCs under kubernetes/apps/longhorn-system/longhorn/storageclass/
Suggested home: existing-skill (longhorn / workload-placement)
Open questions / unfinished
[OPEN] Real-job measurement not yet done: confirm the -fast files synced to the Forgejo mirror, commit+push the infra on_release_published.yml change, trigger a release, and compare wall-clock (expect no setup-qemu/emulation step) and cache hit on run #2/#3. First observed fast-path run was 10m43s (likely cold cache + heavy image), not yet A/B-confirmed against the old path.
[OPEN] Is the action-clone wall still significant once arm64/QEMU is gone? If yes, execute ADR-0035's scoped LAN mirror (mirror ~6 docker-build action repos into in-cluster Forgejo; also actions/github-script currently uses an explicit https://github.com/... URL that would need repointing).
[OPEN] act ~/.cache/act/<hash>/... top-level path stability across runs is unverified (the local exec harness never populated it cleanly) — so even pre-baking viability is unconfirmed (moot given offline mode is absent).
[OPEN] Whether to add a docker-build-and-push-ghcr-fast.yml wrapper for symmetry (deferred until a GHCR build needs it). Note: per the latest file state, release-distribute-ghcr already exists and also builds amd64-only, but GHCR images are not yet cosign-signed.
[OPEN] Whether to build a Forgejo-Actions-API → Prometheus exporter + Grafana "CI overview" dashboard (the only viable "better UI"/trends path, since native metrics lack CI data).
Explicit preferences/feedback I gave
Wanted RFC(s) and ADR(s) authored BEFORE implementation, then implementation to proceed.
Chose the constrictor/strangler pattern for the build-workflow change (new -fast files, migrate callers incrementally) rather than editing the existing workflow in place.
For the action-clone wall (after offline mode proved impossible): chose measure-first — ship the amd64/no-QEMU fix and re-time before building cache infra.
Chose amd64-only as the default build arch.
When pre-baking scope was offered, chose the narrow docker-build action set (not the broad common set).
Asked to understand why RWX is avoided in this cluster (wanted the rationale, open to adopting it if justified).
Dislikes the Forgejo Actions run UI; was probing for a genuinely better view/dashboard.
General working style (inferred from approvals): values verifying assumptions against the real system before committing to a design, and honest surfacing when a verified finding contradicts the approved plan.
