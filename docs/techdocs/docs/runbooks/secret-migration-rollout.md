# SOPS → OpenBao/ESO migration — phased rollout

Execution plan for migrating the remaining ~39 SOPS secrets into OpenBao via ESO.
Complements the architecture + full inventory in the [external-secrets plan](../external-secrets-plan.md).
Bootstrap, the no-live-root design, and the proven recipe live in the
[external-secrets runbook](external-secrets.md) and project memory.

## The universal recipe (proven on `grafana-github-api`)

Every existing secret is migrated **value-preserving** — never regenerated — so the recipe
is uniform regardless of class:

1. **Phase A (seed, app-safe):** add a `PushSecret` (`external-secrets.io/v1alpha1`, store
   `openbao-push`) copying the existing Secret → OpenBao `secret/<app>/<name>`. Wait for
   `status: True/Synced`. *No app impact* — nothing reads OpenBao yet.
2. **Phase B (swap):** in one commit, add an `ExternalSecret` (`v1`, store `openbao`) that
   recreates the **same Secret name + keys**, and delete the `*.sops.yaml`. Verify the Secret
   is `ownerReferences → ExternalSecret`, the value is intact, and the app is healthy.

Because Phase A never touches apps, **seed broadly, then swap deliberately per class.**
Flux+ESO latency is ~5–10 min per phase → always batch.

**Gate (every phase):** `./scripts/run-flux-local-test.sh` build green; after apply,
`kubectl get secret <n> -n <ns>` shows ESO ownership + the consuming pod healthy. Delete a
`*.sops.yaml` only after its ExternalSecret Secret is confirmed present.
**Rollback:** `git revert` the phase's commits (the SOPS file returns; ESO Secret lingers
harmlessly with `deletionPolicy: Retain`). At-rest values never change owner → no data loss.

## Prerequisites (P0 — do before/with Phase 1)

- **Fix OpenBao's own OIDC self-login** — `config.sh`'s Authentik fetch returns empty (UI
  login via Authentik). Independent of app secrets; debug the cross-ns token read /
  `authentik-server` API / `SECRET_DOMAIN` env. (OpenBao UI is still reachable via the
  root-revoked break-glass `generate-root` if needed.)
- **Resolve unknowns:** `twitch-exporter` app `kustomization.yaml` does **not** list its
  `secret*.sops.yaml` (confirm how those Secrets are applied before touching). Confirm the
  `keys=[]` secrets' block-scalar formats at execution. Confirm the two on-disk
  `.decrypted~*.sops.yaml` (flux-instance, guac) are gitignored, **not** committed plaintext.

## Status

- ✅ **Done:** `grafana-github-api` (full migration, pilot).
- 🌱 **Seeded (Phase A only):** `cloudflare-dns-secret`, `cloudflare-tunnel-secret` (swap held for Phase 7).

---

## Phase 1 — Low-risk external tokens

Wrong value ⇒ degraded *non-critical* function (metrics/alerting/mirroring/runners/ACME),
easy to verify, no data at risk. Biggest batch; proves scale.

| Secret | ns | keys | verify |
| --- | --- | --- | --- |
| `gha-runner-scale-set-secrets` | arc-systems | github_app_id, github_app_installation_id, github_app_private_key, github_config_url | runner registers |
| `gha-runner-scale-set-secrets` (heavy) | arc-systems | (same) | runner registers |
| `cert-manager-secret` | cert-manager | api-token | a cert renews / no ACME errors |
| `grafana-annotations-token` | flux-system | token | flux→grafana annotations |
| `github-webhook-token-secret` | flux-system | token | flux receiver |
| `forgejo-runner-secret` | forgejo | uuid, token | runner online |
| `forgejo-runner-scaler-token` | forgejo | token | scaler |
| `forgejo-s3-secret` | forgejo | MINIO_ACCESS_KEY_ID, MINIO_SECRET_ACCESS_KEY | LFS upload/download |
| `twitch-exporter-secret` | observability | TWITCH_CLIENT_ID/SECRET, TWITCH_SELF_CHANNEL | exporter metrics (resolve kustomization first) |
| `twitch-exporter-eventsub-secret` | observability | (same) | exporter |
| `alertmanager-discord` | observability | (keys TBD) | a test alert posts |
| `renovate-webhook-auth` | renovate | token | webhook |
| `dependency-track-api-key` | security | api-key | DT API calls |

## Phase 2 — App OIDC client secrets

