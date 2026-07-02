# RFCs & design docs

Broad designs and programs; each spawns [ADRs](../adr/index.md) for its individual decisions.
Statuses: Proposed (open) · Accepted (decided, executing) · Implemented (done) · Withdrawn.

- **Implemented** — [Harbor registry](rfc-harbor-registry.md), [Harbor proxy
  cache](rfc-harbor-proxy-cache.md), [node taxonomy & storage
  placement](rfc-node-taxonomy-and-storage-placement.md), [observability alerting
  reliability](rfc-observability-alerting-reliability.md), [external-secrets migration
  plan](external-secrets-plan.md) (complete; canonical secret inventory).
- **Accepted, executing** — [Renovate on Forgejo](rfc-renovate-forgejo.md) (GitHub retirement
  gated on the Flux cutover), [CI pipeline performance](rfc-ci-pipeline-performance.md) (lives in
  `webgrip/workflows`), [Codeberg Pages TechDocs](rfc-codeberg-pages-techdocs.md) (interim;
  publish path unproven), [security hardening](rfc-security-hardening.md) (program frame),
  [Kyverno audit→enforce hardening](rfc-kyverno-audit-enforce-hardening.md) (waves pending).
- **Proposed / open** — [Flux source → Forgejo](rfc-flux-forgejo-source.md) (the big cutover),
  [dynamic database credentials](rfc-dynamic-database-credentials.md) (pilot rolled back),
  [Backstage TechDocs](rfc-backstage-techdocs.md) (+ [implementation
  plan](plan-backstage-techdocs.md)), [layered hardware
  architecture](rfc-layered-hardware-architecture.md) (program doc).
