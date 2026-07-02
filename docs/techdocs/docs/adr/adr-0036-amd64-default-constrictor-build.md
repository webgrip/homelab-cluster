# amd64-by-default image builds via a constrictor fast-build workflow

* Status: accepted
* Date: 2026-07-02

Technical Story: [RFC: CI pipeline performance](../rfc/rfc-ci-pipeline-performance.md)

## Context and Problem Statement

The shared build composite `docker-build-push-registry` (in `webgrip/workflows`) defaults to
`platforms: linux/amd64,linux/arm64`. The cluster — and everything CI builds for it — is
**amd64-only** (Talos on amd64), so every build emits an arm64 image under QEMU emulation — slower
than the entire action-clone wall combined, on every image, for an artifact nothing runs. The
composite also unconditionally runs `docker/setup-qemu-action` even for pure-amd64 targets. We want
the speedup without a flag-day rewrite of every build job, and without breaking the rare build that
genuinely needs arm64.

## Considered Options

* amd64-by-default `-fast` workflow files, migrated constrictor-style
* Edit the existing composite in place
* Drop buildx too (default docker driver)
* Keep the multi-arch default
* Matrix-split amd64/arm64 into parallel jobs

## Decision Outcome

Chosen option: "amd64-by-default `-fast` workflow files, migrated constrictor-style", because the
cluster — and everything CI builds for it — is amd64-only, so emulated arm64 is the largest
build-time cost for an artifact nothing runs, and new `-fast` files deliver the speedup without a
flag-day rewrite of every build job.

**Default builds to `linux/amd64`, run QEMU only on demand, and migrate constrictor-style via new
workflow files in `webgrip/workflows`** (this repo records the decision; the artifacts live there):

* `.forgejo/composite-actions/docker-build-push-registry-fast/action.yml` — a copy of the current
  composite with `platforms` defaulting to `linux/amd64` and `docker/setup-qemu-action` gated
  `if: ${{ inputs.platforms != 'linux/amd64' }}` (emulate only when a non-amd64 arch is requested).
* `.forgejo/workflows/docker-build-and-push-registry-fast.yml` — the matching reusable workflow
  calling the `-fast` composite.
* **Keep `docker/setup-buildx-action` and the Harbor registry layer cache verbatim.** The
  `cache-from`/`cache-to: type=registry,…:cache,mode=max` export requires buildx's
  `docker-container` driver — dropping setup-buildx **silently disables the layer cache**.
* **Constrictor migration:** move one caller onto the fast workflow, prove it, migrate the rest
  over subsequent commits; delete the old composite only once nothing references it.
* **arm64 stays reachable** — any caller can pass `platforms: linux/amd64,linux/arm64`, which
  re-enables QEMU via the gate.

### Positive Consequences

* The dominant build-time cost (emulated arm64) disappears for the common case; setup-qemu no
  longer runs for amd64 builds.
* The Harbor registry layer cache is inherited unchanged — verified effective (cache import →
  `CACHED` layers on rebuild) as part of this work, not rebuilt.
* A future genuine multi-arch need (e.g. an arm64 node) is a per-call `platforms` override, not a
  workflow change.

### Negative Consequences

* Two parallel build stacks exist during migration — the intended strangler state, cleaned up by
  deleting the old composite at the end.

## Pros and Cons of the Options

### amd64-by-default `-fast` workflow files, migrated constrictor-style

* Good, because migration is one caller at a time and revertible per-job — no flag-day change.
* Good, because arm64 stays reachable — any caller can pass `platforms: linux/amd64,linux/arm64`,
  which re-enables QEMU via the gate.
* Bad, because two parallel build stacks exist during migration.

### Edit the existing composite in place

* Good, because fewer files.
* Bad, because a flag-day change to every caller at once, harder to revert per-job. Rejected in
  favour of the constrictor pattern the owner asked for.

### Drop buildx too (default docker driver)

* Bad, because it breaks `cache-to: type=registry` (needs the `docker-container` driver), silently
  disabling the layer cache.

### Keep the multi-arch default

* Bad, because it retains the largest build-time cost for an unused artifact.

### Matrix-split amd64/arm64 into parallel jobs

* Bad, because it helps wall-clock only when arm64 is actually needed; pure overhead when it
  isn't. Not now.

## Links

* 2026-06-25 — accepted (eea51342); the workflow artifacts land in `webgrip/workflows`
* 2026-07-02 — audit: the cluster remains amd64-only; migration progress lives in
  `webgrip/workflows` and is not verifiable from this repo
