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
- **Optional keys for Docker Hub rate-limit avoidance:**
  - `RENOVATE_DOCKERHUB_USERNAME`
  - `RENOVATE_DOCKERHUB_TOKEN`
- **Optional key for GitHub Enterprise:**
  - `RENOVATE_GITHUB_API` (for example `https://ghe.example.com/api/v3`; defaults to `https://api.github.com`)

Template: `secret.template.yaml`

### 2) Renovate runtime token (NOT GitOps-managed)

This Secret is created/updated automatically in-cluster (do not commit it to git).

- **Secret name:** `renovate-runtime-token`
- **Namespace:** `renovate`
- **Key:** `token` (the GitHub App installation token; expires hourly)
- **Additional generated keys:**
  - `RENOVATE_TOKEN`
  - `RENOVATE_HOST_RULES` (always includes GHCR auth; includes Docker Hub auth when configured AND accepted by Docker Hub — a credential the probe sees rejected (401) is left out so Renovate falls back to the anonymous path, while the Job still fails so `RenovateTokenMinterFailing` fires)

Created/rotated by: CronJob `renovate-github-app-token`

### Bootstrap (run once, manually)

The GitHub App token is rotated by the CronJob every 15 minutes.
If you want the runtime Secret created immediately (e.g. right after first install), run a one-off Job from the CronJob:

- `kubectl -n renovate create job --from=cronjob/renovate-github-app-token renovate-github-app-token-bootstrap-$(date +%s)`

### 3) Webhook auth

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
- The webhook bearer `token` is separate; it only protects the webhook receiver.
- The in-cluster token minter uses `ghcr.io/mshekow/github-app-installation-token` pinned by digest (see the CronJob manifest).
- The token minter also builds `RENOVATE_HOST_RULES` for registry auth. Without Docker Hub credentials, Renovate talks to Docker Hub anonymously and can hit 429 rate limits.

## Webhook exposure

The receiver is LAN-only: its route hangs off `envoy-internal`, so `renovate-webhook.${SECRET_DOMAIN}`
has no public DNS record and nothing on the internet reaches it. Its callers are Forgejo and the
Forgejo Actions runners, which post to the in-cluster Service (below). On 2026-09-27 no GitHub repo carried a hook to it and the
operator had logged no accepted GitHub event in 30 days, so the `webgrip-gitops` job relies on its cron.

The operator enforces authentication itself, per RenovateJob: a request is accepted only when a job
that owns the project has `spec.webhook.authentication.enabled: true` and the request carries a token
from the job's Secret (`Authorization: Bearer <token>`, `X-Gitlab-Token`, or an HMAC signature of the
body). A job with `webhook.enabled` and no `authentication` block accepts unauthenticated requests for
every project it owns, so never add one. The blackbox alert `RenovateWebhookGateOpen` fires when an
unauthenticated schedule request for `webgrip/homelab-cluster` stops getting `401`.

Re-exposing it for a GitHub webhook takes a second hostname on its own `envoy-external` route, not
an extra `parentRef` on this one: k8s-gateway would otherwise answer the one name with both gateway
IPs. The GitHub payload URL is
`https://<that host>/webhook/v1/github?namespace=renovate&job=webgrip-gitops`, content type
`application/json`, secret = the token, events **Issues** and **Pull requests**.

## Make Dependency Dashboard actions immediate (Forgejo webhook)

Same idea for the Forgejo path. The operator's **native** auto-registration
(`webhook.forgejo.sync` on `webgrip-forgejo.yaml`) is **disabled** — it calls a repo-by-topic search
that 404s on Forgejo 15 (operator 4.10.1 bug; no config workaround). The webhook *receiver* is fine;
only the auto-registration is broken. Forgejo has no GitHub-App-style org webhook, so register a
**per-repo** hook with the `webhook` action of [`scripts/forgejo-sync.sh`](../../../../../scripts/forgejo-sync.sh)
(idempotent, dry-run by default):

```sh
scripts/forgejo-sync.sh --repo infrastructure --only webhook          # dry-run (prints intent, never the token)
scripts/forgejo-sync.sh --repo infrastructure --only webhook --apply  # apply one repo
scripts/forgejo-sync.sh --all --only webhook --apply                  # all de-mirrored repos
```

It registers a Forgejo repo webhook with:

- **Payload URL:** `http://renovate-operator.renovate.svc.cluster.local:8082/webhook/v1/forgejo?namespace=renovate&job=webgrip-forgejo`
  — Forgejo is **in-cluster**, so it hits the operator Service directly. No gateway hop.
- **Content type:** `json`, **method:** `POST`
- **Auth:** `Authorization: Bearer <token>` — set via the hook's **top-level** `authorization_header`
  field (NOT a `config` key — Forgejo silently drops unknown config keys, so nesting it sends no auth
  header and the receiver 401s). Token = the FIRST entry in Secret `renovate-webhook-auth` key `token`
  (OpenBao `renovate/webhook-auth`); script reads `$RENOVATE_WEBHOOK_AUTH_TOKEN` else the cluster
  Secret via `kubectl`. Never printed (Forgejo also masks it on read).
- **Events:** **Issues** (Dependency Dashboard checkboxes) and **Pull requests** (PR checkboxes).

