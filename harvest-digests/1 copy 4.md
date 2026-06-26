
Thread Digest: Migrating webgrip CI from GitHub Actions/GHCR to a Forgejo-led, Harbor-centric supply chain
One-line summary: Building and debugging an in-cluster Forgejo Actions pipeline that builds ops/docker/* images, publishes + signs to Harbor (and dual-publishes to GHCR), with cosign+OpenBao signing, Dependency-Track SBOMs, Kyverno verification, and storage hygiene — culminating in making Forgejo the sole release authority with GitHub as a pure mirror.

Approx date / status: 2026-06-23 → 2026-06-26 — in progress (final controlled release running; Kyverno Enforce intentionally deferred)

Items
[GOTCHA] Forgejo's job-parser rejects workflow_call: blocks that declare secrets:
Type: GOTCHA
Verification: [VERIFIED] (seen in forgejo server logs)
What: Forgejo's DetectWorkflows ignores any workflow whose on.workflow_call has a secrets: key, logging [W] ignore invalid workflow "X": invalid value on key "workflow_call": workflow_call only supports keys "inputs" and "outputs", but key "secrets" was found. This affects ~30 webgrip/workflows reusable workflows. It is benign at runtime — when those workflows are called via uses: they still execute correctly (proven by a successful Harbor build) — it only blocks standalone detection and clutters logs.
Why it matters: Prevents panic when you see dozens of "invalid workflow" warnings; they are not the cause of a missing run.
Snippet: none
Suggested home: memory
[GOTCHA] Forgejo composite/reusable resolution: internal refs need absolute URLs; data.forgejo.org is an incomplete mirror
Type: GOTCHA
Verification: [VERIFIED]
What: On the in-cluster Forgejo runner, job-level reusable-workflow uses: (webgrip/workflows/.forgejo/workflows/*.yml@main) and the top-level call resolve against the LOCAL instance (bare slug works; nested workflow_call is supported). But step-level composite-action uses: resolve against [actions] DEFAULT_ACTIONS_URL, which defaults to https://data.forgejo.org — an incomplete mirror that has actions/checkout + docker/* but 404s on actions/github-script, sigstore/cosign-installer, anchore/sbom-action, and all webgrip/*.
Why it matters: Internal composite actions 404 with remote: Not found unless pinned to an absolute URL.
Snippet: Internal: uses: https://forgejo.webgrip.dev/webgrip/workflows/.forgejo/composite-actions/<name>@main · External-missing: uses: https://github.com/actions/github-script@v8
Suggested home: memory
[DECISION] Pin missing external actions to github.com case-by-case, NOT a global DEFAULT_ACTIONS_URL flip
Type: DECISION
Verification: [VERIFIED]
What: When a Forgejo job 404s on data.forgejo.org/<action>, pin that single uses: to https://github.com/<owner>/<repo>[/subpath]@ref. Ryan explicitly chose this over setting [actions] DEFAULT_ACTIONS_URL: github server-wide, "so it's easily findable later" (greppable per use-site).
Why it matters: Keeps each external dependency explicit at its use site; avoids a global behavior change.
Snippet: none
Suggested home: memory
[GOTCHA] github.repository_owner and github.sha are EMPTY in Forgejo workflow_dispatch runs
Type: GOTCHA
Verification: [VERIFIED] (produced harbor.webgrip.dev//<image> double-slash → "invalid reference format")
What: In a Forgejo workflow_dispatch-triggered run, github.repository_owner and github.sha are empty. Hardcode webgrip for the Harbor owner/project instead. github.repository (e.g. webgrip/infrastructure) IS populated.
Why it matters: Empty owner yields invalid image tags and breaks builds; empty sha yields blank IMAGE_REVISION.
Snippet: docker-tags: | webgrip/${{ needs.parse-release-tag.outputs.image }}:${{ ...version }}
Suggested home: memory
[GOTCHA] semantic-release-monorepo's outputs.version is the FULL namespaced tag, not bare semver
Type: GOTCHA
Verification: [VERIFIED] (a prepend produced techdocs-builder-vtechdocs-builder-v1.2.14)
What: The exec successCmd echo "version=${nextRelease.version}" emits the tagFormat-prefixed value (e.g. techdocs-builder-v1.2.19), NOT a bare 1.2.19. Pass it to the dispatch verbatim — do not prepend <package-name>-v (that doubles the prefix). The per-image .releaserc.cjs sets tagFormat: '<image>-v${version}'.
Why it matters: A wrong "fix" (commit ca732f2) doubled the tag; the original passthrough was correct. The real original failure was the data.forgejo.org 404, misdiagnosed as a tag-format bug.
Snippet: TAG: ${{ steps.semantic-release.outputs.version }}
Suggested home: memory
[GOTCHA] Forgejo flattens nested reusable-workflow jobs and ignores the caller job's if:
Type: GOTCHA
Verification: [VERIFIED] (two concurrent Docker Build and Push (Registry) jobs ran)
What: Forgejo expands a reusable workflow's inner jobs into the caller's graph, and the caller job's if: does NOT gate those flattened inner jobs. Two mutually-exclusive if:-gated reusable-workflow calls (e.g. distribute vs distribute-prerelease) BOTH run their inner build — racing on the same registry tag + buildx :cache ref. Fix: use ONE call and push the conditional inside its inputs (e.g. gate the :latest tag inline so it resolves to '' on prereleases; the engine skips blank tags). Also: every workflow_call level shows as its own job (a thin uses: wrapper appears as a pass-through job next to the engine job — cosmetic, only the engine runs steps).
Why it matters: Caller-level if: gating silently fails to dedupe under flattening.
Snippet: ${{ needs.parse-release-tag.outputs.is_prerelease != 'true' && format('webgrip/{0}:latest', needs.parse-release-tag.outputs.image) || '' }}
Suggested home: memory
[GOTCHA] Forgejo cannot emit a release Actions event for a CI-created release — dispatch on_release_published explicitly
Type: GOTCHA
Verification: [VERIFIED]
What: A release created from inside a CI job does not fire a release Actions event (loop-prevention). The .forgejo semantic-release action must POST /api/v1/repos/${REPO}/actions/workflows/on_release_published.yml/dispatches after cutting a release. workflow_dispatch inputs must be explicitly typed (type: string) or Forgejo rejects the workflow.
Why it matters: Without the explicit dispatch, the build/sign workflow never runs.
Snippet: curl -fsS -X POST -H "Authorization: token ${GITEA_TOKEN}" "${GITEA_URL%/}/api/v1/repos/${REPO}/actions/workflows/on_release_published.yml/dispatches" -d "{\"ref\":\"${REF}\",\"inputs\":{\"tag\":\"${TAG}\",\"is_prerelease\":\"${IS_PRERELEASE}\"}}"
Suggested home: memory
[GOTCHA] Forgejo on_source_change occasionally misses scheduling a push; amending a commit does NOT re-trigger it
Type: GOTCHA
Verification: [VERIFIED]
What: A valid push (0d28a07) with matching paths: landed on Forgejo main but created no run — a transient detection miss (not parse/paths/concurrency; confirmed via /api/v1/repos/.../actions/tasks showing run numbers stop). To re-trigger you must change a file matching the paths: filter — git commit --amend + force-push does NOT trigger, because the tree is identical so the push diff is empty and no path matches. A subsequent real-change commit scheduled normally (run #33).
Why it matters: Don't waste time hunting a config bug for a one-off miss; re-trigger with a real file change, not an amend.
Snippet: none
Suggested home: memory
[FACT] OpenBao cosign-signer JWT role must bind the Forgejo workflow_dispatch shape, not GitHub's release/tag shape
Type: FACT
Verification: [VERIFIED] (signing succeeded after rebind: claims aud=openbao-cosign, event_name=workflow_dispatch, ref=refs/heads/main)
What: The auth/forgejo JWT role cosign-signer originally bound event_name=release + ref=refs/tags/* (GitHub shape) → OpenBao 400'd the login because the Forgejo flow triggers via workflow_dispatch on a branch. Rebound bound_claims to {"repository":"webgrip/infrastructure","event_name":"workflow_dispatch","ref":"refs/heads/*"}. The Forgejo OIDC token's request URL may lack a query string, so use ? vs & correctly when appending audience= (a malformed URL yields the default audience → 400).
Why it matters: Signing fails with a bare curl (22) 400 until the role matches the actual claims.
Snippet: File kubernetes/apps/security/openbao/bootstrap/config.sh; case "$ACTIONS_ID_TOKEN_REQUEST_URL" in *\?*) sep='&';; *) sep='?';; esac
Suggested home: memory
[DECISION] Disable public sigstore tlog upload (--tlog-upload=false) when signing with a static OpenBao key
Type: DECISION
Verification: [VERIFIED] (logs previously showed tlog entry created with index: …)
What: cosign defaults to uploading a transparency-log record to the public Rekor (rekor.sigstore.dev) even with --key hashivault://…. For private homelab images this leaks image digests+timestamps to a world-readable immutable log + adds an internet dependency. Add --tlog-upload=false to cosign sign and cosign attest. Safe because Kyverno verification is key-only (no rekor block → no tlog lookup).
Why it matters: Keeps signing fully in-cluster; the Kyverno policy already does key-based verification.
Snippet: cosign sign --yes --tlog-upload=false --key "hashivault://${TRANSIT_KEY}" "$IMAGE"
Suggested home: doc
[FACT] Kyverno verifies a static key (no rekor) by simply omitting the rekor block; keyless rules add rekor.url
Type: FACT
Verification: [VERIFIED] (Harbor policy has no rekor block and verifies; GHCR keyless policy explicitly sets rekor.url)
What: In Kyverno verifyImages, a keys.publicKeys attestor with no rekor block performs key-only verification (no transparency-log lookup). The presence of an explicit rekor: { url: https://rekor.sigstore.dev } is what opts into keyless/tlog checks. This is why disabling cosign tlog upload is safe for the key-based Harbor policy.
Why it matters: You don't need ctlog.ignoreTlog: true to skip tlog for static-key verification — just don't add rekor.
Snippet: attestors: [{count: 1, entries: [{keys: {publicKeys: '{{ cosignpub.data."cosign.pub" }}'}}]}]
Suggested home: doc
[DECISION] Harbor "Deployment security" (Cosign/Notation enforce + vuln-block) should stay OFF; Kyverno is the single gate
Type: DECISION
Verification: [ASSERTED]
What: Leave Harbor project Deployment-security off. Harbor's cosign check only verifies a signature exists (not against your key); it blocks pulls of unsigned artifacts including the buildx :cache tag (breaking cache-from). "Prevent vulnerable images" at LOW blocks essentially everything, and even at Critical can make a running image unpullable when a new CVE lands. Notation is redundant (standardized on cosign+OpenBao). Keep enforcement at Kyverno admission only.
Why it matters: Avoids operational fragility and cache breakage from registry-layer gates.
Snippet: none
Suggested home: doc
[DECISION] Architecture: "release once, publish many" — Forgejo is the sole release authority; GitHub is a pure mirror
Type: DECISION
Verification: [ASSERTED] (implemented; controlled release in flight)
What: Exactly one system decides a version (runs semantic-release, tags, writes changelog, bumps package.json). GitHub (which mirrors Forgejo) must run zero Actions — the entire .github/ tree was deleted. Forgejo's in-cluster runner fans out to BOTH Harbor (LAN) and GHCR (internet). GitHub Release objects are recreated via a best-effort step (not an inline plugin, so a GitHub/PAT hiccup can't abort the Forgejo release or block the Harbor build). Tags+commits mirror to GitHub as git data; Release objects do not, hence the mirror step.
Why it matters: Two CI systems on one repo cut divergent version sequences and fight over package.json commit-back; centralizing the version decision fixes it.
Snippet: none
Suggested home: new-skill (repo-migration / forgejo-leading)
[GOTCHA] Harbor/Dockerfile inter-image pin: use the GHCR-proxy path so ONE digest works in both pipelines
Type: GOTCHA
Verification: [VERIFIED] (GHCR techdocs-builder:1.2.7 digest = sha256:ac891…, identical via the harbor ghcr proxy)
What: Native Harbor (harbor.webgrip.dev/webgrip/techdocs-builder) and GHCR builds have DIFFERENT digests, so a single @sha256: pin can't serve both pipelines. Instead pin the inter-image base via REGISTRY_GHCR (default ghcr.io, Forgejo overrides to harbor.webgrip.dev/ghcr) — the Harbor GHCR pull-through proxy preserves GHCR's digest, so one ref webgrip/techdocs-builder:<ver>@sha256:<ghcr-digest> is valid on ghcr.io AND via the proxy, and Renovate tracks it (it substitutes the ARG default).
Why it matters: Reconciles digest-pinning + Renovate + Harbor-routing across a dual pipeline.
Snippet: ARG REGISTRY_GHCR=ghcr.io then ARG TECHDOCS_BUILDER=${REGISTRY_GHCR}/webgrip/techdocs-builder:1.2.7@sha256:ac891abd9e03fe3384b4d9d48f448f268aa7d8250ceb2a0c4a26029569df5632
Suggested home: doc
[DECISION] Parameterize Dockerfile base registries via ARGs (default upstream) so external builds are unchanged
Type: DECISION
Verification: [VERIFIED] (kustomize/js-yaml validated; defaults keep docker.io/ghcr.io)
What: Every base ref goes through ARG REGISTRY_DOCKERHUB=docker.io, REGISTRY_GHCR=ghcr.io, REGISTRY_WEBGRIP(dropped, see GHCR-proxy item), REGISTRY_MCR=mcr.microsoft.com, defaulting to upstream so GitHub-hosted builds are byte-identical. The .forgejo in-cluster build overrides them to harbor.webgrip.dev/{dockerhub,ghcr,mcr} proxy projects via docker-build-args (release) and --build-arg in .releaserc.js's cached verifyRelease branch. Each image consumes only the ARGs it declares; buildx warns (harmlessly) on unused build-args. Renovate resolves ARG-default chains, so the resolved upstream ref stays trackable. Harbor proxy paths use a prefix (dockerhub/library/alpine), so a transparent buildkit registry-mirror does NOT cover them — the path must be explicit in FROM, which is exactly why hardcoding harbor.webgrip.dev would break LAN-unreachable GitHub builds.
Why it matters: Routes in-cluster builds through Harbor pull-through cache without breaking the GHCR/GitHub pipeline.
Snippet: ARG REGISTRY_DOCKERHUB=docker.io / ARG BASE_IMAGE=${REGISTRY_DOCKERHUB}/library/alpine:3.23.4@sha256:5b10f432… / FROM ${BASE_IMAGE}
Suggested home: doc
[PROCEDURE] Provision a Forgejo org Actions secret from a GitHub PAT via OpenBao + the forgejo-actions-secrets CronJob
Type: PROCEDURE
Verification: [VERIFIED] (org secrets GHCR_USERNAME/GHCR_TOKEN/GH_RELEASE_TOKEN created)
What: (1) Add an ExternalSecret reading secret/github/ci-pat (props username,token); (2) add it to the kustomization; (3) add env vars + put_secret calls to forgejo-actions-secrets.cronjob.yaml. Forgejo reserves GITHUB_/GITEA_/FORGEJO_ secret-name prefixes — GHCR_/GH_ are fine. The Forgejo Actions secrets API is write-only — verify by the cronjob log (created org secret webgrip/GHCR_TOKEN), not by reading the secret back. Trigger immediately: kubectl -n forgejo create job fas-manual --from=cronjob/forgejo-actions-secrets.
Why it matters: GHCR push + GHCR cosign sign + GitHub Release mirror all need a write:packages+repo PAT in Forgejo.
Snippet: - {secretKey: GHCR_TOKEN, remoteRef: {key: github/ci-pat, property: token}}
Suggested home: existing-skill
[PROCEDURE] Write to OpenBao as admin via OIDC (root token is revoked and never stored)
Type: PROCEDURE
Verification: [VERIFIED] (ESO error Secret does not exist resolved after the PAT was seeded via OIDC)
What: This OpenBao revokes the initial root token and persists only the unseal key (Secret openbao-keys). Admin is OIDC via Authentik: the admins policy (path "*" full) is granted to identity group openbao-admins ← Authentik homelab-admins. kubectl exec into the pod gives a non-admin token → 403 on sys/internal/ui/mounts. Correct: OpenBao Web UI OIDC login, or CLI bao login -method=oidc role=default (redirect URIs include localhost:8250), then bao kv put. Break-glass: bao operator generate-root using the unseal key. Mount is secret (KV v2); ESO policy grants secret/data/* (wildcard).
Why it matters: Prevents the 403 dead-end and explains why there's no root token to paste.
Snippet: export VAULT_ADDR=https://openbao.webgrip.dev; bao login -method=oidc role=default; bao kv put secret/github/ci-pat username='<gh-user>' token='<REDACTED>'
Suggested home: memory
[FACT] Harbor webgrip project is PRIVATE — images are there but invisible without admin/member access
Type: FACT
Verification: [VERIFIED] (GET /api/v2.0/projects?name=webgrip → [] anon; GET /projects/webgrip → 401; build pushed a real digest)
What: Pushed images "missing" from Harbor were actually present in the private webgrip project — anonymous/non-member views can't see private projects. Harbor is OIDC (auth_mode: oidc_auth, oidc_admin_group: harbor-admins, oidc_auto_onboard: true). Local break-glass admin: username admin (not harbor-admin, which is the secret name), password kubectl -n harbor get secret harbor-admin -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d, login form at /account/sign-in (don't click the OIDC button). Or add your Authentik user to harbor-admins.
Why it matters: Stops a wild goose chase over "the push succeeded but I don't see the image."
Snippet: kubectl -n harbor get secret harbor-admin -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d
Suggested home: memory
[PROCEDURE] Harbor GC + tag retention + scan/SBOM-on-push via the harbor-proxy-config CronJob (Harbor v2 API)
Type: PROCEDURE
Verification: [VERIFIED] (cronjob logged GC/retention/scan/sbom enabled; SBOM gen succeeded)
What: GC and retention are complementary: retention (per-project) untags old versions; GC (registry-wide, delete_untagged:true) reclaims the bytes — including orphaned buildx mode=max :cache manifests (each cache-to overwrites the cache tag and orphans the prior ~2.6 GiB manifest). API: POST/PUT /system/gc/schedule {"schedule":{"type":"Custom","cron":"0 30 3 * * 0"},"parameters":{"delete_untagged":true,"workers":1}}; POST /retentions (template latestPushedK, exclude tag cache); per-project PUT /projects/{id} {"metadata":{"auto_scan":"true"}} and {"metadata":{"auto_sbom_generation":"true"}} (Harbor ≥2.11). Trigger SBOM manually: POST .../artifacts/{ref}/scan {"scan_type":"sbom"} (needs robot sbom:create perm or 403). Manual GC now: POST /system/gc/schedule {"schedule":{"type":"Manual"},...}.
Why it matters: mode=max cache bloats the registry; nothing reclaims it without scheduled GC.
Snippet: GC cron 0 30 3 * * 0; retention runs daily; chart goharbor/harbor 1.19.1 ≈ Harbor ~2.13
Suggested home: existing-skill
[FACT] Harbor robot sbom:create permission is required for auto-SBOM, separate from repository push/pull
Type: FACT
Verification: [VERIFIED] (per the committed harbor-proxy-config comment + convergence logic)
What: Harbor ≥2.11 gates native SBOM generation behind a dedicated sbom resource, NOT repository. The webgrip CI robot's access list must include {"resource":"sbom","action":"create"} alongside repository push/pull, or POST .../scan {"scan_type":"sbom"} returns 403 and Harbor's SBOM column stays empty (cosign SBOM attestation + DT upload are unaffected). Existing robots provisioned before this need their access list converged (the create-only POST won't fix them) — re-PUT /robots/{id} reusing the exact stored name (robot$webgrip+ci).
Why it matters: Explains an empty Harbor SBOM column despite auto-sbom being enabled.
Snippet: _perms='[{"kind":"project","namespace":"webgrip","access":[{"resource":"repository","action":"push"},{"resource":"repository","action":"pull"},{"resource":"sbom","action":"create"}]}]'
Suggested home: existing-skill
[FACT] The harbor-proxy-config configmap uses $$ escaping for Flux post-build substitution
Type: FACT
Verification: [VERIFIED] (file header + ks.yaml note)
What: In harbor-proxy-config.configmap.yaml every shell $ is doubled to $$ so Flux's postBuild substitution leaves the script intact (an un-doubled ${var} referencing an undefined var gets blanked at apply time; Flux restores $$→$). The sibling forgejo-actions-secrets ks deliberately has no postBuild.substituteFrom, so its script uses single $.
Why it matters: Editing these scripts requires knowing which escaping convention applies, or the script breaks at apply.
Snippet: AUTH="$$ADMIN_USER:$$HARBOR_ADMIN_PASSWORD"
Suggested home: doc
[DECISION] Per-registry build/push collapsed to one engine + thin wrappers (the -ghcr action was a misnamed generic engine)
Type: DECISION
Verification: [VERIFIED] (net −114 lines; structure deployed)
What: In webgrip/workflows, the build/push lives in ONE composite action docker-build-push-registry (login + tag-normalize + buildx + summary) wrapped by ONE reusable workflow docker-build-and-push-registry.yml; thin docker-build-and-push-{harbor,ghcr}.yml uses: the engine, pinning the registry + mapping their named secrets (HARBOR_ROBOT_* → REGISTRY_USERNAME/TOKEN). A -fast variant defaults platforms: linux/amd64 and skips QEMU (ADR-0036). The original docker-build-push-ghcr was actually the generic registry engine (display name "(Registry)", "Harbor by default") — a misnomer; docker-build-push (no suffix) is the Docker-Hub-only one.
Why it matters: Avoids duplicating ~200-line engine logic across registries; clarifies confusing naming.
Snippet: none
Suggested home: doc
[FACT] The sign-attest action signs BY DIGEST and was generalized to any registry (REGISTRY_USERNAME/TOKEN)
Type: FACT
Verification: [VERIFIED] (Harbor + GHCR sign steps wired; Harbor-native-SBOM step gated to harbor)
What: .forgejo/actions/cosign-sign-attest resolves the pushed digest (docker buildx imagetools inspect … --format '{{.Manifest.Digest}}') and signs by digest (prevents tag-mutation). Generalized creds from HARBOR_ROBOT_* to REGISTRY_USERNAME/REGISTRY_TOKEN so it signs Harbor AND GHCR with the same OpenBao key (each invocation mints its own OIDC→OpenBao token). The Harbor-native-SBOM step is gated if: ${{ contains(inputs.registry, 'harbor') }} (no analog on ghcr.io). Sign & Attest needs: both distribute jobs — couples signing to the GHCR push, so GHCR secrets must exist first.
Why it matters: One key, both registries; don't call the Harbor-API SBOM step against ghcr.io.
Snippet: if: ${{ contains(inputs.registry, 'harbor') }}
Suggested home: doc
[PROCEDURE] semantic-release commit-back of package.json, Forgejo-gated, with [skip ci]
Type: PROCEDURE
Verification: [ASSERTED] (config committed; not yet confirmed on a real release at digest time)
What: Add @semantic-release/npm (npmPublish:false) + @semantic-release/git (assets:['package.json'], message chore(release): ${nextRelease.gitTag} [skip ci]) to .releaserc.js, gated on process.env.SEMANTIC_RELEASE_GITEA so only the Forgejo (sole-authority) run commits back — GitHub mirror never re-versions. Both Forgejo and GitHub honor [skip ci], so the mirror push of the release commit re-triggers nothing. The action needs the plugins installed and git identity env (GIT_AUTHOR_NAME/EMAIL, GIT_COMMITTER_NAME/EMAIL).
Why it matters: Single writer of package.json avoids the dual-pipeline conflict; [skip ci] avoids a mirror loop.
Snippet: npm install … @semantic-release/npm@12.0.1 @semantic-release/git@10.0.1 …
Suggested home: doc
[REFERENCE] Forgejo Actions runs API + Kyverno policy action listing
Type: REFERENCE
Verification: [VERIFIED]
What: Inspect Forgejo Actions runs (auth required, repo private): GET https://forgejo.webgrip.dev/api/v1/repos/webgrip/infrastructure/actions/tasks?limit=N (.workflow_runs[] has .run_number,.status,.conclusion,.name,.head_sha). Branch HEAD: GET …/branches/main. The status-filter UI is …/webgrip/infrastructure/actions?status=<int> (5=Waiting,6=Running,7=Blocked). List all Kyverno policy enforcement actions: kubectl get clusterpolicy -o custom-columns=NAME:.metadata.name,ACTION:.spec.validationFailureAction.
Why it matters: Lets you confirm whether a push scheduled a run and whether any policy enforces.
Snippet: kubectl get clusterpolicy -o custom-columns=NAME:.metadata.name,ACTION:.spec.validationFailureAction
Suggested home: memory
[REFERENCE] Key file paths / version pins for this pipeline
Type: REFERENCE
Verification: [VERIFIED]
What: Repos: webgrip/infrastructure (images + .forgejo CI, origin = Forgejo SSH), webgrip/workflows (reusable workflows/actions, origin = github.com, mirrored to Forgejo), webgrip/homelab-cluster (Flux GitOps, origin = github.com). Forgejo runner label is docker (single in-cluster ephemeral KEDA-scaled pool). Per-image release config: ops/docker/<image>/.releaserc.cjs spreads root .releaserc.js, sets tagFormat: '<image>-v${version}'; placeholder package.json is {"version":"0.0.0","private":true}. semantic-release pins: semantic-release@24.2.7, semantic-release-monorepo@8.0.2. Kyverno policies: homelab-cluster/kubernetes/apps/kyverno/policies/app/{image-verify-audit,image-attestations-audit,image-verify-harbor-audit}.yaml (all validationFailureAction: Audit).
Why it matters: Orientation for future edits across the three repos.
Snippet: tagFormat: '<image>-v${version}'
Suggested home: CLAUDE.md
[FACT] checkout@v6 is broken on non-GitHub runners — pin actions/checkout@v5 on Forgejo
Type: FACT
Verification: [ASSERTED] (used throughout; noted as the reason for v5 pin)
What: actions/checkout@v6 is broken on non-GitHub runners; the .forgejo actions/workflows pin actions/checkout@v5.
Why it matters: v6 fails on the Forgejo runner.
Snippet: uses: actions/checkout@v5
Suggested home: memory
Open questions / unfinished
[OPEN] Final controlled release (run #33, fix(techdocs-builder)) was still running at digest time — not yet confirmed that the image+signature landed in BOTH Harbor and GHCR, the chore(release) [skip ci] package.json commit-back occurred, and the GitHub Releases tab populated.
[OPEN] GHCR webgrip/* package visibility unknown — if private, the two ghcr Kyverno policies need a ghcr-pull secret in imageRegistryCredentials.
[OPEN] infrastructure/ops/kyverno/cluster-policies/verify-webgrip-images.yaml is a ghcr-keyless Enforce policy in the infra repo; appears not deployed via homelab-cluster but should be removed/converted (would block key-signed GHCR images if applied).
[OPEN] exception-arc-runners.yaml (PolicyException for arc-runner attestations) — review if still needed under the new key model.
[OPEN] @semantic-release/git + semantic-release-monorepo asset-path behavior (cwd = package dir) unverified on a real release.
[OPEN] GHCR images are signed but a SECOND Dependency-Track project is created per image (harbor…/… and ghcr.io/…) — accept or dedupe later.
[OPEN] Pending (Ryan's standing reminder): flip Kyverno image-verify-harbor-audit (and the ghcr policies) from Audit → Enforce once a release is green with zero false positives. Explicitly NOT done.
Explicit preferences/feedback I gave
Keep enforcement to Audit only for now — "don't ENFORCE anything yet, only audits" — and remind me to flip Enforce later.
Pin missing external actions to github.com case-by-case so each is "easily findable later" — not a global DEFAULT_ACTIONS_URL change.
"ghcr should be ghcr, harbor should be harbor" — per-registry named actions, not one generic engine doing double duty (later refined to engine + thin per-registry wrappers).
DRY things up "as far as possible" (single engine + wrappers).
I want package.json version updated on release; inter-image base pinned by version number + digest with Renovate keeping it bumped.
"Forgejo is leading"; GitHub mirrors Forgejo; both cannot cut separate releases.
Give me a checklist + commands I need to run (runbook style) for manual/operational steps.
Don't commit until I say so (during the long review phase); commit on main.
