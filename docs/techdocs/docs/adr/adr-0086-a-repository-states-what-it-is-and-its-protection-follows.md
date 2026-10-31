---
status: accepted
date: 2026-10-31
decision-makers: Ryan Grippeling
---

# A repository states what it is, and its protection follows

## Context and Problem Statement

[ADR-0083](adr-0083-nobody-pushes-to-main-and-core-repositories-need-a-second-person.md) put every active Forgejo repository on `protected` or `protected-core` and named the five core repositories in the validator. Within a day three gaps showed:

- twente.dev's `development` branch was deleted when its promotion pull request merged with "delete branch after merge" on. Its open Renovate pull request moved to `main` and the post-release safety net failed. Only unfold had a rule on `development`, written by hand.
- semantic-release-config, infrastructure, ai-skills, frontend-toolkit and action-typescript-template run in other repositories (the release config, the CI images, the skills and hooks on developer machines, an npm package, an action), but sat on `protected` without an approval.
- obsidian-vault and previews were outside the model, because an account pushes their `main` directly.

A first fix (pull request #934) gave every repository a protection `kind` (`gitops`, `supply-chain`, `app-promoted`, nine in all) that picked a profile. While it waited, [ADR-0078](adr-0078-one-release-recipe-four-kinds.md) gave every repository a `kind` too: what it ships (`service`, `image-set`, `package`, `site`, `config`, `none`). Two classifications under one key cannot both stand, and most of the nine restated rules that already existed: "core" is ADR-0083's list, "promoted" is ADR-0078's staged branch shape, "archived" is a setting, and four kinds changed nothing but a Renovate default.

Settings reach a repository from eight places today (repo-config, renovate-config presets, the Renovate operator, agent-standards packs, workflows, semantic-release-config, the CI secrets provisioner, Forgejo and Flux signing), and four of them pick something per repository on their own. How does a repository say what it is once, so its protection and the other places follow?

## Decision Drivers

* One classification per repository, the one ADR-0078 already made; no second system.
* Only the protection standards that really differ get a name.
* What applies to a repository can be read from the model, and a pull request shows it before it lands.
* A repository's own rule can make its protection stricter, never weaker, without a second look.
* A required check that a repository never reports blocks every merge.

## Considered Options

* ADR-0078's `kind` as the one key, the profile derived from it and three per-repository facts (`core`, `staged`, `writer`)
* A second, protection `kind` that picks a profile (pull request #934 as first written)
* A profile per repository, as ADR-0083 left it

## Decision Outcome

Chosen option: "ADR-0078's `kind` as the one key", because it names what a repository is once, keeps the three profiles that really differ, and states the few facts a release kind cannot tell as facts instead of as more kinds.

How others solve the same problem shaped the details. GitHub targets organisation rulesets by a repository's custom properties instead of by name lists; safe-settings applies organisation, then sub-organisation, then repository settings in a fixed order and runs a dry run on every pull request; a GitHub repository ruleset can only add to an organisation ruleset, never relax it; Backstage classifies a component by one `spec.type` and a `lifecycle`; Allstar covers every repository unless one opts out; Prow's branchprotector only requires jobs that always run; OpenSSF Scorecard grades branch protection in tiers, the second of which is one approving review.

1. **One key.** A Forgejo repository in `repos.yaml` states its ADR-0078 `kind` and never names a profile. GitHub repositories keep their `profile`; they are all `baseline` mirrors or rulesets of their own.
2. **The profile is derived**, in this order: `settings.archived: true` gives `baseline`, `writer` gives `workspace`, `core: true` gives `protected-core`, anything else `protected`.
3. **One resolution order**, the same in the Terraform module and in the validator: profile, then the `staged` layer, then the writer's push, then the repository's own rule. The repo-config Terraform object stores a readable plan of every apply.
4. **Core is a property.** `core: true` replaces the list of names in the validator. The repositories ADR-0083 named keep a guard: dropping `core` from one of them fails the validator.
5. **`staged: true`** adds the `staged` layer of `profiles.yaml`: a `development` rule (nobody pushes; `ryangr0`, `yon` and `renovate` merge), fast-forward merges on, and the branch kept after a merge. This is ADR-0078's staged branch shape, declared where it holds today: unfold, twente.dev, seekframe, erfbeeld and compyutah.
6. **`writer: <account>`** is the only way an account pushes: it puts the repository on the new `workspace` profile, where that account pushes `main` and nothing else does. obsidian-vault (`ryangr0`, through the Obsidian git plugin) and previews (`agent-builder`) enter the model this way.
7. **A repository rule only tightens.** The validator refuses a repository rule that lowers `required_approvals` or turns off `dismiss_stale_approvals`, `block_on_rejected_reviews` or `block_on_outdated_branch` where its profile sets them, and every pusher outside a workspace's `main`.
8. **The kind carries the Renovate default.** `kinds` in `profiles.yaml` maps `service` to `profile-app`, `site` to `profile-site`, `package` to `profile-library` and `image-set` to `profile-image-set`. A repository that states no Renovate policy gets its kind's, the drift check compares the live `renovate.json` against it, and the validator refuses a policy that only repeats the default.
9. **Every repository is covered.** The `every_active_repo_is_modelled` check warns on every hourly plan when a Forgejo repository that is neither archived nor a mirror is missing from the model. It reads the organisation anonymously, so it sees public repositories only.
10. **Only pull request checks are required.** The validator refuses a required context that does not end in `(pull_request)` or `(pull_request_target)`.

Decisions carried over from pull request #934, 2026-10-27, by Ryan Grippeling:

- semantic-release-config, infrastructure, ai-skills, frontend-toolkit and action-typescript-template are core: one approval, no fast-forward or rebase merges.
- erfbeeld and compyutah keep their `development` branches and protect them; unfold now keeps its branch after a merge too.
- obsidian-vault and previews enter the model with their writer.
- A repository requires a check only when it reported that check on each of its last 12 pull requests: agent-standards, ai-skills, renovate-config, semantic-release-config and omnigraph-explorer, next to the lists homelab-cluster, unfold, unfold-cluster and talos-kata-extension already had.
- CODEOWNERS is not generated yet; with two developers a review request reaches the right person anyway.

### Consequences

* Good, because a new repository gets its protection and its Renovate default from its kind and at most three facts, and a promoted application cannot lose its `development` branch.
* Good, because one key now exists that agent-standards (`agentstd init`) and a workflows check can read next, instead of each guessing from a repository's files.
* Good, because a repository rule that weakens protection fails before review, and a new public repository outside the model shows up in the hourly checks.
* Bad, because the five new core repositories wait for a second person's approval, Renovate's minor updates included.
* Bad, because most repositories still require no check: a check has to run on every pull request first, and twente.dev and webgrip.nl report theirs on `push`.
* Neutral: `staged` is declared, not derived from the kind. ADR-0078 makes every service and site staged, but omnigraph-explorer, counterscale and webgrip.nl have no `development` branch yet; each turns `staged` on when it gets one.

### Confirmation

- `scripts/validate-repo-config-model.sh` resolves every Forgejo repository through the derivation above; `scripts/test-validate-repo-config-model.sh` proves each rule both ways: a repository that names a profile, a core repository from ADR-0083 without `core`, an archived repository with `core`, a core repository with a writer, a writer on another branch, someone else pushing a workspace's `main`, a `staged` layer that reopens push, a rule that lowers approvals or turns off a review guard (and one that raises approvals, which passes), a Renovate policy that repeats the kind default (and one that differs, which passes), and a required check reported on `push` (and one on `pull_request_target`, which passes).
- `tofu console` on the module renders the same settings, branch rules, tag rules and Renovate policies as pull request #934 did, rebased on `main`.
- The coverage check, run against live Forgejo, passes on the model and fails when a modelled repository is taken out.

## More Information

- Amends [ADR-0083](adr-0083-nobody-pushes-to-main-and-core-repositories-need-a-second-person.md) (core is `core: true`, five more repositories are core, a workspace's writer pushes) and [ADR-0078](adr-0078-one-release-recipe-four-kinds.md) (the kind carries the Renovate default; `staged` declares the branch shape).
- Rules per repository: [Forgejo branch protection](../runbooks/forgejo-branch-protection-rollout.md).
- Sources: [GitHub ruleset targeting by property](https://github.blog/changelog/2025-06-23-filter-based-ruleset-targeting), [safe-settings](https://github.com/github/safe-settings), [Prow branchprotector](https://docs.prow.k8s.io/docs/components/optional/branchprotector/), [Allstar](https://github.com/ossf/allstar), [OpenSSF Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md).
- 2026-10-27 — decided by Ryan Grippeling: one key per repository instead of a second protection kind.
- 2026-10-27 — amended: GitHub repositories no longer keep their `profile` (rule 1). It is derived the same way, and today every GitHub entry derives `baseline`, the one profile with a `github` block; the schema refuses `profile` on either forge. This also amends [ADR-0085](adr-0085-github-push-mirrors-are-tracked-in-the-model-and-reconciled-for-drift-and-releases.md) rule 1: an active mirror is `{forge: github, mirror_of: <name>}`.
- 2026-10-27 — amended: rule 9's coverage check moved out of tofu into the hourly CronJob `repo-config/repo-config-inventory`, which lists the organisation with a read-only token (`read:organization`, `read:repository`, minted by `forgejo/repo-config-provisioner`) and so sees private repositories too. It publishes `repo_config_unmodelled_repository` per active repository to vmagent; `ForgejoRepositoryNotInRepoConfigModel` warns after 2h and `ForgejoRepoInventoryStale` after 3h without a successful run. The tofu check `every_active_repo_is_modelled` and its anonymous `data "http" "org_repos"` are gone: OpenTofu cannot pass the module's ephemeral token to a `data "http"` source. The per-repository drift checks stay in tofu and still read public repositories only. `scripts/test-repo-config-inventory.sh` proves the job both ways ([runbook](../runbooks/forgejo-branch-protection-rollout.md#every-repository-is-in-the-model)).
- 2026-10-31 — amended: rule 8's kinds carry the renovate-config gates instead of the profile names, which renovate-config keeps only as generated aliases: `service` and `site` take `reviewed`, `package` takes `unattended`, `image-set` takes `unattended` plus `docker-arg-pins`. The model key is `renovate.gate`, and every Forgejo repository with a Renovate config moves to the gates through a pull request of its own.
- 2026-10-31 — amended by [ADR-0088](adr-0088-one-branch-every-merge-releases-and-environments-promote-the-artifact.md):
  `staged: true` is retired as repositories move to artifact promotion, and a repository states its
  release layout (`single`, `trains`, `upstream`) next to its kind.
