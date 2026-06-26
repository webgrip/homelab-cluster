Thread Digest: Forgejo Actions → Harbor CI, cosign/OpenBao signing, runner topology, and TechDocs restructure (webgrip homelab)
One-line summary: Built/hardened the in-cluster Forgejo Actions pipeline (Harbor publish, cosign-via-OpenBao signing, runner host-mode), debugged several Forgejo-specific footguns, then set up Codeberg Pages docs hosting and restructured TechDocs into a per-repo taxonomy with zero dead links.
Approx date / status: 2026-06-17 → 2026-06-18 — done (committed/pushed to main in webgrip/homelab-cluster, webgrip/infrastructure, webgrip/workflows).

Items
[FACT] Forgejo Actions workflow-directory precedence is first-existing-dir-wins (not merged)
Type: FACT
Verification: [VERIFIED] (Forgejo source modules/actions/workflows.go + docs)
What: Forgejo's ListWorkflows checks, in order, .forgejo/workflows → .gitea/workflows → .github/workflows, and uses only the first directory that exists — it is NOT additive. The trigger is the directory's existence, even if empty ("a valid source… no matter whether it contains workflows or not"). So once .forgejo/workflows/ exists on a branch/commit, Forgejo completely ignores .github/. GitHub only ever reads .github/. The .github fallback exists purely so un-migrated mirrored repos "just work." Resolution is per-commit/per-branch. There is no admin toggle to disable the .github fallback yet (open: forgejo#9203).
Why it matters: Prevents the fear that Forgejo double-runs .github + .forgejo (e.g. accidentally pushing to ghcr from the in-cluster runner). Adding an empty .forgejo/workflows/.gitkeep is a valid lever to stop Forgejo running a repo's .github workflows without porting them.
Snippet: https://code.forgejo.org/forgejo/forgejo/src/branch/forgejo/modules/actions/workflows.go
Suggested home: doc
[GOTCHA] Forgejo v15 reusable-workflow expansion breaks when caller job id == an inner job id
Type: GOTCHA
Verification: [VERIFIED] (error reproduced + collision confirmed in files; fix is [ASSERTED] — not re-run live yet)
What: Forgejo 15.0.0+ expands reusable-workflow (uses:) calls into their inner jobs (PR forgejo#10525, merged into the v15.0.0 milestone 2025-12-24). If a calling job's id is identical to a job id inside the reusable workflow it calls, the flattened graph ends up with no dependency-free job and Forgejo rejects the workflow at detection time with "the workflow must contain at least one job without dependencies." Example that broke: caller job determine-changed-directories calling determine-changed-directories.yml whose inner job was also determine-changed-directories. Fix: rename the caller job (renamed to changed-images). GitHub never hits this because it namespaces inner jobs under the caller.
Why it matters: The error message points at needs:/cycles and sends you down the wrong path; the real cause is a name collision under Forgejo's young expansion feature. Correction of an in-thread wrong hypothesis: the "Forgejo lacks reusable-workflow expansion" theory was FALSE — expansion shipped in 15.0.0, so the running 15.0.2 has it.
Snippet: https://codeberg.org/forgejo/forgejo/pulls/10525 ; invariant: a caller uses: job id must differ from every inner job id of the workflow it calls.
Suggested home: doc
[GOTCHA] forgejo-runner agent_labels are fixed at registration; config.yaml label edits do NOT propagate
Type: GOTCHA
Verification: [VERIFIED] (queried the live Forgejo Postgres)
What: A runner started with forgejo-runner one-job --uuid … --token-url … advertises only the labels stored server-side in action_runner.agent_labels, set when the runner was registered. Adding labels to the runner config.yaml does not update the server. The live DB showed agent_labels=["docker"] and an empty version (meaning the runner had never actually run a job). Forgejo's UI warning "no matching online runner with label X" is a static check against agent_labels, not a scheduling-time check. one-job does support --label name:backend (repeatable) and --handle (Forgejo ≥15).
Why it matters: Explains why a config-declared label silently never works, and why the "no matching runner" warning appears even though KEDA would spin a pod. Query to check:
Snippet:

kubectl -n forgejo exec forgejo-db-1 -c postgres -- env PGPASSWORD="$(kubectl -n forgejo get secret forgejo-db-app -o jsonpath='{.data.password}' | base64 -d)" psql -h 127.0.0.1 -U forgejo -d forgejo -tAc "select id, name, version, agent_labels from action_runner order by id;"
Suggested home: doc
[DECISION] Runner advertises ONE honest label docker; no GitHub-ARC/ubuntu-latest masks
Type: DECISION
Verification: [VERIFIED] (config + all .forgejo workflows swept; user-driven)
What: The in-cluster runner is a single ephemeral KEDA DinD pool. It advertises only docker (truthful), not arc-runner-set, ubuntu-latest, or default (those were GitHub-ARC/compat masks that were never even declared server-side). All .forgejo/workflows in webgrip/workflows (41 files) and webgrip/infrastructure were swept from arc-runner-set/[homelab, heavy] → docker. The .github tree was left on arc-runner-set (it runs on real GitHub ARC).
Why it matters: User preference: "the labels should be TRUE, and not masking something else." A label that maps to a different runtime is a lie that costs debugging time.
Snippet: none
Suggested home: doc
[FACT] ghcr.io/webgrip/github-runner image contents (and what it lacks)
Type: FACT
Verification: [VERIFIED] (ran a throwaway pod and probed command -v)
What: Built FROM ghcr.io/actions/actions-runner + PHP/.NET tooling. Has: docker, dockerd, the buildx plugin, git, jq, gh, php, dotnet, composer; runs as non-root runner (uid 1001). Lacks: node on PATH (the actions-runner base bundles it under externals/), cosign, syft, forgejo-runner. (Corrects an in-thread assumption that the image had no docker CLI — it does.)
Why it matters: Determines what works in host-mode: docker build/buildx work; JS-action node resolution and cosign/syft are open questions / installed by the action.
Snippet:

kubectl -n forgejo run ghr-bins --image=ghcr.io/webgrip/github-runner@sha256:<digest> --restart=Never --command -- bash -lc 'for b in docker buildx node git cosign syft; do echo "$b: $(command -v $b || echo MISSING)"; done; echo "uid=$(id -u)"'
Suggested home: doc
[PROCEDURE] Runner host-mode: run the agent inside the toolchain image, inject the binary via init container
Type: PROCEDURE
Verification: [VERIFIED] (manifests render via kubectl kustomize; not yet proven on a live job)
What: To make docker build "just work," run the workflow steps in the same container as the agent so it shares the pod network namespace with the privileged dind sidecar (DOCKER_HOST=tcp://localhost:2376 then resolves). Because the toolchain image (github-runner) lacks forgejo-runner, an init container copies the static binary out of the pinned code.forgejo.org/forgejo/runner:12.10.2 image into a shared emptyDir, and the main container execs it. Config label becomes docker:host (host execution). Container-job mode (docker://image) is avoided because the spawned job container is NOT in the pod netns, so localhost:2376 doesn't reach the daemon.
Why it matters: Resolves the whole localhost:2376 reachability class of bugs; documented in kubernetes/apps/forgejo/forgejo-runner/app/scaledjob.yaml.
Snippet:

initContainers:
  - name: runner-bin
    image: code.forgejo.org/forgejo/runner:12.10.2@sha256:379b324d6942824b7487706c0a06be4d63e546c17b62bece4ae18c74364a8fae
    command: [sh, -ec]
    args: ['cp "$(command -v forgejo-runner)" /dist/forgejo-runner; chmod 0755 /dist/forgejo-runner']
    volumeMounts: [{name: runner-bin, mountPath: /dist}]
# main container: image ghcr.io/webgrip/github-runner@sha256:…  ;  exec /dist/forgejo-runner --config /config/config.yaml one-job …
# config.yaml runner.labels: [ "docker:host" ]
Suggested home: doc
[DECISION] CI build-engine topology roadmap: prove on privileged DinD now → shared rootless BuildKit later
Type: DECISION
Verification: [VERIFIED] (written into ADR-0008, committed)
What: Separate three roles — agent (orchestrates), toolchain/job (node/git/buildx/cosign/syft + the secrets + checkout), build engine (dockerd→buildkitd). Invariant: privilege and secrets never share a container. Sequence: (A) privileged DinD sidecar host-mode to prove the runner on a real job, then (C) a long-lived rootless buildkitd reached as a Service with a Harbor registry cache, dropping privileged. Topology B (rootless sidecar per-pod) is rejected as a destination (rootless tax + cold cache). ARC "Kubernetes mode" is a non-starter — it has no container runtime and cannot build OCI images.
Why it matters: Ephemeral runners lose BuildKit cache every job; a shared builder + registry cache fixes that and removes the only privileged container. Aligns with ADR-0008 "rootless CI image builds."
Snippet: homelab-cluster/docs/techdocs/docs/adr/adr-0008-rootless-ci-image-builds.md
Suggested home: doc
[GOTCHA] Forgejo rejects org Actions secret/variable names with reserved prefixes
Type: GOTCHA
Verification: [ASSERTED] (documented as observed PUT 400 in the repo's provisioner comments)
What: Forgejo's org Actions API rejects secret/variable names beginning with FORGEJO_, GITHUB_, or GITEA_ (secret PUT → 400, var POST/PUT → 400/404). So the in-cluster forgejo-actions-secrets CronJob publishes the CI bot token as WEBGRIP_CI_TOKEN and the instance URL as WEBGRIP_FORGEJO_URL. CODEBERG_TOKEN, HARBOR_ROBOT_USER/TOKEN, DT_API_KEY are fine (no reserved prefix). Note: secrets.FORGEJO_TOKEN inside a workflow is the built-in per-job token, distinct from the org bot token.
Why it matters: Naming a provisioned secret FORGEJO_* silently fails to publish; prefix with the org name instead.
Snippet: path kubernetes/apps/forgejo/forgejo-actions-secrets/app/forgejo-actions-secrets.cronjob.yaml
Suggested home: doc
[FACT] cosign signing via OpenBao Transit, authorized by Forgejo Actions OIDC
Type: FACT
Verification: [ASSERTED] (architecture committed; not yet run end-to-end — gated on a one-time OpenBao break-glass)
What: Harbor images are signed keyed, not keyless: cosign sign --key hashivault://cosign-webgrip calls OpenBao's Transit engine (cosign-webgrip, ECDSA-P256); the private key never leaves OpenBao. Authorization is per-job: the release job sets enable-openid-connect: true, Forgejo mints an OIDC token (issuer https://forgejo.webgrip.dev/api/actions), and OpenBao's JWT auth (auth/forgejo, role cosign-signer) only exchanges it for a sign-only Transit token when bound_claims match {repository: webgrip/infrastructure, event_name: release, ref: refs/tags/*}. Forgejo Actions OIDC is disabled for fork PRs, so a fork can't mint a signer token. The public key is published to a cosign-webgrip-pub ConfigMap by a CronJob (no hand-pasted PEM); Kyverno image-verify-harbor-audit verifies against it (Audit, failurePolicy: Ignore).
Why it matters: Keyless/Fulcio won't trust a private Authentik; this is the keyed equivalent with per-workflow identity. Requires a one-time generate-root break-glass to enable Transit + the forgejo jwt auth on the already-initialized cluster.
Snippet: cosign sign --key hashivault://cosign-webgrip
Suggested home: doc
[FACT] Garage supports S3 static-website hosting (unlike Minio/Ceph)
Type: REFERENCE
Verification: [ASSERTED] (Garage docs; not stood up in this cluster)
What: Garage can serve a bucket as a static website via its s3_web endpoint (default port 3902), mapping domain names → bucket names, with the index file set per-bucket via PutBucketWebsite. This is an option for serving a built mkdocs/techdocs site sovereignly behind Envoy + cert-manager.
Why it matters: Garage is already the cluster's blob store (LFS, packages, registry blobs at 10.0.0.110:3900); reusing it for docs avoids new infra.
Snippet: https://garagehq.deuxfleurs.fr/documentation/cookbook/exposing-websites/
Suggested home: doc
[FACT] Codeberg Pages: .domains file, pages branch, must push to a NON-mirror repo
Type: REFERENCE
Verification: [ASSERTED] (Codeberg docs/research)
What: Codeberg Pages serves a repo's pages branch at <owner>.codeberg.page/<repo>; custom domains come from a .domains file in that branch + a DNS CNAME <domain> -> <owner>.codeberg.page (auto Let's Encrypt). You cannot push to a pull-mirror's pages branch — publish to a dedicated non-mirror repo. Self-hostable equivalents exist: Codeberg pages-server (maintenance), git-pages (successor), forgejo-pages. The webgrip implementation force-pushes an orphan snapshot of the techdocs-site artifact.
Why it matters: Off-site DR for docs (survives cluster loss), public-only; chosen as the interim host before Backstage TechDocs (ADR-0022 vs ADR-0023).
Snippet: https://codeberg.org/Codeberg/pages-server
Suggested home: doc
[PROCEDURE] Path-aware markdown link rewriter for mkdocs doc moves (with overshoot-strip + dead-link neutralize)
Type: PROCEDURE
Verification: [VERIFIED] (own resolver reported 0 broken in both repos; mkdocs --strict not run — see OPEN)
What: When moving mkdocs docs into a new folder taxonomy, links must be rewritten file-relative (the mkdocs convention, even with use_directory_urls: true — mkdocs transforms .md links itself). The reusable approach: (1) build a move_map (old→new docs-relative); (2) for each link, resolve against the source file's current dir, strip author-overshoot ../ until it lands in-repo (this also fixes pre-existing ../../blog/ bugs), remap via move_map, and recompute relpath from the new dir; (3) repo-source links (../../kubernetes/…) get their ../ depth corrected against the repo root; (4) any link whose target genuinely doesn't exist is neutralized ([text](dead) → text, keeping the path visible) so there are zero dead links; (5) verify with a strict resolver that every link resolves. Use git mv/mv+git add -A so renames are detected (history preserved).
Why it matters: 95+ cross-dir links broke on the homelab move; a naive sed would corrupt them. Saved scripts: /tmp/restructure_docs.py, /tmp/fix_links.py, /tmp/neutralize.py (ephemeral — candidate for a committed tool/skill).
Snippet: verify command pattern: python3 fix_links.py <repo> → prints links: ok=N fixed=N ext=N broken=N.
Suggested home: new-skill
[GOTCHA] techdocs-core image lacks mkdocs-redirects/awesome-pages; enabling the plugin before rebuilding the image breaks the build
Type: GOTCHA
Verification: [ASSERTED] (plugin set confirmed; failing build not exercised)
What: The TechDocs build image installs mkdocs-techdocs-core==1.5.3 (+ mermaid2, macros, dracula) but not mkdocs-redirects or mkdocs-awesome-pages-plugin. Declaring plugins: [- redirects] in mkdocs.yml while the deployed image lacks the package fails the build with unknown plugin "redirects". Correct order: add the pin to the image Dockerfile, rebuild+publish, then enable the plugin in mkdocs.yml. The webgrip pin added: mkdocs-redirects==1.2.2 in infrastructure/ops/docker/techdocs-builder/Dockerfile. (Because of this, nav was kept as an explicit regenerated block rather than switching to awesome-pages.)
Why it matters: A hard ordering dependency now live on main — the next docs build fails until the techdocs-builder image is rebuilt.
Snippet: mkdocs-redirects maps redirect_maps: {'old/path.md': 'new/path.md'}; redirects only matter once the site is published (no value before first publish).
Suggested home: doc
[GOTCHA] git add -A then committing sweeps pre-staged files into an unrelated commit
Type: GOTCHA
Verification: [VERIFIED] (happened; fixed with git reset --soft HEAD~2 && git reset)
What: If files were previously staged (e.g. an earlier git add -A docs/techdocs), a later git add <subset> + git commit includes ALL staged files, not just the subset — producing a commit whose contents don't match its message. Fix before pushing: git reset --soft HEAD~N (undo commits, keep changes) → git reset (unstage all) → stage per-commit explicitly.
Why it matters: Mislabels history; always git reset to unstage before selective staging when prior add -A may have run.
Snippet: git reset --soft HEAD~2 && git reset -q
Suggested home: CLAUDE.md
[FACT] Running versions / coordinates (this cluster)
Type: REFERENCE
Verification: [VERIFIED] (queried)
What: Forgejo server 15.0.2+gitea-1.22.0 (OIDC needs ≥ v15). forgejo-runner image code.forgejo.org/forgejo/runner:12.10.2. dind sidecar docker:29.5.3-dind. KEDA ScaledJob runner pinned to nodegroup: fringe, minReplicaCount: 0, maxReplicaCount: 6, automountServiceAccountToken: false. Forgejo internal URL http://forgejo-http.forgejo.svc.cluster.local:3000; public https://forgejo.webgrip.dev. Harbor harbor.webgrip.dev (LAN-only, private project webgrip, robot robot$webgrip+ci). Garage S3 10.0.0.110:3900.
Why it matters: Version-gated features (OIDC, reusable-workflow expansion) and exact endpoints for future work.
Snippet: kubectl -n forgejo exec deploy/forgejo -c forgejo -- forgejo --version ; curl -s https://forgejo.webgrip.dev/api/v1/version
Suggested home: doc
[FACT] The in-cluster runner is forgejo-runner, NOT act_runner
Type: FACT
Verification: [VERIFIED] (user correction, repeated emphatically)
What: The cluster's Forgejo CI runner is forgejo-runner (Forgejo's fork). act_runner is a GitHub/act concept; do not reason about behavior from act_runner/act docs. The proven-working label was docker (later made the only label).
Why it matters: Reasoning from act_runner semantics led to wrong conclusions; the user corrected this three times.
Snippet: none
Suggested home: CLAUDE.md
[DECISION] Two-tree .github/.forgejo parity, enforced by a forbidden-literal check
Type: DECISION
Verification: [VERIFIED] (parity script exists; sweeps done)
What: webgrip/workflows and webgrip/infrastructure maintain mirrored .github/ (GitHub/ghcr) and .forgejo/ (in-cluster/Harbor) trees. A parity check (webgrip/workflows/scripts/forgejo-parity-check.sh, ADR docs/adrs/0002-forgejo-actions-parity.md) fails if anything under a .forgejo/ tree mentions ghcr.io, actions/checkout@v6, create-github-app-token, or @semantic-release/github (comments included). .forgejo uses @saithodev/semantic-release-gitea + .releaserc.forgejo.js; actions/checkout@v5 (not v6).
Why it matters: Keeps the Forgejo tree free of GitHub-isms; "depending on GitHub to run the CI that frees you from GitHub" is caught by a linter.
Snippet: webgrip/workflows/scripts/forgejo-parity-check.sh
Suggested home: doc
[DECISION] Docs taxonomy per repo; nest don't flatten; keep filename prefixes
Type: DECISION
Verification: [VERIFIED] (applied + committed)
What: Target layout under docs/techdocs/docs/: adr/ rfc/ blogs/ incidents/ runbooks/ general/ + root index.md. Routing rule: decision→adr/, proposal/design/plan/roadmap→rfc/, dated narrative→blogs/, postmortem→incidents/, how-to-operate→runbooks/, else→general/. Keep adr-/rfc- filename prefixes (folder + prefix). For a repo that already has a coherent topical IA (infra: overview/ cicd/ docker-images/ security/ operations/ testing/), nest those under general/ (general/overview/…) and only migrate adrs/→adr/ — preserve the existing nav structure, don't flatten it.
Why it matters: The taxonomy fits decision-record-heavy repos (homelab); product-docs repos should be nested, not bulldozed. User: "don't bulldoze good IA."
Snippet: none
Suggested home: doc
[PREFERENCE] GitOps-first, statelessly rebuildable, minimize manual commands
Type: PREFERENCE
Verification: [VERIFIED] (stated repeatedly)
What: "I want my cluster to be statelessly rebuildable" and "can we get around my having to actually run commands?" Prefer reconciled-from-git mechanisms (provisioner Jobs/CronJobs reading OpenBao, ExternalSecrets, publisher CronJobs) over manual steps. Acceptable exceptions: one-time OpenBao generate-root break-glass (root ops kept deliberate, not automated). Flag any remaining manual prerequisite explicitly as a handoff (e.g. create Codeberg repo, seed codeberg/pages token, set DNS CNAME).
Why it matters: Shapes every design toward GitOps reconciliation; surface the irreducible manual steps rather than hiding them.
Snippet: none
Suggested home: memory
[PREFERENCE] Working-style: honesty, no fabrication, surface contradictions, lightweight planning
Type: PREFERENCE
Verification: [VERIFIED] (multiple instances)
What: "Make SURE there are no dead links." Don't fabricate (neutralized dead links to deleted files rather than invent replacements; flagged 7 stale .sops/.template refs + 9 phantom example-ADRs as pre-existing content issues). When findings contradict the request's premise, surface it instead of proceeding (infra's topical IA didn't fit the taxonomy → raised it as a decision). Don't write a full RFC for a trivial/mechanical change — "just make a temporary claude plan" (a scratch plan, e.g. under ~/.claude/plans/). Keep adr-/rfc- prefixes. Commits unsigned via --no-gpg-sign (pinentry hangs non-interactively).
Why it matters: Calibrates verification honesty, planning weight, and when to ask vs act.
Snippet: commit footer (required): Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Suggested home: memory
[REFERENCE] Backstage TechDocs external-storage config (the in-cluster docs target)
Type: REFERENCE
Verification: [ASSERTED] (designed in ADR-0023, not implemented)
What: Backstage is already deployed (homelab-cluster/kubernetes/apps/backstage/). Plan: techdocs.builder: 'external' (serve prebuilt, never build on read) + techdocs.publisher.type: 'awsS3' pointed at a Garage techdocs bucket; CI runs techdocs-cli publish --publisher-type awsS3 --storage-name techdocs --entity <ns>/<kind>/<name>; each docs set needs a catalog entity with backstage.io/techdocs-ref: dir:docs/techdocs. Codeberg Pages stays as the off-site DR mirror.
Why it matters: The "correct" TechDocs home (search + catalog + Authentik SSO); sequenced after the Codeberg interim.
Snippet: homelab-cluster/docs/techdocs/docs/rfc/plan-backstage-techdocs.md
Suggested home: doc
Open questions / unfinished
mkdocs --strict not run locally (mkdocs isn't on the workstation); "0 dead links" was verified by a custom file-relative resolver, not mkdocs. [OPEN]
techdocs-builder image must be rebuilt+published with mkdocs-redirects==1.2.2 before the next docs build, or the build fails on the unknown redirects plugin (the plugin is already enabled in both mkdocs.yml on main). [OPEN]
Codeberg Pages deploy not live — needs one-time manual: create a non-mirror Codeberg repo, seed a PAT (write:repository) at OpenBao codeberg/pages key token, set DNS docs.webgrip.dev CNAME webgrip.codeberg.page. [OPEN]
Runner never proven on a real job (version empty in DB); host-mode + label declaration unverified end-to-end. Pending OpenBao break-glass (enable transit + auth/forgejo jwt + create cosign-webgrip key). [OPEN]
The job-name-collision rename fix was pushed but not confirmed to clear the Forgejo warning (docs not yet rebuilt/mirrored). [OPEN]
homelab-cluster has no on_docs_change.yml of its own, so its (richer) architecture docs/blog are not yet wired to any Forgejo docs-deploy — only webgrip/infrastructure's docs are. [OPEN]
Stale branch: webgrip/infrastructure origin feat/forgejo-harbor-ci is behind main (everything merged); deletable. [OPEN]
Pending reminder: flip Kyverno image-verify-harbor-audit from Audit→Enforce once supply-chain hygiene is steady (from prior memory). [OPEN]
Explicit preferences/feedback I gave
"This will not run on act runner. That's github only" — it's forgejo-runner, not act_runner (corrected 3×).
"The labels should be TRUE, and not masking something else. Change the workflows if you must."
"I would like this to all be as much gitops first as possible… I want my cluster to be statelessly rebuildable."
"Make SURE that there are no dead links. Feel free to restructure at your own discretion."
Infra docs: chose (b) nest topical dirs under general/ (don't flatten the existing IA).
"Don't drop the adr-/rfc- prefixes."
"Nah, don't rfc this change. Just make a temporary claude plan."
Keep diagrams + mention webgrip/infrastructure and webgrip/workflows in the forge-home blog; style "dev friendly and C-level."
Prefers OpenBao as the single machine secret/identity plane (Transit signing, JWT auth, and aspirationally OIDC provider + dynamic secrets).
