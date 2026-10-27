---
status: accepted
date: 2026-10-27
decision-makers: Ryan Grippeling
---

# A repository's kind decides its protection

## Context and Problem Statement

[ADR-0083](adr-0083-nobody-pushes-to-main-and-core-repositories-need-a-second-person.md) put every active Forgejo repository on `protected` or `protected-core`, with the five core repositories named in the validator. Three things it left open showed up within a day:

- twente.dev's `development` branch was deleted when its promotion pull request merged with "delete branch after merge" on. Its open Renovate pull request moved to `main` and the post-release safety net failed. Only unfold had a rule on `development`, written by hand.
- semantic-release-config, infrastructure, ai-skills, frontend-toolkit and action-typescript-template run in other repositories (the release config, the CI images, the skills and hooks on developer machines, an npm package, a GitHub-style action) but sat on `protected` without an approval.
- 24 of 26 active repositories required no check at all, and obsidian-vault and previews were outside the model because a bot or a plugin pushes their `main`.

An inventory of every repository (2026-10-27) grouped them by what they are, and the groups decide the protection better than a per-repository profile name does.

## Decision Drivers

* One field per repository, read by the existing model and validator; no second system.
* The profiles stay the building blocks; a kind only picks one and adds what every repository of that kind needs.
* A required check that a repository never reports blocks every merge, so a check is only required where it runs on every pull request.

## Considered Options

* A `kind` per repository that resolves to a profile, adds kind-wide settings, branch rules and a Renovate default, and is checked by the validator
* More profiles (`protected-app-promoted`, `protected-workspace`, …), one per combination
* Keep per-repository rules for long-lived branches and widen the core list by hand

## Decision Outcome

Chosen option: "a `kind` per repository", because it names what a repository is once and lets every rule follow from it, without multiplying profiles.

`profiles.yaml` carries a `kinds` map next to `profiles`; every Forgejo repository in `repos.yaml` names its `kind` instead of a profile. A repository may still name a `profile`, only together with a `profile_reason`.

| Kind | Profile | Adds | Repositories |
| --- | --- | --- | --- |
| `gitops` | `protected-core` | — | homelab-cluster, unfold-cluster |
| `supply-chain` | `protected-core` | Renovate default `profile-library` | agent-standards, workflows, renovate-config, semantic-release-config, infrastructure, ai-skills, frontend-toolkit, action-typescript-template |
| `app-promoted` | `protected` | a `development` rule (no push; merges by `ryangr0`, `yon`, `renovate`; a protected branch cannot be deleted), delete-branch-after-merge off, fast-forward on; Renovate default `profile-app` | unfold, twente.dev, seekframe, erfbeeld, compyutah |
| `app` | `protected` | Renovate default `profile-app` | omnigraph-explorer, telemetry-service, webgrip.nl, counterscale |
| `infra` | `protected` | — | cloudflare, talos-kata-extension |
| `bench` | `protected` | Renovate `absent` | ploeg-bench, ploeg-bench-world (the harness's `bench/*` branches stay free) |
| `workspace` | `workspace` | Renovate `absent` | obsidian-vault, previews |
| `profile` | `protected` | — | `.profile` |
| `archived` | `baseline` | — | every archived repository |

`workspace` is a new profile: `main` cannot be deleted or force-pushed and only the named writer pushes (obsidian-vault: `ryangr0`, through the Obsidian git plugin; previews: `agent-builder`). Nothing else changes there: a person still edits notes and a bot still publishes previews directly.

Decisions taken with it, 2026-10-27, by Ryan Grippeling:

1. The kind is the source of a repository's profile.
2. semantic-release-config, infrastructure, ai-skills, frontend-toolkit and action-typescript-template are `supply-chain`, so they need one approval and lose fast-forward and rebase merges.
3. erfbeeld and compyutah keep their `development` branches as `app-promoted` instead of deleting them.
4. obsidian-vault and previews enter the model as `workspace`.
5. A kind may carry a default set of required checks, and a repository adds its own. Today no check is reported on every pull request across a whole kind: the `Agents check` contexts are the natural default, but that workflow runs only when agent files change. So every kind's default is empty, and the repositories that report a check on every pull request require it themselves: agent-standards, ai-skills, renovate-config, semantic-release-config and omnigraph-explorer, next to the lists homelab-cluster, unfold, unfold-cluster and talos-kata-extension already had.
6. CODEOWNERS is not generated yet; with two developers a review request reaches the right person anyway.

### Consequences

* Good, because a new repository gets its whole protection from one line, and a promoted application cannot lose its `development` branch.
* Good, because the validator checks the kinds, not a list of names: a `gitops` or `supply-chain` kind that resolves to anything but `protected-core` fails, and so does an active repository on `baseline` or a pusher outside a `workspace`.
* Bad, because the five new `supply-chain` repositories now wait for a second person's approval, Renovate's minor updates included.
* Bad, because most repositories still require no check: a check has to run on every pull request before it can be required, and twente.dev and webgrip.nl report their checks on `push`, not on `pull_request`.
* Neutral: the Renovate default of a kind only applies to a repository that states no Renovate policy; every repository in the model states one today.

### Confirmation

- `scripts/validate-repo-config-model.sh` resolves every repository through its kind; `scripts/test-validate-repo-config-model.sh` covers an unknown kind, a profile override without a reason, an override that repeats the kind's profile, a `supply-chain` kind off `protected-core`, a core repository on the wrong kind, an archived repository that is not kind `archived`, and a `workspace` repository without a writer, each with a case that must pass.
- Every rendered branch rule validates against the svalabs/forgejo 1.7.0 provider before it reaches the cluster.

## More Information

- Amends [ADR-0083](adr-0083-nobody-pushes-to-main-and-core-repositories-need-a-second-person.md): the core repositories are the `gitops` and `supply-chain` kinds instead of a named list, and promoted applications protect `development`.
