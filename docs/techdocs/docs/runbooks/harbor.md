# Runbook: Harbor (container registry)

Operational guide for the Harbor OCI registry. Design rationale lives in the
[RFC](../rfc/rfc-harbor-registry.md) and ADRs
[0001–0006](../adr/index.md). Manifests: `kubernetes/apps/harbor/`.

## Architecture at a glance

- **Chart** `harbor` 1.19.1 (Harbor 2.15.x), HelmRelease in ns `harbor`.
- **Database** external CNPG `harbor-db` (db `registry`, owner `harbor`); CNPG mints the
  `harbor-db-app` Secret. Backups → Garage `s3://cnpg-backups-bucket/homelab-cluster/harbor-db/`.
- **Redis** chart-internal `redis-photon`.
- **Blobs** Garage S3 bucket `harbor` (`10.0.0.110:3900`, path-style, `disableredirect`).
- **Ingress** LAN-only `HTTPRoute` on `envoy-internal` → `https://harbor.${SECRET_DOMAIN}` (TLS at the gateway).
- **Secrets**: `harbor-admin` (admin password + at-rest `secretKey`) is **generated in-cluster** (ESO
  `password-generator-16/-32`, never manual); the **chart** owns its other internal secrets + the
  token-signing cert in its own `harbor-core` secret. `harbor-s3` and (phase 2) `harbor-oidc-values`
  come from OpenBao. See [External Secrets](../rfc/external-secrets-plan.md).

## Retrieve the local admin password

The `admin` password is generated (day-to-day login is Authentik OIDC once Phase 2 is on):

```
kubectl -n harbor get secret harbor-admin -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d; echo
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
- **Metrics**: `harbor_core_http_request_total` in VictoriaMetrics; the **Harbor** Grafana dashboard
  (`/d/harbor/harbor`, folder *Apps*) populates. The `prometheusrule` wires only
  `harbor_core_http_request_total` / `up{}`. Storage panels should use the canonical Harbor exporter
  metrics **`harbor_quotas_size_bytes`** (label `type` = `hard`/`used`) and `harbor_system_volumes_bytes` —
  verify/adjust after the first scrape (treat as unverified until then). Do **not** use
  `harbor_statistics_total_storage_consumption` / `harbor_project_quota_usage_byte` — those names are not
  emitted by this exporter.
- **Backups**: trigger an on-demand `Backup` for `harbor-db`; confirm an object under
  `s3://cnpg-backups-bucket/homelab-cluster/harbor-db/`. Restore drills: see below.

## Using Harbor day-to-day (the happy path)

Two distinct flows — pulling *third-party* images through the cache, and publishing *your own*.
Design: [RFC: Harbor Pull-Through Proxy Cache](../rfc/rfc-harbor-proxy-cache.md) and
[ADR-0023–0018](../adr/index.md).

### Pull third-party images through the proxy cache

**Seven** proxy-cache projects are created idempotently by the `harbor-proxy-config` CronJob (creds from
OpenBao `secret/harbor/registry-proxy`, [ADR-0025](../adr/adr-0025-harbor-config-idempotent-job.md)):
`dockerhub` → `docker.io`, `ghcr` → `ghcr.io`, `quay` → `quay.io`, `gcrmirror` → `mirror.gcr.io`,
`k8s` → `registry.k8s.io`, `forgejo` → `code.forgejo.org`, and `mcr` → `mcr.microsoft.com` (playwright base).
`dockerhub` uses Harbor's **native `docker-hub` provider** (url `hub.docker.com`), not a generic
docker-registry endpoint. The Talos registry mirror covers only **six** of these — `mcr` is proxy-only,
with no Talos `machine.registries.mirrors` entry. Two ways to consume them:

- **Explicit** (works now): pull through the project path —
  `docker pull harbor.${SECRET_DOMAIN}/dockerhub/library/<repo>:<tag>` (or `.../ghcr/<owner>/<repo>`).
  Harbor fetches from upstream once, scans, and caches; later pulls are local.
- **Transparent** (live — `talos/patches/global/machine-registries.yaml`): your manifests keep their
  `docker.io/…` / `ghcr.io/…` references and containerd routes them through Harbor automatically —
  **Spegel peers → Harbor proxy → upstream**, with containerd falling back to upstream if Harbor is
  down ([ADR-0024](../adr/adr-0024-registry-mirror-talos-spegel.md)).

### Publish & consume your own private images

Harbor is **LAN-only** ([ADR-0021](../adr/adr-0021-lan-only-exposure.md)), so the push must come
from a host that can reach `envoy-internal` — i.e. an **in-cluster runner** (`arc-systems` / `forgejo-runner`).
GitHub-hosted Actions cannot reach it. The build-and-push therefore lives in **`webgrip/workflows`**, not here.

1. **One-time Harbor-side setup (GitOps, this repo):** a private project (default: `webgrip`) and a
   push/pull **robot account**, provisioned the same idempotent-API way as the proxy projects; the robot
   token is generated and stored in OpenBao, surfaced to the runner via ESO.
2. **Push (on an in-cluster runner):**

   ```
   docker login harbor.${SECRET_DOMAIN} -u 'robot$webgrip+ci' -p "$HARBOR_ROBOT_TOKEN"
   docker push harbor.${SECRET_DOMAIN}/webgrip/<image>:<tag>
   ```

3. **Consume in-cluster:** reference `harbor.${SECRET_DOMAIN}/webgrip/<image>:<tag>` with an
   `imagePullSecret` built from a pull-only robot (or make the project public for anonymous in-cluster pulls).
