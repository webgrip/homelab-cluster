---
name: authentik-oidc
description: Add SSO / OIDC login for an app via Authentik. Use when wiring an application to Authentik for single sign-on, creating an OIDC provider blueprint, or debugging OIDC login failures.
---

# Authentik OIDC onboarding

Authentik is the identity provider. Providers are defined as **blueprints** that the Authentik operator applies.

## Add an app to SSO
1. **Blueprint:** `kubernetes/apps/authentik/app/blueprints/<nn>-oidc-<app>.yaml`.
   - Blueprints apply in **alphabetical filename order** — the `<nn>` numeric prefix controls ordering.
   - Declare cross-blueprint dependencies with `metaapplyblueprint` entries (core groups/users, policies, MFA flows). **Missing dependency declarations fail silently** — if a blueprint "can't see" objects it needs, this is the first thing to check.
2. **Register** the blueprint filename in `kubernetes/apps/authentik/app/kustomization.yaml` (`configMapGenerator`).
3. **App side:** create `<app>-oidc-secrets.template.yaml` documenting the keys (client_id/client_secret/issuer), encrypt with SOPS (human step — never write `*.sops.yaml` directly), and add it to the app's kustomization. Wire into the app via `existingSecret`/`envFromSecret`.
4. **Redirect URI** must match exactly, e.g. `https://<app>.${SECRET_DOMAIN}/<callback-path>` (callback path varies per app — check the app's OIDC docs).
5. After Flux reconciles the blueprint (~10m), fetch the generated `client_id`/`client_secret` from Authentik (API or UI) to populate the secret.

## Debugging OIDC login failures
Login failures are **almost never** Authentik itself. Check, in order:
1. **Pod DNS** — can the app pod resolve the Authentik hostname? (Split-DNS: in-cluster CoreDNS forwards the cluster zone to k8s-gateway `10.0.0.26`.) After any DNS/CoreDNS fix, **restart the app pods** — they cache NXDOMAIN.
2. **Credentials** — do the app's `client_id`/`client_secret` match the Authentik provider?
3. **Redirect URI** — does it exactly match what's configured in the provider?

Full reference: `docs/techdocs/docs/authentik.md`, `docs/techdocs/docs/runbooks/authentik-oidc-login.md`.