Preserve the Authentik-minted value (do **not** rotate). Verify real login E2E per app
**before** deleting SOPS. (Optional future enhancement: OIDC-elimination via generator +
PushSecret to Authentik — out of scope here.)

| Secret | ns | keys |
| --- | --- | --- |
| `grafana-oauth` | observability | GF_AUTH_GENERIC_OAUTH_CLIENT_ID/SECRET |
| `forgejo-oidc-secret` | forgejo | key, secret |
| `n8n-oidc-secrets` | n8n | N8N_…_OIDC_CLIENT_ID/SECRET |
| `backstage-oidc-secrets` | backstage | AUTH_OIDC_CLIENT_ID/SECRET |

## Phase 3 — Shared S3 components (special: multi-namespace)

These live in kustomize **components** mixed into many namespaces, so the Secret exists in
each. Approach: seed OpenBao once (one-off PushSecret from any one namespace's copy), then
put the **ExternalSecret in the component** so ESO writes one copy per target namespace;
delete the component's `*.sops.yaml`. Same Secret name + keys everywhere → CNPG ObjectStores
and consumers unchanged.

| Component | Secret | keys | applied to |
| --- | --- | --- | --- |
| `components/cnpg-backup` | `cnpg-backup-s3` | S3_* incl S3_BUCKET | every CNPG app ns |
| `components/observability-s3` | `observability-s3` | S3_ACCESS_KEY_ID/SECRET, S3_REGION, S3_ENDPOINT | observability |
| `components/security-s3` | `security-s3` | S3_* + S3_GUAC_BUCKET | security |

## Phase 4 — Human-login + app session/misc

Preserve values (login creds / session entropy). Verify the relevant login or function.

`forgejo-admin-secret` (forgejo: username/password/email), `grafana-admin` (observability),
`cluster-user-auth` (flux-system: username/password — Weave GitOps UI),
`freshrss-secrets`, `sparkyfitness-secrets`, `zomboid-secrets`, `renovate-secrets`,
`guac-secrets` (security: username/password/values.yaml). Confirm exact keys at execution.

## Phase 5 — At-rest encryption keys (CRITICAL — never regenerate)

A wrong/rotated value makes already-encrypted data unreadable. Value-preserving migration is
mandatory; verify the app reads existing data **before** deleting SOPS. Highest care.

- `authentik-secret` — AUTHENTIK_SECRET_KEY (+ bootstrap pw/token/email). **Authentik is the
  cluster OIDC provider**; its `AUTHENTIK_BOOTSTRAP_TOKEN` is also read cross-ns by OpenBao's
  config.sh — keep that key intact. Migrate carefully, verify SSO still works everywhere.
- `gitea-mirror-secret` — ENCRYPTION_SECRET (at-rest) + BETTER_AUTH_SECRET.
- `n8n-secrets` — N8N_ENCRYPTION_KEY (confirm keys).
- `invoiceninja-secrets` — APP_KEY (confirm keys).
- `backstage-secrets` — BACKEND_SECRET + many provider tokens (mixed; one ExternalSecret, all keys).
- `dependency-track-secret` — secret.key (at-rest) + username/password.

## Phase 6 — CNPG database secrets (DR-sensitive)

Seed the **existing** value (DB role passwords are rotatable but a needless rotation is
disruptive). Before deleting SOPS: confirm whether the CNPG `Cluster` references the secret
(superuser/app/bootstrap), verify DB connectivity, and run a restore drill
(`cnpg-restore-test`, see [cnpg-database] skill) for the at-rest-bearing ones.

`backstage-db-secret`, `freshrss-db-secret` (username/password), `n8n-db-secret`,
`sparkyfitness-db-secret`, `grafana-db-secret`. (CNPG-auto `*-db-app` secrets are **not**
migrated — already automated.)

## Phase 7 — Public-facing (deliberate, last)

Already seeded (Phase A done). Swap one at a time, verify external reachability between each.

- `cloudflare-tunnel-secret` (TUNNEL_TOKEN) — public ingress; verify a public host loads.
- `cloudflare-dns-secret` (api-token) — external-dns; verify a DNS record reconciles.

---

## Stays SOPS forever (the floor)

`sops-age`, `github-deploy-key`, `cluster-secrets` (`${SECRET_DOMAIN}` build-time
substitution), `talsecret`, and `openbao-keys` (runtime-generated unseal key, a k8s Secret
not git). Everything else above moves to OpenBao.
