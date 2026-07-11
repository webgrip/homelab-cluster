---
name: renovate-debug
description: Diagnose in-cluster Renovate (mogenius renovate-operator, RenovateJob CRs webgrip-gitops/webgrip-forgejo) — per-repo run status, worker-pod bunyan debug logs, forcing a run for one job/project, and mapping branch-failure signatures ("Error updating branch", artifactErrors, "Cannot find replaceString", "Digest is not updated") to causes.
when_to_use: Use when a Renovate PR is missing/stale/errored, a dependency-dashboard tick "did nothing", PRs stop appearing or stay frozen, the dashboard shows Errored/Pending items that never resolve, or a Renovate run must be triggered for one repo. NOT for adding/updating Renovate config rules.
allowed-tools: Bash(mise exec -- kubectl get:*), Bash(mise exec -- kubectl logs:*), Bash(kubectl get:*), Bash(kubectl logs:*)
---

# renovate-debug — why didn't this update become a PR?

**Mental model:** the dashboard issue body is Renovate's ONLY approval state. If an approved branch
produces zero file changes (failed auto-replace, dead manager, artifact error), no PR exists to carry
the state — the tick is consumed and the item re-renders unchecked. "My click vanished" ⇒ find the
silent branch failure; soak (`renovate/stability-days`) does not eat clicks.

## Triage order

1. **Per-repo run outcome** (MCP can't list this CRD — use kubectl):
   `mise exec -- kubectl get renovatejob -n renovate webgrip-gitops -o json | jq '.status.projects[] | {name, lastRun, status, prActivity, logIssues}'`
   (jobs: `webgrip-gitops` = GitHub, `webgrip-forgejo` = Forgejo)
2. **Worker-pod log** — pods `webgrip-<job>-<repo>-<hash>` persist **~30 min** (cleanup cron), logs NOT in VictoriaLogs, bunyan JSON:
   `kubectl logs -n renovate <pod> --tail=-1 | grep '^{' | jq -rc 'select(.level >= 40) | {branch, msg, artifactErrors}'`
   Per-branch trace: `jq -rc 'select(.branch=="renovate/<branch>") | [.level, .msg, (.packageFile//""), (.depName//"")] | @tsv'`
3. **Match the signature** → cause/fix table in [runbooks/renovate.md](../../../docs/techdocs/docs/runbooks/renovate.md) (canonical; covers preset digest-pin, mise digest-pin, Harbor-401 artifactErrors, multi-ARG replaceString, zombie branch, release-age).

## Force a run (one project, right job)

Without `job=` only the gitops job's projects schedule — the Forgejo job needs explicit addressing.
Prefer the `renovate-trigger` agent; raw form (token: `renovate-webhook-auth` secret):

```
POST http://renovate-operator.renovate.svc:8082/webhook/v1/schedule?job=<renovatejob>&namespace=renovate&project=<owner%2Frepo>
```

## Gotchas

- Dashboard-edit webhook races the click: the instant run may read the pre-click body; the tick is honored next run.
- Run schedule (`after 3am and before 7am every weekday,every weekend`, Europe/Amsterdam) gates branch work — a manual trigger outside the window discovers but won't create branches.
- `renovateResultStatus: done` with `prActivity` all zeros is normal for a repo with nothing to do; `Onboarding` means no repo config merged yet.
- Group branches fail atomically: ONE un-replaceable dep aborts the whole grouped branch ("Error updating branch: update failure") — find the single failing dep, don't debug the group.
