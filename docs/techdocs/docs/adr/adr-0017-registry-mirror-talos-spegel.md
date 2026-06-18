# ADR-0017: Inject the Harbor mirror at the Talos/containerd layer, composed with Spegel

> Status: **Proposed** · Date: 2026-06-13 · Part of [RFC: Harbor Pull-Through Proxy Cache](../rfc/rfc-harbor-proxy-cache.md)

## Context

Having adopted Harbor proxy-cache projects ([ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md)),
pulls have to *reach* them without rewriting the ~64 upstream image references in the tree and
without making Harbor a hard dependency. Two facts about this cluster constrain the choice:

- **Spegel already owns the containerd registry config.** Its HelmRelease sets
  `containerdRegistryConfigPath: /etc/cri/conf.d/hosts` — the directory Talos ≥ 1.5 uses for
  containerd's `hosts.toml`. Spegel writes per-registry mirror files there at runtime, pointing
  containerd at its own `localhost:29999` peer cache. There is **no** `machine.registries` config
  in Talos today.
- **Harbor proxy cache is per-upstream.** Each upstream maps to a *different* project path:
  `docker.io` → `/v2/dockerhub`, `ghcr.io` → `/v2/ghcr`. A mirror mechanism that can't express
  per-registry targets can't route them.

Spegel's `additionalMirrorTargets` is a **flat list applied to all mirrored registries**, so it
cannot send `docker.io` and `ghcr.io` to different Harbor project paths — it's the wrong layer for
this. Talos `machine.registries.mirrors` *is* per-registry, and Spegel exposes
`prependExisting: true` to **keep existing mirror configuration and prepend itself** rather than
overwrite it.

## Decision

Inject the Harbor proxy as a **per-registry Talos `machine.registries.mirrors`** entry, and set
**Spegel `prependExisting: true`** so the two compose. The resolved containerd mirror order
becomes **Spegel peers → Harbor proxy → upstream**.

Talos patch (`talos/patches/global/machine-registries.yaml`, activated at Phase-1 cutover; the
`${secretDomain}` value is supplied via `talenv` since the domain is SOPS-sealed):

```yaml
machine:
  registries:
    mirrors:
      docker.io:
        endpoints:
          - https://harbor.${secretDomain}/v2/dockerhub
        overridePath: true   # use the /v2/dockerhub path as-is; don't append another /v2/
      ghcr.io:
        endpoints:
          - https://harbor.${secretDomain}/v2/ghcr
        overridePath: true
    # skipFallback left at default (false): containerd falls back to the upstream
    # registry when every listed mirror is unreachable.
```

Spegel HelmRelease values change:

```yaml
spegel:
  prependExisting: true   # keep the Talos-written Harbor mirror; prepend the peer cache
```

**`overridePath: true`** is mandatory: without it containerd appends its own `/v2/` to the
endpoint, producing `…/v2/dockerhub/v2/…`. With it, containerd uses `https://harbor.…/v2/dockerhub`
verbatim and appends `<repo>/manifests/<ref>`, which is exactly Harbor's proxy-project URL shape.

## Consequences

- **Manifests are untouched.** Image references stay `docker.io/…` / `ghcr.io/…`; routing is a
  node-level concern, fully reversible by removing the patch.
- **Fails open.** `skipFallback` defaults off and Talos ≥ 1.9 matches CRI fallback semantics
  (these nodes run **v1.13.3**), so Harbor/Garage/Envoy being down degrades pulls to direct-from-
  upstream, not `ImagePullBackOff`. This is the property that makes [ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md)
  acceptable — and it must be **drilled** (scale Harbor to zero, pull an uncached image) before the
  change is trusted cluster-wide.
- **Bootstrap-safe by the same mechanism.** At cold boot Harbor isn't up; the mirror is
  unreachable; nodes pull upstream. The storage/bootstrap chain therefore needs no special-casing.
- **Peer cache stays in front.** Spegel still serves any image a node already holds, even with
  Harbor *and* upstream unreachable.
- **Node-touching change.** Applying `machine.registries.mirrors` is a machine-config apply per
  node (reboot-safe drain via the `talos` skill) — hence Phase 1, human-gated, not bundled with
  the GitOps provisioning plane.
- **Ordering is forgiving.** If the Spegel flip lands before the Talos patch, Spegel prepends to
  nothing custom (no-op). If the Talos patch lands before the Spegel flip, Spegel overwrites the
  Harbor mirror with just-itself (Harbor bypassed, upstream fallback intact) — degraded, never
  broken. Neither order risks an outage.

## Alternatives considered

- **Spegel `additionalMirrorTargets`.** A *flat* list applied to every registry — cannot route
  `docker.io`→`/v2/dockerhub` and `ghcr.io`→`/v2/ghcr` to distinct project paths. Rejected as
  structurally unable to express per-registry proxying.
- **Hand-written `hosts.toml` via Talos `machine.files`.** Would collide with the files Spegel
  manages in the same directory; `prependExisting` is the supported composition seam, so fighting
  it with raw files is fragile.
- **Rewriting image references to `harbor.…`.** Couples every manifest to Harbor with no fallback;
  rejected in [ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md).
- **`skipFallback: true`** (force pulls through Harbor only). Turns Harbor into a hard SPOF in the
  pull path — the precise failure mode this design exists to avoid. Rejected.
