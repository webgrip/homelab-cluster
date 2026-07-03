# Adopt Harbor pull-through proxy cache for third-party images

* Status: accepted
* Date: 2026-06-23

Technical Story: [RFC: Harbor Pull-Through Proxy Cache](../rfc/rfc-harbor-proxy-cache.md)

## Context and Problem Statement

The cluster pulled every third-party image (≈64 at decision time, mostly `docker.io` + `ghcr.io`)
straight from public registries. That exposes it to Docker Hub's anonymous rate limit (a rollout
storm or new node can trip `429` → cluster-wide `ImagePullBackOff` with no local recourse), to
upstream outages (no second source for an image no node holds), and to a blind spot where
third-party images enter with no scan-at-ingress. [Spegel](https://spegel.dev/) shares images a node
*already has* peer-to-peer but cannot source a new one — it is not a cache of record. Harbor is
already deployed ([ADR-0017](adr-0017-adopt-harbor.md)) and supports **proxy-cache projects**: a
project bound to an upstream registry that pulls through and caches on first request, with Trivy
scanning and Garage-backed durability.

## Considered Options

* Harbor proxy-cache projects for all six upstreams
* Spegel alone
* A standalone pull-through registry (`registry:2`, `zot`)
* Docker Hub creds as imagePullSecrets everywhere
* Rewriting all image references to `harbor.…`

## Decision Outcome

Chosen option: "Harbor proxy-cache projects for all six upstreams", because Harbor is already
deployed and its proxy-cache projects deliver a rate-limit-absorbing cache of record with Trivy
scanning at ingress and Garage-backed durability — no new component to run and secure.

Run **public, anonymous-pull Harbor proxy-cache projects for all six upstreams** used in the tree:
`dockerhub` (docker.io), `ghcr` (ghcr.io), `quay` (quay.io), `gcrmirror` (mirror.gcr.io), `k8s`
(registry.k8s.io) and `forgejo` (code.forgejo.org). Upstream **credentials live on the registry
endpoint**, not the project, and exist solely to lift anonymous rate limits (Docker Hub/GHCR).
Images are pulled as `harbor.${SECRET_DOMAIN}/<project>/<repo>`. This ADR covers *adopting* the
cache and *which* registries; how pulls are routed to it is
[ADR-0024](adr-0024-registry-mirror-talos-spegel.md), and how the projects are provisioned in GitOps
is [ADR-0025](adr-0025-harbor-config-idempotent-job.md).

### Positive Consequences

* Docker Hub rate limits are absorbed by an authenticated endpoint + local cache; a cache of record
  survives upstream outages for any image pulled at least once; Trivy scans third-party images at
  ingress.

### Negative Consequences

* **Harbor enters the pull path** — a new local dependency sitting on Garage S3 (the
  [WAL-SPOF](../blogs/2026-06-13-harbor-as-a-pull-through-cache.md) component). Acceptable only
  because the mirror layer falls back to upstream when Harbor is down
  ([ADR-0024](adr-0024-registry-mirror-talos-spegel.md)); the fallback drill was a release gate and
  passed at cutover.
* Storage growth in the Garage `harbor` bucket; proxy-cache retention/TTL policies bound it.
* **Helm charts narrow the fail-open stance (2026-06-23).** Image pulls fail open via the containerd
  mirror, but Flux's source-controller fetches OCI *charts* directly (no containerd, no Talos
  mirror), so routing them through Harbor required rewriting the `OCIRepository` `url:` to
  `harbor.${SECRET_DOMAIN}/<project>/…`. Unlike images this is **not** fail-open: while Harbor is
  down, the affected apps cannot **install or upgrade** (already-running releases keep running —
  charts are only fetched on reconcile-with-change). The blast radius is deliberately bounded: only
  **non-bootstrap** OCI charts were rewritten; everything in the bootstrap / reach-Harbor path
  (flux, cilium, coredns, cert-manager, external-secrets, kyverno, k8s-gateway, envoy-gateway,
  spegel, trust-manager) stays upstream, and the HTTP `HelmRepository` sources stay upstream
  (Harbor's proxy is OCI-only — ChartMuseum was removed in 2.8). Renovate keeps working without
  `registryAliases`: Harbor 2.15's proxy returns the full upstream tag list, so version discovery
  through the proxy path is complete (the `ghcr.io`-keyed packageRules were widened to also match
  the `harbor.${SECRET_DOMAIN}/ghcr` path).

## Pros and Cons of the Options

### Harbor proxy-cache projects for all six upstreams

* Good, because Harbor already exists, scans, and has RBAC/observability — pull-through caching
  with Trivy scanning and Garage-backed durability lands on infrastructure already operated.
* Bad, because Harbor enters the pull path — acceptable only with the upstream fallback of
  [ADR-0024](adr-0024-registry-mirror-talos-spegel.md).

### Spegel alone

* Bad, because it is a best-effort peer cache, not a rate-limit-absorbing source of record; it
  composes *in front of* the proxy, it doesn't replace it.

### A standalone pull-through registry (`registry:2`, `zot`)

* Bad, because it is another component to run and secure; Harbor already exists, scans, and has
  RBAC/observability.

### Docker Hub creds as imagePullSecrets everywhere

* Good, because it raises the rate limit.
* Bad, because it adds no cache, no scan, no outage resilience, and sprays a credential across
  every namespace.

### Rewriting all image references to `harbor.…`

* Bad, because it hard-codes the SPOF into every manifest with no fallback; the mirror layer
  ([ADR-0024](adr-0024-registry-mirror-talos-spegel.md)) routes transparently and reversibly.

## Links

* 2026-06-13 — proposed, scoped to two projects (`dockerhub`, `ghcr`)
* 2026-06-23 — accepted after the Phase-1 cutover: mirror applied on all 5 nodes
  ([ADR-0024](adr-0024-registry-mirror-talos-spegel.md)), fallback drill passed (pulls succeed with
  Harbor scaled to zero), coverage expanded to all six upstreams
* 2026-06-23 — non-bootstrap OCI Helm charts rewritten through the proxy (`595ee402`); see the
  fail-open-narrowing consequence above
* 2026-07-03 — renumbered from ADR-0016 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
