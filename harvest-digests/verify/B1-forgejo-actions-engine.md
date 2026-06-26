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
