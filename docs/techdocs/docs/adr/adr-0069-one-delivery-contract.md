---
status: accepted
date: 2026-10-17
---

# One delivery contract: forges produce, registries carry, clusters consume

Technical Story: [RFC: One delivery contract for every project](../rfc/rfc-unfold-release-train.md).
Builds on [ADR-0050](adr-0050-per-repo-delivery-contract.md) (branch protection and the PR flow per
repository). Decided by the owner on 2026-10-17.

## Context and Problem Statement

A one-line Ploeg fix needed eight hand steps to reach the homelab, spread over three release models:
Ploeg cuts releases with a hand-written prepare PR and a hand-pushed tag on GitHub; the Forgejo repos
use semantic-release through `@webgrip/semantic-release-config`; the homelab pins for Ploeg, Unfold
and both runner images were all bumped by hand. Erfbeeld alone reaches the homelab with no hand step:
its `development` branch cuts prereleases, `main` cuts stables, and Renovate automerges each channel
into the matching environment.

Projects live on more than one forge (Forgejo, GitHub, possibly GitLab or Bitbucket later). The
question is what single process every project plugs into, whichever forge hosts it.

## Decision Drivers

* One human step per change: reviewing the code.
* The forge must not matter after the release is cut.
* Reuse what is proven in this estate (Erfbeeld's channel model, the shared semantic-release config,
  the Harbor proxy, Renovate) instead of building a new bot.
* A project joins by adding files, not by negotiating a process.

## Considered Options

* One contract in five layers, with a forge adapter as the only per-forge part
* A custom release-train bot in the homelab that reads a release manifest and opens the bump PR
  (the RFC's first draft)
* Keep per-project release processes and document them

## Decision Outcome

Chosen option: **one contract in five layers**, because it removes every hand step on the current map
with machinery that already runs here, and confines forge differences to one adapter.

1. **Branches.** `development` cuts `-rc.N` prereleases; `main` cuts stables. Merging `development`
   into `main` in the project's repository is the only promotion act.
2. **Release.** semantic-release with `@webgrip/semantic-release-config`. The project's **home forge**
   is its release authority; a forge adapter selects the platform plugin (Gitea for Forgejo, GitHub,
   GitLab; tags and notes only for Bitbucket). This replaces the config's rule that Forgejo is the sole
   release authority. Every releasable merge to `development` (`feat`, `fix`, `perf`, `refactor`,
   `revert`, dependency bumps) cuts a candidate.
3. **Artifacts.** Every deployable is an OCI image and an OCI Helm chart, pushed by digest, signed,
   with an SBOM. Open-source projects publish to GHCR, private ones to Harbor; clusters pull through
   Harbor.
4. **Consumption.** Renovate reads registries, never forges. One shared preset maps channels to
   environments: the **prerelease** channel automerges every candidate, the **stable** channel
   automerges stables only. The homelab is the prerelease channel; customer clusters take the stable
   channel. A dependency between projects (Unfold on Ploeg) is a released version Renovate bumps,
   never a source submodule.
5. **Verify.** After Flux applies a bump, a check confirms readiness and the running digest. Failure
   reverts the bump and pages; success records a deploy event.

### Consequences

* Good, because the current eight hand steps go to zero, and a new project joins with a 3-line
  release config, one CI wrapper and one channel entry.
* Good, because GitHub, Forgejo, GitLab and Bitbucket differ only in the adapter and its CI wrapper.
* Good, because Unfold stops building and testing Ploeg's source, which removed one class of
  release-blocking failure (2026-10-04).
* Bad, because every Ploeg merge becomes a candidate, so tags multiply.
* Bad, because a faulty candidate reaches the homelab without a person in between; the verify layer
  and the e2e checks carry that risk.
* Bad, because Ploeg ADR-0063 and ADR-0064, Unfold ADR-0019 and the shared config's release-authority
  rule each need a superseding record in their own repository.

### Confirmation

* A Ploeg merge to `development` produces a tagged `-rc.N` release with chart version and CHANGELOG
  written, and no hand step.
* That release reaches Unfold through a Renovate automerge, and the homelab through a Renovate
  automerge, each gated by its CI.
* A deliberately broken candidate is reverted by the verify layer and pages.
* `grep` over the homelab's Ploeg, Unfold and runner pins finds no pin Renovate does not manage.

## Pros and Cons of the Options

### One contract in five layers

* Good, because it reuses Erfbeeld's proven channel rules and the shared release config.
* Bad, because the forge adapter is new work in the shared config.

### A custom release-train bot

* Good, because it can bump a certified pair in one PR.
* Bad, because it is a second writer beside Renovate and one more component to keep alive.

### Per-project processes

* Good, because nothing changes.
* Bad, because it is the state that produced eight hand steps.

## More Information

* Plan and diagrams: [Release supply chain](https://claude.ai/artifact/RNeXfn8qdVH8XhutYXHta8)
  (private artifact, shared by the owner).
* Implementation runs in a separate work stream; the first slice is the homelab branch
  `fix/renovate-ploeg-unfold-release` ("deploy Ploeg and Unfold releases as one tested pair").
* 2026-10-22 — P0, P2 and P3 are done and P4's detection is live; phase status and evidence are in
  the RFC's "Status on 2026-10-22". Unfold ADR-0043 makes one Unfold chart, carrying Ploeg, the
  release a cluster consumes, which this contract's consumption layer allows: the registry still
  carries it and Renovate still reads it.
