---
status: accepted
date: 2026-11-01
---

# Tooling repositories release in layers

## Context and Problem Statement

[ADR-0088](adr-0088-one-branch-every-merge-releases-and-environments-promote-the-artifact.md)
point 5 gives every repository a release layout run by one shared release action. The repositories
that build that action released through each other:

* `semantic-release-config` released with a `webgrip/workflows` composite action that ran in the
  config's own image, so the config needed a workflows release and workflows needed a config
  release.
* `webgrip/workflows` ran its policy tests in the `semantic-release:0.3.x` image that
  `webgrip/infrastructure` built, while infrastructure called workflows at `@main` and at SHAs with
  no version label.
* Two repositories pushed to `harbor.webgrip.dev/webgrip/semantic-release`: infrastructure on a
  0.x line and semantic-release-config on 1.x and 2.x. Which image a tag meant depended on who
  pushed last.

On 2026-10-31 and 2026-11-01 a change in any of the three needed a release of another before it
could release itself, and a broken release could not be repaired from either side alone. How do
the tooling repositories depend on each other so that each can always release on its own?

## Decision Drivers

* Every tooling repository can cut a release when every other one is broken.
* Release logic exists once; everything else calls it.
* An image name has one meaning.
* A broken seam between two repositories fails a test before it fails a release.
* A consumer learns about a new release without anyone watching for it.

## Considered Options

* Layers: one release image carrying the command, wrappers call it, consumers pin, contract tests
  at every seam, releases trigger Renovate on consumers
* Keep the release logic in a `webgrip/workflows` composite and break the loop by hand when it
  bites
* Merge the tooling repositories into one repository

## Decision Outcome

Chosen option: "Layers", because it is the only option that removes the cycles instead of
working around them, and it keeps the three repositories as separate products with their own
consumers.

1. **The layers, bottom up.** A repository may depend at release time only on a lower layer, and
   only at a released version.
   1. `semantic-release-config` is the bottom layer. It ships the `webgrip-release` command
      (layouts `single`, `trains` and `upstream`, tag seeding, align and retry, step outputs) in its
      npm package and in the image `harbor.webgrip.dev/webgrip/semantic-release:<config version>`,
      and it releases itself with that command from its own tree. It depends on no other webgrip
      tooling repository to release.
   2. `webgrip/workflows` wraps commands; it never copies their logic. Its `semantic-release`
      composite maps its inputs onto `webgrip-release` options and nothing more. Its own tests run
      on a public base image with their own dependencies, not on an image another tooling
      repository builds. Reusable workflows may still name infrastructure images as defaults for
      their callers' jobs, pinned by tag and digest; that is a reference a consumer runs, not a
      dependency of the workflows release.
   3. `webgrip/infrastructure` and every application repository release with `webgrip-release`,
      from the config image or a root npm toolchain pinned to a config version, and call
      `webgrip/workflows` only at a released version.
2. **Pins name a version.** A reference to a tooling repository is `@vX.Y.Z` or
   `@<40-character SHA> # vX.Y.Z`. `@main`, another branch, a floating `@vN` tag, a short SHA and a
   SHA without a version label are not allowed. A repository referencing its own files is outside
   this rule.
3. **Bootstrap.** A new tooling repository seeds `v0.0.0` (or `<train>-v0.0.0` per train) at its
   root commit and releases with `webgrip-release` from the config image. It needs no release of
   any other repository to cut its first version.
4. **One producer per image name.** Each `harbor.webgrip.dev/webgrip/<name>` has exactly one
   repository that pushes to it. `semantic-release` belongs to `semantic-release-config`;
   infrastructure retired its 0.x `semantic-release` and `semantic-release-monorepo` images. A
   retired name with no successor is removed from Harbor through the provisioner's
   `retired-repositories` list once no repository pulls it.
5. **A contract test at every seam.** Where one layer calls another, a test in the caller runs the
   callee's real code at the pinned version: the config image proves the command it ships, and the
   workflows composite feeds its input mapping into the real `parseOptions` of the pinned config.
6. **Releases trigger Renovate on consumers.** A tooling release starts a Renovate run on the
   repositories that consume it, so a new version arrives as a pull request without a person
   asking for it. Pins move only through those pull requests.

### Consequences

* Good, because each tooling repository can release while the others are broken, and a fix to the
  release command ships from one repository.
* Good, because a wrong option mapping in workflows fails its own contract test against the real
  config, not a consumer's release.
* Good, because a Harbor tag means one thing, so a digest pin cannot pick up another repository's
  image.
* Bad, because the workflows composite became a breaking change (v4.0.0), and every consumer moves
  through a Renovate pull request.
