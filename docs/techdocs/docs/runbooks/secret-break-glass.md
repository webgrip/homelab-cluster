# Runbook: Secret break-glass (suspected compromise)

**When to use:** you believe a pod, node, credential, or the cluster has been compromised and you
want to **rotate everything the blast could have touched** — fast, without corrupting data.

> **The one rule that prevents a self-inflicted outage:** never blindly "delete all generated
> secrets." Some generated secrets are **at-rest encryption keys** — regenerating them **destroys the
> data they encrypt** (Harbor `secretKey`, app DB owner passwords). The safe sets and the hard
> exclusions are listed below. Rotate by class.

Rotation splits along *where the secret lives*: **OpenBao leases** (dynamically-minted creds) vs.
**Kubernetes Secrets** (generated in-cluster) vs. **external provider tokens**. Do all three.

---

## Part 1 — OpenBao-minted dynamic credentials (Class A) — revoke by lease

These are short-lived already, but on compromise revoke them *now* rather than wait for TTL. Needs a
`bao` login (OIDC). See the [dynamic-db-credentials runbook](dynamic-db-credentials.md).

```bash
mise exec -- just bao-login

# Kill every credential a role/mount minted (the "compromise button"):
bao lease revoke -prefix database/creds/freshrss/     # all freshrss dynamic DB creds
bao lease revoke -prefix database/                    # everything the database engine minted

# Rotate the privileged connection password an attacker may have seen in memory:
#   NB: do NOT use rotate-root here — CNPG owns vault_admin's password. Instead rotate it CNPG-side
#   (regenerate freshrss-vault-admin, below) so CNPG and OpenBao stay in sync.

# Confirm nothing is outstanding:
bao list sys/leases/lookup/database/creds/freshrss
```

Within minutes ESO mints fresh, clean credentials and PgBouncer reloads onto them (zero downtime).

---

## Part 2 — Generated Kubernetes secrets (Class C) — delete to regenerate

Deleting an ESO-owned generated Secret makes ESO **recreate it with a fresh random value**
(`deletionPolicy: Retain` + generator). Reloader then restarts the consumer; two-sided creds also
need their provisioner re-run.

### ✅ SAFE to regenerate

| Secret | Namespace | After regenerating |
|---|---|---|
| `searxng-secrets` | `searxng` | self-contained (session key) — Reloader restarts searxng, done |
| `forgejo-ci-bot-password` | `forgejo` | re-run the CI provisioner: `kubectl -n forgejo delete job forgejo-ci-provisioner` (Flux recreates it → re-registers the bot password + re-mints the token) |
| `renovate-forgejo-bot-password` | `renovate` | re-run: `kubectl -n renovate delete job renovate-forgejo-provisioner` |
| `harbor-robot-webgrip` | `harbor` | the `harbor-proxy-config` CronJob re-registers the robot secret on its next tick (hourly `:17`), or trigger it now |
| `harbor-oidc-client` | `authentik` | two-sided (Authentik blueprint + Harbor); it re-syncs via the PushSecret → `harbor-oidc-values` ES on the next reconcile — verify Harbor SSO login after |

```bash
# The sweep (safe set only):
kubectl -n searxng  delete secret searxng-secrets
kubectl -n forgejo  delete secret forgejo-ci-bot-password
kubectl -n renovate delete secret renovate-forgejo-bot-password
kubectl -n harbor   delete secret harbor-robot-webgrip
kubectl -n authentik delete secret harbor-oidc-client
# then re-run the provisioners (see table)
kubectl -n forgejo  delete job forgejo-ci-provisioner
kubectl -n renovate delete job renovate-forgejo-provisioner
```

### ⛔ DO NOT delete — these corrupt data or break the cluster

| Secret | Why excluded | Rotate instead by |
|---|---|---|
| `harbor-admin` (harbor) | **contains `secretKey`, Harbor's at-rest encryption key** — regenerating orphans all stored LDAP/OIDC/robot creds | it is **not rotatable**; treat as fixed-and-guarded (§Part 4) |
| `devex-db-secret` (observability) | it's the **devex DB owner password** — regenerating breaks the database | rotate CNPG-side deliberately, not via the sweep |
| `freshrss-vault-admin` (security + freshrss) | the **OpenBao→Postgres mint credential** — mid-flight regeneration disrupts minting | rotate via the dynamic-db-credentials runbook |
| `devex-grafana-ro` (observability) | grafana RO DB password **set by a migration Job** — needs the Job to reset it in Postgres | re-run the devex migration Job |
| `freshrss-pooler-app-cred` (freshrss) | loopback app↔pooler password — needs a **coordinated** pgbouncer reload + app restart | rotate deliberately with a freshrss restart |

