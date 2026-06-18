# ADR-0022: Serve TechDocs from Codeberg Pages (interim + off-site)

> Status: **Accepted** · Date: 2026-06-18 · Part of [RFC: TechDocs hosting after GitHub Pages](../rfc/rfc-codeberg-pages-techdocs.md)
> · sequenced before [ADR-0023 (Backstage TechDocs)](adr-0023-backstage-techdocs.md) · related: [ADR-0020 (Codeberg mirror)](adr-0020-codeberg-offsite-push-mirror.md)

## Context

TechDocs (the Backstage-format mkdocs site under `docs/techdocs/`) is built by CI and was deployed
to **GitHub Pages**. The GitHub exit removes that target, and **Forgejo has no native Pages**. The
`.forgejo` deploy workflow today only pushes the built site to a `pages` branch that nothing serves
— a no-op. We need a working, serving target **now**, while the in-cluster destination (Backstage
TechDocs, [ADR-0023](adr-0023-backstage-techdocs.md)) is built out later.

Five options were surveyed in the [RFC](../rfc/rfc-codeberg-pages-techdocs.md): Garage S3 static website,
Backstage TechDocs, a signed OCI image in Harbor, **Codeberg Pages**, and a self-hosted Forgejo
Pages server. The deciding constraint for the *interim* is: minimal in-cluster infrastructure, real
off-site durability, and alignment with the redundancy story already chosen in
[ADR-0020](adr-0020-codeberg-offsite-push-mirror.md).

## Decision

**Publish the built TechDocs site to Codeberg Pages.** CI force-pushes the static `techdocs-site`
artifact to a Codeberg repository's `pages` branch (as an orphan snapshot), with a `.domains` file
carrying `docs.webgrip.dev`; Codeberg serves it over its own Let's Encrypt certificate. DNS points
`docs.webgrip.dev` at `webgrip.codeberg.page` (CNAME).

This is **explicitly interim and off-site**: it is the documentation half of the off-site
redundancy already adopted for Git in ADR-0020, and it survives a total cluster outage. When
Backstage TechDocs (ADR-0023) lands as the primary in-cluster surface, Codeberg Pages is **retained
as the DR/off-site mirror**, not removed.

## Consequences

- **Docs survive cluster loss.** The published site lives off-cluster; an outage that takes down
  Forgejo/Backstage does not take the docs with it. This is the main reason to do it first.
- **Zero in-cluster serving infrastructure.** No bucket, Deployment, or pages-server to operate —
  only a CI push step and DNS.
- **Public-only.** Codeberg Pages serves public content; do not publish docs that must be access-
  controlled this way (those wait for Backstage + Authentik, ADR-0023).
- **New credential + external dependency.** A Codeberg token (`CODEBERG_TOKEN`) is provisioned as a
  Forgejo org Actions secret from OpenBao (`codeberg/pages`), mirroring the Harbor/DT pattern. The
  external dependency is acceptable: Codeberg is the community Forgejo host, philosophically aligned,
  and already our chosen off-site Git mirror.
- **CI change.** `on_docs_change.yml`'s deploy job calls a new reusable
  `webgrip/workflows/.forgejo/workflows/techdocs-deploy-codeberg.yml`; the dead `pages`-branch push
  to the in-cluster Forgejo is dropped.
- **One-time manual prerequisites** (handed off, not GitOps): create the Codeberg repo, mint the
  token into OpenBao, set the DNS CNAME. See the [RFC](../rfc/rfc-codeberg-pages-techdocs.md) §Operations.

## Alternatives considered

- **Backstage TechDocs (in-cluster)** — the correct long-term home (search, catalog, SSO), but a
  larger change; sequenced as [ADR-0023](adr-0023-backstage-techdocs.md), *later*.
- **Garage S3 static website** — sovereign and simple, but in-cluster only (no DR) and needs an
  Envoy/authz front for anything private. A good alternative primary; rejected for *interim* because
  it does not provide off-site durability.
- **Signed OCI image in Harbor + Flux** — most cohesive with the supply-chain work (cosign-signed,
  Kyverno-verified), but an image build per docs change and in-cluster only. Deferred.
- **Self-hosted Forgejo Pages server** (`pages-server`/`git-pages`) — most literal "Forgejo Pages"
  and general-purpose, but another in-cluster service to operate; in-cluster only. Deferred.
