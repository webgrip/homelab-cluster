---
status: accepted
date: 2026-10-26
decision-makers: Ryan Grippeling
---

# Nobody pushes to main, and the core repositories need a second person

## Context and Problem Statement

[ADR-0050](adr-0050-per-repo-delivery-contract.md) made delivery a server-enforced contract per repository, but kept two openings: the owner pushes straight to `main` of homelab-cluster (and of talos-kata-extension and unfold-cluster), and most repositories had no rule at all, so anyone with write access could push to `main` or create a tag.

A security review of the agent standard on 2026-10-26 found what those openings cost:

- No repository had tag protection. agent-standards, workflows and renovate-config are pinned by tag in every other repository, by `uvx` on every developer machine and in CI, and Renovate merges their minor releases on its own. Whoever can move or create one tag runs code everywhere.
- A token with write access to every repository (`webgrip-ci`, through team `ci`) was an organisation Actions secret, readable by any repository's workflow. With no rule on `main`, such a token could push to the GitOps repositories, which Flux applies without a person in between.
- A direct push skips every `pull_request` check: the 506 commits the owner landed directly on homelab-cluster's `main` in October 2026 never ran the `e2e /` jobs that guard Renovate's merges.

## Decision Drivers

* A rule that people follow is not a control; the server has to refuse the push.
* The repositories that every other repository executes, and the ones Flux deploys, carry the supply-chain risk.
* Two developers today, more later: the rule must work with two and scale without a redesign.
* Renovate keeps landing updates where nothing else needs a person.

## Considered Options

* Nobody pushes to any `main`; the core repositories also need one approval; only the release bot creates tags
* Nobody pushes to any `main`, no approvals anywhere
* One approval on every repository
* Keep ADR-0050 as it is and only add tag protection

## Decision Outcome

Chosen option: "Nobody pushes to any `main`; the core repositories also need one approval; only the release bot creates tags", because it closes direct pushes and tag moves for every identity, human or bot, and spends a second person's time only where a bad change reaches every repository or production.

The repo-config model carries it as two profiles:

| Profile | Repositories | `main` | Tags |
| --- | --- | --- | --- |
| `protected-core` | agent-standards, workflows, renovate-config, homelab-cluster, unfold-cluster | no push for anyone; merge through a pull request by the merge whitelist; one approval, stale approvals dismissed, a rejecting review blocks, an outdated branch blocks; fast-forward and rebase merges off, so every new `main` HEAD is a merge or squash commit Forgejo signs and Flux's signature check accepts; the repository's required checks | only `webgrip-ci` creates or updates any tag |
| `protected` | every other active Forgejo repository | no push for anyone; merge through a pull request by `ryangr0`, `yon` or `renovate`; the repository's required checks | only `webgrip-ci` creates or updates any tag |

Archived repositories stay on `baseline`: they are read-only already. A repository-level rule only adds to its profile (status checks, a narrower or wider merge list): unfold-cluster keeps `ryangr0` as its only merger (identity-and-access G-01), and unfold's `development` adds `ploeg-release`, which merges the Ploeg pin pull requests. Releases stop committing to `main`: semantic-release only tags (decided the same day), so the release bot needs no push right, only the tag whitelist.

### Consequences

* Good, because no token, leaked or not, can push to `main` or move a release tag; a release tag can only come from the release pipeline.
* Good, because every change to the GitOps repositories runs the checks Flux relies on before it is applied.
* Bad, because the owner can no longer iterate on homelab-cluster at trunk speed: every change is a pull request with green checks and, in the core repositories, an approval from the other developer. An author cannot approve their own pull request, so with two developers each waits for the other.
* Bad, because Renovate's minor updates in the core repositories wait for a human approval instead of merging themselves, and Renovate's branch automerge in homelab-cluster becomes pull-request automerge.
* Bad, because a break-glass change while the other developer is away needs a site administrator to lift the rule by hand; the hourly repo-config apply puts it back. See the [runbook](../runbooks/forgejo-branch-protection-rollout.md#break-glass).
* Neutral: `apply_to_admins` is not in the svalabs/forgejo provider, so a repository administrator can still force-merge past approvals and checks in the web UI. That is the break-glass path; it is visible in the pull request.

### Confirmation

- `scripts/validate-repo-config-model.sh` fails when an active Forgejo repository is off `protected` or `protected-core`, when a core repository is on `protected`, when any rule lists a pusher, and when `protected-core` asks for no approval; `scripts/test-validate-repo-config-model.sh` proves each case both ways.
- The repo-config Terraform object applies `forgejo_branch_protection` and `restapi_object.tag_protection`; `curl -s $API/repos/webgrip/<repo>/branch_protections` shows `enable_push: false` and `curl -s $API/repos/webgrip/<repo>/tag_protections` shows `*` with `webgrip-ci`.
- A push to `main` as `ryangr0` is refused with `Not allowed to push to protected branch main`.

## More Information

- Amends [ADR-0050](adr-0050-per-repo-delivery-contract.md) points 1 and 2: the owner's trunk push and the release bot's push whitelist are gone; the server-enforced contract, the janitor and the harness guard stay.
- 2026-10-26 — decided by Ryan Grippeling: core repositories need one approval, elsewhere none; releases only tag; signed commits for the GitOps repositories follow in their own change.
- 2026-10-27 — amended by [ADR-0086](adr-0086-a-repository-states-what-it-is-and-its-protection-follows.md): a repository says `core: true` instead of being named in the validator, five more repositories are core, and a workspace's named writer pushes its `main`.
