---
status: accepted
date: 2026-10-31
---

# One branch, every merge releases, and environments promote the artifact

## Context and Problem Statement

[ADR-0078](adr-0078-one-release-recipe-four-kinds.md) points 6 and 7 stage a repository whose bad
release breaks more than itself: `development` cuts release candidates, `main` cuts stables, and a
fast-forward promotes one to the other. In twente.dev, the one repository that runs the shape end to
end, that takes a second branch, Renovate aimed at it, a channel parser, a promotion pull request, a
back-merge safety net and a production deploy that rebuilds: about 170 copied lines, and a
divergence failure that needs a person. Production still does not run the bytes staging ran.

Separately, repositories version in three ways the kinds do not name: one train, several trains
(ai-skills, frontend-toolkit, infrastructure, Erfbeeld, Unfold, each with its own tooling), and a
version taken from upstream (talos-kata-extension).

How does a repository put a change in front of users safely, with the fewest moving parts, and how
does it say how it versions?

## Decision Drivers

* Production runs the artifact staging ran, not a rebuild.
* Promotion and rollback are one deliberate step each.
* No state that two branches must keep in step.
* Renovate, branch protection and the release job have one branch to know about.
* One shared release action covers every way the estate versions.

## Considered Options

* One branch, every merge releases, environments promote the artifact
* Keep staged branches and move twente.dev's workflow into shared actions
* Keep staged branches as they are

## Decision Outcome

Chosen option: "One branch, every merge releases, environments promote the artifact", because it
removes every part that exists only to keep `development` and `main` in step, and it is the only
option in which production runs the bytes staging ran.

1. **`main` is the only long-lived branch.** A releasing merge cuts `vX.Y.Z`; there is no `-rc`
   channel and no `development`. `@webgrip/semantic-release-config` defaults its branches to `main`
   plus maintenance ranges.
2. **The release builds once and stages without a person.** Sites and Workers upload a Workers
   version tagged with the release; services publish a signed digest that staging follows;
   packages, presets, reusable workflows and image sets reach their one named canary consumer at
   once (`minimumReleaseAge: 0`).
3. **Production is a promote of that artifact.** Sites: `wrangler versions deploy` of the tagged
   version, optionally gradual. Services: a pull request moving the production pin. Packages: the
   other consumers' Renovate pull requests after the soak. Rollback promotes the previous version.
4. **A hotfix that must skip unreleased work** goes on a maintenance branch cut from the stable tag.
5. **A repository states its release layout** in the repo-config model, next to its kind:
   `single` (commits, `vX.Y.Z`), `trains` (commits scoped per directory, `<train>-vX.Y.Z`, every
   train in one job) or `upstream` (a version file, tagged when new). The shared `semantic-release`
   composite action runs all three in a normal job on the one toolchain image.
6. **Previews** are for repositories a person judges by looking: sites (Workers preview URLs) and
   single-page apps (preview-host).

This replaces ADR-0078 points 6 and 7 and the `staged` shape of
[ADR-0086](adr-0086-a-repository-states-what-it-is-and-its-protection-follows.md). Every other
point of ADR-0078 stands.

### Consequences

* Good, because promotion PRs, back-merges, channel parsers and Renovate base-branch overrides
  disappear from every repository.
* Good, because rollback is a promote of a version that already ran in staging.
* Good, because ai-skills, frontend-toolkit, infrastructure, Erfbeeld, Unfold and
  talos-kata-extension release through the shared action instead of their own scripts.
* Bad, because `main` carries released work that production does not run yet; the promote is the
  record of what does.
* Bad, because a site's production artifact lives in Cloudflare's version store, which we do not
  control; a missing version fails the promote and is re-uploaded from the tag.
* Bad, because Unfold, Erfbeeld and twente.dev migrate off `development`, Unfold last, on its own
  plan.

### Confirmation

* No repository in the repo-config model sets `staged: true`, and none has a `development` branch.
* `@webgrip/semantic-release-config` defaults its branches to `main` and maintenance ranges, and
  no release configuration in the estate names `development`.
* A merge to webgrip.nl puts a new version on staging with no hand step, and promoting it changes
  production without a build; `wrangler versions list` shows the same version id in both.
* The Delivery estate board shows a release layout for every deliverable and no repository with
  release path `none`.

## Pros and Cons of the Options

### One branch, every merge releases, environments promote the artifact

* Good, because one branch serves releases, Renovate and branch protection.
* Good, because the promote moves a known artifact, so staging and production cannot disagree on
  what was built.
* Neutral, because every merge produces a version, so version numbers climb faster.
* Bad, because the release workflows, the promote action and three staged repositories change.

### Keep staged branches and move twente.dev's workflow into shared actions

* Good, because the copied lines become one shared action per part.
* Bad, because the second branch, its Renovate override and the divergence failure all remain.
* Bad, because production still rebuilds at the stable tag.

### Keep staged branches as they are

* Good, because nothing changes.
* Bad, because every newly staged repository copies about 170 lines and inherits the divergence
  failure.

## More Information

* Technical story: [RFC: Promote the artifact, not the branch](../rfc/rfc-artifact-promotion.md).
* 2026-10-31 — Accepted. The owner chose artifact promotion over staged branches, release layouts
  `single`, `trains` and `upstream` in the shared action, and previews for sites and single-page
  apps, with product sites for fogbell and wellhead to follow.
* Refines [ADR-0078](adr-0078-one-release-recipe-four-kinds.md): replaces points 6 and 7.
* Refines [ADR-0086](adr-0086-a-repository-states-what-it-is-and-its-protection-follows.md):
  `staged` is retired as repositories migrate; a repository adds `release` next to `kind`.
