
Thread Digest: Speeding up Forgejo release-per-image via cached verifyRelease build
One-line summary: Diagnosed a >10-min per-image release job and made semantic-release's verifyRelease docker build reuse the Harbor buildx registry cache (read-only) so it drops to ≤2 min.
Approx date / status: 2026-06-24 → 2026-06-26 — done (changes in working tree of both repos; not committed at end of session; user subsequently extended them with GitHub-mirror + base-image-proxy bits).

Items
[FACT] Two-repo split: webgrip/workflows holds reusables; webgrip/infrastructure holds the consuming pipeline + images
Type: FACT
Verification: [VERIFIED]
What: webgrip/workflows contains ONLY reusable workflows (.forgejo/workflows/, .github/workflows/) and composite actions (.forgejo/composite-actions/, .github/composite-actions/). The per-image build images (ops/docker/<image>/), the .releaserc.js, the runner images (github-runner, act-runner, techdocs-builder, etc.), and the live On Source Change / release-per-image workflow all live in webgrip/infrastructure. The two repos are sibling checkouts at /home/ryan/projects/webgrip/workflows and /home/ryan/projects/webgrip/infrastructure.
Why it matters: A CI log mentioning release-per-image / changed-images is NOT debuggable from the workflows repo alone; the build logic is config-side in infrastructure's .releaserc.js.
Snippet: none
Suggested home: CLAUDE.md
[FACT] infrastructure mirrors workflows' composites as local .forgejo/actions/* copies — the live path uses the LOCAL copy
Type: FACT
Verification: [VERIFIED]
What: infrastructure/.forgejo/workflows/on_source_change.yml → job release-per-image calls uses: ./.forgejo/actions/semantic-release-monorepo (an infrastructure-local hand-maintained mirror), NOT webgrip/workflows/.forgejo/composite-actions/semantic-release-monorepo. The workflows copies are canonical templates that infra was mirrored from; editing the workflows copy alone does NOT affect the live release path. Keep both in sync to prevent drift re-introducing regressions.
Why it matters: Performance/behavior fixes for the live path must be edited in infrastructure/.forgejo/actions/...; the workflows copy is parity-only.
Snippet: none
Suggested home: doc
[FACT] The ~9-min cost was a plain, uncached docker build inside semantic-release's verifyReleaseCmd
Type: FACT
Verification: [VERIFIED]
What: In infrastructure/.releaserc.js, the @semantic-release/exec plugin had verifyReleaseCmd: 'docker build --file Dockerfile .'. On the ephemeral DinD runner this rebuilt the entire heavy image (multiple base images + apk add of ~194 packages incl. chromium/graphviz) cold on every release, BEFORE the tag was cut — and it duplicated the build that on_release_published.yml does afterward (which already uses buildx + Harbor registry layer-cache). Log timing: setup-node ~30s, npm install ~15s, version analysis ~2s, docker build ≈ the remaining ~9 min.
Why it matters: The exec verify step, not the toolchain, was the dominant cost; the build was redundant with the publish path.
Snippet: none
Suggested home: doc
[DECISION] Make verifyRelease a buildx build that READS the publish path's :cache ref (no cache-to)
Type: DECISION
Verification: [VERIFIED] (logic + JS output verified; cache-hit speedup [ASSERTED] until run in CI)
What: Env-gate verifyReleaseCmd: when BUILD_CACHE_REF is set, run docker buildx build … --cache-from type=registry,ref=<ref> --output=type=cacheonly; else fall back to the plain docker build. Deliberately NO cache-to. Rationale: the verify gate is amd64-only while the publish build is amd64+arm64 into the SAME :cache ref; writing amd64-only cache-to would clobber the arm64 layers the publish path depends on, forcing arm64 to rebuild cold every release. Cache is populated solely by publish, so verify reads "one release behind" — a full hit for the common no-Dockerfile-change "bump" commit. --output=type=cacheonly builds every stage and discards the result (it's only a gate). The plain-build fallback keeps GitHub behavior unchanged.
Why it matters: Achieves the ≤2-min goal for common commits without regressing publish's arm64 caching.
Snippet:

const cacheRef = process.env.BUILD_CACHE_REF;
const verifyReleaseCmd = cacheRef
    ? [
        'docker buildx build --file Dockerfile --platform linux/amd64',
        `--cache-from type=registry,ref=${cacheRef}`,
        '--output=type=cacheonly .',
    ].join(' ')
    : 'docker build --file Dockerfile .';
Suggested home: doc
[GOTCHA] github.repository_owner is EMPTY on this Forgejo runner — hardcode webgrip in the cache ref
Type: GOTCHA
Verification: [VERIFIED] (user-applied correction during thread)
What: Building BUILD_CACHE_REF from ${{ github.repository_owner }} yields <registry>//<image>:cache (double slash) on Forgejo because the value is empty there — an invalid ref that never matches the publish cache. The publish path (on_release_published.yml) also hardcodes webgrip, so the verify cache ref must too. Final form: BUILD_CACHE_REF=${{ inputs.registry }}/webgrip/${{ inputs.package-name }}:cache.
Why it matters: Silent cache miss (always cold) if the owner is taken from the context var.
Snippet: echo "BUILD_CACHE_REF=${{ inputs.registry }}/webgrip/${{ inputs.package-name }}:cache" >> "$GITHUB_ENV"
Suggested home: doc
[FACT] Publish-path cache ref convention: <registry>/<owner>/<image>:cache (primary tag with :cache)
Type: FACT
Verification: [VERIFIED]
What: webgrip/workflows/.forgejo/composite-actions/docker-build-push-registry/action.yml derives its buildx cache tag by taking the first normalized tag (<registry>/<owner>/<image>:<version>), stripping the tag, and appending :cache. It uses cache-from type=registry,ref=…:cache and cache-to type=registry,ref=…:cache,mode=max,compression=zstd. For Harbor the ref is harbor.webgrip.dev/webgrip/<image>:cache. To reuse this cache elsewhere, the ref must match exactly.
Why it matters: Any other build wanting cache reuse must reconstruct this exact ref.
Snippet: cache-to: type=registry,ref=harbor.webgrip.dev/webgrip/<image>:cache,mode=max,compression=zstd
Suggested home: doc
[FACT] cache-from/cache-to type=registry requires the buildx docker-container driver (not the default docker driver)
Type: FACT
Verification: [ASSERTED]
What: To use registry cache import/export, run docker/setup-buildx-action@v3 first (it creates a docker-container driver builder). The default docker driver does not support cache-to type=registry. The Harbor :cache repo also needs auth to pull, so docker/login-action@v3 to the registry is required even for read-only cache-from.
Why it matters: Without setup-buildx + login, the cached verify build fails or silently misses.
Snippet:

- name: Set up Docker Buildx
  if: ${{ inputs.harbor-robot-token != '' }}
  uses: docker/setup-buildx-action@v3
- name: Log in to Harbor (verifyRelease build cache)
  if: ${{ inputs.harbor-robot-token != '' }}
  uses: docker/login-action@v3
  with:
    registry: ${{ inputs.registry }}
    username: ${{ inputs.harbor-robot-user }}
    password: ${{ inputs.harbor-robot-token }}
Suggested home: doc
[GOTCHA] @semantic-release/exec verifyReleaseCmd is Lodash-templated — build dynamic strings in JS, not in the command
Type: GOTCHA
Verification: [ASSERTED]
What: semantic-release expands ${...} in exec commands as Lodash templates against its release context (e.g. ${nextRelease.version}), NOT as shell. So you cannot put ${process.env.FOO} in the command string. Because .releaserc.js is real JS, read process.env and interpolate at config-load time instead (e.g. const cacheRef = process.env.BUILD_CACHE_REF). successCmd: 'echo "version=${nextRelease.version}" >> $GITHUB_OUTPUT' is the intended Lodash use.
Why it matters: Prevents template/shell collisions and lets env-driven config branch cleanly.
Snippet: none
Suggested home: doc
[FACT] Per-image .releaserc.cjs spread the shared root .releaserc.js
Type: FACT
Verification: [VERIFIED]
What: Each infrastructure/ops/docker/<image>/.releaserc.cjs does const base = require('../../../.releaserc.js'); module.exports = { ...base, tagFormat: '<image>-v${version}' };. Editing the root .releaserc.js propagates to every image. The shared config also branches on process.env.SEMANTIC_RELEASE_GITEA to pick @saithodev/semantic-release-gitea (Forgejo) vs @semantic-release/github.
Why it matters: One edit changes all images; tagFormat (<image>-v<version>) is the per-image override.
Snippet:

const base = require('../../../.releaserc.js');
module.exports = { ...base, tagFormat: 'mkdocs-runner-v${version}' };
Suggested home: doc
[FACT] Forgejo does not emit a release event for CI-created releases — on_release_published.yml is dispatched explicitly
Type: FACT
Verification: [VERIFIED]
What: Forgejo suppresses the release Actions event for releases created inside a CI job (loop prevention), so on_release_published.yml never auto-fires on the Forgejo side. The monorepo action dispatches it via the Gitea API. steps.semantic-release.outputs.version is ALREADY the full namespaced tag <image>-v<version> (semantic-release-monorepo emits the tagFormat-prefixed value, not bare semver) — pass it through verbatim; prepending the package name doubles the prefix (techdocs-builder-vtechdocs-builder-v1.2.14). parse-release-tag expects ^(.+)-v(.+)$.
Why it matters: Explains the explicit dispatch step and a real double-prefix footgun.
Snippet:

curl -fsS -X POST -H "Authorization: token ${GITEA_TOKEN}" -H "Content-Type: application/json" \
  "${GITEA_URL%/}/api/v1/repos/${REPO}/actions/workflows/on_release_published.yml/dispatches" \
  -d "{\"ref\":\"${REF}\",\"inputs\":{\"tag\":\"${TAG}\",\"is_prerelease\":\"${IS_PRERELEASE}\"}}"
Suggested home: doc
[GOTCHA] 'runs-on' key not defined in … changed-images is benign, and the changed-images job name is deliberate
Type: GOTCHA
Verification: [VERIFIED]
What: The Forgejo log line 'runs-on' key not defined in [Workflow] On Source Change/changed-images is NOT an error — changed-images is a uses: (reusable-workflow caller) job, which correctly has no runs-on. The job is deliberately named changed-images (not the reusable's inner job id determine-changed-directories) because Forgejo v15 flattens an expanded reusable workflow's inner jobs into the caller graph; if the caller job id equals the inner job id, the plan has no dependency-free job and Forgejo rejects it with "the workflow must contain at least one job without dependencies". (GitHub namespaces inner jobs, so the same file is fine there.)
Why it matters: Avoids chasing a non-issue and explains a non-obvious naming invariant.
Snippet: none
Suggested home: doc
[FACT] In-cluster Forgejo runner advertises label docker; it is the only pool reaching LAN-only Harbor
Type: FACT
Verification: [VERIFIED]
What: All .forgejo/workflows/ jobs with direct steps pin runs-on: docker (the in-cluster ephemeral DinD runner's only label). It's the only pool that can reach LAN-only registries like harbor.webgrip.dev. Orchestrator jobs that only uses: a reusable correctly omit runs-on. Documented in README.md and docs/adrs/0002-forgejo-actions-parity.md.
Why it matters: Harbor-touching jobs must run on docker; explains the runner-label convention.
Snippet: runs-on: docker
Suggested home: memory
[REFERENCE] Pinned semantic-release toolchain + npm download cache step
Type: REFERENCE
Verification: [VERIFIED] (YAML parses; cache effectiveness [ASSERTED])
What: The monorepo action installs a pinned, lockfile-less set via npm install --no-save --no-audit --no-fund. To avoid re-fetching ~400 packages each run, an actions/cache@v4 step caches ~/.npm keyed on the pinned versions (bump the key suffix when versions change). The workflows-repo canonical copies were aligned to node-version: "24" (was 22). The infra install list (post-thread, user-extended) is: semantic-release@24.2.7 semantic-release-monorepo@8.0.2 @semantic-release/commit-analyzer@13.0.0 @semantic-release/exec@7.0.3 @semantic-release/npm@12.0.1 @semantic-release/git@10.0.1 @saithodev/semantic-release-gitea @semantic-release/release-notes-generator@14.0.0 conventional-changelog-conventionalcommits@7.0.2.
Why it matters: Reusable cache pattern + exact version pins.
Snippet:

- name: Cache npm downloads
  uses: actions/cache@v4
  with:
    path: ~/.npm
    key: ${{ runner.os }}-npm-semrel-24.2.7
Suggested home: doc
[DECISION] Skipped GitHub/GHCR parity for the cached verify build (no regression)
Type: DECISION
Verification: [VERIFIED] (decision made; fallback behavior verified)
What: The GitHub/GHCR path (.github/actions/semantic-release-monorepo, publishing to ghcr.io/<owner>/<image> via github.actor/secrets.GITHUB_TOKEN) was NOT given the cached verify build. It would require adding packages: write + GHCR login to the GitHub release job for a path that isn't the reported pain point (GitHub-hosted runners). Because .releaserc.js falls back to the plain docker build when BUILD_CACHE_REF is unset, GitHub behavior is unchanged — no regression. Easy to add later if wanted.
Why it matters: Scoped the change to where the cost actually was.
Snippet: none
Suggested home: doc
[FACT] Post-thread extensions by user: base-image Harbor proxy args + GitHub mirror release + git commit-back
Type: FACT
Verification: [ASSERTED] (observed in modified files, not run here)
What: The user extended the cached verify branch to also pull base images through the Harbor proxy (only on the cached/Forgejo branch, since the plain GitHub fallback can't reach LAN-only Harbor): --build-arg REGISTRY_DOCKERHUB=harbor.webgrip.dev/dockerhub, --build-arg REGISTRY_GHCR=harbor.webgrip.dev/ghcr, --build-arg REGISTRY_MCR=harbor.webgrip.dev/mcr (Dockerfiles default REGISTRY_* to docker.io/ghcr/mcr). Also added: a github-release-token input (secrets.GH_RELEASE_TOKEN, a GitHub PAT) to mirror the Release object onto the github.com mirror's Releases tab (best-effort; skipped when unset); and Forgejo-gated @semantic-release/npm (npmPublish:false) + @semantic-release/git version-bump commit-back with message: 'chore(release): ${nextRelease.gitTag} [skip ci]\n\n${nextRelease.notes}' and identity webgrip-ci <ci@webgrip.nl>. GitHub is now a pure mirror that cuts no releases / never re-versions, so the two sequences don't diverge; [skip ci] is honored by both Forgejo and GitHub so the mirror push re-triggers nothing.
Why it matters: Captures the final architecture: Forgejo is the sole release authority + version-bumper; GitHub mirrors. Base-image proxying is required for the in-cluster cached build to match the publish build.
Snippet:

const harborBaseArgs = [
    '--build-arg REGISTRY_DOCKERHUB=harbor.webgrip.dev/dockerhub',
    '--build-arg REGISTRY_GHCR=harbor.webgrip.dev/ghcr',
    '--build-arg REGISTRY_MCR=harbor.webgrip.dev/mcr',
];
Suggested home: doc
[PROCEDURE] Validating YAML and JS config changes in this environment (no pyyaml/ruby)
Type: PROCEDURE
Verification: [VERIFIED]
What: Python yaml and ruby are unavailable here; npx --yes js-yaml@4 <file> works for YAML validation. For .releaserc.js, use node --check and exercise the env-gated branch directly.
Why it matters: Reliable local validation path before committing CI config.
Snippet:

npx --yes js-yaml@4 path/to/action.yml >/dev/null && echo OK
node --check .releaserc.js
BUILD_CACHE_REF="harbor.webgrip.dev/webgrip/techdocs-builder:cache" node -e "const c=require('./.releaserc.js');console.log(c.plugins.find(p=>Array.isArray(p)&&p[0]==='@semantic-release/exec')[1].verifyReleaseCmd)"
Suggested home: new-skill
[GOTCHA] Bash tool: cd does not persist between calls, and zsh errors on unmatched globs
Type: GOTCHA
Verification: [VERIFIED]
What: Each Bash invocation resets cwd to the project root, so cd repoA && … ; … ; cd-less git diff runs the later commands in the WRONG repo (saw two repos' diffs both come from infrastructure). Use git -C <path> per command instead. Also, the shell is zsh: unquoted globs with no match hard-error (ls ops/docker/*/ → no matches found; grep --include=*.yml → no matches found). Quote glob args or use find.
Why it matters: Prevents mis-targeted commands and confusing "no matches" failures.
Snippet: git -C /home/ryan/projects/webgrip/workflows --no-pager diff
Suggested home: CLAUDE.md
Open questions / unfinished
[OPEN] End-to-end ≤2-min target not yet confirmed in CI — needs a real run: first release warms cache (still slow once), then a second no-Dockerfile-change bump to ops/docker/techdocs-builder/ should show CACHED layers and ≤2 min.
[OPEN] Does the in-cluster Forgejo actions/cache@v4 backend actually persist ~/.npm across ephemeral runs? Assumed to warn-and-continue on miss; effectiveness unverified.
[OPEN] Changes were not committed in-session (left in working tree of both repos); user asked nothing further before extending them.
Explicit preferences/feedback I gave
(User preferences observed this thread:)
Prefer additive workflows — add a new workflow rather than repurposing an existing one for a new target (pre-existing memory, reaffirmed by repo conventions).
When the user pastes a raw log with no instruction, clarify the actual goal before planning — here the real ask was pure speed ("must be 2 minutes max"), not the surface-level warning.
The user pushed back hard ("No I think that's all wrong") on locating the fix, then self-corrected ("I was wrong, continue") — verify the diagnosis with concrete evidence (quoting the exact .releaserc.js line + log) rather than deferring to the assertion.