**Token rotation:** ESO re-materialises the *same* `renovate-webhook-auth` value hourly, so registered
hooks do **not** go stale on refresh — only a real rotation of the OpenBao `renovate/webhook-auth` value
does. After such a rotation, re-run `scripts/forgejo-sync.sh --all --only webhook --apply` (its PATCH
re-sets the embedded bearer). The hook needs **repo admin** to create/update (same as `protect`).

## Run Renovate when shared tooling releases

The `webgrip-forgejo` job runs on `33 * * * *`, and a full pass over its ~20 projects takes well over
an hour at `parallelism: 1`. A release of shared tooling (`webgrip/workflows`,
`webgrip/semantic-release-config`, `webgrip/renovate-config`, `webgrip/agent-standards`) would wait
for that queue. Instead, each of those repositories calls the `renovate-trigger` composite action of
`webgrip/workflows` after a release, which schedules the consumers through the operator's schedule
webhook:

```text
POST http://renovate-operator.renovate.svc.cluster.local:8082/webhook/v1/schedule?namespace=renovate&job=webgrip-forgejo&project=<owner/repo>
Authorization: Bearer <token>
```

What the operator (5.2.0, `src/webhook/server.go` and `resolver.go`) does with it:

- `project` is required; without it the answer is `400`. There is no "schedule every project" form,
  so the action sends one request per project.
- The job is found by `namespace`, `job` and the project being in its `status.projects`; a project
  the job does not own answers `404` before authentication.
- With `webhook.authentication.enabled`, the bearer token must be one of the comma-separated entries
  of `renovate-webhook-auth`/`token`; otherwise `401`.
- A match sets the project to `scheduled` at priority 1 and answers `200`; the queue then runs it
  like any other project.

Targeting: almost every repository consumes `webgrip/workflows` and `webgrip/agent-standards`, so the
action schedules every non-archived, non-mirror repository of the organisation with the `renovate`
topic (the same selector as `discoverTopics`), except the releasing repository. Each project run is
one executor pod writing about 1 GB to disk; a release therefore costs one extra pass, mostly
reordering work the hourly cron would do anyway. A caller can pass `projects:` to narrow it.

The token reaches the workflows as the repository secret `RENOVATE_WEBHOOK_TOKEN`, a bridge-level
secret (ADR-0055 L3):

1. `ExternalSecret/forgejo-renovate-webhook` in namespace `forgejo`
   (`kubernetes/apps/forgejo/forgejo-actions-secrets/app/renovate-webhook.externalsecret.yaml`)
   reads OpenBao `renovate/webhook-auth` property `token` and keeps its first comma-separated entry.
   `eso-grants.txt` grants `forgejo read renovate/webhook-auth`.
2. The `forgejo-actions-secrets` CronJob publishes it to the repositories `SECRET_REPOS` names for
   `RENOVATE_WEBHOOK_TOKEN`: agent-standards, renovate-config, semantic-release-config and workflows.
   There is no verify call: the operator has no endpoint that checks a token without scheduling a
   run, so a stale token shows up as a `::warning::` in the next release run instead.
3. NetworkPolicy `forgejo-runner-allow-renovate-webhook` (`kubernetes/apps/forgejo/networkpolicy.yaml`)
   lets `forgejo-runner` and `forgejo-dind` pods reach the operator pod on 8082. Without it
   `forgejo-allow-egress` drops the call, because it excludes the pod and service CIDRs. Jobs with a
   `container:` run on the shared `forgejo-dind` pods, so both identities are needed.

Rotating `renovate/webhook-auth` needs nothing extra: the ExternalSecret refreshes hourly and the
CronJob republishes on its next tick.

## Renovate manifests

- RenovateJob: `webgrip-gitops.yaml`
- Renovate config: `configmap-gitops.yaml`

The RenovateJob runs one repository per executor Job. Autodiscovery is disabled in the config so a job created for `org/repo` doesn't scan the whole org.

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

- **Classic PAT** (recommended for simplicity): include `repo`, `workflow`, and `security_events` scopes.
- **Fine-grained PAT**: grant repo/org permissions including **Dependabot alerts: Read**, plus permissions for normal Renovate work (e.g. Contents, Pull requests, Issues, Workflows).
- **GitHub App**: ensure the app has **Dependabot alerts: Read**, **Contents: Read and write**, **Pull requests: Read and write**, **Issues: Read and write**, and **Workflows: Read and write**. Workflow permission is required for Renovate to update `.github/workflows/*`.

After updating the GitHub App permissions and `renovate-secrets`, wait for the CronJob to refresh `renovate-runtime-token`.

## Reduce Docker Hub rate limiting

Renovate scans a lot of Docker-based dependencies in this estate, so anonymous Docker Hub traffic is the most common source of aborted runs.

### Recommended Docker Hub setup

1. Create a Docker Hub account if you do not already have one.
2. Create a Docker Hub personal access token for Renovate.
3. Add these keys to `kubernetes/apps/renovate/renovate-operator/jobs/secret.sops.yaml`:
   - `RENOVATE_DOCKERHUB_USERNAME`
   - `RENOVATE_DOCKERHUB_TOKEN`
4. Wait for CronJob `renovate-github-app-token` to refresh `renovate-runtime-token`, or trigger it manually once.

After that refresh, Renovate executor Jobs will authenticate Docker Hub requests via `RENOVATE_HOST_RULES` instead of using the anonymous Docker Hub rate limit bucket.
