# Authenticate Harbor via Authentik OIDC, layered in a second phase

* Status: accepted
* Date: 2026-06-12

Technical Story: [RFC: Harbor Container Registry](../rfc/rfc-harbor-registry.md)

## Context and Problem Statement

The cluster's SSO is [Authentik](../general/authentik.md), wired to apps via blueprint-driven OIDC
providers (grafana, n8n, backstage, forgejo). Harbor supports OIDC, but with a wrinkle: **Harbor
stores its auth configuration in its own database, not in Helm values** — OIDC is applied at
runtime (UI/API), or declaratively via the chart's `core.configureUserSettings` JSON. Wiring OIDC
before the matching Authentik application exists would crash-loop the core, and Harbor still needs
a working login the moment it boots (for the admin and for robot/CLI flows).

## Considered Options

* A two-phase rollout (local `db_auth` first, OIDC second)
* Local accounts only
* Wiring OIDC in a single phase at install

## Decision Outcome

Chosen option: "A two-phase rollout (local `db_auth` first, OIDC second)", because Harbor needs a
working login the moment it boots, and wiring OIDC before the matching Authentik application
exists would crash-loop the core.

Roll OIDC out in **two phases** (both are now live):

1. **Phase 1 — local auth.** Harbor boots in `db_auth` with a local admin (password from
   `secret/harbor/core` → `HARBOR_ADMIN_PASSWORD`). Robot accounts / CLI use tokens regardless of
   auth mode.
2. **Phase 2 — OIDC.** The Authentik blueprint
   `kubernetes/apps/authentik/app/blueprints/36-oidc-harbor.yaml` (redirect URI
   `https://harbor.${SECRET_DOMAIN}/c/oidc/callback`, slug `harbor`) issues the provider; the
   client id/secret live in `secret/harbor/oidc` as a `core.configureUserSettings` `values.yaml`
   fragment, surfaced via the `harbor-oidc-values` ExternalSecret and merged into the HelmRelease
   with `valuesFrom … optional: true`.

### Positive Consequences

* Harbor is usable from first boot; SSO is added without a chicken-and-egg crash-loop.
* `optional: true` on the OIDC `valuesFrom` means the core starts even if `secret/harbor/oidc` is
  absent — Phase 2 is genuinely additive and reversible.
* Keeps a **local admin fallback** for break-glass if Authentik is unavailable.

### Negative Consequences

* **`configureUserSettings` is re-applied on every core restart** — it is the source of truth, so
  auth settings changed in the UI get reverted. The fragment is kept minimal and version-controlled
  (the literal domain, not `${SECRET_DOMAIN}`, since ESO does not do build-time substitution).

## Pros and Cons of the Options

### A two-phase rollout (local `db_auth` first, OIDC second)

* Good, because Harbor is usable from first boot and SSO lands without a chicken-and-egg
  crash-loop.
* Good, because Phase 2 is genuinely additive and reversible (`optional: true` on the OIDC
  `valuesFrom`).
* Bad, because it takes more commits than wiring OIDC in a single phase.

### Local accounts only

* Good, because simplest — no blueprint.
* Bad, because no SSO and a separate identity silo divorced from the cluster's Authentik groups.

### Wiring OIDC in a single phase at install

* Good, because fewer commits.
* Bad, because it risks a first-boot loop against a not-yet-existent Authentik application.
* Bad, because it couples the registry's availability to SSO setup ordering.

## Links

* 2026-06-12 — accepted; deployed with Phase 1 (`db_auth`) live at first boot
* 2026-06-12 — Phase 2 implemented the same day: blueprint `36-oidc-harbor.yaml` +
  `harbor-oidc-values` ExternalSecret landed (fully GitOps client credential, no CLI ceremony)
* 2026-07-03 — renumbered from ADR-0006 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
