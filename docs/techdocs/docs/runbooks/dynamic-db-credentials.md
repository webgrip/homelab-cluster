# Runbook: Dynamic Postgres credentials (OpenBao database engine)

**Status:** pilot (freshrss) · **Scope:** OpenBao `database` secrets engine minting short-lived,
auto-revoked Postgres credentials · **Design:** [ADR-0016](../adr/adr-0016-openbao-dynamic-postgres-credentials.md)
· [RFC](../rfc/rfc-dynamic-database-credentials.md) · **Rotation model:** [ADR-0015](../adr/adr-0015-secret-rotation-model.md)

> **What this gives you.** Instead of a static password that lives forever, OpenBao mints a fresh
> Postgres role (`v-freshrss-<random>`) valid for ~1h, hands it to the app via ESO, and `DROP`s it
> when the lease expires. A leaked credential dies within the hour and every credential is
> attributable in the audit log. On freshrss the rotation is **zero-downtime**: only a local
> **PgBouncer** sidecar's backend credential rotates; the app never restarts.

## Architecture

```text
OpenBao database engine ──mint(1h lease)──▶ ESO (openbao-db store) ──▶ Secret freshrss-pgbouncer-backend
  │  vault_admin conn (CREATEROLE)                                          │ (databases.ini, rotates every 15m)
  ▼                                                                         ▼
freshrss-db-rw:5432  ◀──backend conn (rotating v-role)──  PgBouncer sidecar ◀─SIGHUP reload─ pgbouncer-reload
                                                              ▲
                             freshrss app ──localhost, STABLE freshrss cred──┘  (never rotates → never restarts)
```

- **`vault_admin`** — a CNPG managed role (`CREATEROLE`, not superuser) OpenBao logs in as to
  create/drop ephemeral roles. Password is generate-once (`freshrss-vault-admin`), the same value
  in `security` (mounted into the config job) and `freshrss` (CNPG). **OpenBao never rotates it**
  (no `rotate-root`) — CNPG owns it.
- **`database/roles/freshrss`** — `default_ttl 1h`, `max_ttl 2h`; creation `GRANT freshrss TO
  "{{name}}"`; **defensive** revocation (`pg_terminate_backend` → `REASSIGN OWNED` → `DROP OWNED`
  → `DROP ROLE`).
- **`ClusterSecretStore/openbao-db`** — `path: database`, **`version: v1`** (so ESO reads
  `database/creds/freshrss` directly, not the KV `/data/` path).
- **PgBouncer sidecar** — freshrss → `127.0.0.1:5432` (stable cred); PgBouncer → `freshrss-db-rw`
  (rotating cred). `pool_mode=transaction`, `ignore_startup_parameters=extra_float_digits` (PHP PDO).

## Rollout state

