# Renovate secrets (SOPS)

This folder intentionally commits **templates only** for Renovate secrets (no plaintext secrets in git).

## Secrets you must create

### 1) GitHub auth for Renovate

- **Secret name:** `renovate-secrets`
- **Namespace:** `renovate`
- **Required keys:**
  - `RENOVATE_TOKEN`: GitHub credential Renovate uses to discover repos and open PRs

Template: `secret.template.yaml`

### 2) Webhook auth (public endpoint)

- **Secret name:** `renovate-webhook-auth`
- **Namespace:** `renovate`
- **Required keys:**
  - `token`: bearer token(s) for the webhook endpoint
    - can be a single token or multiple tokens separated by commas

Template: `webhook-auth.secret.template.yaml`

## Create the encrypted secrets

1) Copy the templates to `*.sops.yaml` files:

- `secret.sops.yaml` (from `secret.template.yaml`)
- `webhook-auth.secret.sops.yaml` (from `webhook-auth.secret.template.yaml`)

2) Fill in values, then encrypt:

- `sops -e -i kubernetes/apps/renovate/renovate-operator/jobs/secret.sops.yaml`
- `sops -e -i kubernetes/apps/renovate/renovate-operator/jobs/webhook-auth.secret.sops.yaml`

3) Add the encrypted secrets to `kustomization.yaml` in this folder.

## Notes

- `RENOVATE_TOKEN` is for GitHub API operations (repo discovery, PRs, issues/comments).
- The webhook bearer `token` is separate; it only protects the public webhook endpoint.
