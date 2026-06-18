# ADR-0006: Authenticate Harbor via Authentik OIDC, layered in a second phase

> Status: **Accepted** · Date: 2026-06-12 · Part of [RFC: Harbor Container Registry](../rfc/rfc-harbor-registry.md)

## Context

The cluster's SSO is [Authentik](../general/authentik.md), wired to apps via blueprint-driven OIDC
providers (grafana, n8n, backstage, forgejo). Harbor supports OIDC, but with a wrinkle: **Harbor
stores its auth configuration in its own database, not in Helm values** — OIDC is applied at
runtime (UI/API), or declaratively via the chart's `core.configureUserSettings` JSON. Wiring OIDC
before the matching Authentik application exists would crash-loop the core, and Harbor still needs
a working login the moment it boots (for the admin and for robot/CLI flows).

## Decision

Roll OIDC out in **two phases**:

1. **Phase 1 — local auth.** Harbor boots in `db_auth` with a local admin (password from
   `secret/harbor/core` → `HARBOR_ADMIN_PASSWORD`). Robot accounts / CLI use tokens regardless of
   auth mode.
2. **Phase 2 — OIDC.** Add the Authentik blueprint
   `kubernetes/apps/authentik/app/blueprints/36-oidc-harbor.yaml` (redirect URI
   `https://harbor.${SECRET_DOMAIN}/c/oidc/callback`, slug `harbor`), store the issued client
   id/secret in `secret/harbor/oidc` as a `core.configureUserSettings` `values.yaml` fragment,
   surface it via the `harbor-oidc-values` ExternalSecret, and merge it into the HelmRelease with
   `valuesFrom … optional: true`.

## Consequences

- Harbor is usable from first boot; SSO is added without a chicken-and-egg crash-loop.
- `optional: true` on the OIDC `valuesFrom` means the core starts even if `secret/harbor/oidc` is
  absent — Phase 2 is genuinely additive and reversible.
- **`configureUserSettings` is re-applied on every core restart** — it is the source of truth, so
  auth settings changed in the UI get reverted. The fragment is kept minimal and version-controlled
  (the literal domain, not `${SECRET_DOMAIN}`, since ESO does not do build-time substitution).
- Keeps a **local admin fallback** for break-glass if Authentik is unavailable.

## Alternatives considered

- **Local accounts only** — simplest, no blueprint, but no SSO and a separate identity silo
  divorced from the cluster's Authentik groups.
- **Wiring OIDC in a single phase at install** — fewer commits, but risks a first-boot loop against
  a not-yet-existent Authentik application and couples the registry's availability to SSO setup
  ordering.
