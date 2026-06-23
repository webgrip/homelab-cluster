# ADR-0016: Adopt Harbor pull-through proxy cache for third-party images

> Status: **Accepted** · Date: 2026-06-13 (accepted 2026-06-23) · Part of [RFC: Harbor Pull-Through Proxy Cache](../rfc/rfc-harbor-proxy-cache.md)
>
> **2026-06-23 cutover:** the mirror ([ADR-0017](adr-0017-registry-mirror-talos-spegel.md)) is
> applied on all 5 nodes and the fallback drill passed (image pulls succeed with Harbor scaled to
> zero). Coverage was extended beyond the original two projects to **all six upstreams** in the
> tree — `dockerhub`, `ghcr`, `quay`, `gcrmirror` (mirror.gcr.io), `k8s` (registry.k8s.io) and
> `forgejo` (code.forgejo.org) — anonymous proxy-cache projects, provisioned idempotently
> ([ADR-0018](adr-0018-harbor-config-idempotent-job.md)).

## Context

The cluster pulls ~64 third-party images straight from public registries (23 `docker.io`,
34 `ghcr.io`, plus quay/k8s). That exposes us to Docker Hub's anonymous rate limit (a rollout
storm or a new node can trip `429` → cluster-wide `ImagePullBackOff` with no local recourse),
to upstream outages (no second source for an image not already on a node), and to a blind spot
where third-party images enter the cluster without any scan-at-ingress. [Spegel](https://spegel.dev/)
shares images a node *already has* peer-to-peer, but cannot source an image no node holds — it is
not a cache of record.

Harbor is already deployed ([ADR-0001](adr-0001-adopt-harbor.md)) and supports **proxy-cache
projects**: a project bound to an upstream registry endpoint that pulls-through and caches on
first request, with Trivy scanning and Garage-backed durability.

## Decision

Create **two Harbor proxy-cache projects** in the existing Harbor:

- **`dockerhub`** → registry endpoint `docker-hub` (`https://hub.docker.com`), and
- **`ghcr`** → a generic `docker-registry` endpoint pointed at `https://ghcr.io`.

Both projects are **public** (anonymous in-cluster pulls need no credentials). The upstream
**credentials live on the registry endpoint**, not the project, and exist solely to lift the
upstream's anonymous rate limit. Images pulled as `harbor.${SECRET_DOMAIN}/dockerhub/<repo>` and
`…/ghcr/<owner>/<repo>` proxy-and-cache the corresponding upstream image.

This ADR covers *adopting* the cache and *which* registries. How pulls are routed to it
([ADR-0017](adr-0017-registry-mirror-talos-spegel.md)) and how the projects are provisioned in
GitOps ([ADR-0018](adr-0018-harbor-config-idempotent-job.md)) are separate decisions.

## Consequences

- **Docker Hub rate limits are absorbed** by an authenticated endpoint + a local cache; `429`s
  under rollout load disappear.
- **A cache of record** survives upstream outages for any image pulled at least once.
- **Scan-at-ingress**: Trivy scans third-party images as they land in Harbor.
- **Harbor enters the pull path** — a new local dependency, sitting on Garage S3 (the
  [WAL-SPOF](../blogs/2026-06-13-harbor-as-a-pull-through-cache.md) component). This is only
  acceptable because the mirror layer falls back to upstream when Harbor is down
  ([ADR-0017](adr-0017-registry-mirror-talos-spegel.md)); the fallback drill is a release gate.
- **GHCR is best-effort**: the generic `docker-registry` provider proxies ghcr.io; if it
  misbehaves it can be dropped without loss, since GHCR has no anonymous-pull limit and `docker.io`
  is the load-bearing win.
- **Storage growth** in the Garage `harbor` bucket; proxy-cache retention/TTL policies bound it
  (Phase 2).
- **Helm charts narrow the fail-open stance (2026-06-23).** Image pulls fail open via the
  containerd mirror, but Flux's source-controller fetches OCI *charts* directly (no containerd, no
  Talos mirror), so routing them through Harbor required rewriting the `OCIRepository` `url:` to
  `harbor.${SECRET_DOMAIN}/<project>/…`. Unlike images this is **not** fail-open: while Harbor is
  down, the affected apps cannot **install or upgrade** (already-running releases keep running —
  charts are only fetched on reconcile-with-change). The blast radius is deliberately bounded:
  only **non-bootstrap** OCI charts were rewritten; everything in the bootstrap / reach-Harbor path
  (flux, cilium, coredns, cert-manager, external-secrets, kyverno, k8s-gateway, envoy-gateway,
  spegel, trust-manager) stays upstream, and the 21 HTTP `HelmRepository` sources stay upstream
  (Harbor's proxy is OCI-only — ChartMuseum was removed in 2.8). Renovate keeps working without
  `registryAliases`: Harbor 2.15's proxy returns the full upstream tag list, so version discovery
  through the proxy path is complete (the `ghcr.io`-keyed packageRules were widened to also match
  the `harbor.${SECRET_DOMAIN}/ghcr` path).

## Alternatives considered

- **Spegel alone.** Already deployed and kept — but it's a best-effort peer cache, not a
  rate-limit-absorbing source of record. It composes *in front of* the proxy, it doesn't replace
  it.
- **A standalone pull-through registry** (e.g. `registry:2` in proxy mode, or `zot`). Another
  component to run and secure; Harbor already exists, scans, and has RBAC/observability.
- **Authenticated direct pulls** (Docker Hub creds as an imagePullSecret on every workload).
  Raises the limit but adds no cache, no scan, no outage resilience, and sprays a credential
  across every namespace.
- **Rewriting all 64 image references to `harbor.…/…`.** Hard-codes the SPOF into every manifest
  with no fallback, and churns the whole tree. The mirror layer ([ADR-0017](adr-0017-registry-mirror-talos-spegel.md))
  achieves the same routing transparently and reversibly.
