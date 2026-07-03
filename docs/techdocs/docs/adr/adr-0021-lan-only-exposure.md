# Expose Harbor LAN-only via envoy-internal

* Status: accepted
* Date: 2026-06-12

Technical Story: [RFC: Harbor Container Registry](../rfc/rfc-harbor-registry.md)

## Context and Problem Statement

Harbor must be reachable for `docker`/`helm` push and pull. The cluster has two Gateway API
gateways (see [Envoy Gateway](../runbooks/envoy-gateway.md)): `envoy-external` (`10.0.0.28`,
public via the Cloudflare tunnel) and `envoy-internal` (`10.0.0.27`, LAN-only). Registry pushes
are **large** multi-megabyte blob uploads, and the public path runs through Cloudflare's free
plan, which **caps request bodies at ~100 MB** — large layer pushes over `envoy-external` would
fail. The registry also holds sensitive artifacts that don't need to be internet-facing.

## Considered Options

* An `HTTPRoute` on `envoy-internal` (LAN-only)
* `envoy-external` (public)
* A dedicated LoadBalancer service / nodePort

## Decision Outcome

Chosen option: "An `HTTPRoute` on `envoy-internal` (LAN-only)", because registry pushes are large
multi-megabyte blob uploads that the public path's Cloudflare ~100 MB body cap would break, and
the registry holds sensitive artifacts that don't need to be internet-facing.

Expose Harbor through an `HTTPRoute` on **`envoy-internal`** at `harbor.${SECRET_DOMAIN}` — LAN
and in-cluster access only. TLS terminates at the gateway's wildcard `*.${SECRET_DOMAIN}`
certificate, so Harbor runs `expose.type: clusterIP` with its own TLS disabled. Lives in
`kubernetes/apps/harbor/harbor/app/`.

### Positive Consequences

* Avoids the Cloudflare body-size cap entirely; large layer pushes work.
* Keeps the registry off the public internet — pushes/pulls require LAN (or VPN) access, a
  reasonable security default.

### Negative Consequences

* **No off-LAN access:** external CI or remote machines can't push/pull directly. If that's needed
  later, flip the `HTTPRoute` `parentRefs` to `envoy-external` (accepting the body-size limit) or
  add a dedicated tunnel — a reversible one-line change.

## Pros and Cons of the Options

### An `HTTPRoute` on `envoy-internal` (LAN-only)

* Good, because the Cloudflare body-size cap never applies — large layer pushes work.
* Good, because a sensitive store stays off the public internet.
* Bad, because no off-LAN access — external CI or remote machines can't push/pull directly.

### `envoy-external` (public)

* Good, because it enables push/pull from anywhere.
* Bad, because the Cloudflare 100 MB body cap breaks realistic image pushes.
* Bad, because it widens the exposure surface of a sensitive store.

### A dedicated LoadBalancer service / nodePort

* Good, because it bypasses the gateway.
* Bad, because it loses the shared wildcard-cert TLS termination and the consistent
  `*.${SECRET_DOMAIN}` routing every other app uses.

## Links

* 2026-06-12 — accepted; `HTTPRoute` live on `envoy-internal`
* 2026-07-03 — renumbered from ADR-0005 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
