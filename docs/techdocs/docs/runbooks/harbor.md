# Runbook: Harbor (container registry)

Operational guide for the Harbor OCI registry. Design rationale lives in the
[RFC](../architecture/rfc-harbor-registry.md) and ADRs
[0001–0006](../architecture/index.md). Manifests: `kubernetes/apps/harbor/`.

## Architecture at a glance

- **Chart** `harbor` 1.19.1 (Harbor 2.15.x), HelmRelease in ns `harbor`.
- **Database** external CNPG `harbor-db` (db `registry`, owner `harbor`); CNPG mints the
  `harbor-db-app` Secret. Backups → Garage `s3://cnpg-backups-bucket/homelab-cluster/harbor-db/`.
- **Redis** chart-internal `redis-photon`.
- **Blobs** Garage S3 bucket `harbor` (`10.0.0.110:3900`, path-style, `disableredirect`).
- **Ingress** LAN-only `HTTPRoute` on `envoy-internal` → `https://harbor.${SECRET_DOMAIN}` (TLS at the gateway).
- **Secrets**: `harbor-core` is **generated in-cluster** (ESO `password-generator-16/-32`, never manual);
  `harbor-s3` and (phase 2) `harbor-oidc-values` come from OpenBao. See [External Secrets](../external-secrets-plan.md).

## First-time bring-up

1. **Garage** (on the Garage host) — create the bucket + a dedicated, bucket-scoped key:

   ```
   garage bucket create harbor
   garage key create harbor-registry
   garage bucket allow --read --write harbor --key harbor-registry
   garage key info --show-secret harbor-registry
   ```

2. **Store the S3 key in OpenBao** — one command from the repo (prompts via `gum`, OIDC login if needed):

   ```
   just harbor-s3-cred
   ```

   This writes `secret/harbor/s3` with `REGISTRY_STORAGE_S3_ACCESSKEY` / `REGISTRY_STORAGE_S3_SECRETKEY`.
   ESO syncs the `harbor-s3` Secret within ~1m. (`harbor-core` needs nothing — it self-generates.)

3. **Reconcile & watch**:

   ```
   flux -n flux-system reconcile kustomization cluster-apps --with-source
   kubectl -n harbor get externalsecret          # harbor-core, harbor-s3, cnpg-backup-s3 → SecretSynced
   kubectl -n harbor get cluster harbor-db -w     # Cluster healthy; harbor-db-app minted
   flux -n harbor get helmrelease harbor
   kubectl -n harbor get pods -w                  # core, registry, portal, jobservice, trivy, redis, exporter
   ```

4. **Verify** — see *Verification* below.

### Retrieve the local admin password

The `admin` password is generated (day-to-day login is Authentik OIDC once Phase 2 is on):

```
kubectl -n harbor get secret harbor-core -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d; echo
```

## Phase 2 — Authentik OIDC SSO

1. The blueprint `kubernetes/apps/authentik/app/blueprints/36-oidc-harbor.yaml` provisions the
   `harbor` OIDC provider/application (redirect `https://harbor.${SECRET_DOMAIN}/c/oidc/callback`).
2. Read the issued client id/secret from Authentik, then store the values fragment in OpenBao:

   ```
   just bao-login
   bao kv put secret/harbor/oidc values.yaml=@harbor-oidc.values.yaml
   ```

   where `harbor-oidc.values.yaml` carries `core.configureUserSettings` (literal domain, not `${SECRET_DOMAIN}`) —
   template is in `kubernetes/apps/harbor/harbor/app/harbor-oidc-values.externalsecret.yaml`.
3. ESO syncs `harbor-oidc-values`; the HelmRelease merges it via `valuesFrom` and `harbor-core` restarts apply it.
   `configureUserSettings` is re-applied on every core restart — it is the source of truth (UI auth edits revert).

## Verification

- **Registry round-trip** (LAN): `docker login harbor.${SECRET_DOMAIN}` → push/pull a test image;
  `helm registry login` + `helm push` an OCI chart. Confirm objects land: `garage bucket info harbor`.
- **Trivy**: scan a pushed image (UI → project → artifact → Scan), expect a CVE report.
- **Metrics**: `harbor_core_http_request_total` in Prometheus; the **Harbor** Grafana dashboard
  (`/d/harbor/harbor`, folder *Apps*) populates. Some Harbor-specific panels depend on exporter metric
  names (`harbor_project_total`, `harbor_quota_usage_byte`) — verify/adjust after the first scrape.
- **Backups**: trigger an on-demand `Backup` for `harbor-db`; confirm an object under
  `s3://cnpg-backups-bucket/homelab-cluster/harbor-db/`. Restore drills: see below.

## Common problems

| Symptom | Cause | Fix |
|---------|-------|-----|
| HelmRelease stuck `not ready`; `harbor-core`/`harbor-s3` not `SecretSynced` | OpenBao path missing or sealed | `kubectl -n harbor get externalsecret`; populate `secret/harbor/s3` (`just harbor-s3-cred`); check `ClusterSecretStore/openbao` Ready |
| PVC `Pending` | no default StorageClass | every PVC must set `storageClass` (`longhorn-general`) — already pinned in the HelmRelease |
| `registry` pod errors talking to S3 / redirect loops | Garage path-style not honored | `disableredirect: true` + `secure: false` + HTTP `regionendpoint` are mandatory (set already); check Garage at `10.0.0.110:3900` |
| Registry 5xx / blob I/O failing | Garage down | Garage is a hard dependency (ADR-0002 / [CNPG ↔ Garage](../cnpg-backups.md)); restore Garage |
| OIDC login fails | redirect URI / RS256 | redirect must equal `https://harbor.${SECRET_DOMAIN}/c/oidc/callback`; see [Authentik OIDC login](authentik-oidc-login.md) |

## Backup & disaster recovery

- Daily CNPG backup (`harbor-db-daily`, 02:45) to Garage; WAL archiving continuous.
- An automated restore drill is wired via the `cnpg-restore-test` component
  (`kubernetes/apps/harbor/harbor/app/database/backup/restore-test/cronjob-patch.yaml`), **suspended by
  default** (cluster default to limit storage pressure). Flip `suspend: false` to enable.
- Full restore: follow the [CNPG Restore Playbook](../cnpg-restore-playbook.md). The registry **blobs** live
  in Garage S3 (the source of truth) — restoring `harbor-db` recovers metadata; blobs are untouched by the DB restore.
