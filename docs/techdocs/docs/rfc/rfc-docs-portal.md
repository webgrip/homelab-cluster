# RFC: One docs portal, in the webgrip look, readable by whoever can read the repository

> Status: **Accepted** 2026-10-31, rollout step 1 in progress · Date: 2026-10-31 · Decider: Ryan Grippeling
> Builds on: [ADR-0052 (Zensical docs site on Garage web)](../adr/adr-0052-zensical-docs-site-garage-web.md) ·
> [ADR-0060 (gateway OIDC for apps without a login)](../adr/adr-0060-gateway-oidc-for-apps-without-a-login.md) ·
> [Access plane](rfc-access-plane.md) · [Docs platform 2026](rfc-docs-platform-2026.md) ·
> [Docs estate rollout](plan-docs-estate-rollout.md)
> Parks: [ADR-0039 (Backstage TechDocs)](../adr/adr-0039-backstage-techdocs.md)

**TL;DR.** docs.webgrip.dev already builds every repository with Zensical into its own bucket
and path. What it lacks is a front door, a look and a rule for who reads what. This RFC assembles
those from existing open source instead of building a docs platform: a portal at the root with
one search across every site, the webgrip brand as one installable Zensical theme (the only new
package), and access that follows the repository: a public repository's docs are public, a
private repository's docs sit behind the Authentik login and are read by the people the access
plane gives them to. Backstage stays parked.

## Why

- **No front door.** The root of docs.webgrip.dev is homelab-cluster's own site; the other
  sites are a list of links on its index page. Nobody lands on "the webgrip docs".