Rollout state is tracked in [ADR-0016's Status log](../adr/adr-0016-openbao-dynamic-postgres-credentials.md), not here.
As of 2026-07-02 the freshrss pilot is in-flight and churning: cutover `678b1da` → reverted `03f222e`
(PG16 ADMIN OPTION grant failure: `permission denied to grant role freshrss`) → re-applied → reverted again
`391eeb1` (pooler needs hands-on runtime iteration). **Verify live state before using this runbook:**
`kubectl -n freshrss get pod` container count — `1/1` = static-cred path, `3/3` (app + pgbouncer + pgbouncer-reload) = pooler path.

## Verify Phase 0 + additive Phase 1 BEFORE the cutover

Run these (some need the OpenBao pod / `bao` — a human step, OIDC-authed). Note: `kubectl cnpg psql`
requires the CNPG kubectl plugin (not in mise) — without it, substitute
`kubectl -n freshrss exec freshrss-db-1 -c postgres -- psql -U postgres -c "..."`:

```bash
# 1. Engine mounted + role present (via the openbao-config job log or bao read):
kubectl -n security logs job/$(kubectl -n security get job -o name | grep openbao-config | tail -1 | cut -d/ -f2) | grep -A2 'database engine'
#   want: "database engine mounted" (or already present), "freshrss-db connection configured", "freshrss role configured"

# 2. vault_admin exists in Postgres with CREATEROLE and ADMIN OPTION on freshrss (CRITICAL for PG16+):
kubectl cnpg psql freshrss-db -n freshrss -- -c "\du vault_admin"
kubectl cnpg psql freshrss-db -n freshrss -- -c "SELECT admin_option FROM pg_auth_members m JOIN pg_roles r ON m.roleid=r.oid JOIN pg_roles v ON m.member=v.oid WHERE r.rolname='freshrss' AND v.rolname='vault_admin';"
#   MUST return admin_option = t. If f, run once (break-glass, as a superuser):
#     GRANT freshrss TO vault_admin WITH ADMIN OPTION;

# 3. The store is Ready and the backend ExternalSecret SYNCED (proves the whole mint pipeline):
kubectl get clustersecretstore openbao-db
kubectl -n freshrss get externalsecret freshrss-pgbouncer-backend
#   want READY=True / SecretSynced. If SecretSyncError → engine/role not live yet, or admin_option missing.

# 4. The rendered backend secret has a real v-role (mint works end to end):
kubectl -n freshrss get secret freshrss-pgbouncer-backend -o jsonpath='{.data.databases\.ini}' | base64 -d
#   want a line: freshrss = host=freshrss-db-rw... user=v-freshrss-... password=...

# 5. The ephemeral role exists in Postgres with an expiry:
kubectl cnpg psql freshrss-db -n freshrss -- -c "SELECT rolname, rolvaliduntil FROM pg_roles WHERE rolname LIKE 'v-%';"
```

**Only proceed to the cutover once #2 shows `admin_option = t` and #3/#4 are green.** Otherwise the
cutover pod will hang (PgBouncer `%include` needs the backend secret) and freshrss will be down.

## Prove zero downtime (after the cutover)

```bash
# freshrss pod has 3 running containers (app, pgbouncer, pgbouncer-reload):
kubectl -n freshrss get pod -l app.kubernetes.io/name=freshrss -o jsonpath='{.items[0].spec.containers[*].name}'; echo

# Continuous client probe against a DB-backed page — keep this running:
while true; do curl -s -o /dev/null -w "%{http_code}\n" https://freshrss.${SECRET_DOMAIN}/i/ ; sleep 1; done

# In another shell, force a rotation (GitOps-safe — an ESO annotation, not an app mutation):
kubectl -n freshrss annotate externalsecret freshrss-pgbouncer-backend force-sync="$(date +%s)" --overwrite

# Within ~90s the pgbouncer-reload sidecar logs the SIGHUP and the backend cred swaps to a new
# v-role. The probe shows ZERO non-200s across the window — that is the zero-downtime proof:
kubectl -n freshrss logs -l app.kubernetes.io/name=freshrss -c pgbouncer-reload --tail=5

# After ~1h the old v-role's lease expires and OpenBao drops it (only ~1-2 v- roles ever exist):
kubectl cnpg psql freshrss-db -n freshrss -- -c "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'v-%';"
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `freshrss-pgbouncer-backend` `SecretSyncError` | engine/role not live, or `admin_option != t` so `GRANT freshrss` fails at mint | verify §2/§1; add the one-time `GRANT ... WITH ADMIN OPTION` |
| config.sh log: `connection write FAILED` | netpol missing, `vault_admin` not in PG yet, or TLS | confirm the security→freshrss-db:5432 netpol, `\du vault_admin`, try `sslmode=prefer` |
| pgbouncer container CrashLoop: `unsupported startup parameter` | PHP PDO `extra_float_digits` | ensure `ignore_startup_parameters = extra_float_digits` in pgbouncer.ini |
| Rotation restarts the whole pod | Reloader watching the rotating secret | the backend Secret carries `reloader.stakater.com/ignore`; ensure controller has no `reloader.../auto: "true"` |
| pgbouncer can't write socket/pidfile | `/var/run/pgbouncer` not writable | it's an emptyDir; the sidecar runs as (userns) root so it can write it |
| Old `v-` roles pile up in `pg_roles` | leases not expiring / revocation failing | check `bao read sys/leases/count`; the defensive revocation must run (terminate+reassign+drop) |

## Rollback (one commit, fully reversible)

Revert the cutover commit: remove the sidecars + repoint the freshrss `app` env back to
`freshrss-db-rw.freshrss.svc.cluster.local` with the static `freshrss-db-secret` credential. The
app restarts onto the CNPG `freshrss` owner cred. No data touched. The engine/role/store can stay
(harmless, unused) or be reverted separately.

## Rotate `vault_admin` (rare)

`vault_admin`'s password is generate-once + CNPG-managed. To rotate: delete the
`freshrss-vault-admin` source Secret in `security` (ESO regenerates), let the PushSecret re-seed KV
and the freshrss-ns ES re-read; CNPG reconciles the new password on the role; `config.sh` rewrites
the connection from the mounted file on its next tick. Do NOT use OpenBao `rotate-root`.

## Extending to another app

Reuse this as a template: add a `vault_admin` managed role + shared-password ES (both namespaces),
a `database/config/<app>` + `database/roles/<app>` block in `config.sh`, a netpol allowing
`security → <app>-db:5432`. Then — **surge-capable app** (multi-replica / no RWO): just an
ExternalSecret on `creds/<app>` + a (longer-TTL) rolling restart, **no pooler**. **RWO single-attach
app:** add the PgBouncer sidecar as on freshrss. See ADR-0016's workload-shape table.
