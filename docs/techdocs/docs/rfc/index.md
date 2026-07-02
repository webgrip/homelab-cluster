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

## Decision-landscape gap RFCs (2026-07-02)

Spawned by the [decision-landscape audit](../adr/landscape.md): the parts of the running platform
that had no decision record. All **Proposed**. Roughly by stakes:

- [Alert delivery](rfc-alert-delivery.md) — no alert currently reaches a human (both planes end in
  `"null"`/nothing).
- [Backup & DR program](rfc-backup-dr.md) — tier map, the OpenBao unseal-key escrow hole, second
  backup leg, drill cadence.
- [Object storage — Garage](rfc-object-storage-garage.md) — the unrecorded S3 backbone everything
  depends on.
- [Runtime detection & response](rfc-runtime-detection-response.md) — Falco *and* Tetragon
  uninstalled since 2026-06-19; pick one, gate the return, wire the response.
- [Platform foundations](rfc-platform-foundations.md) — retroactive ADRs for Talos, Flux topology,
  Cilium datapath.
- [Ingress, DNS & edge](rfc-ingress-dns-edge.md) — dual gateways, tunnel, split DNS; enforce the
  internal-by-default posture.
- [Identity & SSO](rfc-identity-sso.md) — Authentik adoption record + the non-OIDC/forward-auth
  hole.
- [Postgres data layer](rfc-postgres-data-layer.md) — CNPG-as-standard, the single-instance
  posture, pooling.
- [Observability pipeline](rfc-observability-pipeline.md) — logs/traces/profiles composition,
  retention tiers, Kepler's fate.
- [Image signing & verification](rfc-image-signing-verification.md) — record the OpenBao Transit
  anchor, own the verify-enforce waves, DT-vs-GUAC.
- [GitHub Actions retirement](rfc-github-actions-retirement.md) — ARC has been 0/0 "TEMP" since
  2026-06-18; retire or restore, on purpose.
