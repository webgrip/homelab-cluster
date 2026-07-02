# ADR-0022: Serve TechDocs from Codeberg Pages (interim + off-site)

> Status: **Accepted** · Date: 2026-06-18 · Part of [RFC: TechDocs hosting after GitHub Pages](../rfc/rfc-codeberg-pages-techdocs.md)

## Context

TechDocs (the Backstage-format mkdocs site under `docs/techdocs/`) is built by CI and was deployed
to **GitHub Pages**. The GitHub exit removes that target, and Forgejo has no native Pages — the
deploy workflow was left pushing the built site to a `pages` branch nothing serves. A working,
serving target is needed *now*, while the in-cluster destination — Backstage TechDocs,
[ADR-0023](adr-0023-backstage-techdocs.md) — is built out later. The
[RFC](../rfc/rfc-codeberg-pages-techdocs.md) surveys five hosting options; the deciding constraints
for the *interim* are minimal in-cluster infrastructure, real off-site durability, and alignment
with the off-site redundancy already chosen in
[ADR-0020](adr-0020-codeberg-offsite-push-mirror.md).

## Decision

**Publish the built TechDocs site to Codeberg Pages.** CI force-pushes the static `techdocs-site`
artifact to a Codeberg repository's `pages` branch (an orphan snapshot), with a `.domains` file
carrying `docs.webgrip.dev`; Codeberg serves it over its own Let's Encrypt certificate, and DNS
CNAMEs `docs.webgrip.dev` to `webgrip.codeberg.page`. The deploy workflow lives in the
`webgrip/workflows` reusable-workflow library, **not this repo** (not verifiable from here); this
repo carries the supporting resources — the `DNSEndpoint`
(`kubernetes/apps/network/cloudflare-dns/app/codeberg-pages-dnsendpoint.yaml`,
`cloudflare-proxied=false`, published by external-dns) and the token provisioning (below).

This is **explicitly interim and off-site** — the documentation half of the ADR-0020 redundancy
story. When Backstage TechDocs (ADR-0023) lands as the primary in-cluster surface, Codeberg Pages
is **retained as the DR/off-site mirror**, not removed.

## Alternatives considered

The [RFC](../rfc/rfc-codeberg-pages-techdocs.md) weighs the full option set — Garage S3 static
website, Backstage TechDocs, a signed OCI image in Harbor, and a self-hosted Forgejo Pages server.
Every in-cluster option lost *for the interim* on the same axis: no off-site durability; and
Backstage is the sequenced long-term primary ([ADR-0023](adr-0023-backstage-techdocs.md)), not the
quick win.

## Consequences

- **Docs survive cluster loss** — the published site lives off-cluster, so an outage that takes
  down Forgejo/Backstage does not take the docs with it. This is the main reason to do it first.
- **Zero in-cluster serving infrastructure** — no bucket, Deployment, or pages-server; only a CI
  push step, a token, and DNS.
- **Public-only.** Codeberg Pages serves public content; access-controlled docs wait for
  Backstage + Authentik (ADR-0023).
- **New credential + external dependency:** a Codeberg token is minted into OpenBao
  (`codeberg/pages`) and provisioned as a Forgejo org Actions secret (`codeberg-pages`
  ExternalSecret + the `forgejo-actions-secrets` CronJob). Acceptable: Codeberg is the community
  Forgejo host, philosophically aligned, and already the chosen off-site Git mirror.
- **One-time manual prerequisites** (handed off, not GitOps): create the Codeberg repo and mint the
  token into OpenBao. See the [RFC](../rfc/rfc-codeberg-pages-techdocs.md) §Operations.

## Status log

- 2026-06-18 — Accepted.
- 2026-06-21 — The `docs` CNAME brought under GitOps: `DNSEndpoint` added for external-dns to
  publish.