- **No look.** Every `mkdocs.yml` uses a stock Material palette (blue, orange, red). The brand
  exists, in [webgrip.nl's tokens](https://forgejo.webgrip.dev/webgrip/webgrip.nl/src/branch/main/src/styles/tokens.css),
  and no docs site uses it.
- **One rule for everything.** The site is LAN-only and has no login (ADR-0052, cons). Most
  repositories are public and open source, so their docs could be read by anyone; a few are
  private and their docs should not be on an unauthenticated host at all.
- **Backstage did not arrive.** ADR-0039 is still proposed, the `backstage-application` release
  path is broken and the repository is archived in the repo-config model. What it was meant to
  give (a catalogue, docs per component, one search) is cheaper to assemble around Zensical.

## What already exists, and what is reused

The owner asked to look around before building. For every part there is open source already;
the only gap is upstream, and it is on Zensical's own roadmap.

| Need | Open source that does it | Used here |
|---|---|---|
| Build each repository's docs | Zensical, from the repository's own `mkdocs.yml` | Yes, unchanged (`techdocs-deploy-docs-site.yml`) |
| One site from many repositories | Zensical "Multiple projects" / [Subprojects, backlog #44](https://github.com/zensical/backlog/issues/44) (accepted 2025-11-13, no date) · [zmerge](https://github.com/KarelZe/zmerge) (MIT, a stopgap that merges sources into one build) · [Antora](https://antora.org/) (AsciiDoc only) · Backstage TechDocs | Not yet. Each repository keeps its own build; the portal links them. zmerge is rejected: one merged build means one search index and one bucket, which cannot keep a private repository's pages out of a public site |
| One search across sites | Pagefind multisite (`mergeIndex`) | Yes. Every site already ships a Pagefind index; the portal merges the indexes the reader can fetch |
| A shared look | Zensical installable custom themes (since 0.0.37); for example the [Bifrost theme](https://pypi.org/project/intility-bifrost-zensical/0.1.3/) on PyPI | Yes: one new package, the webgrip theme |
| Login and who reads what | Authentik + Envoy Gateway `SecurityPolicy` (ADR-0060) + the access-plane model | Yes, extended with per-path authorization |
| Catalogue: what exists, who owns it | Backstage catalogue · the repo-config model (`repos.yaml`) | The repo-config model: it already knows every repository, its description, its visibility and whether it publishes docs |
| Ask the docs | `docs-mcp-server` (deployed), Open WebUI (deployed) · [Ask0](https://github.com/amicalhq/ask0) (AGPL, alpha) · RAGFlow (heavy) | Later phase; not in this RFC's rollout |

## Design

### 1. The portal at the root

A small Zensical site, in its own repository (`docs-portal`), published to the root bucket that
homelab-cluster's site occupies today. homelab-cluster's site moves to `/homelab-cluster/`;
the old paths get redirect stubs (the deploy workflow already writes them for renamed pages).

The portal's pages are generated at build time from the repo-config model, so a repository that
starts publishing docs appears without an edit to the portal:

- **Catalogue**: every repository with docs, its description, owner and licence, public or
  private, and a link to its site.
- **Search**: one box over every site the reader can open (below).
- **What changed**: recent releases and recent decision records across the estate.

### 2. One search across sites

Each site already builds a Pagefind index at `/<prefix>/pagefind/`. The portal's search box
lists the sites from the catalogue, fetches each index's entry file, keeps the ones that answer
200 and merges them with `mergeIndex`, each with its own `baseUrl`. A private site's index
answers 403 to a reader without access and is left out before the merge, so search never shows
a title the reader may not open.

### 3. The webgrip theme for Zensical

The one new package: `webgrip-zensical-theme`, an installable Zensical custom theme, open
source (Apache-2.0, like the estate's other products), published to the Forgejo PyPI registry
and mirrored to PyPI.

- **Tokens** from webgrip.nl: `--brand-orange #e7682d` marks action, `--brand-teal #408375`
  marks structure; light ground `#fcfbfa`, ink `#1e2a27`, muted `#4a5652`, border `#d8e0dd`;
  dark ground `#14201d`, ink `#f2f4f3`, accent `#f0824b`, link `#6fb3a2`. Manrope Variable as
  the one typeface. The rule in the tokens file, orange for action and teal for structure, is
  the rule in the theme.
- **Surfaces** as tokens (`--surface`, `--border`, `--shadow`), so both schemes stay one rule set
  and sites can draw their own panels the same way.
- **Logo and favicon** from webgrip.nl's generated brand assets.
- **Installed** into the techdocs-builder image's Zensical venv, so a repository opts in with
  `theme.name` in its `mkdocs.yml` and nothing else.

A theme cannot add markdown extensions; those stay in each `mkdocs.yml`, as the Bifrost theme
documents.

### 4. Who reads what

The rule is the repository's own visibility, read from the repo-config model:

- **A public repository's docs are public.** Its path is routed on `envoy-external`, with public
  DNS for docs.webgrip.dev. These repositories are already open source; their docs say nothing
  the source does not.
- **A private repository's docs sit behind the Authentik login.** Its path is routed only with a
  `SecurityPolicy` that adds a JWT provider reading the ID token from the OIDC cookie and an
  `authorization` block allowing the path to the token's groups. The readers are a capability in
  the access-plane model (by default the platform engineers and the repository's own team),
  projected onto an Authentik group like every other grant.
- **A repository whose docs must not be published at all** stays unpublished (erfbeeld today:
  it builds TechDocs and deliberately deploys nothing).

The routes and the authorization rules are generated from the two models, never hand-written,
so a repository changing visibility changes who can read its docs in the same merge.

Two checks before anything is public:

- The deploy workflow's gitleaks gate already blocks secrets. A public site also must not leak
  internal host names it does not need; a review of the public set is part of rollout step 4.
- Garage's web port must be reachable only through the gateways, so a private bucket is never
  readable around the login. This needs a network policy check; it is not verified today.

### 5. Backstage

Parked. ADR-0039 stays proposed and gets a dated note pointing here. The catalogue the portal
renders from the repo-config model, and the per-site docs, cover what Backstage would have given
this estate. Revisit when a second reason for a developer portal appears (scaffolding, ownership
of running services).

### 6. Upstream: Zensical project composition

Zensical's own model for this, "Subprojects" ([backlog #44](https://github.com/zensical/backlog/issues/44)),
is independently built projects composed into one site, which is how this design already
builds. When it lands, the portal becomes a composition instead of a link page, and the theme
carries over unchanged. The issue is accepted and locked to collaborators, so the way to help is
not a comment there; it is to share the use case through Zensical's own channels. Nothing is
posted without the owner's approval.

## Rollout

Each step is a pull request; the next waits until the previous one is live.

| Step | What | Done when |
|---|---|---|
| 1 | `webgrip-zensical-theme` repository, first release, installed in the techdocs-builder image | A repository building with `theme.name: webgrip` shows the brand in both schemes |
| 2 | `docs-portal` repository: catalogue and search, generated from the repo-config model, published to a staging prefix | The portal lists every publishing repository and finds pages across sites |
| 3 | Swap: the portal to the root, homelab-cluster to `/homelab-cluster/`, redirect stubs | Old homelab-cluster links land on the new paths; the weekly link check stays green |
| 4 | Public exposure: routes on `envoy-external` and public DNS for public repositories only, after the host-name review | A public site answers from outside the LAN; a private site does not |
| 5 | Private sites: `SecurityPolicy` with per-path authorization from the access-plane model | Signed out: login. A reader with the capability: 200. Without: 403. Search leaves the site out |
| 6 | Every repository's `mkdocs.yml` moves to the theme | No stock palette remains |

## Progress

- **Step 1, 2026-11-02:** [`webgrip-zensical-theme`](https://forgejo.webgrip.dev/webgrip/webgrip-zensical-theme)
  is on Forgejo with its first commit (theme package, tests, Test workflow, Renovate). The
  repository was created by hand; its entry in the repo-config model (`repos.yaml`) brings it
  under management with the Test workflow as the required check. The tests build a fixture site strict on the
  newest Zensical and on 0.0.53, the builder image's version; light and dark were checked in a
  headless browser. Not yet: the first release, the PyPI publish, and the builder image
  installing it.

## Questions answered by the owner, 2026-10-31

All four as recommended: the portal at the root with homelab-cluster on its own path;
`webgrip-zensical-theme` on the Forgejo PyPI registry, mirrored to PyPI; platform engineers plus
the repository's own team read a private repository's docs; the use case goes to Zensical after
step 3.
