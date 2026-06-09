---
name: authentik-oidc
description: Add SSO / OIDC login for an app via Authentik. Use when wiring an application to Authentik for single sign-on, creating an OIDC provider blueprint, or debugging OIDC login failures.
---

# Authentik OIDC onboarding

Authentik is the IdP; providers are **blueprints** the operator applies.

## Add an app to SSO
1. **Blueprint** `kubernetes/apps/authentik/app/blueprints/<nn>-oidc-<app>.yaml`. `<nn>` numeric prefix sets apply order (enforced by `guard-skills.sh`). Declare cross-blueprint deps with `metaapplyblueprint` (groups/users, policies, MFA flows) — **missing deps fail silently**; check this first if a blueprint "can't see" objects.
2. **Register** the filename in `authentik/app/kustomization.yaml` (`configMapGenerator`).
3. **App side:** `<app>-oidc-secrets.template.yaml` documenting `client_id`/`client_secret`/`issuer`; human SOPS-encrypts (never write `*.sops.yaml`); wire via `existingSecret`/`envFromSecret`.
4. **Redirect URI** must match exactly: `https://<app>.$${SECRET_DOMAIN}/<callback>` (path varies — check app docs).
5. After reconcile (~10m), fetch the generated `client_id`/`client_secret` from Authentik to populate the secret.

## Debugging login failures (almost never Authentik itself — check in order)
1. **Pod DNS** — can the app pod resolve the Authentik host? (Split-DNS → k8s-gateway `10.0.0.26`.) After a DNS fix, **restart app pods** (they cache NXDOMAIN).
2. **Credentials** match the provider.
3. **Redirect URI** matches exactly.

Refs: `docs/techdocs/docs/authentik.md`, `docs/techdocs/docs/runbooks/authentik-oidc-login.md`.
