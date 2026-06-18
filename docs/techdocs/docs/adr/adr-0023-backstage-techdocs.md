# ADR-0023: TechDocs served by Backstage with Garage S3 external storage (target)

> Status: **Proposed** · Date: 2026-06-18 · Part of [RFC: TechDocs hosting after GitHub Pages](../rfc/rfc-codeberg-pages-techdocs.md)
> · sequenced after [ADR-0022 (Codeberg Pages, interim)](adr-0022-codeberg-pages-techdocs.md)
> · implementation: [Backstage TechDocs plan](../rfc/plan-backstage-techdocs.md)

## Context

The docs under `docs/techdocs/` are **Backstage TechDocs** (mkdocs + the TechDocs addon format),
and **Backstage is already deployed** in-cluster (`kubernetes/apps/backstage/`). The interim host,
Codeberg Pages ([ADR-0022](adr-0022-codeberg-pages-techdocs.md)), serves a bare static site
off-site, but it is public-only and disconnected from the service catalog. The point of authoring in
TechDocs format is the integrated experience: per-entity docs, cross-doc search, and SSO — which is
only realised by serving through Backstage.

## Decision

*(Proposed.)* Make **Backstage the primary TechDocs surface**, using the **`external` TechDocs build
strategy** with the **`awsS3` publisher** pointed at a **Garage S3** bucket
([ADR-0002](adr-0002-registry-blob-storage-garage-s3.md) already uses Garage for blob storage):

- CI builds the docs and runs `techdocs-cli publish --publisher-type awsS3` into a dedicated Garage
  bucket (`techdocs`), keyed by catalog entity (`<namespace>/<kind>/<name>`).
- Backstage runs TechDocs with `builder: 'external'` (it serves prebuilt docs, never builds on
  read) and `publisher.type: 'awsS3'` reading the same Garage bucket via an S3-compatible endpoint.
- Docs are reachable at `backstage.webgrip.dev/docs/<namespace>/<kind>/<name>`, behind **Authentik
  SSO**, with TechDocs search and catalog entity-linking.

**Codeberg Pages is retained as the off-site DR mirror** (ADR-0022): `on_docs_change` keeps a second
deploy job that publishes the same artifact to Codeberg, so docs survive a cluster outage.

## Consequences

- **Real TechDocs experience** — search, "docs" tab on catalog entities, SSO for private docs.
- **Sovereign + in-cluster** — storage is Garage (already operated); serving is Backstage (already
  operated). No new platform component, only configuration + a bucket.
- **Access control** — private docs become possible (Backstage behind Authentik), which Codeberg
  Pages cannot offer.
- **Catalog coupling** — each docs set must map to a catalog entity (a `catalog-info.yaml` with a
  `backstage.io/techdocs-ref` annotation). This is new metadata to maintain.
- **CI change** — `on_docs_change` gains a `techdocs-cli publish` (S3) job as primary; the Codeberg
  job stays as DR. Both consume the one `techdocs-site` artifact (no rebuild).
- **Two copies** — Garage (primary, in-cluster) + Codeberg (DR, off-site). Acceptable and deliberate.

## Alternatives considered

- **Garage S3 static website (no Backstage)** — simpler serving, but loses search/catalog/SSO; it is
  effectively a worse Backstage for the same storage. Use only if Backstage is dropped as the portal.
- **Signed OCI image in Harbor + Flux** — immutable + signed + Kyverno-verified, the most
  supply-chain-cohesive; but no TechDocs integration and an image build per change. A strong
  alternative if the catalog experience is not wanted.
- **Self-hosted Forgejo Pages server** — general static Pages for all repos, but again no TechDocs
  integration. Orthogonal; could coexist for non-TechDocs sites.
- **Stay on Codeberg Pages only** — rejected as the *primary*: public-only and disconnected from the
  catalog. Retained as the DR mirror.
