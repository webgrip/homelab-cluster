# Forgejo Actions engine: behaviors that differ from GitHub Actions

Forgejo Actions is *mostly* GitHub-compatible, but its young engine (≥ v15.0.0) has a handful of
sharp edges that bite when porting GitHub workflows to `.forgejo/`. This is the reference for those
divergences — author/debug a `.forgejo` workflow against it. (Repo/runner *infra* — the KEDA
ScaledJob, DinD, pod sizing — is the [Forgejo runner runbook](../runbooks/forgejo-runner.md); the
GitHub→Forgejo repo cutover is the `forgejo-leading` skill.)

The runner label is **`docker`** (the only label reaching the LAN-only Harbor). Jobs with direct
steps must pin `runs-on: docker`; orchestrator jobs that only `uses:` a reusable omit it (see below).

## Reusable-workflow expansion is conditional — and can race two builds

Forgejo (≥ v15.0.0, PR forgejo#10525) **flattens** a called reusable workflow's inner jobs into the
caller's job graph. **The expansion is conditional: it happens ONLY when the calling job OMITS
`runs-on`.** Keep `runs-on` on the caller and no expansion occurs.

When expansion **is** active, two things break versus GitHub (which namespaces inner jobs):

- **The caller job's `if:` does NOT gate the inner jobs.** They are dispatched independently. So two
  mutually-exclusive `if:`-gated reusable calls (e.g. a `distribute` vs `distribute-prerelease`, or an
  `is_prerelease`-gated build split) **BOTH** run their inner build — racing on the same registry tag
  and the same buildx `:cache` ref.
- **The caller job id must differ from every inner job id.** A collision leaves the flattened graph
  with no dependency-free job, and Forgejo rejects it at detection:
  `the workflow must contain at least one job without dependencies`. (The error points at
  `needs:`/cycles and misdirects you.) Example: a caller `determine-changed-directories` calling
  `determine-changed-directories.yml` whose inner job was *also* `determine-changed-directories` —
  rename the caller (e.g. `changed-images`). *(Collision mechanism observed in-thread, not upstream-documented; applies only while expansion is active.)*

### Two fixes

1. **Keep `runs-on` on the caller** — suppresses expansion, so `if:` gates normally and job ids can't
   collide. Cheapest dedupe.
2. **Use ONE call and push the condition into `inputs`.** Resolve the conditional inside an input so a
   single job covers both branches — e.g. gate the `:latest` tag inline so it resolves to `''` on
   prereleases (the engine skips blank tags). One build, no race.

```yaml
# Orchestrator job that only delegates → omit runs-on (expansion is fine here, no inner if:-gating).
build:
  uses: webgrip/workflows/.forgejo/workflows/docker-build-and-push-harbor.yml@main
  with:
    latest-tag: ${{ github.event.inputs.is_prerelease == 'true' && '' || 'latest' }}
```

## Action resolution splits by call-site

Where a `uses:` resolves depends on **what kind** of `uses:` it is:

| `uses:` site | Resolves against | Notes |
|---|---|---|
| **Job-level** reusable-workflow (`uses:` on a job) | the **LOCAL Forgejo instance** | bare slug `webgrip/workflows/.forgejo/workflows/*.yml@main`; nested `workflow_call` supported |
| **Step-level** composite-action (`uses:` on a step) | `[actions] DEFAULT_ACTIONS_URL` → default `https://data.forgejo.org` | a **curated/incomplete mirror** |

`data.forgejo.org` carries `actions/checkout` + `docker/*` but **404s** (`remote: Not found`) on
`actions/github-script`, `sigstore/cosign-installer`, `anchore/sbom-action`, and **all `webgrip/*`**.
**Pin those step-level composites to absolute URLs** case-by-case —
`https://github.com/<owner>/<action>@<ref>` or `https://forgejo.${SECRET_DOMAIN}/<owner>/<action>@<ref>`.

This cluster's `forgejo/app/helmrelease.yaml` sets `gitea.config.actions.ENABLED: true` and leaves
**`DEFAULT_ACTIONS_URL` unset** (defaults to `data.forgejo.org`). Flipping it globally would make
in-cluster Forgejo authoritative for *every* action (un-mirrored ones would then 404 — high blast
radius), so the chosen pattern is per-action absolute-URL pins, not a global flip.

## Workflow-directory precedence: first-existing wins

Forgejo reads workflows from the **first existing** of `.forgejo/workflows` → `.gitea/workflows` →
`.github/workflows`. Only one directory is read. This is a useful lever: an **empty
`.forgejo/workflows` directory disables a repo's Actions** (it wins precedence over `.github`, then
finds no workflows). Used to keep reusable-workflow library repos from running stray in-repo jobs.

## `workflow_call: secrets:` is rejected by the parser

