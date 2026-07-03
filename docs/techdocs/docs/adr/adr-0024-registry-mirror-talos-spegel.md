# Inject the Harbor mirror at the Talos/containerd layer, composed with Spegel

* Status: accepted
* Date: 2026-06-23

Technical Story: [RFC: Harbor Pull-Through Proxy Cache](../rfc/rfc-harbor-proxy-cache.md)

## Context and Problem Statement

With Harbor proxy-cache projects adopted ([ADR-0023](adr-0023-harbor-pull-through-proxy-cache.md)),
pulls have to *reach* them without rewriting the upstream image references in the tree and without
making Harbor a hard dependency. Two facts constrain the choice: **Spegel already owns the
containerd registry config** (its HelmRelease sets `containerdRegistryConfigPath:
/etc/cri/conf.d/hosts` and writes per-registry mirror files there for its `localhost:29999` peer
cache), and **Harbor's proxy cache is per-upstream** — each registry maps to a different project
path (`docker.io` → `/v2/dockerhub`, `ghcr.io` → `/v2/ghcr`, …). Spegel's
`additionalMirrorTargets` is a flat list applied to every mirrored registry, so it cannot express
per-registry targets. Talos `machine.registries.mirrors` can, and Spegel exposes
`prependExisting: true` to keep existing mirror configuration and prepend itself.

## Considered Options

* Per-registry Talos `machine.registries.mirrors` + Spegel `prependExisting: true`
* Spegel `additionalMirrorTargets`
* Hand-written `hosts.toml` via Talos `machine.files`
* Rewriting image references to `harbor.…`
* `skipFallback: true` (pulls through Harbor only)

## Decision Outcome

Chosen option: "Per-registry Talos `machine.registries.mirrors` + Spegel `prependExisting: true`",
because Talos mirrors can express Harbor's per-registry project paths — which Spegel's flat
`additionalMirrorTargets` cannot — and `prependExisting: true` is the supported seam that composes
the two.

Inject the Harbor proxy as **per-registry Talos `machine.registries.mirrors` entries**, and set
**Spegel `prependExisting: true`** so the two compose. The resolved containerd mirror order is
**Spegel peers → Harbor proxy → upstream**.

The patch is [`talos/patches/global/machine-registries.yaml`](../../../../talos/patches/global/machine-registries.yaml):
one mirror block per upstream (all six of ADR-0023), each endpoint
`https://harbor.${secretDomain}/v2/<project>` with `overridePath: true`, and `skipFallback` left at
its default (`false`). The `${secretDomain}` value comes from plaintext `talos/talenv.yaml`
(`webgrip.dev` — not sensitive), since the domain literal is otherwise SOPS-sealed.

**`overridePath: true` is mandatory**: without it containerd appends its own `/v2/` to the
endpoint, producing `…/v2/dockerhub/v2/…`. With it, containerd uses the endpoint verbatim and
appends `<repo>/manifests/<ref>` — exactly Harbor's proxy-project URL shape.

### Positive Consequences

* **Manifests are untouched.** Image references stay `docker.io/…` / `ghcr.io/…`; routing is
  node-level, fully reversible by removing the patch.
* **Fails open.** With `skipFallback: false` and Talos ≥ 1.9 CRI fallback semantics,
  Harbor/Garage/Envoy down degrades pulls to direct-from-upstream, never `ImagePullBackOff` — the
  property that makes ADR-0023 acceptable, drilled before being trusted cluster-wide.
* **Bootstrap-safe** by the same mechanism: at cold boot the mirror is unreachable and nodes pull
  upstream — no special-casing of the storage/bootstrap chain.
* **Peer cache stays in front** — Spegel serves any image a node already holds, even with Harbor
  *and* upstream unreachable.
* **Ordering is forgiving** — whichever of the Spegel flip / Talos patch lands first, the worst
  interim is "Harbor bypassed, upstream fallback intact"; degraded, never broken.

### Negative Consequences

* **Node-touching change**, but mild: registry mirrors are a containerd config reload
  (`MODE=no-reboot`), no drain or reboot.

## Pros and Cons of the Options

### Per-registry Talos `machine.registries.mirrors` + Spegel `prependExisting: true`

* Good, because per-registry mirror entries route each upstream to its distinct Harbor project
  path, and `prependExisting: true` composes with the files Spegel manages.
* Bad, because it is a node-touching change — though only a containerd config reload
  (`MODE=no-reboot`), no drain or reboot.

### Spegel `additionalMirrorTargets`

* Bad, because it is a flat list applied to every registry; structurally unable to route
  `docker.io` and `ghcr.io` to distinct project paths.

### Hand-written `hosts.toml` via Talos `machine.files`

* Bad, because it collides with the files Spegel manages in the same directory; `prependExisting`
  is the supported composition seam.

### Rewriting image references to `harbor.…`

* Bad, because it couples every manifest to Harbor with no fallback; rejected in
  [ADR-0023](adr-0023-harbor-pull-through-proxy-cache.md).

### `skipFallback: true` (pulls through Harbor only)

* Bad, because it turns Harbor into a hard SPOF in the pull path, the precise failure mode this
  design exists to avoid.

## Links

* 2026-06-13 — proposed
* 2026-06-23 — accepted: applied on all 5 nodes via `task talos:apply-node … MODE=no-reboot`,
  Spegel `prependExisting: true` shipped, all six upstreams mirrored. Fallback drill passed — an
  uncached pull succeeded with Harbor scaled to zero
* 2026-07-03 — renumbered from ADR-0017 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
