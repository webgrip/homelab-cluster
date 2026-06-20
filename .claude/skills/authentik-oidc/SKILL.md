---
name: authentik-oidc
description: Add SSO / OIDC login for an app via Authentik — provider blueprints (apply order), client_id/client_secret via ESO+OpenBao, exact redirect-URI matching.
when_to_use: Use when wiring an app to Authentik SSO, creating an OIDC provider blueprint, or debugging an OIDC login failure or redirect-URI mismatch.
---

# Authentik OIDC onboarding

Authentik is the IdP; providers are **blueprints** the operator applies.

## Add an app to SSO
1. **Blueprint** `kubernetes/apps/authentik/app/blueprints/<nn>-oidc-<app>.yaml`. `<nn>` numeric prefix sets apply order (enforced by `guard-skills.sh`). Declare cross-blueprint deps with `metaapplyblueprint` (groups/users, policies, MFA flows) — **missing deps fail silently**; check this first if a blueprint "can't see" objects.
2. **Register** the filename in `authentik/app/kustomization.yaml` (`configMapGenerator`).
3. **Secret — ESO+OpenBao, never SOPS** (see the `external-secrets` skill). `client_secret` is internal entropy → **generate it in-cluster**, never hand-enter it:
   - authentik-side `ExternalSecret` → `generatorRef` password-generator (`refreshInterval: "0"`, `deletionPolicy: Retain`), rewrite `password` → `<APP>_OIDC_CLIENT_SECRET`;
   - inject into the blueprint via the authentik HelmRelease `global.env` + `client_secret: !Env <APP>_OIDC_CLIENT_SECRET` (`client_id` is a pinned literal, not secret);
   - a `PushSecret` (store `openbao-push`) mirrors it to `secret/<app>/oidc`;
   - the **app** reads it back via an `ExternalSecret` (store `openbao`, `creationPolicy: Owner`), consumed by `existingSecret`/`envFromSecret`.
   - Pattern files: `kubernetes/apps/authentik/app/harbor-oidc-client.{externalsecret,pushsecret}.yaml` + app-side `kubernetes/apps/harbor/harbor/app/harbor-oidc-values.externalsecret.yaml`.
4. **Redirect URI** must match exactly: `https://<app>.$${SECRET_DOMAIN}/<callback>` (path varies — check app docs).
5. **Rotation:** generate-once + Retain keeps the value stable. To rotate, delete the `<app>-oidc-client` Secret — it re-generates + re-pushes, and Authentik + the app re-sync on the next reconcile (~10m).

## Debugging login failures (almost never Authentik itself — check in order)
1. **Pod DNS** — can the app pod resolve the Authentik host? (Split-DNS → k8s-gateway `10.0.0.26`.) After a DNS fix, **restart app pods** (they cache NXDOMAIN).
2. **Credentials** match the provider.
3. **Redirect URI** matches exactly.

Refs: `docs/techdocs/docs/authentik.md`, `docs/techdocs/docs/runbooks/authentik-oidc-login.md`.

## Validate
`mise exec -- kustomize build kubernetes/apps/authentik/app` (renders the blueprints ConfigMap) → `./scripts/run-flux-local-test.sh`.