Forgejo's `DetectWorkflows` **rejects** any workflow whose `on.workflow_call` declares a `secrets:`
key (only `inputs` and `outputs` are supported), logging
`ignore invalid workflow "X": ... key "secrets" was found`.

- **Benign ONLY on a pure-reusable file** that is never triggered standalone — when reached via
  `uses:` it still executes correctly; only standalone detection is skipped.
- **NOT benign on a mixed-trigger file.** If the same file also has `push`/`pull_request` triggers,
  the rejection **suppresses those triggers too** (issue forgejo#6069) — the file silently stops
  running on push/PR.
- **Fix:** drop `workflow_call.secrets` and **pass secrets from the calling job** instead.

## `workflow_dispatch` context gotchas

*Observed on the deployed version — possibly version-specific. The workarounds are defensive
regardless; re-verify the underlying emptiness after a Forgejo upgrade.*

- **`github.repository_owner` and `github.sha` can be empty** in a `workflow_dispatch` run.
  Empty owner → `harbor.${SECRET_DOMAIN}//<image>` double-slash → `invalid reference format`;
  empty sha → a blank `IMAGE_REVISION`. **`github.repository` IS populated.** Hardcode `webgrip`
  defensively in any derived image/cache ref — e.g.
  `BUILD_CACHE_REF=${{ inputs.registry }}/webgrip/${{ inputs.package-name }}:cache` — or a
  never-matching ref gives you a permanent cold cache.
- **A CI-created release fires NO release Actions event.** A release created inside a CI job does not
  trigger an `on: release` workflow (loop-prevention; even a real user PAT won't fire it — GitHub's
  GitHub-App token does, Forgejo has no equivalent). **Dispatch the build workflow explicitly:** make
  the build reachable via `workflow_dispatch`, and have the release step `POST` a dispatch.
  Every `workflow_dispatch` input **must declare `type:`** — an input without an explicit type makes
  Forgejo render `Invalid input type ""` and reject the API dispatch (GitHub tolerates omission):

  ```yaml
  on:
    workflow_dispatch:
      inputs:
        tag:          { type: string, required: true }
        is_prerelease: { type: string, default: "false" }
  ```

- **`semantic-release-monorepo` `outputs.version` is the FULL namespaced tag**, not bare semver —
  e.g. `techdocs-builder-v1.2.19`, because `tagFormat` is `<image>-v${version}`. **Pass it verbatim**
  to the dispatch/parse (it matches `^(.+)-v(.+)$`). **Never re-prefix it** — prepending
  `<package-name>-v` doubled it to `techdocs-builder-vtechdocs-builder-v...`.

## Authorization is per-UNIT — token scope is not permission

Forgejo checks two independent layers on every call: the token's **scopes** cap what the token
*may* do; the user's **team unit permissions** (`repo.code`, `repo.releases`, `repo.packages`
via org membership, …) decide what the user *can* do. A bot whose team grants `repo.code`
write but not `repo.releases` git-pushes fine (200) while `POST /api/v1/repos/…/releases`
fails `403 Forbidden @ v1.reqRepoWriter` — even with a `write:repository`-scoped token.
The complementary hole: the built-in per-job Actions token can create releases but gets
`401 reqPackageAccess` on the package registry.

- Fix pattern: reconcile the team's unit set on every provisioner run — `PATCH
  /api/v1/teams/{id}` with the full desired `units` list. Create-time units alone can't fix a
  live team. (Applied 2026-07-12 in `forgejo-ci-provisioner.job.yaml` after webgrip-ai-skills
  release runs 11–15 failed exactly this way.)
- Triage signature: "auth works partially" (git ✓, one API family ✗) = missing unit, not a
  bad token.

## Triage CI failures without job-log access

Job logs require authentication (`…/actions/runs/{n}/jobs/{j}/logs` → 404 unauthenticated),
but two read-only sources reconstruct most failures:

- **Run status (public):** `GET /api/v1/repos/{owner}/{repo}/commits/{sha}/status` — per-job
  state + which job failed.
- **The Forgejo server router log via VictoriaLogs** logs every API/git request with status
  code and handler: `router: completed POST /api/v1/… 403 Forbidden … @ v1.reqRepoWriter`.
  Time-bound a LogsQL query to the failure window:
  `namespace:forgejo container:forgejo "POST /api/v1/repos/<owner>/<repo>"` — the exact
  failing call, its code, and the enforcing handler. The hourly
  `PUT /api/v1/orgs/webgrip/actions/secrets/<NAME> … 204` lines from the secrets provisioner
  also prove whether an org Actions secret exists (values are write-only; existence isn't).

## See also

- Forgejo app overview, ingress, SSO, runner pointer → [Forgejo](forgejo.md)
- Runner/KEDA/DinD pod infra → [Forgejo runner runbook](../runbooks/forgejo-runner.md)
- GitHub→Forgejo repo cutover (un-mirror, remotes, parity) → `forgejo-leading` skill