---

## Part 3 — External provider tokens (Class B) — rotate at the source

OpenBao can't mint these; you regenerate them **at the provider**, then write to KV and ESO
propagates (≤ `refreshInterval`). Highest-value first:

```bash
mise exec -- just bao-login
# Regenerate at the provider (GitHub / Cloudflare / Garage S3 / Authentik) THEN:
# NB: `put` REPLACES the whole secret. secret/github/ci-pat also carries `username`,
# and dropping it makes GHCR_USERNAME silently fall back to "webgrip" — use patch:
printf '%s' "$TOKEN" | bao kv patch secret/github/ci-pat token=-   # value via stdin
bao kv put secret/cloudflare/tunnel    TUNNEL_TOKEN=<new>
bao kv put secret/cloudflare/dns       api-token=<new>
bao kv put secret/s3/cnpg-backup       S3_ACCESS_KEY_ID=<new> S3_SECRET_ACCESS_KEY=<new>
# force fast propagation instead of waiting for refreshInterval:
kubectl -n <ns> annotate externalsecret <name> force-sync="$(date +%s)" --overwrite
```

!!! warning "Forgejo org Actions secrets are reconciled — never edit them in the UI"
    `GHCR_USERNAME` / `GHCR_TOKEN` / `GH_RELEASE_TOKEN`, `HARBOR_ROBOT_*`,
    `WEBGRIP_CI_TOKEN`, `DT_API_KEY` and `TECHDOCS_S3_*` are published onto the `webgrip`
    org by the hourly `forgejo-actions-secrets` CronJob (`23 * * * *`) from OpenBao via
    ESO. A value typed into the Forgejo UI works until the next tick and is then silently
    overwritten — on 2026-08-25 that cost most of a day, because CI kept passing for four
    runs and then reverted to the dead token.

    Rotate in OpenBao, then **wait for `SecretSynced` before re-running the job** — a Job
    created seconds after the annotation mounts the *old* Secret and republishes it:

    ```bash
    kubectl -n forgejo get externalsecret forgejo-github-pat   # wait for SecretSynced
    kubectl -n forgejo create job --from=cronjob/forgejo-actions-secrets ghcr-token-refresh
    ```

    Since 2026-08-25 that CronJob also validates the GitHub PAT and fails when it is
    rejected or within 14 days of expiry, which raises `ForgejoActionsSecretsReconcileStale`.

OIDC client secrets (grafana/backstage/forgejo/harbor `*/oauth`, `*/oidc`) are Authentik-issued —
rotate in Authentik, then `bao kv put`.

---

## Part 4 — At-rest encryption keys (Class D) — mostly *rebuild*, not rotate

See the [secret-rotation strategy §D](../general/secret-rotation-strategy.md). On compromise:

- **n8n** — rotate via native key rotation (`N8N_ENV_FEAT_ENCRYPTION_KEY_ROTATION`); back up first.
- **InvoiceNinja/Laravel `APP_KEY`** — add the old key to `APP_PREVIOUS_KEYS`, set a new `APP_KEY`,
  run the re-encrypt migration.
- **Dependency-Track** — Tink KEK rotation covers *new* secrets only.
- **Harbor `secretKey`, Authentik note** — Harbor's key can't be rotated; if truly compromised,
  **rebuild Harbor and re-enter stored credentials**. Authentik's `SECRET_KEY` is a *signing* key —
  rotating it (just logs users out) is cheap and safe; do it.
- **Disk-level** — if a node/disk is compromised, rotate the LUKS/StorageClass key (once wired).

---

## Verify

```bash
kubectl get externalsecret -A | grep -iv 'SecretSynced'   # all should be SecretSynced
kubectl get pods -A | grep -ivE 'Running|Completed'       # consumers restarted cleanly
# spot-check a rotated app actually works (Harbor SSO login, a Forgejo Actions run, etc.)
```

## Follow-up hardening

The safe-set sweep is a curated list today. A future enhancement labels those Secrets
`rotate.webgrip.io/on-compromise: "true"` (validated in isolation first, so an ESO template change
can't blank a live secret) to make Part 2 a single `kubectl delete secret -l …` — with the ⛔ set
structurally excluded because it's never labeled.
