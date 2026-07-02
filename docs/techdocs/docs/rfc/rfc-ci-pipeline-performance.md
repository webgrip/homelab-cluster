# RFC: CI pipeline performance — kill the per-job cold start

> Status: **Accepted** · Date: 2026-06-25 · Owner: Ryan · Implementation lives in
> `webgrip/workflows` (constrictor fast-build, ADR-0036) — not verifiable from this repo.
>
> Sibling of [RFC: Security Hardening](rfc-security-hardening.md) (which owns the *rootless*
> build-engine move, [ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md)). This RFC is about
> **speed**, not isolation — but it lands the **warm-cache half** of ADR-0008's "topology C" early,
> independent of the rootless engine.

## Context

The Forgejo CI runner ([`kubernetes/apps/forgejo/forgejo-runner/`](https://forgejo.webgrip.dev/webgrip/homelab-cluster))
is a KEDA `ScaledJob` — **one ephemeral pod per job**, whose only storage is `emptyDir`. That shape
is correct for isolation (ADR-0008) but it means **every job pays a full cold start** before doing
any useful work. A representative Harbor build (`release-distribute-harbor.build.build`) spends
**minutes** in setup. Two costs dominate, both visible in the runner log:

1. **The action-clone wall.** Every action — `actions/checkout`, `docker/login-action`,
   `docker/setup-qemu-action`, `docker/setup-buildx-action`, `docker/build-push-action`,
   `actions/github-script` — is `git clone`'d fresh from `data.forgejo.org` / `github.com` on every
   run, because the act action cache at `/home/runner/.cache/act` is empty in a fresh pod. ~6 serial
   internet clones, every job, forever.
2. **Emulated arm64.** The build composite defaults to `platforms: linux/amd64,linux/arm64`. The
   cluster is amd64-only (Talos), so arm64 is built under **QEMU emulation** — slower than the whole
   clone wall, on every image, for an artifact nothing in the homelab runs.

A third lever is **already in place**: the Harbor **registry layer cache**
(`cache-from`/`cache-to: type=registry,…:cache,mode=max,compression=zstd`) lives in the
`docker-build-push-registry` composite today. So the build layers already cache; what's missing is a
warm *action* cache and a sane *platform* default.

## Goals / non-goals

**Goals.** Setup phase from **minutes → seconds**; an unchanged rebuild dominated by the registry
push, not by setup. Keep the one-job-per-pod isolation model intact (no shared mutable runtime
state, no RWX). Stay GitOps-reconciled.

**Non-goals.** The rootless build engine (topology C's *other* half — dropping `privileged: true`)
stays with [ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md); this RFC does not touch
privilege. No shared cross-node cache (see *Why not RWX*).

## Approach

Three levers, two of them new decisions:

| Lever | Decision | Where it lives |
|---|---|---|
| Stop building **arm64** by default | [ADR-0036](../adr/adr-0036-amd64-default-constrictor-build.md) — **amd64-default** image builds via a **new** "fast" reusable workflow, migrated constrictor-style | `webgrip/workflows` |
| **Layer** cache to Harbor | *(no new ADR)* — already shipped in the `docker-build-push-registry` composite; **verify it's effective**, inherit it in the fast workflow | `webgrip/workflows` |
| The **action-clone** wall | [ADR-0035](../adr/adr-0035-action-clone-wall.md) — **measure first** (offline mode verified absent); scoped LAN mirror only if it still dominates | runner / Forgejo server *(deferred)* |

### Why the action cache is deferred (offline mode does not exist)

The first draft of this RFC proposed pre-baking the actions into the runner image and enabling
runner **offline mode**. Verification against the exact image (`code.forgejo.org/forgejo/runner:12.10.2`)
killed that: there is **no offline mode at any layer** — not in `generate-config`, not in
`one-job --help`, and this Forgejo act fork has even stripped `--action-offline-mode` /
`--action-cache-path` from `exec`. The only action lever is the server's `DEFAULT_ACTIONS_URL`.

Consequences, captured in [ADR-0035](../adr/adr-0035-action-clone-wall.md):

- **Pre-baking is rejected.** With no offline mode, a baked `~/.cache/act` would still `git fetch`
  upstream every job (only *clone* → *fetch*), and the cache path's run-to-run stability is
  unverified — fragile for little gain.
- **Measure first.** Ship the amd64 fix (which removes the *larger* cost, emulated arm64) and verify
  the Harbor layer cache, then re-time a real job. The clones are likely seconds once QEMU is gone;
  build cache infra only if the wall still dominates.
- **If still needed: a *scoped* LAN mirror** — mirror the docker-build actions into the in-cluster
  Forgejo and reference them by explicit LAN URLs in the `-fast` composite only. Guaranteed-fast LAN
  clones, blast radius of one composite — **not** a server-wide `DEFAULT_ACTIONS_URL` flip (which
  would make local Forgejo authoritative for every action and break un-mirrored ones).

### Why not RWX (a shared cache PVC)

A shared cache across all pods/nodes would need `ReadWriteMany`, and in this cluster that is a
deliberate dead-end:

- **Longhorn RWX = an NFS `share-manager` pod per volume** — one extra fragile component (stale
  handles, evictions hang *every* consumer's mount) on the same RAM-tight fringe nodes that have
  already produced storage SEVs. The Kyverno policy `storage-cnpg-governance.disallow-rwx-pvcs`
  exists to keep this class of risk out by default; there are **zero** RWX PVCs in the repo.
- **The benefit here is marginal.** With the hot path baked, RWX would only cache *non-baked,
  long-tail* actions, once cluster-wide instead of once per node — a tiny win for a real
  operational liability (6 concurrent pods writing git objects to one NFS share).
- **Door left open, not opened.** If profiling ever shows non-baked actions dominate, the
  lower-risk next step is a **per-node `hostPath`** cache (node-local, no NFS, no RWX); reach for
  RWX only if even that is insufficient. We are not there.

### Why not a dind `daemon.json` / ConfigMap for base-image mirroring (rejected, backed out 2026-06-25)

Routing build-time base-image pulls (the `FROM` in `docker build`) through the in-cluster Harbor pull-through cache does **not** belong in a `daemon.json`/`buildkitd.toml` mounted on the runner's **dind sidecar** — that's the wrong layer, and it was backed out as a dead-end. The CI build path uses buildx's **`docker-container` driver** (required for the Harbor registry *layer* cache), which runs buildkitd in a separate `buildx_buildkit_*` container and reads its mirror config from the file passed to `docker buildx create --config <path>`, resolved from the **runner container's** filesystem — not dind's. A `daemon.json` in dind only affects the classic embedded `docker` driver (Docker-Hub-only mirror, and bypassed entirely by docker-container builds), and a `buildkitd.toml` in dind is read by nothing. The right place for per-registry base-image mirrors is the **buildkitd config of the docker-container builder**, set in `webgrip/workflows` where the builder is created — a workflows-layer change, not a homelab dind manifest.

### Constrictor (strangler) migration for the build workflow

[ADR-0036](../adr/adr-0036-amd64-default-constrictor-build.md) ships as **new** files —
a `docker-build-push-registry-fast` composite + a `docker-build-and-push-registry-fast.yml`
reusable workflow — leaving the existing composite untouched. Callers move **one at a time**; the
old composite is deleted only once nothing references it. This avoids a flag-day rewrite of every
build job and keeps each migration independently revertible.

## Risks

- **The amd64 default could surprise a multi-arch consumer.** Mitigated: `platforms` is still an
  input; passing `linux/amd64,linux/arm64` re-enables QEMU. Nothing in the homelab consumes arm64
  today.
- **Two build stacks during migration.** The intended constrictor state; cleaned up by deleting the
  non-fast chain once nothing references it.
- **The measurement might say the clone wall still hurts.** Then we execute the scoped LAN mirror
  from [ADR-0035](../adr/adr-0035-action-clone-wall.md) — a bounded, already-designed follow-up, not
  a re-think.

## Relationship to ADR-0008

ADR-0008's topology-C table promises a **warm** build cache (PVC + Harbor registry cache) as part of
the rootless end-state. This RFC realizes the **layer-cache** dimension now (Harbor registry cache,
already shipped), on topology A, without waiting for the rootless engine — they are orthogonal. When
the rootless `buildkitd` Service eventually lands, the registry layer cache carries over unchanged;
only the build *engine* swaps. The *action* cache is deferred (ADR-0035) and is likewise
engine-independent.

## Decisions

| ADR | Decision |
|-----|----------|
| [ADR-0036](../adr/adr-0036-amd64-default-constrictor-build.md) | Default image builds to linux/amd64 (QEMU only on demand) via a new constrictor "fast" workflow; keep buildx (registry-cache driver) and the Harbor layer cache. |
| [ADR-0035](../adr/adr-0035-action-clone-wall.md) | The action-clone wall: no runner offline mode exists (verified), so measure after the amd64 fix; scoped LAN mirror if still needed; reject pre-bake / global DEFAULT_ACTIONS_URL / RWX. |
