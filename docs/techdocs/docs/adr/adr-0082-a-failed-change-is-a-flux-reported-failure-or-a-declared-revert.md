---
status: proposed
date: 2026-10-25
decision-makers: Ryan Grippeling
---

# A failed change is a Flux-reported failure or a declared revert, counted per deployment

## Context and Problem Statement

The Executive dashboards show delivery health through proxies: Flux objects not Ready now, Flux
apply p95, distinct Flux revisions. None is a change failure rate, a time to restore or a lead
time. 97% of changes on `main` are agent commits pushed straight to trunk, Renovate adds 30–50
merged PRs a week, and VictoriaMetrics keeps 15 days. Which event counts as a failed change, what
is a deployment, and where do the numbers live so that two readers get the same answer? The
spike with the four-week computation is [VIK-2423](https://vikunja.webgrip.dev/tasks/2423).

## Decision Drivers

* Two readers computing the same week get the same number.
* Agent, Renovate and owner changes are measured by one rule.
* Existing sources first; at most one new signal.
* Low upkeep: alert churn or commit-message style must not move the rate.

## Considered Options

* Flux-reported failure ≥15 minutes, or a declared `Reverts:` trailer, per root revision
* Revert-linked commits only
* A `fix:` commit touching a same file within 24 hours
* A critical alert within one hour of a deployment

## Decision Outcome

Chosen option: "Flux-reported failure or declared revert, per root revision", because it is the
only option that is mechanical, treats every actor alike, and catches both apply failures (which
nobody reverts) and runtime breakage that Flux reports as healthy (which only a revert reveals).

* A deployment is a root `flux-system` Kustomization revision that became Ready.
* A deployment failed when, after it, a Kustomization or HelmRelease is Ready=False for a
  root-cause reason (not `DependencyNotReady`) for 15 minutes or longer, or a HelmRelease upgrade
  or rollback fails, or a later commit carries `Reverts: <sha>` for a change it contained.
* Time to restore runs from failure onset to the object Ready again, or from the failed deployment
  to the reverting deployment.
* Lead time is reported in two lanes: trunk (author time to Ready) and pull request (open to merge
  to Ready), split by renovate, agent and owner.
* A daily job writes one row per deployment to a durable store that the dashboards read.

### Consequences

* Good, because the four-week baseline is reproducible: 2.7% (W42) and 4.0% (W43), restore median
  10.5 and 49 minutes.
* Good, because Renovate's PR wait (p90 6–21 days) becomes visible next to a one-minute trunk.
* Bad, because a runtime failure that is fixed forward without a `Reverts:` trailer is not counted.
* Bad, because a new job and table must be kept, and the 15-minute threshold is a judgement.

### Confirmation

The commit-msg lint rejects a `revert` commit without `Reverts: <sha>` and passes one that has it.
The daily job's row count for a day equals the number of distinct `flux-system` revisions VM shows
for that day, and a deliberately broken Kustomization in a test revision is counted as failed.

## More Information

Spike data and queries: [VIK-2423](https://vikunja.webgrip.dev/tasks/2423). Related: Executive value-flow dashboard
(`exec-value-flow-delivery`).
