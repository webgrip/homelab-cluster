# Plan: docs.webgrip.dev estate rollout — every repo's docs, one domain

> Status: **Planned** (research-refined 2026-08-11; awaiting go) · Date: 2026-08-11 · For
> [ADR-0052](../adr/adr-0052-zensical-docs-site-garage-web.md) /
> [RFC: Docs platform 2026](rfc-docs-platform-2026.md). Option A (path-per-repo) chosen by the
> owner; Backstage TechDocs (ADR-0039) remains the later cross-repo-search lane and consumes the
> same artifacts.

Each repo publishes its Zensical-built site into the shared Garage `docs-site` bucket under its
own prefix; Garage web serves it all at `docs.${SECRET_DOMAIN}/<repo>/`. homelab-cluster stays at
the root. Opt-in is explicit: a repo is published **iff** it carries the `on_docs_change` caller.

## Research base (2026-08-11, three verified sweeps)

- **Subpath serving is proven**: Zensical output is 100% relative URLs (`"base":"../.."`,
  relative search-worker path, zero absolute hrefs) — no per-repo `site_url` surgery needed.
- **Live Forgejo sweep of all 38 org repos** (all public; exposure analysis in §Security):
  11 repos have a `docs/techdocs` tree; caller drift is 4-way (SHA-pinned Codeberg /
  `@main` gh-pages / `@main` update_techdocs / none). **twente.dev is an empty repo on Forgejo**
  (no branches — excluded until content lands); **backstage-application's mkdocs.yml is 0
  bytes** (full bootstrap needed). 9 of 11 configs use the `markdown_inline_mermaid` +
  `markdown_inline_graphviz` extensions; 5 (the template family) add `custom_dir: overrides` +
  the Material `privacy` plugin.
- **Dual-engine config, verified empirically** (mkdocs-material 9.7.7 + zensical 0.0.53):
  one shared `mkdocs.yml` is the answer — Zensical's team recommends *against* `zensical.toml`
  for existing projects, and everything we want is expressible in the shared file:
  `theme.variant` (Material ignores it, even `--strict`), unknown `theme.features` strings
  (both engines ignore), and — the unlock — **`material.extensions.preview` works in BOTH
  engines** (Zensical remaps `material.extensions.*` → `zensical.extensions.*`). Two traps:
  the `zensical.extensions.*` spelling crashes Material at render, and every
  `markdown_extensions` entry must be importable in *both* environments — which rules out
  `zensical.extensions.glightbox` until the techdocs-core lane retires (zensical cannot be
  pip-installed beside techdocs-core; the pymdown conflict from run 334). Zensical caching:
  always `zensical build --clean` in CI (upstream's own recommendation).
- **gitleaks 8.30.1, empirically mutation-tested** on synthetic trees: `gitleaks dir site/`
  (modern CLI), inline `# gitleaks:allow` works in no-git dir scans, `[[allowlists]]` with
  path + line-regex targeting suppresses runbook examples while a planted AWS key still fires;
  0.4 s over 18 MB/400 files. Static binary via the Harbor ghcr proxy
  (`COPY --from=…/gitleaks/gitleaks:v8.30.1 /usr/bin/gitleaks`); Alpine apk only has it in
  edge/testing. Keep line-regexes anchored to explicit markers (`example|placeholder|dummy`) —
  broad patterns were shown to mask real keys.

## Inventory and per-repo actions

| Repo | Today | Action | Risk |
| ---- | ----- | ------ | ---- |
| homelab-cluster | three-leg caller, root | **done**; gains feature adoption + strict | low |
| infrastructure | SHA-pinned Codeberg leg; clean config | flip → `infrastructure` | **low — first drop-in** |
| telemetry-service | `update_techdocs@main`; clean + inline-ext | replace → `telemetry-service` | low¹ |
| ledgerflow | GitHub-side caller only | add caller → `ledgerflow` | low¹ |
| monitoring-platform | GitHub-side only; graphviz load-bearing | add caller → `monitoring-platform` | low¹ |
| searxng-application | GitHub-side only; 1-page site | add caller → `searxng-application` | low¹ |
| workflows | gh-pages leg; custom_dir + privacy + inline-ext | flip → `workflows` | medium² |
| action-typescript-template | gh-pages leg; template family | flip — **new repos inherit** | medium² |
| application-template | no caller; template family | add caller — **template leverage** | medium² |
| freshrss-application | GitHub-side only; family + live `G-FAKE` gtag | add caller; drop the fake gtag | medium² |
| invoiceninja-application | GitHub-side only; family | add caller | medium² |
| backstage-application | mkdocs.yml is 0 bytes | bootstrap a real mkdocs.yml first | high³ |
| ploeg | no docs tree | out of scope until docs exist | — |
| twente.dev | empty repo on Forgejo | blocked — nothing to build | — |
| erfbeeld | not on this Forgejo | excluded | — |

¹ needs the two inline markdown extensions in the **zensical venv** (Phase 0 image work; the
Material lane already ships both — `markdown-inline-mermaid` direct, `markdown-graphviz-inline`
via techdocs-core; the `dot` binary is in the image).
² `custom_dir: overrides` must be vetted under Zensical's MiniJinja (fallback: drop the feedback
partials); `privacy` runs in the Material lane (CI has egress) and is silently ignored by
Zensical — acceptable.
³ full bootstrap: real `site_name`/theme/nav for `docs/adr` + `docs/structurizr`.

