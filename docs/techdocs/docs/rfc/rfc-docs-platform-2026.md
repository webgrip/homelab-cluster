# RFC: Docs platform 2026 — engine succession and agent-era enhancements

> Status: **Proposed** · Date: 2026-08-09
> Relates to: [ADR-0038 (Codeberg Pages interim)](../adr/adr-0038-codeberg-pages-techdocs.md) ·
> [ADR-0039 (Backstage TechDocs target)](../adr/adr-0039-backstage-techdocs.md) ·
> [plan-backstage-techdocs](plan-backstage-techdocs.md)

## Verdict

**Keep the TechDocs bet (ADR-0039) and build it now; do not migrate generators.** The
MkDocs ecosystem our docs are authored in is collapsing on a hard date — Material for MkDocs hits
EOL **2026-11-05** — but the succession path (Zensical, from the same author, reads `mkdocs.yml`
natively) is the one the Backstage TechDocs maintainers themselves have proposed adopting
(RFC [#33990](https://github.com/backstage/backstage/issues/33990)). Our content format survives
the transition unchanged; the engine swap is a CI-container detail we inherit from upstream. The
real 2026 upgrade is not a prettier site — it is making the doc set **agent-consumable** (llms.txt
+ per-page raw markdown + an in-cluster docs-search MCP tool), because agents are already the
majority reader of engineering docs industry-wide, and in this repo they are effectively the *only*
reader today.

## What the 2026-08-09 research established

Four parallel research streams (Backstage/TechDocs state, generator landscape, AI-era docs trends,
local estate map). Key findings, each sourced:

### The MkDocs foundation is on a countdown

- **MkDocs core is effectively unmaintained**: last release 1.6.1 (2024-08-30); maintainer
  implosion documented in
  ["The Slow Collapse of MkDocs"](https://fpgmaas.com/blog/collapse-of-mkdocs/). The announced
  MkDocs 2.0 **removes the plugin system** — incompatible with `mkdocs-techdocs-core` by design.
- **Material for MkDocs entered maintenance mode 2025-11-05; EOL 2026-11-05**
  ([announcement](https://squidfunk.github.io/mkdocs-material/blog/2025/11/05/zensical/)). 9.7.0
  was the final feature release; all Insiders features were made free; the line ends at 9.7.x.
- **Zensical** ([zensical.org](https://zensical.org)) is squidfunk's successor: MIT, Rust core,
  differential builds, **reads `mkdocs.yml` natively** — existing Material projects carry over
  with minimal changes. Pre-1.0; ~5.4k stars in nine months.

### Backstage TechDocs: alive, feature-frozen, and choosing the same exit

- TechDocs is maintained (mkdocs-techdocs-core 1.7.0, 2026-06-10; security patches in Backstage
  v1.47) but in a strategic holding pattern: zero TechDocs items on the Backstage roadmap; the
  energy is on engine succession
  ([#32815](https://github.com/backstage/backstage/issues/32815)).
- **RFC [#33990](https://github.com/backstage/backstage/issues/33990)** (2026-04-17, filed by the
  TechDocs maintainers) proposes migrating TechDocs from MkDocs to Zensical — dual-engine
  transition, aiming to complete before the Material EOL. It **explicitly rejects** Docusaurus and
  Sphinx: "a full rewrite of TechDocs internals" that would "break every existing user's setup."
  Not ratified yet.
- TechDocs remains **hard-coupled to the MkDocs format** — no official support for any other
  generator exists, and none is planned. The de-risking path is Zensical compatibility, not
  generator pluralism.
- Backstage itself is healthy: CNCF Incubating with a Graduation audit in progress, monthly
  releases, and an official MCP plugin (`@backstage/plugin-mcp-actions-backend`) exposing catalog
  actions to agents.

### The generator landscape outside TechDocs

Momentum leaders for docs-as-code in 2026, if we ever leave the TechDocs world:

| Tool | Status 2026 | Why it matters / why not us |
|---|---|---|
| **Zensical** | pre-1.0, 5.4k★, Rust | `mkdocs.yml`-compatible successor; TechDocs' own proposed target — our default destination |
| **Astro Starlight** | ~9k★, prod-grade | Cloudflare/OpenAI/Microsoft docs; plain-MD, Pagefind offline search — strongest *independent* choice, but no TechDocs integration |
| **Fumadocs** | 12.8k★, fastest riser | Vercel's Next.js docs stack; MDX-centric, React — wrong shape for us |
| **Docusaurus 3.9** | mature incumbent | best versioning, but heavy MDX/React, slow at scale; rejected by Backstage RFC #33990 anyway |
| **Hugo + Hextra** | rising | fastest air-gapped builds, mermaid built-in; no portal integration |
| Mintlify / GitBook / ReadMe | SaaS, ~$300+/mo | feature benchmarks only; not self-hostable, pointless spend here |

### Agents are the reader now

- [Mintlify's mid-2026 traffic report](https://www.mintlify.com/blog/state-of-docs-traffic):
  agents = **66% of docs traffic** across their platform (July 2026: 213M agent requests vs 105M
  human page loads; Claude Code alone 199M). [GitBook's April 2026
  data](https://www.gitbook.com/blog/ai-docs-data-april-2026): agents are 51.8% of intentional
  reads. Vendor-sourced but log-based, and directionally consistent.
- In **this repo** the pattern is already at its endpoint: the render/publish leg was never built
  (no docs-publish workflow exists; see the [Codeberg RFC's implementation
  status](rfc-codeberg-pages-techdocs.md)), so the 165-page doc set is consumed exclusively as raw
  markdown in git — by Claude agents (CLAUDE.md + 30+ skill references treat runbooks/ADRs as
  canonical) and humans reading the repo.
- **llms.txt** failed as an SEO artifact (Google won't consume it; crawler pickup ~0.1%) but works
  as an **on-demand agent affordance** — coding agents fetch it when pointed at a docs site, and
  the [Agent-Friendly Docs Spec](https://agentdocsspec.com/) calls it the single most effective
  discovery mechanism for coding agents. MkDocs plugins exist today:
  [`mkdocs-llms-source`](https://github.com/TimChild/mkdocs-llms-source) (llms.txt + llms-full.txt
  + per-page `.md` at the same URL path, nav-derived) and
  [`mkdocs-llmstxt`](https://github.com/pawamoy/mkdocs-llmstxt).
- **Docs-as-MCP** is table stakes for SaaS platforms (Mintlify, GitBook auto-generate MCP
  servers). The self-hosted pattern is a thin MCP server exposing **one search tool** over your
  own index ([Prefect's writeup](https://dev-log.prefect.io/making-a-docs-mcp-server/)) — exactly
  the shape this cluster already runs for VictoriaLogs docs (`mcp__victorialogs__documentation`).
- Polished AI answer layers (Kapa, Algolia AskAI, Mintlify chat) are SaaS-only; Diátaxis remains
  the reference structure framework, newly relevant because agents navigate predictable content
  typing well.

## Layer map — who claims which seam

| Seam | Today | Claimant going forward |
|---|---|---|
| Authoring format | Markdown + `mkdocs.yml` (TechDocs format) | unchanged — survives the engine swap |
| Build engine | mkdocs + mkdocs-material (EOL 2026-11-05) | **Zensical via mkdocs-techdocs-core**, inherited from upstream |
| Publish/serve | **nothing** (publish leg never built) | ADR-0039: CI `techdocs-cli publish` → Garage S3 → Backstage `builder: external` |
| Portal integration | Backstage deployed + catalog entities annotated | Backstage TechDocs reader (only claimant; healthy) |
| Human search | mkdocs lunr (unused — site unpublished) | TechDocs built-in; revisit only if outgrown |
| Agent discovery | none (agents read git directly) | **unclaimed → llms.txt + per-page raw .md** (this RFC) |
| Agent Q&A/search | none | **unclaimed → optional in-cluster docs-search MCP tool** (watchlist) |
| Off-site DR | Codeberg Pages (DNS + token landed, workflow missing) | ADR-0038 unchanged — build the missing workflow leg |

## The one honest scenario for leaving TechDocs

If Backstage's catalog value never materialises for a one-operator homelab — and agents stay the
dominant consumer — then a rendered portal is ballast, and the simpler architecture is "raw
markdown in git + llms.txt + one MCP search tool + a trivial static site (Starlight) for public
sharing." The tension is **portal-integrated human docs vs agent-first markdown**. We are not
taking that fork now because Backstage is already deployed, healthy, and SSO-gated, the marginal
cost of ADR-0039 is configuration plus a bucket, and the agent-first affordances layer on top of
TechDocs rather than competing with it. Re-open this fork only on the triggers below.

## Recommendations

1. **Execute ADR-0039 now** ([plan](plan-backstage-techdocs.md) Phases 0–5): Garage `techdocs`
   bucket, Backstage `builder: external` + `awsS3`, CI publish job — and finally build the missing
   Codeberg DR publish leg (ADR-0038) from the same artifact. The external-builder strategy is
   also the engine-swap insulation: Backstage serves prebuilt objects and never cares what built
   them.
2. **Add agent affordances to the build**: `mkdocs-llms-source` (or `mkdocs-llmstxt`) in the
   TechDocs CI image so every publish emits `llms.txt`, `llms-full.txt`, and per-page raw `.md` at
   stable URLs. Near-zero cost, highest-leverage agent win.
3. **Do not migrate to Starlight/Fumadocs/Docusaurus** — it would sever the TechDocs coupling that
   is the point of the format (ADR-0039's own rationale), and Backstage upstream rejected those
   engines for the same reason.
4. **Track the Zensical transition passively** — do nothing until the flip triggers below fire;
   then the migration should be a CI-image bump + `mkdocs.yml` compatibility pass, not a rewrite.
5. **Defer the docs-search MCP server** until the site is actually published and a real
   retrieval gap shows up; the Prefect one-tool pattern is the template when it does.

## Watchlist — concrete flip triggers

| Trigger | Watch | Action when it fires |
|---|---|---|
| Backstage RFC #33990 ratified / `mkdocs-techdocs-core` ships Zensical support | [backstage/backstage#33990](https://github.com/backstage/backstage/issues/33990), [mkdocs-techdocs-core releases](https://github.com/backstage/mkdocs-techdocs-core) | Bump the techdocs CI image; run a compatibility build of this doc set under Zensical |
| Material for MkDocs EOL passes (2026-11-05) with no ratified TechDocs successor | same as above | Pin the last-known-good techdocs container digest; re-evaluate this RFC — the "leave TechDocs" fork re-opens |
| Zensical 1.0 with a redirects-equivalent plugin (we depend on `mkdocs-redirects` for ~100 legacy URLs) | [zensical/zensical releases](https://github.com/zensical/zensical) | Compatibility pass becomes safe to schedule |
| Backstage catalog still single-entity and agents >90% of consumption 6 months after ADR-0039 ships | our own usage | Re-open the "one honest scenario" fork above |

## More Information

- 2026-08-09 — *[research]* four-stream landscape survey (TechDocs state, generator landscape,
  AI-era trends, local estate map); verdict folded into this RFC and ADR-0039's history.
- 2026-08-09 — the Zensical watchlist trigger was pulled **early, deliberately**, for the human
  surface only: the owner dropped the Codeberg leg and chose a Zensical-built site served from
  Garage's web endpoint ([ADR-0052](../adr/adr-0052-zensical-docs-site-garage-web.md)). A live
  spike validated the bet first (this exact tree: 166 pages, 1.95 s, mermaid + search native;
  redirects + llms.txt grafted in CI from the mkdocs artifact). The TechDocs artifact pipeline
  (ADR-0039, recommendation 1) is unchanged and remains the Backstage on-ramp; recommendation 4's
  "wait for the flip triggers" is thereby overtaken for the site, still standing for the artifact.

## Estate patterns + frontier survey (2026-08-11, post-rollout)

Three research streams after the estate wipe incident prompted "should we do this differently".

**Verdict: keep the architecture.** The CI-build-per-repo → bucket-prefix pattern is exactly
Backstage TechDocs' own storage model ("TechDocs without Backstage"); no standalone OSS estate-hub
tool exists to adopt instead, and the orgs with resources (HashiCorp `web-unified-docs`,
Cloudflare) are retreating INTO content monorepos rather than federating — a non-option here
because docs-beside-code is what the agent fleet reads. Two structural hardenings adopted onto
the watchlist instead of any redesign:

1. **Per-prefix scoped Garage keys + `rclone --backup-dir`** — deletion isolation by credential
   construction (the wipe becomes impossible, not merely guarded) with deletes moved to a trash
   prefix. Supersedes trust in the dynamic-exclude guard alone.
2. **Pagefind multisite** — the missing cross-estate search: each repo's CI adds a
   `pagefind --site site/` pass; the landing page merges every `/{prefix}/pagefind` bundle
   browser-side (same-domain, no CORS, no server). This is the standard answer to "one search
   box over N static sub-sites".

**Ranked "next wave" menu** (full sourcing in the session research; effort ≈ half-day each unless
noted): own-docs **MCP server** (arabold/docs-mcp-server, Ollama/keyword, beside the existing
grafana/victorialogs MCPs — agents are the majority reader); **docs dashboards from Envoy access
logs already in VictoriaLogs** (pageviews, 404-repeat alerts, agent-vs-human split — zero new
services); **nightly drift agent** (manifest commits vs docs pages, one rolling PR);
**build-time cluster inventory pages** (mkdocs-macros over `kubernetes/apps/**` — macros is
native in both engines); **site-wide glossary tooltips** (`abbr` + snippets `auto_append` +
`content.tooltips` — the mkdocs-material docs' own no-plugin trick, pairs with the
domain-language work); **lychee external-link CI** (closes what `--strict` internal-only leaves);
**Vale prose lint** (added-lines-only via reviewdog); **freshness footers**
(git-revision-date-localized; Zensical Tier 2); **social cards** (Material built-in; Zensical
Tier 2); **Kroki self-hosted** (D2/C4/Structurizr fences — renders backstage-application's
`workspace.dsl`; structurizr-site-generatr, 1–2 d, is the drill-down C4 endgame); **Runme
executable runbooks** (1 d); **deepwiki-open** over the estate as a labeled generated overview.
Already at parity, no action: llms.txt/llms-full/raw-md, hover previews, instant nav, redirects
(Pydantic ships the identical set; FastAPI + SQLModel already build with Zensical in production).

