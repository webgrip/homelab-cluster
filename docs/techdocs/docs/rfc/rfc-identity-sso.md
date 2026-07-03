# RFC: Identity & SSO architecture

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** Authentik is the cluster's identity provider, configured entirely as code, with five
> apps on OIDC — and none of that is a recorded decision. Worse, OIDC is the **only** integration
> mode in use: everything without native OIDC support (Longhorn UI, searxng, flux-ui, drawio,
> excalidraw, the alertmanager/vmsingle routes, policy-reporter, …) sits on the LAN with **no
> authentication at all**. This RFC backfills the adoption ADRs and forces the real decision: what
> is the SSO story for apps that can't speak OIDC?

## Why

What exists (verified in-tree 2026-07-02):

- **Authentik 2026.5.2** (`kubernetes/apps/authentik/`), CNPG-backed, blueprint-driven: 8
  blueprints covering core groups/users, policies, MFA flows, and OIDC providers for **grafana,
  backstage, forgejo, openbao, harbor**. The [authentik doc](../general/authentik.md) describes
  operations; no record says why Authentik (vs Keycloak, Zitadel, Dex, or nothing).
- **Configuration-as-code is total**: providers/flows/groups land via blueprints (apply-order
  matters — see the [authentik-oidc-login runbook](../runbooks/authentik-oidc-login.md)); the
  client secrets ride ESO+OpenBao. This is a house pattern other decisions build on (ADR-0022
  Phase 2) and it has no parent record.
- **Machine identity is deliberately outside SSO** — the Renovate bot
  ([ADR-0030](../adr/adr-0030-forgejo-static-bot-pat.md)), Harbor's break-glass local admin
  ([ADR-0022](../adr/adr-0022-authentik-oidc-phased.md)) — decided per-app, never as a principle.
- **No outpost, no proxy provider, no forward-auth** exists anywhere in the tree. Repo-wide, the
  only "outpost" hit is an alert-description comment. So the integration menu is: native OIDC, or
  nothing.

The hole: of ~25 apps routed on `envoy-internal`, only five authenticate via Authentik and a few
more have app-local logins. The rest are protected solely by "you must be on the LAN" — which
default-deny (ADR-0006) does nothing about (it governs pod-to-pod, not human-to-gateway), and
which erodes with every device that joins the network. Longhorn's UI can **delete volumes**;
flux-ui can inspect the cluster; the observability routes leak everything the cluster knows.
A single phished/compromised LAN device inherits all of it.

## Proposal

1. **Backfill two retroactive ADRs**: (a) adopt Authentik as the cluster IdP — context,
   alternatives (Keycloak's weight, Zitadel's youth, Dex's statelessness-without-UI), and the
   accepted consequence that login availability now depends on one single-replica app + its DB;
   (b) blueprint-as-code as the only sanctioned configuration path (UI changes are drift), with
   machine-identity-stays-local as a recorded principle, not per-app folklore.
2. **Decide the non-OIDC story** (the real new decision). Options to weigh:
   - **Authentik proxy provider + embedded outpost as forward-auth on the gateway** — Envoy
     Gateway supports ext-auth via a `SecurityPolicy`; Authentik's outpost is the house-native
     answer. One decision covers every non-OIDC app; per-app opt-in via route config.
   - **Per-app basic-auth / oauth2-proxy sidecars** — no new Authentik surface, but N moving
     parts and N configs; loses central groups/MFA.
   - **Accept LAN-only for a named list** — legitimate for some (echo, drawio?), but it must be a
     *list with a rationale*, not the default outcome of "app lacks OIDC".
   The recommendation is forward-auth via Authentik outpost + Envoy `SecurityPolicy`, rolled out
   app-by-app starting with the highest-privilege UIs (Longhorn, flux-ui).
3. **Inventory + classify every route** as part of the rollout: OIDC / forward-auth / app-local /
   deliberately-open, recorded in the [applications doc](../general/applications.md) so coverage
   is checkable rather than vibes.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Adopt Authentik as the cluster IdP (retroactive) |
| candidate | — | Blueprint-as-code config model + machine-identity-stays-local principle (retroactive) |
| candidate | — | Forward-auth for non-OIDC apps via Authentik outpost + Envoy SecurityPolicy (new) |

## Out of scope

- Kubernetes API access (kubeconfig/talosctl credentials) — single-operator today; revisit if a
  second human arrives.
- OIDC for CLI/robot flows (Harbor robot accounts, Forgejo tokens) — already decided per-app.
- Authentik HA — bound by the single-instance posture of the [Postgres RFC](rfc-postgres-data-layer.md)
  and not worth solving separately.

## References

- [Authentik](../general/authentik.md) · [authentik-oidc-login runbook](../runbooks/authentik-oidc-login.md) ·
  the `authentik-oidc` skill
- [ADR-0022](../adr/adr-0022-authentik-oidc-phased.md) ·
  [ADR-0030](../adr/adr-0030-forgejo-static-bot-pat.md) ·
  [observability-auth runbook](../runbooks/observability-auth.md)