## Phase 0 — plumbing (one commit each in infrastructure + workflows)

- [ ] **techdocs-builder v1.5.0**: gitleaks binary (`COPY --from` the ghcr proxy, digest-pinned)
      + estate config baked at `/etc/gitleaks/docs.toml` (`[extend] useDefault`, runbook-path +
      explicit-marker allowlists) + `requirements-zensical.in` gains
      `markdown-inline-mermaid==1.0.4` and `markdown-graphviz-inline==1.1.3` (recompiled,
      hash-locked) so Zensical can build the 9 inline-extension repos.
- [ ] **`techdocs-deploy-docs-site.yml`**: `dest-prefix` input (prefix-scoped `rclone sync` —
      repos cannot clobber each other); `strict` input (default false; runs
      `zensical build --clean --strict`); **gitleaks gate** before every sync
      (`gitleaks dir site/ --config /etc/gitleaks/docs.toml --no-banner --redact` — findings
      fail the leg, nothing publishes); bump container to 1.5.0.
- [ ] Mutation-test the gate exactly once: plant a fake AWS key in a scratch page → leg must
      fail; marked example line → must pass (the alerting-rules lesson: test both directions).

## Phase 1 — flagship adoption (homelab-cluster)

- [ ] Fix the 3 link defects Zensical's validator found (2 anchors in
      rfc-layered-hardware-architecture, 1 template link) and flip `strict: true`.
- [ ] Shared-safe feature block in `mkdocs.yml`: `navigation.instant`,
      `navigation.instant.progress`, `navigation.instant.preview`, `navigation.path`,
      `navigation.prune`, `search.highlight`, plus `material.extensions.preview` targeting
      `adr/*`, `runbooks/*`, `rfc/*` (hover previews of cross-references in both engines) and
      `theme.variant: modern` (explicit). Verify BOTH lanes locally in the 1.5.0 image before
      pushing.
- [ ] Estate landing: "Estate docs" section on the root index linking each prefix.

## Phase 2 — the four clean drop-ins

- [ ] infrastructure (flip the Codeberg leg; delete its stale `site_url`), then
      telemetry-service, ledgerflow, monitoring-platform, searxng-application (replace/add
      callers; `strict: false` until each repo's links are cleaned). Verify
      `docs.${SECRET_DOMAIN}/<repo>/` + `/llms.txt` per repo before moving on; check
      monitoring-platform's graphviz diagrams render.

## Phase 3 — the template family

- [ ] Vet `overrides/` partials under Zensical on ONE repo (workflows); drop the feedback
      partials if MiniJinja rejects them. Then flip/add callers: workflows,
      action-typescript-template, application-template, freshrss-application (also remove the
      `G-FAKE` gtag), invoiceninja-application. Template repos get the caller so every future
      repo is born published.

## Phase 4 — stragglers + polish

- [ ] backstage-application: write a real mkdocs.yml (ADRs + structurizr exports), add caller.
- [ ] Retire the GitHub-side `.github/workflows/on_docs_change.yml` copies in repos that gained
      Forgejo callers (one system of record).
- [ ] Watchlist ([RFC](rfc-docs-platform-2026.md)): glightbox + TOML-only features when the
      techdocs-core lane retires; Zensical subprojects (their roadmap's hierarchical
      multi-project model may replace path-prefixes wholesale); Disco vector search; ZAP-009
      agentic topic model.

## Security posture (the "secret docs" question, answered)

1. **Nothing on the site exceeds git's exposure.** Every publishing repo is public on Forgejo +
   GitHub; the site is the same content, LAN-only (envoy-internal + split DNS, external-dns
   excluded, no public DNS record, Codeberg gone).
2. **Secret values in docs** are the real risk (they'd also be a git leak): the Phase-0 gitleaks
   gate blocks publish, with the estate allowlist keeping runbook examples green — and the gate
   is mutation-tested in both directions before trust.
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