* Bad, because a pin at a version needs a release and a Renovate run before a fix in a lower layer
  reaches a consumer; `@main` reached it at once.
* Bad, because existing `@main` and label-less pins are violations from today and are fixed
  repository by repository.

### Confirmation

* `scripts/check-tooling-pins.sh <repository-dir>...` scans each repository's `.forgejo/**/*.yml`
  and `.yaml` for a `uses:` of `webgrip/semantic-release-config`, `webgrip/workflows` or
  `webgrip/infrastructure` that is not pinned as in point 2, prints `file:line` for each, and exits
  with status 1. `scripts/test-check-tooling-pins.sh` proves it against fixtures, in e2e CI. Run it over the
  local clones at `origin/main`; it passes once every estate repository is pinned. On 2026-11-01
  it reported 25 references: 19 in erfbeeld, 3 in homelab-cluster and 3 in infrastructure.
* `git grep -nE 'webgrip/(workflows|infrastructure)/' origin/main -- .forgejo` in
  `semantic-release-config` finds nothing. On 2026-11-01 it found three references to
  `webgrip/workflows` at v3.4.0: the `agents-check` workflow and, in `on_release_published.yml`,
  the `docker-build-push-registry-fast` and `cosign-sign-attest` composites that build and sign
  the image after the tag is cut.
* `git ls-tree -d origin/main ops/docker/semantic-release ops/docker/semantic-release-monorepo` in
  infrastructure prints nothing, so no second repository builds either image.
* `harbor.webgrip.dev/webgrip/semantic-release-monorepo` is listed in the Harbor provisioner's
  `retired-repositories` and absent from Harbor.

## Pros and Cons of the Options

### Layers

* Good, because the dependency graph has no cycle, so there is always a repository that can
  release first.
* Good, because the contract tests turn a broken seam into a red pull request.
* Neutral, because each layer keeps its own release cadence.
* Bad, because a change that spans layers takes one release per layer, bottom up.

### Keep the release logic in a workflows composite and break the loop by hand

* Good, because nothing moves.
* Bad, because the cycle stays, and the next breaking change in either repository needs a person
  to release one of them by hand.
* Bad, because the release logic stays split between a composite and the image it runs in.

### Merge the tooling repositories into one repository

* Good, because one commit changes every layer at once.
* Bad, because the npm package, the reusable workflows and the image set have different consumers
  and release cadences, and one repository would release all three for any change.
* Bad, because it undoes the per-product boundaries every consumer already pins against.

## More Information

* 2026-11-01 — Accepted. The owner chose one release image carrying the command, releases
  triggering Renovate on consumers, and contract tests as the floor, after the cycles between
  semantic-release-config, workflows and infrastructure blocked releases on 2026-10-31. Delivered
  in:
  * semantic-release-config [#46](https://forgejo.webgrip.dev/webgrip/semantic-release-config/pulls/46)
    and [#48](https://forgejo.webgrip.dev/webgrip/semantic-release-config/pulls/48): the
    `webgrip-release` command in the npm package and in `semantic-release:<config version>`, with
    a contract check in that image (2.4.0, 2.5.0).
  * infrastructure [#188](https://forgejo.webgrip.dev/webgrip/infrastructure/pulls/188): every
    image releases with `webgrip-release` from the root npm toolchain;
    [#189](https://forgejo.webgrip.dev/webgrip/infrastructure/pulls/189): the 0.x
    `semantic-release` and `semantic-release-monorepo` images are retired.
  * workflows [#108](https://forgejo.webgrip.dev/webgrip/workflows/pulls/108): policy tests run on
    `node:24-trixie` with their own `yaml` dependency;
    [#111](https://forgejo.webgrip.dev/webgrip/workflows/pulls/111): the `semantic-release`
    composite wraps `webgrip-release`, with a contract test against the pinned config's
    `parseOptions` (v4.0.0).
* 2026-11-01 — Not yet done: release-triggered Renovate (point 6) is being built; existing
  `@main` and label-less pins remain (Confirmation, first check); the Harbor repository
  `webgrip/semantic-release-monorepo` stays until Unfold stops pulling
  `semantic-release-monorepo:0.3.4` in its pull request and release workflows; and workflows'
  reusable `semantic-release-monorepo.yml` still calls its own composite at `@main`, which point 2
  does not cover. `semantic-release-config` cuts its tag on its own, but still builds and signs
  its image with `webgrip/workflows` composites pinned at v3.4.0 (Confirmation, second check).
* Refines [ADR-0088](adr-0088-one-branch-every-merge-releases-and-environments-promote-the-artifact.md):
  point 5's shared release action is the `webgrip-release` command in the config image, and the
  workflows composite only wraps it.
