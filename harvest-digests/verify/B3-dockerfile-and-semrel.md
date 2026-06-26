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
