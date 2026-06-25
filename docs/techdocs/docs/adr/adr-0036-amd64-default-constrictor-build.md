# ADR-0036: amd64-by-default image builds via a constrictor fast-build workflow

> Status: **Accepted** · Date: 2026-06-25 · Part of [RFC: CI pipeline performance](../rfc/rfc-ci-pipeline-performance.md)

## Context

The shared build composite `docker-build-push-registry` (in `webgrip/workflows`) defaults to
`platforms: linux/amd64,linux/arm64`. The cluster — and everything CI builds for it — is **amd64
only** (Talos on amd64). So every build emits an arm64 image **under QEMU emulation**, which is
slower than the entire action-clone wall combined, on every image, for an artifact nothing runs.

The composite also unconditionally runs `docker/setup-qemu-action` (binfmt install) even when the
target is pure amd64. It correctly keeps `docker/setup-buildx-action` and a Harbor registry layer
cache (`cache-from`/`cache-to: type=registry,…:cache,mode=max`) — both must stay: the registry
cache export requires buildx's `docker-container` driver, so dropping buildx would silently disable
layer caching.

We want the speedup without a flag-day rewrite of every build job, and without breaking the rare
build that genuinely needs arm64.

## Decision

**Default builds to `linux/amd64`, run QEMU only on demand, and migrate to it constrictor-style via
new workflow files** — leaving the existing composite in place until callers have moved.

- **New files (additive), in `webgrip/workflows`:**
  - `.forgejo/composite-actions/docker-build-push-registry-fast/action.yml` — a copy of the current
    composite with `platforms` defaulting to `linux/amd64`, and `docker/setup-qemu-action` gated
    `if: ${{ inputs.platforms != 'linux/amd64' }}` (emulate only when a non-amd64 arch is actually
    requested). **Keep** `docker/setup-buildx-action` and the existing Harbor `cache-from`/`cache-to`
    block verbatim.
  - `.forgejo/workflows/docker-build-and-push-registry-fast.yml` — a copy of the registry reusable
    workflow defaulting `platforms` to `linux/amd64` and calling the `-fast` composite.
- **Constrictor migration.** Move one caller (the Harbor wrapper / one app's build) onto the fast
  workflow, prove it, then migrate the rest over subsequent commits. Delete the old composite only
  once nothing references it.
- **`arm64` stays reachable** — any caller can still pass `platforms: linux/amd64,linux/arm64`, which
  re-enables QEMU via the gate.

## Consequences

- The dominant build-time cost (emulated arm64) is gone for the common case; setup-qemu no longer
  runs for amd64 builds.
- The Harbor registry layer cache is **inherited unchanged** — verified effective (cache import →
  `CACHED` layers on rebuild) as part of this work, not rebuilt.
- Two parallel build stacks exist during migration; this is the intended strangler state and is
  cleaned up by deleting the old composite at the end.
- A future genuine multi-arch need (e.g. an arm64 node) is a per-call `platforms` override, not a
  workflow change.

## Alternatives considered

- **Edit the existing composite in place** (just change the default + gate QEMU). Fewer files, but a
  flag-day change to every caller at once, harder to revert per-job. Rejected in favor of the
  constrictor pattern the owner asked for.
- **Drop buildx too** (use the default docker driver). Would break `cache-to: type=registry` (needs
  the `docker-container` driver), silently disabling the layer cache. Rejected.
- **Keep multi-arch default.** Retains the largest build-time cost for an unused artifact. Rejected.
- **Matrix-split amd64/arm64 into parallel jobs.** Helps wall-clock only if arm64 is actually needed;
  pure overhead when it isn't. Not now.
