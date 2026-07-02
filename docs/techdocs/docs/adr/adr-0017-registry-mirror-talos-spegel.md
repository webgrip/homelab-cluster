# ADR-0017: Inject the Harbor mirror at the Talos/containerd layer, composed with Spegel

> Status: **Accepted** · Date: 2026-06-13 · Part of [RFC: Harbor Pull-Through Proxy Cache](../rfc/rfc-harbor-proxy-cache.md)

## Context

With Harbor proxy-cache projects adopted ([ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md)),
pulls have to *reach* them without rewriting the upstream image references in the tree and without
making Harbor a hard dependency. Two facts constrain the choice: **Spegel already owns the
containerd registry config** (its HelmRelease sets `containerdRegistryConfigPath:
/etc/cri/conf.d/hosts` and writes per-registry mirror files there for its `localhost:29999` peer
cache), and **Harbor's proxy cache is per-upstream** — each registry maps to a different project
path (`docker.io` → `/v2/dockerhub`, `ghcr.io` → `/v2/ghcr`, …). Spegel's
`additionalMirrorTargets` is a flat list applied to every mirrored registry, so it cannot express
per-registry targets. Talos `machine.registries.mirrors` can, and Spegel exposes
`prependExisting: true` to keep existing mirror configuration and prepend itself.

## Decision

Inject the Harbor proxy as **per-registry Talos `machine.registries.mirrors` entries**, and set
**Spegel `prependExisting: true`** so the two compose. The resolved containerd mirror order is
**Spegel peers → Harbor proxy → upstream**.

The patch is [`talos/patches/global/machine-registries.yaml`](../../../../talos/patches/global/machine-registries.yaml):
one mirror block per upstream (all six of ADR-0016), each endpoint
`https://harbor.${secretDomain}/v2/<project>` with `overridePath: true`, and `skipFallback` left at
its default (`false`). The `${secretDomain}` value comes from plaintext `talos/talenv.yaml`
(`webgrip.dev` — not sensitive), since the domain literal is otherwise SOPS-sealed.

**`overridePath: true` is mandatory**: without it containerd appends its own `/v2/` to the
endpoint, producing `…/v2/dockerhub/v2/…`. With it, containerd uses the endpoint verbatim and
appends `<repo>/manifests/<ref>` — exactly Harbor's proxy-project URL shape.

## Alternatives considered

- **Spegel `additionalMirrorTargets`** — a flat list applied to every registry; structurally unable
  to route `docker.io` and `ghcr.io` to distinct project paths.
- **Hand-written `hosts.toml` via Talos `machine.files`** — collides with the files Spegel manages
  in the same directory; `prependExisting` is the supported composition seam.
- **Rewriting image references to `harbor.…`** — couples every manifest to Harbor with no fallback;
  rejected in [ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md).
- **`skipFallback: true`** (pulls through Harbor only) — turns Harbor into a hard SPOF in the pull
  path, the precise failure mode this design exists to avoid.

## Consequences

- **Manifests are untouched.** Image references stay `docker.io/…` / `ghcr.io/…`; routing is
  node-level, fully reversible by removing the patch.
- **Fails open.** With `skipFallback: false` and Talos ≥ 1.9 CRI fallback semantics,
  Harbor/Garage/Envoy down degrades pulls to direct-from-upstream, never `ImagePullBackOff` — the
  property that makes ADR-0016 acceptable, drilled before being trusted cluster-wide.
- **Bootstrap-safe** by the same mechanism: at cold boot the mirror is unreachable and nodes pull
  upstream — no special-casing of the storage/bootstrap chain.
- **Peer cache stays in front** — Spegel serves any image a node already holds, even with Harbor
  *and* upstream unreachable.
- **Node-touching change**, but mild: registry mirrors are a containerd config reload
  (`MODE=no-reboot`), no drain or reboot.
- **Ordering is forgiving** — whichever of the Spegel flip / Talos patch lands first, the worst
  interim is "Harbor bypassed, upstream fallback intact"; degraded, never broken.

## Status log

- 2026-06-13 — Proposed.
- 2026-06-23 — Accepted: applied on all 5 nodes via `task talos:apply-node … MODE=no-reboot`,
  Spegel `prependExisting: true` shipped, all six upstreams mirrored. Fallback drill passed — an
  uncached pull succeeded with Harbor scaled to zero.
