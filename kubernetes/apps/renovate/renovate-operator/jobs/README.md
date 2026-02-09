# Renovate secrets (SOPS)

This folder commits SOPS-encrypted Secrets for Renovate, plus plaintext templates for reference.

## Secrets in this setup

### 1) GitHub App credentials (SOPS-managed)

These credentials are used by the token minter CronJob to mint a short-lived GitHub App installation token.

- **Secret name:** `renovate-secrets`
- **Namespace:** `renovate`
- **Required keys:**
  - `RENOVATE_GITHUB_APP_ID`
  - `RENOVATE_GITHUB_APP_INSTALLATION_ID`
  - `RENOVATE_GITHUB_APP_PRIVATE_KEY` (PEM)

Template: `secret.template.yaml`

### 2) Renovate runtime token (NOT GitOps-managed)

This Secret is created/updated automatically in-cluster (do not commit it to git).

- **Secret name:** `renovate-runtime-token`
- **Namespace:** `renovate`
- **Key:** `token` (the GitHub App installation token; expires hourly)

Created/rotated by: CronJob `renovate-github-app-token`

### Bootstrap (run once, manually)

The GitHub App token is rotated by the CronJob every 15 minutes.
If you want the runtime Secret created immediately (e.g. right after first install), run a one-off Job from the CronJob:

- `kubectl -n renovate create job --from=cronjob/renovate-github-app-token renovate-github-app-token-bootstrap-$(date +%s)`

### 3) Webhook auth (public endpoint)

- **Secret name:** `renovate-webhook-auth`
- **Namespace:** `renovate`
- **Required keys:**
  - `token`: bearer token(s) for the webhook endpoint
    - can be a single token or multiple tokens separated by commas

Template: `webhook-auth.secret.template.yaml`

## Create / update the SOPS secrets

1) Update `kubernetes/apps/renovate/renovate-operator/jobs/secret.sops.yaml` with the GitHub App keys above.

1) Update `kubernetes/apps/renovate/renovate-operator/jobs/webhook-auth.secret.sops.yaml` with your bearer token(s).

## Notes

- Renovate executor Jobs read the token from `renovate-runtime-token`.
- The webhook bearer `token` is separate; it only protects the public webhook endpoint.
- The in-cluster token minter uses `ghcr.io/mshekow/github-app-installation-token` pinned by digest (see the CronJob/Job manifests).

## Enable Vulnerability Alerts feature (GitHub)

Renovate's vulnerability alerts integration reads GitHub Dependabot/Vulnerability Alerts.
If the GitHub credential cannot read those alerts, Renovate will log:

`Cannot access vulnerability alerts. Please ensure permissions have been granted.`

### 1) GitHub repository settings

For each repository you want vulnerability-fix PRs for, ensure GitHub has these enabled:

- **Dependency graph**
- **Dependabot alerts**

GitHub UI: Repository → **Settings** → **Code security and analysis**.

### 2) GitHub credential permissions

Whatever you use for `RENOVATE_TOKEN` (PAT or GitHub App token) must be able to read Dependabot alerts.

- **Classic PAT** (recommended for simplicity): include `repo` and `security_events` scopes.
- **Fine-grained PAT**: grant repo/org permissions including **Dependabot alerts: Read**, plus permissions for normal Renovate work (e.g. Contents, Pull requests, Issues).
- **GitHub App**: ensure the app has **Dependabot alerts: Read** (and normal PR/contents permissions).

After updating the GitHub App permissions and `renovate-secrets`, wait for the CronJob to refresh `renovate-runtime-token`.
