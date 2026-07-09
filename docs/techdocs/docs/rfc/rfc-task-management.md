# RFC: Task management — survey the field, pick a system

> Status: **Proposed** · Date: 2026-07-09

> **TL;DR.** The cluster has no task-management system: work lives in a 100-item
> [roadmap.md](../general/roadmap.md), Forgejo issues, and heads. Twenty OSS candidates were
> surveyed (facts web-verified 2026-07-09 — licenses, paywalls, and maintenance status all
> moved in 2025–2026, so training-data folklore is stale). Exactly **one** candidate clears
> every cluster-derived constraint — FOSS license, CNPG Postgres, free OIDC, small footprint,
> API+webhooks, recurring tasks/CalDAV: **Vikunja**. Proposal: adopt it as a *complement* to
> Forgejo issues (ADR-0040), not a replacement.

## Why

- **The incumbent can't do this job.** Forgejo issues are solid for code-adjacent work (labels,
  milestones, due dates, dependencies, time tracking, full REST API + webhooks) and stay the
  home for repo-bound tasks. But as a *task system* it stops there — verified against Forgejo
  v15 (2026-04): project boards have **no REST API at all** (can't list boards, move cards, or
  read a column — [forgejo#5330](https://codeberg.org/forgejo/forgejo/issues/5330), open since
  2024, no milestone), no board webhooks, no recurring tasks, no CalDAV, no reminders, no
  cross-repo "today" view, and mobile apps are blocked on the missing API. Board state is
  invisible to n8n by construction.
- **Task-shaped work is piling up outside git.** The roadmap holds strategy fine, but
  operational and personal tasks (drills, renewals, household/chores, "check X after the next
  release") have no home with recurrence, reminders, or a calendar.
- **The platform is ready for a tenant app.** CNPG, ESO+OpenBao, Authentik, the app-template +
  Harbor-proxy pattern, ntfy, and n8n mean a well-chosen app is mostly configuration.

## What "fits" means here

Criteria derived from the platform, not from feature checklists:

| # | Criterion | Source |
| --- | --------- | ------ |
| C1 | OSI-approved FOSS license, low rug-pull risk | sovereignty program; 2025–26 relicensing wave |
| C2 | PostgreSQL on CNPG — no new DB engine to operate | [ADR-0019](../adr/adr-0019-external-cnpg-database.md), [Postgres data layer RFC](rfc-postgres-data-layer.md) |
| C3 | OIDC in the **free** tier (Authentik) | [ADR-0022](../adr/adr-0022-authentik-oidc-phased.md), identity SoT plan |
| C4 | Small footprint — 1 continuous watt ≈ €3/yr; single container ≫ microservice sprawl | hardware RFCs; 5-node mini-PC cluster |
| C5 | REST API + outgoing webhooks — automatable from n8n, notifiable via ntfy | existing automation plane |
| C6 | Solo-operator features: recurring tasks, reminders, CalDAV, kanban, cross-project views | the actual job to be done |
| C7 | Maintenance health: active releases, plausible bus factor, honest funding | Focalboard/Tegon corpses below |

## The field — top 20, ranked

Facts verified 2026-07-09 (releases via GitHub API, gating via vendor pricing/docs pages).
Footprints are user-report ranges, not benchmarks. ✓ pass · ~ partial/via plugin · ✗ fail.

| # | System | License (C1) | DB (C2) | OIDC free (C3) | Idle footprint (C4) | API+hooks (C5) | Verdict |
| --- | ------ | ------------ | ------- | -------------- | ------------------- | -------------- | ------- |
| 1 | **Vikunja** v2.3.0 (2026-04) | AGPL-3.0 ⚠ new "Pro" tier | ✓ PG/MySQL/SQLite | ✓ native | ✓ Go binary, ~100–350 MB | ✓ REST + native webhooks | The only all-✓. Kanban/list/gantt/table, **recurring + reminders + CalDAV**, Trello/Todoist import. Flags: Pro drift, bus factor ~1, v1→v2 in a month |
| 2 | **Kanboard** 1.2.52 (2026-04) | ✓ MIT, 12 yrs, no paywall ever | ✓ PG recommended | ~ OAuth2 plugin | ✓ PHP, <100 MB | ~ JSON-RPC (not REST) + webhooks | License-safest; swimlanes, WIP limits, automation rules. Feature-frozen by design ("complete"); 3 critical CVEs 2025–26 (patched fast); dated UX |
| 3 | **Planka** v2.1.1 (2026-04) | ✗ **Fair-Use since 2.0 — not FOSS** (MIT→AGPL→fair-code) | ✓ PG only | ✓ native, Authentik doc'd | ✓ ~80–150 MB | ✓ REST + Apprise/webhooks | Best Trello UX in the field; personal use permitted, but recurring cards already Pro-paywalled + upsell banner in CE. License excludes it from winning |
| 4 | **Donetick** v0.1.75 (2026-04) | ✓ AGPL, self-host ungated | ✓ PG/SQLite | ✓ native, names Authentik | ✓ Go binary, tiny | ✓ REST + webhooks + HA integration | Chores/household niche done right: adaptive recurrence, gamification, Telegram/Pushover. 0.x; not project management — a *complement*, not the system |
| 5 | **tududi** v1.2.0 (2026-07) | ✓ MIT | ~ SQLite; PG undocumented | ✓ incl. Authentik | ✓ light Node | ✓ REST + Swagger, Telegram capture | Fastest-moving newcomer: bidirectional CalDAV, recurring, GTD-ish. Solo maintainer, weeks-old 1.0, DB story thin — watch-list, not yet a bet |
| 6 | **Kan** (kan.bn) v0.6.0 (2026-06) | ✓ AGPL (SaaS-funded) | ✓ PG | ✓ generic OIDC | ~ Next.js, unmeasured | ~ tRPC-first, webhooks, MCP server | Credible AGPL Trello: import, checklists, S3 attachments. Pre-1.0 ("prerelease" tags), due dates unconfirmed — re-evaluate at 1.0 |
| 7 | **WeKan** v9.83 (2026-07) | ✓ MIT | ✗ **MongoDB** (FerretDB shim possible) | ✓ OAuth2/OIDC | ✗ ~400 MB + Mongo, leak history | ✓ rich REST + webhooks | Richest pure kanban (real swimlanes, rules engine), near-daily releases. Mongo breaks C2; bus factor 1; recent upload-RCE patched |
| 8 | **Redmine** 7.0 (2026-06) | ✓ GPL-2.0, no open core | ✓ PG | ~ plugin (bake into image) | ~ lightest Rails, 0.5–1 GB | ✓ mature REST + **native webhooks in 7.0** | The 20-year workhorse, 3 supported branches, accelerating. Kanban is plugin territory; 2010s UX |
| 9 | **OpenProject** 17.6 (2026-07) | ~ GPL-3.0 open-core | ✓ PG required | ✗ **OIDC/SAML = Enterprise** | ✗ Rails suite, 1.5–2.5 GB, 4–5 pods | ✓ APIv3 + webhooks | Most capable suite + the field's best official Helm chart; but SSO paywall kills it for an Authentik shop, and useful kanban variants are Enterprise too |
| 10 | **Plane** v1.3.1 (2026-05) | ~ AGPL CE, editions split | ✓ PG (+Redis+RabbitMQ+MinIO) | ✗ **OIDC = Enterprise Grid** | ✗ ~1.8 GB, 12-pod Helm default | ✓ REST + webhooks in CE | Best Linear-shaped CE (cycles/modules/5 views). SSO gating steepest of the field; VC ($4M seed); already relicensed once (Apache→AGPL 2023) |
| 11 | **Leantime** v3.9.8 (2026-07) | ✓ AGPL + proprietary-plugin carve-out | ✗ **MySQL/MariaDB** | ✓ native, free | ✓ ~2 containers | ~ JSON-RPC + MCP | ADHD-friendly PM, time tracking free, very active. MySQL = a second DB engine to operate; breaks C2 |
| 12 | **Taiga** 6.10.2 (2026-07) | ✓ MPL-2.0 | ✓ PG (+RabbitMQ ×2) | ~ community plugin + image rebuild | ✗ 8–9 containers, ~4 GB host | ✓ REST + webhooks | Best-in-class Scrum; maintained (security fixes) but feature-frozen under new stewards; AngularJS 1.x frontend; successor is Tenzu (#18) |
| 13 | **Nextcloud Deck** 1.18.2 (2026-06) | ✓ AGPL | ✓ PG (via Nextcloud) | ✓ user_oidc | ✗ requires **full Nextcloud** (+Redis+cron) | ✓ REST; Flow automation | Healthy app, new Gantt view, CalDAV-adjacent via Tasks — but the Nextcloud tax is unjustifiable for one board |
| 14 | **Huly** v0.7.x (2026-07) | ✓ EPL-2.0, self-host ungated | ✗ **CockroachDB+ES+Redpanda+MinIO** | ✓ native | ✗ 15+ containers, 8–16 GB | ~ TS client SDK, no plain REST | Feature monster (tracker+docs+chat). Hosted service shuts down 2026-07-20 "no longer funded"; company pivoting to blockchain — viability risk on top of the sprawl |
| 15 | **AppFlowy** 0.12.5 (2026-06) | ✓ AGPL ⚠ commercial self-host fork appeared | ✓ PG (+GoTrue+Redis+MinIO) | ~ **SAML** via Authentik; OIDC still an open request | ✗ 6–8 containers, 2–4 GB | ~ limited/underdocumented | Notion-class docs/grid, not a task tracker; client-first heritage; category mismatch |
| 16 | **Odoo 19 Project** (2025-10) | ~ LGPL CE / proprietary Enterprise | ✓ PG only | ~ free via OCA `auth_oidc` addon | ✗ ~1–2 GB realistic | ✓ JSON-RPC, n8n has nodes | ERP with a project module: kanban+timesheets free, **Gantt/Planning Enterprise**; major-version migration treadmill; massive surface for a to-do board |
| 17 | **Worklenz** v2.1.7 (2026-02) | ✓ AGPL core | ✓ PG (+Redis+MinIO) | ✗ SSO = $99/mo tier | ✗ ~5–6 containers | ✗ **no webhooks, no public API docs** | Time tracking + resource views free, but automation-blind and small (3.1k stars); slow cadence |
| 18 | **Tenzu** 1.x (2025-09) | ✓ (BIRU; NLnet-funded) | ✓ PG (Django) | unverified | unmeasured (young) | unverified | The official Taiga-next: genuinely maintained, far too young to bet on — revisit in 12 months |
| 19 | **Super Productivity** v18 (2026-07) | ✓ MIT | ~ local-first; optional PG sync server | ✗ none (passkeys on sync) | ✓ negligible server | ✗ no server API (data lives client-side) | Excellent *personal client* (pomodoro, timeboxing, Jira/OpenProject sync) — architecturally not a multi-user server app; wrong shape |
| 20 | **Tasks.md** v3.3.0 (2026-03) | ✓ MIT | ✓ none — tasks are `.md` files | ✗ no auth (forward-auth only) | ✓ tiny | ✗ none | Charming git-friendly single-user board; deliberately "low maintenance"; a toy next to C5/C6 |

**Evaluated and disqualified** (kept to prevent re-derivation): **Focalboard** — standalone
unmaintained since 2023-10, open call-for-maintainers; **Taskcafe** — abandoned in alpha, 2021;
**Tegon** — repo archived 2025-06, company pivoted to AI (the rug-pull case study);
**ZenTao** — MySQL-only + non-OSI dual license; **Tracks** — GTD on life support (dependabot-only
commits, no SSO); **GitLab CE** — 5–8 GB behemoth, redundant next to Forgejo; **4ga Boards,
myTinyTodo, Nullboard, Taskwarrior** — wrong shape (fork-of-Planka-lineage / toys / CLI).

## Reading of the field

Three patterns worth recording:

1. **SSO is the open-core moat of this category.** OpenProject, Plane, and Worklenz all paywall
   OIDC — precisely the feature an Authentik shop can't compromise on. C3 does more elimination
   work than any other criterion.
2. **2025–2026 was a license-drift year**: Planka left FOSS entirely; Vikunja and AppFlowy both
   sprouted commercial self-host edges; Huly's free-everything model visibly failed to fund
   itself. The MIT twelve-year-old (Kanboard) and the GPL twenty-year-old (Redmine) are the
   stability outliers.
3. **Nothing beats the incumbent for code work.** Every candidate's issue tracking is worse than
   Forgejo's for repo-bound tasks. The gap is *around* code: recurrence, calendar, reminders,
   automation-visible boards — which is why the proposal is complement, not replace.

## Proposal

1. **Adopt Vikunja** ([ADR-0040](../adr/adr-0040-vikunja-task-management.md)) as the task system
   for everything that isn't a repo-bound issue: `kubernetes/apps/vikunja/` via the app-template
   + Harbor-proxy pattern, CNPG cluster + barman backup component, ESO/OpenBao secrets, Authentik
   OIDC blueprint, `vikunja.${SECRET_DOMAIN}` on envoy-internal (LAN-first per
   [ADR-0021](../adr/adr-0021-lan-only-exposure.md) posture), worker-pool placement, webhooks →
   n8n → ntfy.
2. **Division of labour**: Forgejo issues keep code/repo work; the git-owned roadmap stays the
   strategy layer; Vikunja owns operational/recurring/personal tasks and the cross-project view.
3. **Open question — mobile capture**: CalDAV sync and the PWA from outside the LAN need an
   exposure decision (VPN vs cloudflare-tunnel vs stay-LAN). Defer to the
   [ingress/edge RFC](rfc-ingress-dns-edge.md) posture; don't let it block LAN adoption.
4. **Watch-list** (conditions to re-open this RFC): Vikunja Pro starts eating core features;
   Kan reaches 1.0 with due dates; Forgejo ships the Projects API
   ([#5330](https://codeberg.org/forgejo/forgejo/issues/5330)); tududi documents Postgres.

## Decisions

| ADR | Status | Decision |
| --- | ------ | -------- |
| [ADR-0040](../adr/adr-0040-vikunja-task-management.md) | proposed | Vikunja as the task-management system, complementing Forgejo issues |

## Verification notes

Release versions/dates checked against GitHub/vendor pages on 2026-07-09; paywall boundaries
against live pricing/docs pages (OpenProject SSO-FAQ, Plane pricing, planka.app/pricing,
worklenz.com/self-hosted). Honest unknowns: Kan due dates + real RAM; tududi Postgres; Tenzu
SSO/API; Odoo Community timesheet exact scope; idle-RAM figures are user reports, not
measurements. Vikunja Pro licensing is contested between vikunja.io/pro ("all AGPL") and
isitreallyfoss.com (admin-panel plugin non-FOSS) — treated here as early open-core drift.
