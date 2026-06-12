# ADR-0005: Expose Harbor LAN-only via envoy-internal

> Status: **Accepted** · Date: 2026-06-12 · Part of [RFC: Harbor Container Registry](rfc-harbor-registry.md)

## Context

Harbor must be reachable for `docker`/`helm` push and pull. The cluster has two Gateway API
gateways (see [Envoy Gateway](../runbooks/envoy-gateway.md)): `envoy-external` (`10.0.0.28`,
public via the Cloudflare tunnel) and `envoy-internal` (`10.0.0.27`, LAN-only). Registry pushes
are **large** multi-megabyte blob uploads, and the public path runs through Cloudflare's free
plan, which **caps request bodies at ~100 MB** — large layer pushes over `envoy-external` would
fail. The registry also holds sensitive artifacts that don't need to be internet-facing.

## Decision

Expose Harbor through an `HTTPRoute` on **`envoy-internal`** at `harbor.${SECRET_DOMAIN}` — LAN
and in-cluster access only. TLS terminates at the gateway's wildcard `*.${SECRET_DOMAIN}`
certificate, so Harbor runs `expose.type: clusterIP` with its own TLS disabled.

## Consequences

- Avoids the Cloudflare body-size cap entirely; large layer pushes work.
- Keeps the registry off the public internet — pushes/pulls require LAN (or VPN) access, a
  reasonable security default.
- **No off-LAN access:** external CI or remote machines can't push/pull directly. If that's needed
  later, flip the `HTTPRoute` `parentRefs` to `envoy-external` (accepting the body-size limit) or
  add a dedicated tunnel — a reversible one-line change.

## Alternatives considered

- **`envoy-external` (public)** — enables push/pull from anywhere, but the Cloudflare 100 MB body
  cap breaks realistic image pushes, and it widens the exposure surface of a sensitive store.
- **A dedicated LoadBalancer service / nodePort** — bypasses the gateway but loses the shared
  wildcard-cert TLS termination and the consistent `*.${SECRET_DOMAIN}` routing every other app
  uses.