4. **Migrate existing `ghcr.io/webgrip/*`** (optional, one-time): `skopeo copy --all
   docker://ghcr.io/webgrip/<image>:<tag> docker://harbor.${SECRET_DOMAIN}/webgrip/<image>:<tag>`, or a
   Harbor *replication* pull-rule from the `ghcr` registry endpoint.

## SBOM column & robot RBAC

Harbor's native SBOM generation (Harbor ≥ 2.11) is gated by a **dedicated RBAC resource** — action
`create` on resource **`sbom`**, **not** `scan:create`. Granting the intuitive `scan:create` does **not**
clear the 403: in Harbor source at the deployed tag (v2.15.1), `src/server/v2.0/handler/scan.go` does
`if scanType == ScanTypeSbom { res = ResourceSBOM }`, and `ResourceSBOM` is defined in
`src/common/rbac/const.go`. So the CI robot's access list must carry `{resource: sbom, action: create}`
alongside its `repository` push/pull (commit `9938e09`).

- **Triggering it:** `POST .../artifacts/{ref}/scan {"scan_type":"sbom"}` authorizes against `sbom:create`.
- **What feeds the column:** the **SBOM** UI column is populated *exclusively* by Harbor's own native
  (Trivy-backed) `.sbom` accessory. This is **separate** from the cosign `.att` attestation — a
  `cosign attest --type cyclonedx` produces a `.att` accessory shown under *Signed*, but it never lands in
  the SBOM column (different media types: the attestation feeds Kyverno verifyImages + Dependency-Track;
  the `.sbom` accessory feeds the Harbor UI/policies). Per-project `auto_sbom_generation` (≥ 2.11) is set
  via `PUT /projects/{id}`.

### Robot provisioner is non-idempotent

The project robot `robot$webgrip+ci` (project-level, id `2`) is provisioned by `configure.sh` inside
`harbor-proxy-config.configmap.yaml` (the same `harbor-proxy-config` CronJob). It is **not idempotent for
permissions**: `ensure_webgrip_robot()` POSTs the permission array only on **first creation**; for an
existing robot it merely PATCHes the secret, so editing the create-body permissions is a no-op against the
live robot. Converge an existing robot with a **`PUT /robots/{id}`** resending the full desired spec each
run. Caveats:

- `UpdateRobot` rejects a changed **name** or **level** — the PUT must reuse the **exact stored full name**.
  `GET /robots/{id}` returns it as `robot$webgrip+ci` (creation used the bare `ci`); read it back and reuse
  it verbatim.
- To find a **project** robot, query `GET /robots?q=Level=project,ProjectID=<id>` (URL-encoded
  `q=Level%3Dproject%2CProjectID%3D<id>`). A bare `GET /robots` lists **system** robots only.

> Verify an RBAC requirement credential-free by reading Harbor source at the deployed tag
> (`src/server/v2.0/handler/*.go`, `src/common/rbac/const.go`).

## Common problems

| Symptom | Cause | Fix |
|---------|-------|-----|
| HelmRelease stuck `not ready`; `harbor-admin`/`harbor-s3` not `SecretSynced` | OpenBao path missing or sealed | `kubectl -n harbor get externalsecret`; populate `secret/harbor/s3` (`just harbor-s3-cred`); check `ClusterSecretStore/openbao` Ready |
| PVC `Pending` | no default StorageClass | every PVC must set `storageClass` (`longhorn-general`) — already pinned in the HelmRelease |
| `registry` pod errors talking to S3 / redirect loops | Garage path-style not honored | `disableredirect: true` + `secure: false` + HTTP `regionendpoint` are mandatory (set already); check Garage at `10.0.0.110:3900` |
| Registry 5xx / blob I/O failing | Garage down | Garage is a hard dependency (ADR-0018 / [CNPG ↔ Garage](cnpg-backups.md)); restore Garage |
| OIDC login fails | redirect URI / RS256 | redirect must equal `https://harbor.${SECRET_DOMAIN}/c/oidc/callback`; see [Authentik OIDC login](authentik-oidc-login.md) |
| New pinned pod stuck `ContainerCreating` (Multi-Attach) when a single-replica RWO Deployment moves nodes | goharbor chart hardcodes `RollingUpdate` (can't switch to `Recreate` via values); old pod still holds the RWO volume — deleting the old *pod* alone fails (the ReplicaSet recreates it) | Delete the **old ReplicaSet** — the Deployment won't recreate a superseded revision, the volume frees, HR goes `UpgradeSucceeded`. Must beat the HR timeout (20m). The Dependency-Track api-server was instead converted to a **StatefulSet** (ordered recreate frees the RWO volume natively); note a StatefulSet's `volumeClaimTemplates.storageClassName` is **immutable** — repointing a chart-rendered STS PVC to a different SC is API-rejected and breaks the HR until STS+PVC are deleted/recreated |

## Backup & disaster recovery

- Daily CNPG backup (`harbor-db-daily`, 02:45) to Garage; WAL archiving continuous.
- An automated restore drill is wired via the `cnpg-restore-test` component
  (`kubernetes/apps/harbor/harbor/app/database/backup/restore-test/cronjob-patch.yaml`), **suspended by
  default** (cluster default to limit storage pressure). Flip `suspend: false` to enable.
- Full restore: follow the [CNPG backups & restore runbook](cnpg-backups.md#restore-dr-drill). The registry **blobs** live
  in Garage S3 (the source of truth) — restoring `harbor-db` recovers metadata; blobs are untouched by the DB restore.
