
Thread Digest: Migrating webgrip/workflows from GitHub Actions to Forgejo Actions (+ in-cluster Harbor publishing)
One-line summary: Planned and executed a full GitHub→Forgejo Actions parity port of a 51-workflow reusable CI library using a frozen-.github/adapted-.forgejo two-tree layout, then added a dedicated Harbor build-and-push workflow targeting the in-cluster Forgejo runner.
Approx date / status: 2026-06-12 → 2026-06-16 — in progress (port done & validated locally; live cutover and systemic runner-label retarget still open)

Items
[FACT] Forgejo v15.0 (Apr 2026 LTS) unblocks reusable-workflow libraries
Type: FACT
Verification: [ASSERTED] (web research, not run against a live instance)
What: Forgejo v15.0 added the three features a cross-repo reusable-workflow library depends on: cross-repository workflow_call, OIDC id-token for Actions (requires forgejo-runner > v12.5.0), and repo-scoped tokens. Cross-repo workflow_call requires the called repo to be public; cross-instance references are supported but disable workflow expansion.
Why it matters: Determines whether a centralized webgrip/workflows-style library is even viable on Forgejo, and forces the library repo to be public.
Snippet: none
Suggested home: doc
[GOTCHA] actions/checkout@v6 is broken on non-GitHub runners
Type: GOTCHA
Verification: [ASSERTED] (web research)
What: actions/checkout@v6 hardcodes GitHub paths in includeIf and fails on Forgejo/Gitea/non-GitHub runners. Pin @v5 (universal HTTP Authorization header). @v4 also works.
Why it matters: Silent auth/checkout failures on the Forgejo runner; node/dotnet workflows shipped with @v6.
Snippet: uses: actions/checkout@v5
Suggested home: doc
[FACT] Forgejo action resolution via DEFAULT_ACTIONS_URL
Type: FACT
Verification: [ASSERTED] (web research)
What: A bare uses: actions/checkout@v4 resolves against DEFAULT_ACTIONS_URL, which defaults to https://data.forgejo.org/ (a curated mirror), NOT github.com. An admin can set it to https://github.com. You can also pin a full cross-instance URL in uses: (e.g. uses: https://forgejo.webgrip.dev/webgrip/workflows/.forgejo/composite-actions/workflow-status-summary@main) to reference an action on a specific instance.
Why it matters: A library consumed by many repos either relies on an instance-wide admin setting or must mirror/pin actions; bare uses: silently hitting a stale mirror is a real failure mode.
Snippet: [actions]\nENABLED = true\nDEFAULT_ACTIONS_URL = https://github.com
Suggested home: doc
[FACT] The in-cluster Forgejo runner's label is docker (NOT arc-runner-set / [homelab, heavy])
Type: FACT
Verification: [VERIFIED] (read webgrip/homelab-cluster/kubernetes/apps/forgejo/forgejo-runner/app/configmap.yaml + scaledjob.yaml)
What: The in-cluster Forgejo runner advertises only labels docker, default, ubuntu-latest; the KEDA scaler watches the docker label. arc-runner-set and [homelab, heavy] are the separate GitHub ARC pools — no Forgejo runner offers them, so jobs using those labels never get scheduled on Forgejo. Build/container jobs must use runs-on: docker.
Why it matters: ADR-0002 originally (wrongly) assumed the Forgejo runner reuses ARC labels; ~48 .forgejo jobs still carry arc-runner-set/[homelab, heavy] and won't run until retargeted to docker.
Snippet: runner:\n labels:\n - docker:docker://-\n - default:docker://node:22-bookworm\n - ubuntu-latest:docker://node:22-bookworm
Suggested home: memory
[FACT] Forgejo runner builds images via a privileged DinD sidecar (buildx works today)
Type: FACT
Verification: [VERIFIED] (read scaledjob.yaml, configmap.yaml, homelab ADR-0008)
What: Each ephemeral forgejo-runner pod (KEDA ScaledJob, code.forgejo.org/forgejo/runner:12.10.2, on nodegroup fringe) runs a privileged docker:dind native sidecar; the runner has DOCKER_HOST=tcp://localhost:2376. So docker/setup-buildx-action + docker/build-push-action multi-arch works as-is. homelab ADR-0008 (Proposed) plans to replace privileged DinD with rootless BuildKit/Kaniko later, explicitly sequenced after the runner is first proven on a real job — at which point build invocations change.
Why it matters: Confirms the existing buildx-based composite works now; flags a future migration that will change how images are built.
Snippet: DOCKER_HOST=tcp://localhost:2376
Suggested home: doc
[REFERENCE] In-cluster Harbor: endpoints, project, robot, secret location
Type: REFERENCE
Verification: [VERIFIED] (read webgrip/homelab-cluster/docs/techdocs/docs/runbooks/harbor.md)
What: Harbor OCI registry at harbor.webgrip.dev, LAN-only (HTTPRoute on envoy-internal 10.0.0.27, split-DNS via OPNsense, valid TLS at the gateway — no --insecure). Private project webgrip; push robot robot$webgrip+ci; robot token in OpenBao secret/harbor/robot-webgrip key CI_TOKEN. Pull-through proxy-cache projects exist: dockerhub → docker.io, ghcr → ghcr.io (e.g. harbor.<domain>/dockerhub/library/<repo>:<tag>). The build-and-push CI lives in webgrip/workflows, not the cluster repo. Harbor project + robot were "not yet provisioned" as of this thread.
Why it matters: Only an in-cluster runner can reach Harbor; GitHub-hosted runners cannot. These are the exact coordinates for wiring the push + imagePullSecrets.
Snippet: docker login harbor.${SECRET_DOMAIN} -u 'robot$webgrip+ci' -p "$HARBOR_ROBOT_TOKEN"
Suggested home: doc
[GOTCHA] The Harbor robot username contains a literal $ — pass it as a YAML value, not in a double-quoted shell string
Type: GOTCHA
Verification: [ASSERTED] (reasoning; not run live)
What: robot$webgrip+ci contains a literal $. In bash, docker login -u "robot$webgrip+ci" (double quotes) expands $webgrip → empty, producing robot+ci (wrong). Correct shell form is single quotes 'robot$webgrip+ci'. Cleaner: pass it through a secret → env → docker/login-action's with: username: (a YAML value, never shell-evaluated), which also masks the token and avoids putting it on a command line.
Why it matters: A copy-pasted docker login snippet silently authenticates as the wrong user.
Snippet: with:\n username: ${{ env.REGISTRY_USERNAME }} # = secret robot$webgrip+ci, safe
Suggested home: doc
[GOTCHA] docker push cannot publish a multi-arch buildx image
Type: GOTCHA
Verification: [ASSERTED] (reasoning)
What: A multi-platform docker buildx/build-push-action build with --push goes straight to the registry and leaves no local image, so a follow-up docker push harbor.../<img>:<tag> won't work. Dual-publish to multiple registries is done by giving both registry-qualified tags to one build-push-action tags: list with logins to each registry — not by a second docker push.
Why it matters: The "add a docker login + docker push step" approach in the original Harbor brief is broken for the existing multi-arch builds.
Snippet: none
Suggested home: doc
[DECISION] Two-tree layout: frozen .github/ + adapted .forgejo/ (Option C)
Type: DECISION
Verification: [VERIFIED] (implemented; recorded in docs/adrs/0002-forgejo-actions-parity.md)
What: Keep .github/workflows + .github/composite-actions byte-for-byte frozen (GitHub consumers unchanged) and add a parallel .forgejo/ full mirror carrying all Forgejo adaptations. GitHub consumers reference webgrip/workflows/.github/workflows/<x>.yml@main; Forgejo consumers reference …/.forgejo/workflows/<x>.yml@main. Inside .forgejo/, all self-references are rewritten .github→.forgejo. Rejected: Option A (one dual-purpose tree — impossible, e.g. checkout v6 vs v5) and Option B (move to .forgejo, flag-day breaks every GitHub consumer's uses:).
Why it matters: Lets both ecosystems run independently during migration without one breaking the other; consumer uses: strings never churn.
Snippet: .github/workflows/ (frozen) | .forgejo/workflows/ (adapted)
Suggested home: doc
[PROCEDURE] Tiered port of a GitHub workflow to .forgejo/
Type: PROCEDURE
Verification: [VERIFIED] (used to port all 51 workflows + 6 composites)
What: Classify each workflow: T1 mechanical (copy + rewrite webgrip/workflows/.github/→.forgejo/ self-refs) — done by scripts/generate-forgejo-workflows.sh; T2 action swap/pin (checkout v6→v5, setup-node v6→v4, cache v5→v4; ghcr→configurable registry); T3 reimplementation (replace actions/github-script octokit/gh CLI with Forgejo REST curl; actions/ai-inference GitHub Models → direct OpenAI; softprops/action-gh-release → Forgejo Releases API; peaceiris/actions-gh-pages → branch-push). Composites are copied/adapted by hand (the generator only handles workflows). actions/github-script steps that use only core.summary can be kept (forgejo-runner provides the summary API); only steps calling github.rest.*/github.graphql must be rewritten.
Why it matters: Repeatable recipe for the remaining/maintenance porting work; separates the scriptable 80% from hand-owned T3.
Snippet: sed 's#webgrip/workflows/\.github/#webgrip/workflows/.forgejo/#g'
Suggested home: new-skill
[REFERENCE] Parity-check + generator scripts (paths, behavior, forbidden patterns)
Type: REFERENCE
Verification: [VERIFIED] (ran both; STRICT parity green at 51/51)
What: scripts/forgejo-parity-check.sh enforces: (1) no orphan .forgejo workflow lacking a .github sibling — except those in its FORGEJO_ONLY allowlist (e.g. docker-build-and-push-harbor.yml, which has no GitHub equivalent because Harbor is unreachable from GitHub runners); (2) no forbidden constructs in .forgejo/: actions/checkout@v6, create-github-app-token, @semantic-release/github, bare ghcr.io; (3) coverage report, fatal under STRICT=1 or a .forgejo/.parity-complete marker. scripts/generate-forgejo-workflows.sh idempotently regenerates mechanical T1 copies, skipping a hand-owned MANUAL[] list, and refuses to emit a generated file containing a forbidden construct.
Why it matters: CI guardrail that keeps the two trees in sync and blocks GitHub-only constructs from leaking into .forgejo/.
Snippet: STRICT=1 scripts/forgejo-parity-check.sh · git diff --quiet -- .github/
Suggested home: existing-skill
[DECISION] Registry engine + thin per-registry wrappers (current state)
Type: DECISION
Verification: [ASSERTED] (engine/wrapper refactor applied post-implementation by user/linter; not re-run by me)
What: One generic engine — docker-build-push-registry composite, wrapped by docker-build-and-push-registry.yml reusable workflow — holds all build/login/push logic (docker/login-action to a configurable registry, multi-arch buildx, registry-host tag normalization OWNER/IMAGE:TAG→<registry>/OWNER/IMAGE:TAG, <registry>/<repo>:cache). Thin per-registry workflows just uses: the engine and map secrets: docker-build-and-push-harbor.yml (registry default harbor.webgrip.dev, maps HARBOR_ROBOT_USER/TOKEN→REGISTRY_USERNAME/TOKEN, runs-on: docker) and docker-build-and-push-ghcr.yml (registry ghcr.io). docker-build-and-push.yml → Docker Hub remains a separate engine.
Why it matters: DRY — one place for build logic; per-registry files stay small and intent-explicit; consumers' public interface is unchanged.
Snippet: uses: webgrip/workflows/.forgejo/workflows/docker-build-and-push-registry.yml@main
Suggested home: doc
[DECISION] Auth model: Forgejo CI bot token replaces GitHub App tokens
Type: DECISION
Verification: [ASSERTED] (designed/implemented; not run against a live Forgejo)
What: actions/create-github-app-token has no Forgejo analog. Use a dedicated Forgejo CI bot user with a repo/org-scoped secret FORGEJO_TOKEN; instance base URL via ${{ vars.FORGEJO_INSTANCE_URL }}. The Forgejo API is Gitea-compatible REST at ${FORGEJO_INSTANCE_URL}/api/v1 with header Authorization: token <FORGEJO_TOKEN}; call it with curl (octokit pointed at GitHub.com will not work). GITHUB_TOKEN and GITHUB_* env/contexts are still injected by forgejo-runner but are repo-scoped only. Bot git remote: https://<bot>:${FORGEJO_TOKEN}@<forgejo-host>/<owner>/<repo>.git.
Why it matters: Every release/repo-management/issue/registry workflow that minted App tokens or used octokit must switch to this model.
Snippet: curl -H "Authorization: token ${FORGEJO_TOKEN}" ${FORGEJO_INSTANCE_URL}/api/v1/...
Suggested home: doc
[REFERENCE] semantic-release on Forgejo
Type: REFERENCE
Verification: [ASSERTED]
What: Replace @semantic-release/github with @saithodev/semantic-release-gitea, set env GITEA_URL=${{ vars.FORGEJO_INSTANCE_URL }} and GITEA_TOKEN=<FORGEJO_TOKEN>. Keep @semantic-release/{changelog,commit-analyzer,release-notes-generator,git,exec} and semantic-release-helm3 / semantic-release-cargo. Drop semantic-release-github-actions-tags (GitHub-Actions-specific, no analog) and id-token: write (npm OIDC) unless actually needed. Consumer .releaserc files that name @semantic-release/github must be updated downstream.
Why it matters: The GitHub release plugin talks to the GitHub API and silently no-ops/fails against Forgejo.
Snippet: GITEA_URL: ${{ vars.FORGEJO_INSTANCE_URL }} / GITEA_TOKEN: ${{ inputs.token }}
Suggested home: doc
[REFERENCE] Forgejo Releases / Issues REST shapes used to replace GitHub actions
Type: REFERENCE
Verification: [ASSERTED]
What: Issues: POST ${FORGEJO_INSTANCE_URL}/api/v1/repos/{owner}/{repo}/issues {"title","body"}; find via GET …/issues?state=all&type=issues; update via PATCH …/issues/{number}. Releases (replacing softprops/action-gh-release): GET …/releases/tags/{tag} (reuse) then POST …/releases, then asset upload POST …/releases/{id}/assets?name=<file> multipart -F "attachment=@<file>". Template repos: POST …/repos/{template_owner}/{template_repo}/generate; topics: PUT …/repos/{owner}/{repo}/topics with {"topics":[...]} (Gitea uses topics, not GitHub's names).
Why it matters: Concrete endpoints for the T3 rewrites; the topics-field name difference is an easy mistranslation from GitHub.
Snippet: POST .../releases/{id}/assets?name=<file> (-F "attachment=@<file>")
Suggested home: doc
[FACT] No native Forgejo Pages; GitHub Advanced Security / Models have no analog
Type: FACT
Verification: [ASSERTED]
What: peaceiris/actions-gh-pages → reimplement as a branch-push of the built site; serving the site needs external infra (Nginx/Caddy/Forgejo Pages add-on) and is out of scope for the library. GitHub Advanced Security / secret-scanning / push-protection / Copilot repo-variable settings, and GitHub Models (actions/ai-inference, replaced by direct OpenAI via existing OPENAI_API_KEY/OPENAI_ORG_ID) have no Forgejo analog and were dropped with # Forgejo: dropped <X> (no analog) comments.
Why it matters: Sets expectations on what cannot be ported and must be dropped or handed to platform infra.
Snippet: none
Suggested home: doc
[REFERENCE] Local tooling availability for validating Forgejo workflows
Type: REFERENCE
Verification: [VERIFIED] (checked in this environment)
What: actionlint, yamllint, and PyYAML are NOT installed locally — YAML was validated structurally + via the parity-check greps; actionlint belongs in CI. Higher-fidelity local validation is forgejo-runner exec (better than act for backend fidelity). Companion repos are checked out as siblings under /home/ryan/projects/webgrip/ (homelab-cluster, infrastructure, etc.), which is where runner/Harbor/consumer facts were found.
Why it matters: Don't assume a YAML linter exists; know where the authoritative runner/registry config lives.
Snippet: find .github/workflows -name '*.yml' ; sibling path /home/ryan/projects/webgrip/homelab-cluster
Suggested home: memory
[PREFERENCE] Add new separate workflows rather than repurposing existing ones
Type: PREFERENCE
Verification: [VERIFIED] (explicit user redirect mid-thread)
What: When adding CI capability for a new target (e.g. a new registry), add a new, separate workflow and keep the existing one untouched — do not repurpose/modify an existing workflow to point at the new target. Concretely: the user rejected "change docker-build-and-push-ghcr.yml to push to Harbor" and required a dedicated docker-build-and-push-harbor.yml with the ghcr/Docker Hub workflows left intact (so consumers dual-publish by calling both).
Why it matters: Keeps working paths stable during migration; makes intent explicit per destination.
Snippet: none
Suggested home: memory
[REFERENCE] Repo scale & key artifact paths
Type: REFERENCE
Verification: [VERIFIED]
What: webgrip/workflows = 51 reusable workflow_call workflows + 6 composite actions, multi-language (PHP/Node/Go/Python/Java/Rust/.NET) + Docker/Helm/semantic-release/TechDocs/WordPress/repo-management. Key new artifacts: docs/adrs/0002-forgejo-actions-parity.md, scripts/forgejo-parity-check.sh, scripts/generate-forgejo-workflows.sh, .forgejo/ tree. EditorConfig: LF, final newline, 4-space indent (2 for YAML/JSON/MD), 150-char max.
Why it matters: Orients future work on the repo's shape and where decisions/tooling live.
Snippet: docs/adrs/0002-forgejo-actions-parity.md
Suggested home: CLAUDE.md
Open questions / unfinished
Systemic runner-label retarget [OPEN]: ~48 .forgejo jobs still use arc-runner-set/[homelab, heavy], which the Forgejo runner (docker/default/ubuntu-latest) won't schedule; they need retargeting to docker and ADR-0002 corrected. (Several files were already changed to runs-on: docker post-thread.)
End-to-end Harbor acceptance [OPEN]: requires Harbor webgrip project + robot$webgrip+ci provisioned, the HARBOR_ROBOT_USER/HARBOR_ROBOT_TOKEN Forgejo secrets synced from OpenBao, and a consumer job in webgrip/infrastructure — none confirmed run.
webgrip/workflows must be public on Forgejo [OPEN]: hard prerequisite for cross-repo workflow_call; not confirmed.
DEFAULT_ACTIONS_URL policy [OPEN]: whether the instance points at github.com vs mirrors vs vendored actions — unconfirmed (affects every bare uses:).
determine-changed-directories.yml [OPEN]: still uses tj-actions/changed-files@v45 (works via resolver); plan suggested a git diff reimplementation.
ghcr push from Forgejo [OPEN]: needs a ghcr PAT secret on Forgejo (no auto GITHUB_TOKEN-for-ghcr); current dual-publish keeps ghcr via the GitHub tree instead.
Many T3 agent-ported files carry [ASSERTED] assumptions (Forgejo API field names, OpenID/OpenAI request shapes, bot email/login, FORGEJO_INSTANCE_URL format https://host no trailing slash) — validated only structurally, not against a live instance.
Explicit preferences/feedback I gave
Add a new, separate workflow for a new target (Harbor); do NOT repurpose/modify the existing ghcr workflow. Keep existing workflows untouched so consumers can dual-publish during migration.
(Earlier, foundational) Use a two-tree layout: keep .github/ working for repos that stay on GitHub, and put Forgejo-adapted copies under .forgejo/ so the two run independently.
