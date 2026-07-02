# ADR-0023: TechDocs served by Backstage with Garage S3 external storage (target)

> Status: **Proposed** · Date: 2026-06-18 · Part of [RFC: TechDocs hosting after GitHub Pages](../rfc/rfc-codeberg-pages-techdocs.md)

## Context

The docs under `docs/techdocs/` are authored in **Backstage TechDocs** format (mkdocs + the
TechDocs addon), and Backstage is already deployed in-cluster (`kubernetes/apps/backstage/`). The
interim host, Codeberg Pages ([ADR-0022](adr-0022-codeberg-pages-techdocs.md)), serves a bare
static site off-site but is public-only and disconnected from the service catalog. The point of
authoring in TechDocs format is the integrated experience — per-entity docs, cross-doc search, SSO
— which is only realised by serving through Backstage.

## Decision

Make **Backstage the primary TechDocs surface**, using the **`external` build strategy** with the
**`awsS3` publisher on Garage S3** ([ADR-0002](adr-0002-registry-blob-storage-garage-s3.md) already
uses Garage for blob storage):

- CI builds the docs and runs `techdocs-cli publish --publisher-type awsS3` into a dedicated Garage
  bucket (`techdocs`), keyed by catalog entity (`<namespace>/<kind>/<name>`).
- Backstage runs TechDocs with `builder: 'external'` (it serves prebuilt docs, never builds on
  read) and `publisher.type: 'awsS3'` reading the same bucket via the S3-compatible endpoint.
- Docs are served at `backstage.webgrip.dev/docs/<namespace>/<kind>/<name>` behind Authentik.

**Codeberg Pages is retained as the off-site DR mirror** (ADR-0022): the docs workflow keeps a
second deploy job publishing the same `techdocs-site` artifact to Codeberg (no rebuild), so docs
survive a cluster outage. Implementation detail:
[Backstage TechDocs plan](../rfc/plan-backstage-techdocs.md).

## Alternatives considered

All alternatives are serving mechanisms without the integrated catalog experience — the reason for
authoring in TechDocs format in the first place:

- **Garage S3 static website (no Backstage)** — simpler serving on the same storage; effectively a
  worse Backstage. Use only if Backstage is dropped as the portal.
- **Signed OCI image in Harbor + Flux** — most supply-chain-cohesive (cosign-signed,
  Kyverno-verified), but an image build per docs change.
- **Self-hosted Forgejo Pages server** — general-purpose static Pages for all repos; orthogonal,
  could coexist for non-TechDocs sites.
- **Stay on Codeberg Pages only** — public-only; retained as the DR mirror, rejected as primary.

## Consequences

- The integrated TechDocs experience lands, and private docs become possible for the first time
  (Backstage sits behind Authentik).
- Sovereign + in-cluster: storage is Garage, serving is Backstage — both already operated. No new
  platform component, only configuration + a bucket.
- Catalog coupling: each docs set must map to a catalog entity (a `catalog-info.yaml` with a
  `backstage.io/techdocs-ref` annotation) — new metadata to maintain.
- CI change: the docs workflow gains a `techdocs-cli publish` (S3) job as primary; the Codeberg job
  stays as DR. Both consume the one `techdocs-site` artifact.
- Two copies — Garage (primary, in-cluster) + Codeberg (DR, off-site). Deliberate.

## Status log

- 2026-06-18 — Proposed.
- 2026-07-02 — Still unbuilt: the Backstage app carries no TechDocs builder/publisher/awsS3
  configuration yet.
