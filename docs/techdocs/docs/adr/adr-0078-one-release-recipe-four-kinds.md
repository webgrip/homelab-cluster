---
status: accepted
date: 2026-10-24
---

# One release recipe: semantic-release tags-only, four kinds of project, fast-forward promotion

Technical Story: [RFC: One release recipe, four kinds of project](../rfc/rfc-one-release-recipe.md).
Refines [ADR-0069](adr-0069-one-delivery-contract.md), whose five layers say what a release must
achieve; this record says how every repository achieves it. Owner answers R1 to R5 given on
2026-10-23 and 2026-10-24.

## Context and Problem Statement

A survey of 32 repositories on 2026-10-23 found five ways to cut a version, four versions of the
shared release config in use, three ways to install the release tooling, five branch models, seven
tag styles, six trigger styles and six registries. Only Unfold (carrying Ploeg) and two runner
images reached the homelab end to end without a person. Knowing how one project releases told you
nothing about the next.

Which single recipe does every repository follow, on Forgejo and GitHub alike, so that a repository
only has to declare what kind of thing it ships?

## Decision Drivers

* Code review stays the only routine human step; promotion to production is a deliberate second one.
* The forge matters in one place only.
* A GitHub release must not depend on the homelab being up, and the reverse.
* No release commit may race with concurrent agents pushing the same branch.
* Reuse what runs today: the shared config, its own Forgejo plugin, Harbor, Renovate.

## Considered Options

* semantic-release, hardened (tags only, one toolchain image, own monorepo trains)
* knope
* release-please
* git-cliff plus an estate-owned tagging script

## Decision Outcome

Chosen option: **semantic-release, hardened**, because it is the only option with branch-based rc
and stable channels that runs on Forgejo and GitHub today and is already in 15 repositories.
release-please supports the GitHub API only and adds a release PR as a second human step; knope is
promising but pre-1.0 with one maintainer and is piloted separately
([VIK-2314](https://vikunja.webgrip.dev/tasks/2314)); git-cliff leaves the release logic to us.

1. **Tags only.** No repository commits a release. The version is stamped into `Chart.yaml`,
   `package.json` or other manifests at package time from the tag.
2. **One toolchain.** The `semantic-release` image, pinned by tag and digest and moved by Renovate,
   carries `@webgrip/semantic-release-config`. It is published to Harbor and copied to GHCR so each
   forge's release job pulls from a registry with that forge's availability.
3. **Monorepo trains** come from the shared config, one train per package with tag format
   `<name>-v<version>`, replacing `semantic-release-monorepo` (no release since 2024-02).
4. **Strict input.** A release job fails on a non-conventional commit in its range instead of skipping
   silently, and runs in one concurrency group per branch.
5. **Four kinds.** Every repository is a **service** (images plus one chart), an **image set**, a
   **package** (npm package, preset, library chart, reusable workflow or action, skill) or a **site**
   (Cloudflare). OpenTofu and Flux trees are applied from `main`, not released.
6. **Branch shape by blast radius.** A repository is *staged* (`development` cuts
   `-rc.N`, `main` cuts stables) when a bad release breaks more than itself: services, sites,
   `workflows`, `renovate-config`, `semantic-release-config` and `infrastructure`. Each staged
   package or image set names one canary consumer on its `-rc` channel. Other packages are *trunk*
   (`main` cuts stables).
7. **Promotion is a fast-forward** of `main` to a commit of `development`; nothing is committed to
   `main` directly. When production needs a fix that `development` cannot ship yet, the fix goes on a
   maintenance branch cut from the stable tag (for example `0.4.x`), and also lands on `development`.
8. **One trigger shape.** A push cuts the version and the forge release; `release: published` builds,
   publishes, signs and deploys. Stables re-tag the candidate's digest instead of rebuilding.
9. **Registry is an input**, default `harbor.webgrip.dev/webgrip`; open-source projects pass GHCR.
   Images and charts are signed with the OpenBao Transit key on Forgejo and keyless on GitHub.
10. **Pinned references.** Reusable workflows refer to their own nested workflows at the same tag;
    callers pin `@<sha> # vX.Y.Z` and Renovate moves them.
11. **Dead release paths are archived** (R4) through the repo-config model; sites without versions
    (`webgrip.nl`, `counterscale`) become versioned sites (R5).

### Consequences

* Good, because a repository joins by declaring its kind; branches, tags, triggers and consumers
  follow from it.
* Good, because the tag-on-wrong-commit failures and release-commit push races cannot occur without
  a release commit.
* Good, because a GitHub release no longer fails when Forgejo is down (2026-10-23 05:05).
* Bad, because the shared config grows monorepo trains we own, replacing a third-party plugin.
* Bad, because two signing roots remain, one per forge.
* Bad, because staged packages need a canary consumer each, which is new wiring for `workflows`,
  presets and runner images.

### Confirmation

* `git grep -l '@semantic-release/git'` across the estate's release configs finds nothing.
* Every active repository in the repo-config model carries a kind, and its branch protection matches
  the kind's branch shape.
* A merge to a trunk package and to a staged service each release with no hand step, and the
  consumer's Renovate PR merges on green.
* A release job given a non-conventional commit fails; given only conventional commits it passes.

## Pros and Cons of the Options

### semantic-release, hardened

* Good, because branch channels match `development` and `main`, with official GitHub and GitLab
  plugins and our own Forgejo plugin.
* Bad, because two core plugins were still betas in October 2026 and the monorepo plugin is
  abandoned.

### knope

* Good, because it is one binary with monorepo support and Gitea releases.
* Bad, because it is pre-1.0, has one main maintainer, and lacks GitLab and release assets on Gitea.

### release-please

* Good, because release PRs give a readable changelog before release.
* Bad, because it talks to the GitHub API only and the release PR is a second human step.

### git-cliff plus a script

* Good, because git-cliff is healthy and forge-neutral.
* Bad, because tags, releases and rc counters become code we write and keep.

## More Information

* 2026-10-23 — Proposed. Owner answers: R1 semantic-release hardened plus a knope pilot; R3
  fast-forward with a maintenance-branch escape hatch; R4 the eight dead Forgejo repositories
  archived (homelab `5ef7a5b9`); R5 versioned sites. R2 refined to "branch shape by blast radius",
  awaiting confirmation.
* 2026-10-24 — Accepted. The owner confirmed R2 (branch shape by blast radius), chose to model
  GitHub repository settings in the same repo-config model ([VIK-2320](https://vikunja.webgrip.dev/tasks/2320)),
  to move the semantic-release toolchain images into `semantic-release-config`, and to archive
  `common-charts` and `application-template` (homelab `0fb4fbd8`).
