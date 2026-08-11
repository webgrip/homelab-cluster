# Plan: docs.webgrip.dev estate rollout — every repo's docs, one domain

> Status: **Planned** · Date: 2026-08-11 · For [ADR-0052](../adr/adr-0052-zensical-docs-site-garage-web.md) /
> [RFC: Docs platform 2026](rfc-docs-platform-2026.md). Option A (path-per-repo) chosen by the
> owner 2026-08-11; Backstage TechDocs (ADR-0039) remains the later cross-repo-search lane and
> consumes the same artifacts.

Each repo publishes its Zensical-built site into the shared Garage `docs-site` bucket under its
own prefix; Garage web serves it all at `docs.${SECRET_DOMAIN}/<repo>/`. homelab-cluster stays at
the root. Opt-in is explicit: a repo is published **iff** it carries the `on_docs_change` caller.

## Inventory (Forgejo org sweep, 2026-08-11)

All 38 org repos are **public** (and mirrored to GitHub) — the rendered site adds no exposure
beyond what git already publishes. Non-mirror, non-archived repos with a `docs/techdocs` tree:

| Repo | Docs workflow today | Action |
| ---- | ------------------- | ------ |
| homelab-cluster | new three-leg caller | **done** (root) |
| infrastructure | generate + Codeberg leg (dead) | flip → prefix `infrastructure` |
| workflows | generate + gh-pages leg (dead) | flip → prefix `workflows` |
| telemetry-service | old `update_techdocs.yml` shape | replace → prefix `telemetry-service` |
| twente.dev | old caller (+ root mkdocs for its website) | flip docs leg → prefix `twente.dev` |
| action-typescript-template | old caller | flip — **template: new repos inherit the caller** |
| application-template | none | add caller — **template leverage** |
| freshrss-application | none | add caller |
| invoiceninja-application | none | add caller |
| ledgerflow | none | add caller |
| monitoring-platform | none | add caller |
| searxng-application | none | add caller |
| backstage-application | none (mkdocs.yml at repo **root**) | add caller with `source-dir: .` |
| ploeg | no docs tree | out of scope until docs exist |
| erfbeeld | not on this Forgejo | excluded |

## Phase 0 — plumbing (webgrip/workflows + techdocs-builder)

- [ ] `techdocs-deploy-docs-site.yml`: add `dest-prefix` input (default `''` = root); sync to
      `garage:docs-site/<prefix>`; with a prefix, `rclone sync` scopes deletion to that prefix —
      repos can never clobber each other.
- [ ] Secret gate (see §Security): add `gitleaks` to techdocs-builder (apk, → v1.5.0) and a
      `gitleaks detect --no-git -s site/` step before every sync — a finding fails the leg and
      nothing publishes.
- [ ] Fix the 3 real link defects Zensical's validator found in this repo (2 anchors in
      rfc-layered-hardware-architecture, 1 template link in adr-0000), then add
      `zensical build --strict` so broken links fail the build estate-wide.

## Phase 1 — estate landing

- [ ] "Estate docs" section on the root index linking each prefix (manual list; auto-index
      later if it grows past ~15).

## Phase 2 — flip the five repos with existing callers

- [ ] infrastructure, workflows, telemetry-service, twente.dev, action-typescript-template:
      replace the dead leg with `deploy-docs-site` (pinned SHA, `dest-prefix: <repo>`).
      Codeberg/gh-pages legs deleted — ADR-0052 applies estate-wide.

## Phase 3 — add callers to the rest

- [ ] application-template (template leverage), freshrss-application, invoiceninja-application,
      ledgerflow, monitoring-platform, searxng-application; backstage-application with
      `source-dir: .`.

## Phase 4 — Zensical feature adoption (shared-config-safe only)

One `mkdocs.yml` still drives BOTH engines (Material builds the TechDocs artifact, Zensical the
site), so only engine-shared settings go in now: `theme.features` gains `navigation.instant`,
`navigation.instant.progress`, `navigation.prune`, `navigation.path`, `search.highlight`
(Material ignores unknown flags; Zensical honours them; `navigation.instant.prefetch` is
Zensical-experimental — enable and watch). Zensical-exclusive goodies (instant hover previews,
native glightbox, TOML config, `variant = "modern"` explicitly) wait for either a `zensical.toml`
layering story or the retirement of the Material artifact lane — tracked in the
[RFC watchlist](rfc-docs-platform-2026.md). Zensical ships **no redirects and no llms.txt** —
both are already covered estate-wide by the graft step in the deploy leg, which is why every repo
uses the shared reusable rather than rolling its own.

## Security posture (the "secret docs" question, answered)

1. **Nothing on the site exceeds git's exposure.** Every publishing repo is public on Forgejo +
   GitHub; the site is the same content, LAN-only (envoy-internal + split DNS, external-dns
   excluded, no public DNS record, Codeberg gone).
2. **Secret values in docs** are the real risk (they'd also be a git leak): the Phase-0 gitleaks
   gate blocks publish; the agent-side guard-secrets hooks remain the first line.
3. **Publishing is opt-in per repo** — no caller file, no site. If a repo ever goes private, its
   docs do NOT get a caller until an authenticated lane exists (Authentik forward-auth via Envoy
   Gateway `SecurityPolicy` on the docs HTTPRoute — the seam
   [rfc-request-authorization-envoy](rfc-request-authorization-envoy.md) names; or Backstage,
   which sits behind Authentik already, ADR-0039).
4. **Do not rely on draft mechanisms**: Zensical ignores MkDocs' `draft_docs`/`exclude_docs`,
   and `search.exclude` only hides pages from search, not from URLs. Convention: anything not
   for publication lives OUTSIDE `docs/techdocs/` (e.g. `docs/internal/`).
5. `llms-full.txt` aggregates only what is already on the site — no additional exposure.

## Rollback

Per repo: delete its caller workflow + `rclone purge garage:docs-site/<prefix>` (or wait — the
next estate sync of that prefix is scoped and touches nothing else). The homelab root site and
the ADR-0039 artifact lane are untouched by any of it.
