---
status: accepted
date: 2026-10-27
decision-makers: Ryan Grippeling
---

# A branch rule requires one gate check, and Forgejo merges Renovate's pull requests on it

## Context and Problem Statement

Renovate merges its own pull requests (`platformAutomerge: false` in every webgrip preset) only while a Renovate run is active. The `webgrip-forgejo` job starts at minute 33 of every hour and visits one repository at a time, so a pull request that turns green after the run passed its repository waits up to an hour, and longer when the run is slow. On 2026-10-27 unfold's pull request #634 was green at 10:37 UTC and merged at 12:26 UTC.

Forgejo's own merge-when-checks-succeed would merge at once, but Forgejo 15.0.10 decides on the branch rule's required contexts only (`services/pull/commit_status.go`, `IsPullCommitStatusPass`). A branch with no rule, or with status checks disabled, merges immediately. A rule that lists some jobs merges without the others. On that day unfold's `development` required four of its eight pull request jobs, and every other repository that merges Renovate updates on its own required none.

How does a repository let Forgejo merge Renovate's pull requests without merging anything untested, and keep its required checks right as its jobs change?

## Decision Drivers

* A Renovate update merges minutes after it is green, not at the next Renovate run.
* Nothing merges before every blocking job of the repository passed.
* A job added to a workflow, or renamed, must not fall out of what the branch requires.
* The repo-config model states the rule and refuses a model that would merge untested; a reviewer does not have to remember it.

## Considered Options

* One `gate` job per pull request workflow, and branch rules that require only that job's context
* A list of required contexts per repository in the model, as before
* Keep Renovate's own merge and run Renovate more often

## Decision Outcome

Chosen option: "One `gate` job per pull request workflow", because the branch rule then names a context every repository spells the same way, the repository decides what blocks a merge in the same place it defines its jobs, and a missing gate fails closed: Forgejo treats a required glob that matches no context as pending, so the pull request waits instead of merging.

1. **The gate job.** A repository's pull request workflow ends in a job named `gate`. It needs every blocking job, runs with `if: always()`, and succeeds only when each job it needs succeeded. Advisory jobs stay outside it. The repository's own policy test fails when a new job is neither in the gate nor named advisory ([unfold's](https://forgejo.webgrip.dev/webgrip/unfold/src/branch/development/scripts/workflow-policy.test.cjs) is the first).
2. **The branch rule.** A branch rule in the model requires `* / gate (pull_request)`. The glob ignores the workflow's name, so one spelling serves every repository.
3. **Forgejo merges, opt in per repository.** The `platform-automerge` preset of `webgrip/renovate-config` sets `platformAutomerge: true`. A repository extends it only once its branch rules require the gate. `scripts/validate-repo-config-model.sh` refuses a Forgejo repository that lists the preset while one of its protected branches does not require the gate.

unfold is the first repository on it: its `development` and `main` require the gate.

### Consequences

* Good, because a Renovate update merges as soon as its gate is green, and Renovate still merges by itself on its next run when Forgejo did not (a pull request opened before the switch has no merge scheduled in Forgejo).
* Good, because a job added to a workflow is required without a change in this repository.
* Good, because the preset cannot reach a repository whose branches require nothing: the validator refuses it.
* Bad, because a required gate blocks people's pull requests on every flaky job it waits for, not only Renovate's; unfold's runner-load timeouts are VIK-2492.
* Bad, because each repository carries the gate job itself: a reusable workflow cannot `need` the jobs of its caller.
* Neutral: Forgejo merges a green pull request even when its base moved since its checks ran; the merge commit is checked again on the base branch. A branch rule can add `block_on_outdated_branch` where that is not acceptable, such as a long-lived feature branch.

### Confirmation

- `scripts/test-validate-repo-config-model.sh` holds the rule both ways: unfold with the preset and the gate passes, seekframe with the preset and no gate fails, and unfold with the preset and one branch off the gate fails.
- `curl -s $API/repos/webgrip/unfold/branch_protections` shows `* / gate (pull_request)` as the only status check context of `development` and `main`.
- A Renovate pull request in unfold opened after the switch shows `merged_by` Renovate within minutes of its gate turning green, outside a Renovate run.

## More Information

- Builds on [ADR-0083](adr-0083-nobody-pushes-to-main-and-core-repositories-need-a-second-person.md) (every branch rule is in the model) and [ADR-0050](adr-0050-per-repo-delivery-contract.md) (the contract is enforced by the server).
- The repository kinds of [ADR-0078](adr-0078-one-release-recipe-four-kinds.md) will decide which branches a repository protects; which kinds require the gate is decided with them.
- The existing rule that homelab-cluster `main` requires `e2e / Lint & static validation (pull_request)` stays: homelab-cluster's own `.renovaterc.json5` uses platform automerge for one group, not the preset.
- 2026-10-27 — decided by Ryan Grippeling: one gate per repository, everything except advisory jobs in it, unfold first and other repositories one by one, merging behind the base accepted for now.
