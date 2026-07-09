# Vikunja as the task-management system, complementing Forgejo issues

* Status: proposed
* Date: 2026-07-09

Technical Story: [RFC: Task management — survey the field, pick a system](../rfc/rfc-task-management.md)

## Context and Problem Statement

The cluster has no task-management system: strategy lives in the git-owned roadmap, code work in
Forgejo issues, and everything else (recurring drills, renewals, chores, cross-project follow-ups)
in nobody's head reliably. Forgejo's project boards cannot fill the gap — as of v15 they have no
REST API, no webhooks, no recurrence, and no CalDAV
([forgejo#5330](https://codeberg.org/forgejo/forgejo/issues/5330)). Which self-hosted system
should own task-shaped work, given the platform's standards (CNPG Postgres, Authentik OIDC,
ESO/OpenBao, app-template deployment, ~€3/yr per continuous watt)?

## Decision Drivers

* OSI-approved FOSS license with low rug-pull risk (2025–26 saw Planka leave FOSS and Tegon die)
* PostgreSQL on CNPG — no second database engine to operate
* OIDC in the free tier — SSO is the category's open-core moat (OpenProject, Plane, Worklenz all
  paywall it)
* Footprint: single container beats microservice sprawl on a 5-node mini-PC cluster
* Automation surface: REST API + outgoing webhooks, so n8n/ntfy can see and drive task state
* The actual job: recurring tasks, reminders, CalDAV, kanban, cross-project views for one operator

## Considered Options

* Vikunja
* Kanboard
* Planka
* Plane (Community Edition)
* OpenProject (Community Edition)
* Stay with Forgejo issues + roadmap only (do nothing)

## Decision Outcome

Chosen option: "Vikunja", because it is the only candidate in the surveyed top-20 that passes
every decision driver (see the RFC's ranked table): AGPL-3.0, a single Go container against CNPG
Postgres, native free OIDC with known-good Authentik integration, ~100–350 MB footprint, a full
REST API plus native outgoing webhooks, and — uniquely in the field — first-party CalDAV,
recurring tasks, and reminders alongside kanban/list/gantt/table views. v2.3.0 (2026-04-09) is
active, with an official image and Helm chart.

Implementation shape (follow-up work, standard patterns throughout):

* `kubernetes/apps/vikunja/vikunja/` — bjw-s app-template, image digest-pinned via the Harbor
  proxy ([ADR-0023](adr-0023-harbor-pull-through-proxy-cache.md)), worker-pool placement
  ([ADR-0002](adr-0002-application-workload-placement.md))
* CNPG `Cluster` + the cnpg-backup component ([ADR-0019](adr-0019-external-cnpg-database.md)
  pattern); OIDC client secret via ESO/OpenBao; Authentik provider blueprint
* `vikunja.${SECRET_DOMAIN}` on envoy-internal, LAN-first
  ([ADR-0021](adr-0021-lan-only-exposure.md) posture); external exposure for mobile
  capture/CalDAV is a separate, deferred decision
* Webhooks → n8n → ntfy for task-event delivery

Division of labour is part of the decision: Forgejo issues keep repo-bound work, the roadmap
stays the git-owned strategy layer, Vikunja owns operational/recurring/personal tasks.

### Positive Consequences

* Recurring/calendar/reminder-shaped work finally has an automatable home; ntfy + n8n can act on
  task events instead of task state being invisible (the Forgejo-boards failure mode).
* Zero new platform primitives: every dependency (Postgres, OIDC, secrets, ingress, backups) is
  an existing, drilled pattern — the app is mostly configuration.
* Tiny standing cost (single Go container) against the €3/W-yr heuristic.

### Negative Consequences

* Open-core watch: "Vikunja Pro" (2026, private beta) introduces paid self-hosted add-ons; core
  remains AGPL today, but drift must be monitored (re-open trigger in the RFC watch-list).
* Bus factor ~1 (lead maintainer) and recent major-version churn (v1.0.0 2026-01 → v2.0.0
  2026-02, which shipped 4 critical security fixes) — pin digests, let Renovate soak releases.
* A second place tasks can live; the Forgejo/Vikunja boundary is a convention that needs
  discipline, not tooling, to hold.

## Pros and Cons of the Options

### Vikunja

* Good, because the only all-pass against the drivers; CalDAV + recurrence + reminders are
  first-party, not plugins.
* Good, because Go single binary + CNPG Postgres + native OIDC — the cheapest candidate to
  operate on this platform.
* Bad, because Pro-tier drift risk and a ~1-person bus factor.

### Kanboard

* Good, because the license-safest option in the field (MIT, 12 years, never monetized) and
  ultra-light.
* Bad, because feature-frozen by design, OIDC only via plugin, JSON-RPC instead of REST, no
  CalDAV/recurrence beyond basics — and the most-CVE'd candidate of 2025–26 (patched fast).

### Planka

* Good, because the best Trello-style UX in the field, Postgres-only, free OIDC with documented
  Authentik integration.
* Bad, because not FOSS since v2.0 (fair-code "Fair Use License"), recurring cards already
  paywalled, upsell banner in the free edition — the drift already happened.

### Plane (Community Edition)

* Good, because the strongest Linear-shaped feature set (cycles, modules, five views) with REST
  API + webhooks in CE.
* Bad, because OIDC is Enterprise-Grid-gated — disqualifying for an Authentik shop — and the
  default deployment is 12 pods / ~1.8 GB.

### OpenProject (Community Edition)

* Good, because the most capable suite with the field's best official Helm chart and required
  Postgres.
* Bad, because OIDC/SAML is an Enterprise add-on (verified against current docs), useful board
  variants are Enterprise too, and it is the heaviest Rails footprint on the shortlist.

### Stay with Forgejo issues + roadmap only

* Good, because zero new watts, zero new surface.
* Bad, because the gap is structural: boards have no API/webhooks (invisible to n8n), and
  recurrence/CalDAV/reminders don't exist at all — the do-nothing option is how task-shaped work
  ended up homeless.

## Links

* Spawned by [RFC: task management](../rfc/rfc-task-management.md) (field survey, ranked top-20,
  watch-list re-open triggers)
* 2026-07-09 — proposed; nothing deployed yet (`kubernetes/apps/vikunja/` does not exist)
* 2026-07-09 — implementation landed: `kubernetes/apps/vikunja/` (app-template, CNPG `vikunja-db`
  Tier 2, zero-trust ns, LAN HTTPRoute) + Authentik blueprint 37 with the generated-client-secret
  loop; status stays proposed until the end-to-end OIDC login + first backup are verified live
