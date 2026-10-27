# Runbook: Renovate

Use this when Renovate alerts are firing (for example `RenovateOperatorDeploymentUnavailable`, `RenovateProjectRunFailed`, `RenovateProjectDependencyIssues`, or the log-based [self-reporting alerts](#self-reporting-alerts)) or Renovate PRs stop appearing.

## Fast triage

**Step 1 — operator / controller**

- `kubectl -n renovate get pods -o wide`
- `kubectl -n renovate logs deploy/renovate-operator --tail=200`

**Step 2 — per-repo run outcomes on the RenovateJob CR** (fastest signal; the MCP read-only role can't list these — use kubectl)

```bash
mise exec -- kubectl get renovatejob -n renovate webgrip-gitops -o json \
  | jq '.status.projects[] | {name, lastRun, status, prActivity, logIssues}'
```

**Step 3 — worker-pod logs.** Worker pods (`webgrip-<job>-<repo>-<hash>`) persist **~30 minutes** until the `renovate-job-cleanup` cron deletes them. Their logs also reach VictoriaLogs (30 days, `LOG_LEVEL: info`); the LogsQL under [self-reporting alerts](#self-reporting-alerts) reads them after the pod is gone. A live pod's output is bunyan JSON:

```bash
kubectl logs -n renovate <worker-pod> --tail=-1 | grep '^{' \
  | jq -rc 'select(.level >= 40) | {branch, msg, artifactErrors}'
# per-branch trace:
#   jq -rc 'select(.branch=="renovate/<branch>") | [.level, .msg] | @tsv'
```

**Step 4 — Dependency Dashboard.** Renovate runs against **both forges** (GitHub + Forgejo), each repo has its own dashboard issue

- Look for authentication errors, rate limiting, or failing managers.
- A ticked approval that "did nothing" = the branch produced zero changes (see signatures below); the tick is consumed and the item re-renders unchecked. Re-tick after fixing the cause.

**Step 5 — Flux status** (if Renovate is deployed via GitOps)

- See the Flux runbook: [docs/techdocs/docs/runbooks/flux.md](flux.md)

## Self-reporting alerts

Renovate exits 0 after most failures, so the operator's `renovate_operator_run_failed` metric stays 0 and a repository can stop getting updates for months without a sign (searxng nine months, litellm four, `webgrip/renovate-config` skipping its `next` base branch on 679 runs in 30 days). Three log-based rules in `kubernetes/apps/renovate/renovate-operator/jobs/renovate-self-reporting.vmrule.yaml` read the executor logs in VictoriaLogs instead. `vmalert-logs` evaluates them every 5 minutes and sends them to Alertmanager with `service: renovate`.

How the executor logs land in VictoriaLogs:

- Executors log bunyan JSON. Alloy ships the `renovate` namespace through its own writer with `_msg_field=msg`, so the message is in `_msg` and plain searches such as `"Base branch"` match. Lines ingested before 2026-10-26 keep the message in a `msg` field and have a placeholder `_msg`; the rules match both (`_msg:"…" or msg:"…"`).
- `logContext` is one id per run. The log shipper can store the same line more than once, so count runs with `count_uniq(logContext)`, never `count()`.
- Each run ends with `Repository finished` and a `result` field: `done`, `onboarding` and `empty` are healthy; `unknown-error`, `external-host-error`, `temporary-error`, `repository-changed` and `config-validation` are not.
- Discovery pods (`<job>-discovery-…`) print the discovered repositories as one JSON array in `_msg`.

Paste the queries below into Grafana Explore (VictoriaLogs datasource) or the `victorialogs` MCP. Grafana sets the time range, so drop the leading `_time:` there.

### RenovateRepositoryRunFailed

A run logged errors and exited non-zero (`Renovate is exiting with a non-zero code due to the following logged errors`). The `first_error` label is the first logged error: `Repository has unknown error` and `Initialization error` abort the whole run, while `lookupUpdates error` and similar ones mean a run that finished but skipped dependencies. When the run failed before it knew its repository (an `Initialization error`), the label carries the slug from the pod name, for example `webgrip-homelab-cluster`.

First step: read the error lines of that repository's failed runs.

```logsql
_time:6h namespace:=renovate level:>=50
| join by (logContext) (_time:6h namespace:=renovate repository:* | uniq by (logContext, repository))
| filter repository:="webgrip/homelab-cluster"
| fields _time, pod, _msg, msg, err.message, err.response.statusCode
```

- `Initialization error` on several repositories within minutes: the token, not the repositories. Check the `renovate-forgejo-token` Secret and the [token minter](#fast-triage).
- `Repository has unknown error` with an HTTP status in `err.message`: a Forgejo API call Renovate cannot handle. 2026-10-26: `422 … DELETE …/issues/878/labels/80` was the org `rebase` label (see [Forgejo path gotchas](#forgejo-path-gotchas)).

### RenovateRepositorySkippedByConfig

A run ended normally but skipped a repository or base branch for a configuration reason: `Base branch does not exist - skipping`, `Repository has invalid config`, `Cannot ensure issue because issues are disabled` (no Dependency Dashboard) or `Skipping repository … because pull requests are disabled`. The alert clears seven hours after the last matching run.

First step: see which repositories and branches are affected and since when.

```logsql
_time:7d namespace:=renovate
(_msg:~"^(Base branch does not exist|Repository has invalid config|Cannot ensure issue because issues are disabled|Skipping repository .* because pull requests are disabled)"
or msg:~"^(Base branch does not exist|Repository has invalid config|Cannot ensure issue because issues are disabled|Skipping repository .* because pull requests are disabled)")
| stats by (repository, baseBranch, _msg, msg) count_uniq(logContext) as runs, min(_time) as first_seen, max(_time) as last_seen
```

- Missing base branch: remove the branch from `baseBranches` in the repository's Renovate config, or create it.
- Invalid config: the run's `Repository has invalid config` line lists the errors; validate locally with `npx --package renovate renovate-config-validator`.
- Issues or pull requests disabled: `scripts/forgejo-sync.sh --repo <name> --only prs --apply` restores the Pull Requests unit; turn Issues on in the repository settings if it should have a dashboard.

### RenovateRepositoryFrozen

A RenovateJob lists the repository in discovery, but no run of it ended with a healthy result in six hours, and that has lasted an hour. It covers both a repository the executor never reaches and one whose every run ends in the same error (for example `repository-changed`).

First step: list the last results per repository and look for the gap.

```logsql
_time:24h namespace:=renovate (_msg:="Repository finished" or msg:="Repository finished")
| filter repository:="webgrip/workflows"
| stats by (repository, result, exitCode) count_uniq(logContext) as runs, max(_time) as last
```

- No `Repository finished` lines at all and no executor pod for the repository: the job never started it. Compare the RenovateJob's `status.projects[]` entry for that project (Step 2 above) and force a run for it (below).
- Only error results: handle it as [RenovateRepositoryRunFailed](#renovaterepositoryrunfailed), or for `repository-changed`, find what pushes to the repository during every run.

## Force a run

The operator's schedule endpoint takes the RenovateJob name and a URL-encoded project. **Without `job=` only the gitops job's projects are scheduled** — the Forgejo job must be addressed explicitly:

```bash
kubectl -n renovate port-forward svc/renovate-operator 18082:8082 &
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:18082/webhook/v1/schedule?job=webgrip-forgejo&namespace=renovate&project=webgrip%2Finfrastructure"
```

(Token: `renovate-webhook-auth` secret. The `renovate-trigger` agent wraps this.)

Note: editing a dashboard issue on Forgejo fires a webhook run near-instantly, but that run can read the **pre-click** issue body — checkbox ticks are honored by the *next* run.

## Unfold releases reach the homelab

An Unfold release is one chart that carries the Ploeg chart it was tested with
([Unfold ADR-0043](https://forgejo.webgrip.dev/webgrip/unfold/src/branch/development/docs/adr/adr-0043-an-unfold-release-is-one-chart-that-carries-the-ploeg-it-was-tested-with.md)),
published only after all its images. The hourly `webgrip-forgejo` run opens or updates the
`ploeg-unfold-release` PR, and that group's `platformAutomerge: true` lets Forgejo merge it on its last
required `e2e /` status. That is safe only while homelab `main` requires the `e2e / Lint & static
validation` context; `scripts/validate-repo-config-model.sh` fails when it stops doing so. For a
faster pickup, force a run (above). The Harbor release relay that triggered runs on each push was
removed on 2026-10-20, and its webhook policy `unfold-release-renovate` was deleted from Harbor
project `webgrip` on 2026-10-22.

## All PRs red at once: OCI digest drift

If `verify-oci-digests` FAILs the same file on main **and** every PR, an upstream chart tag was re-pushed (coredns `1.46.0` has shipped three digests). Confirm against the registry, then let the automerged digest PR fix it (or bump the pin by hand — precedent: `72f52195`, `796989d0`):

```bash
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:<org>/<chart>:pull" | jq -r .token)
curl -s -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{header_json}' \
  "https://ghcr.io/v2/<org>/<chart>/manifests/<tag>" | jq -r '."docker-content-digest"[0]'
```

Since renovate-config v1.5.0 + the repo's digest-automerge rule this self-heals; a wedge recurring means that pipeline broke.

## Known failure signatures (worker-pod log → cause)

| Signature | Cause | Fix |
|---|---|---|
| `Digest is not updated` on `renovate.json` / `webgrip/renovate-config` | Global `pinDigests: true` tried to digest-pin the preset reference; the replace never applies and **aborts the whole grouped branch** | renovate-config ≥ v1.5.1 (`pinDigests: false` for the preset package) |
| `Digest is not updated` on `.mise.toml` / `aqua:*` | Same class: the mise manager can't write digests into aqua entries | renovate-config ≥ v1.5.2 (digest updates disabled for the mise manager) |
| `artifactErrors` + `Command failed: ./scripts/update-oci-digests.sh` on **every** branch | The postUpgradeTask 401'd against Harbor (public projects still require an anonymous bearer token) and died at the first harbor-proxied chart | fixed in `scripts/lib/oci.sh` (`/service/token?service=harbor-registry`); if it recurs, run the script locally |
| `Cannot find replaceString in current file content` → `No files to commit` | Multi-ARG Dockerfile FROM composition (`${REGISTRY}/img:${VER}-suffix`): the dockerfile manager resolves ARGs at extraction, then can't find the resolved string in the raw file — the update **silently no-ops** | own the ARG with an annotated-ARG regex manager and disable the dockerfile manager for that file (see webgrip/infrastructure `renovate.json`) |
| PR shows "branch already included / nothing to merge", only a "Manually merged" button | Zombie group-branch: a merged PR's branch survived, the group got a new update, Renovate reopened a PR on the stale branch without pushing | Renovate self-heals next run (closes PR, deletes branch); prevent with delete-branch-after-merge |
| `Update has not passed minimum release age` | Release younger than soak (patch 1d / minor 3d / major 14d). Not an error; on the Forgejo path the PR still opens with a pending `renovate/stability-days` status | check the tag age with `curl -s https://hub.docker.com/v2/repositories/library/<img>/tags/<tag>` piped to `jq -r .last_updated` |
| Dashboard `Failed to look up docker package harbor.webgrip.dev/webgrip/*` (proxy projects like `…/dockerhub/*` still resolve) + `artifactErrors` | Renovate's Harbor robot credentials are invalid — the Harbor-side robot secret was never PATCHed because `harbor-proxy-config` crashed mid-provision | Check the latest `harbor-proxy-config` pod log in ns `harbor` for `parameter not set`; see the [Harbor runbook](harbor.md) Common problems table |
| `Can't find version matching <ver>` for a **public** proxy path (`…/dockerhub/*`) while the tag demonstrably exists in the registry | Same invalid-robot cause as the row above. A *rejected* credential is worse than none on a public proxy project: Harbor 401s instead of serving anonymously, so the tag list never arrives. An anonymous `curl` of the same path succeeds, which makes it look like a Renovate versioning bug | Fix the robot secret first; only suspect versioning if the tag list is genuinely fine (see next row) |
| `Can't find version matching <ver>`, tag list verified present, dep offers **no** updates at all | The upstream tag scheme is unparseable by the default `docker` versioning — e.g. FOUR numeric components (`v0.16.6.3`), so the pinned value can't be anchored | `versioning: "loose"` for that package (precedent: the `sparkyfitness` rule in `.renovaterc.json5`). Group lockstep image pairs while you're there |
| `Reached PR limit - skipping PR creation`; dashboard renders everything as **Rate-Limited** | `prConcurrentLimit` takes the **LOWEST** value among a branch's upgrades, so the org preset's 5 silently beats the admin ConfigMap's 10. Deadlocks completely when the open PRs are ones Renovate can't resolve (hand-edited, `automerge:false` by our gates, or a conflicted human PR) | Look for `Calculated lowest prConcurrentLimit ... is N` in the worker log. Set `prConcurrentLimit`/`branchConcurrentLimit` at **repo** level; clear unresolvable PRs (closing a Renovate PR is safe — it is recreated clean) |
| Everything green and `automerge=true`, yet only ~1 PR merges per run | `rebaseWhen: "behind-base-branch"` (preset default): merging one PR moves `main`, every other branch is then "behind", each is rebased, each rebase restarts its e2e checks, none can merge until the next run. Worse on a repo with concurrent writers on `main` | `rebaseWhen: "conflicted"` at repo level. Confirm via `Skipping behind base branch check due to rebaseWhen=conflicted` in the log |
| PR body says `Automerge: Enabled`, branch status green, still unmerged | Usually just the soak: check the `renovate/stability-days` status (yellow = `minimumReleaseAge` not met). `mergeStatus=no automerge` in the log is **benign** for `automergeType: pr` — it is the branch-automerge step declining, not a block | Verify a real automerge by looking for `PR automerged` in the log, or bot-authored `Merge pull request` commits on `main` (`git log --author=renovate`) |

## Common causes

- Token expired / revoked (GitHub app token / PAT).
- Repository permissions changed.
- Renovate image updated but config incompatible.
- Cluster resource pressure causing restarts.

## Forgejo path gotchas

The in-cluster Renovate also runs against Forgejo (`webgrip-forgejo` RenovateJob). Four failure modes are silent — Renovate keeps running, it just quietly does nothing for the affected repos.

- **Un-mirrored repos have the Pull Requests unit OFF, so Renovate skips them.** Converting a `gitea-mirror` pull-mirror to a regular repo leaves `has_pull_requests=false` (mirrors are read-only). Renovate then logs `Skipping repository <r> because pull requests are disabled` and excludes it — the repo is *discovered but skipped*. Also note autodiscovery **can only seed `status.projects` on the cron** (`33 * * * *`); the per-project webhook path can't add a *new* project mid-cron. Fix / restore PR-unit parity for every de-mirrored repo:

  ```bash
  scripts/forgejo-sync.sh --all --only prs --apply
  ```

- **The webhook `authorization_header` must be a TOP-LEVEL field, not a `config` key.** On the Forgejo hook API, `authorization_header` is top-level; Forgejo silently drops unknown `config` keys, so nesting it sends NO `Authorization` header and the operator receiver 401s. Diagnose via the hook's UI "Recent Deliveries" (it shows the sent headers + response code). The per-repo webhook is registered by `scripts/forgejo-sync.sh --only webhook` and points at the internal Service (`http://renovate-operator.renovate.svc.cluster.local:8082/webhook/v1/forgejo?…`), not the envoy-external hairpin.

- **Renovate can only attach a label that already exists.** On Forgejo it looks each label up among the repository's and the organisation's labels and drops the ones it cannot find, with a single `Some labels could not be looked up` warning. Until 2026-10-26 no repository or the `webgrip` org had any of them, so no Renovate pull request carried `automerge`, `type/*`, `security` or `dependencies`, although the hidden `renovate-debug` block in each PR body lists them. The `renovate-labels-provisioner` CronJob (`kubernetes/apps/forgejo/forgejo-actions-secrets/app/`) now converges the label set in `renovate-labels.json` onto the org every hour and deletes the org labels listed in `renovate-labels-retired.json`, and `scripts/test-renovate-labels-provisioner.sh` tests it against a fake Forgejo in e2e. A preset in `webgrip/renovate-config` that adds a label needs a row in that file. Check the org's labels with `curl -s https://forgejo.webgrip.dev/api/v1/orgs/webgrip/labels | jq -r '.[].name'`.

- **A cancelled CI run reads as a failure, and Renovate never retries it.** Forgejo reports a cancelled job as `failure` with the description `Has been cancelled`, whether a person cancelled it, a newer push superseded it, or the runner pod was killed. Renovate's automerge then waits forever, and a person-merged PR shows red with nothing wrong in it (unfold#614 sat like that on 2026-10-25). The `renovate-cancelled-ci-retry` CronJob runs hourly at :21. It labels `rebase` every open Renovate PR whose head commit has no pending check and only cancelled failures, settled for an hour; The operator runs one repository at a time, so the label takes effect on that repository's next run, up to about an hour later (a run already past its PR lookup when the label lands misses it): Renovate rebases the branch, CI runs again, and Renovate removes the label. It labels at most five PRs a run. `scripts/test-renovate-cancelled-ci-retry.sh` tests it against a fake Forgejo in e2e. A PR that keeps getting cancelled points at the runners, not at the PR. **`rebase` must be a repository label, never an org label:** Renovate removes it with `DELETE /repos/<o>/<r>/issues/<n>/labels/<id>`, which Forgejo answers with 422 for an org label's id, and Renovate then aborts the whole repository run with `Repository has unknown error`. That happened on 2026-10-26: homelab-cluster's runs failed on `issues/878/labels/80` until the org label was retired. The job creates the repository label on first use and labels by its id.

Debugging trick for "which repos are skipped and why": `renovate --autodiscover --write-discovered-repos` with `LOG_LEVEL=debug`.

## More detail

- Full Renovate docs/config: [docs/techdocs/docs/renovate.md](../general/renovate.md)
- Forgejo migration design: [RFC — Renovate on Forgejo](../rfc/rfc-renovate-forgejo.md)
