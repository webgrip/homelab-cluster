---
name: add-app
description: Scaffold a new application in the Flux GitOps tree — namespace + ks.yaml wiring, bjw-s app-template HelmRelease via the Harbor OCI proxy (digest-pinned), HTTPRoute, ESO secrets, and the reusable platform components (placement, CNPG set, gateway-egress, S3 creds, resource-quota).
when_to_use: Use when adding/creating/deploying a new app, service, or workload under kubernetes/apps/<namespace>/<app>, wiring a new namespace, or choosing which platform components and dependsOn targets a new app needs.
---

# Add an application

Tree: `kubernetes/apps/<ns>/kustomization.yaml` (+ `namespace.yaml`) → registers `<app>/ks.yaml`
(Flux wiring) → `<app>/app/` (resources). Compose from the **verified skeletons in
[reference.md](reference.md)** and the component catalog below — never by copying another app
(apps change and disappear; the skeletons and components are the stable contract).

## Pipeline

1. **Namespace** — `namespace.yaml` + ns-level `kustomization.yaml`; register `<ns>` in
   `kubernetes/apps/kustomization.yaml`. Zero-trust opt-in + per-app netpols → `network-policy` skill.
2. **`ks.yaml`** (skeleton §1) — `targetNamespace`, `path`, `postBuild.substituteFrom:
   cluster-secrets` (provides `${SECRET_DOMAIN}`), `prune: true`, `wait: false`, `dependsOn`
   from the menu below. The root `cluster-apps` ks injects `decryption` + remediation into every
   child — re-declaring them is hook-blocked.
3. **Chart** (skeleton §3) — `OCIRepository` through the Harbor proxy
   (`oci://harbor.webgrip.dev/ghcr/…`, [ADR-0023](docs/techdocs/docs/adr/adr-0023-harbor-pull-through-proxy-cache.md)),
   pinned by **tag + digest** — refresh pins with `./scripts/update-oci-digests.sh`. Generic
   apps: bjw-s **app-template**, `HelmRelease.spec.chartRef` → the OCIRepository, values under
   `controllers`/`service`/`persistence`. Plain Deployment `image:` pins (the mcp-* pattern) have
   no script and skopeo/crane aren't in mise — digest = sha256 of the manifest body fetched with an
   anonymous Harbor token (Harbor's `docker-content-digest` header comes back empty on a
   proxy-cache first pull):

   ```sh
   tok=$(curl -s 'https://harbor.webgrip.dev/service/token?service=harbor-registry&scope=repository:ghcr/<org>/<img>:pull' | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
   curl -s "https://harbor.webgrip.dev/v2/ghcr/<org>/<img>/manifests/<tag>" -H "Authorization: Bearer $tok" \
     -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json' -o /tmp/m.json && sha256sum /tmp/m.json
   ```
4. **Route** (skeleton §4) — `hostnames: ["<app>.${SECRET_DOMAIN}"]` (single `$`: Flux
   substitutes it; `$$` renders literally and breaks the route). `parentRefs` →
   `envoy-internal` (LAN default) or `envoy-external` (public — a deliberate exposure choice),
   `namespace: network`, `sectionName: https`. TLS terminates at the gateway. Gateway API only —
   `Ingress` is hook-blocked.
5. **Secrets** — ESO + OpenBao, never a new `*.sops.yaml` → `external-secrets` skill (random →
   in-cluster generator; provided → OpenBao KV). Consume via `existingSecret`/`envFrom`; put
   `reloader.stakater.com/auto: "true"` on the controller so rotations restart the pod.
6. **Database** → `cnpg-database` skill, plus the cnpg components below.
7. **Placement** → `workload-placement` skill: pin to workers — native
   `pod.nodeSelector: {node.webgrip.io/pool: worker}` when the chart exposes it, else the
   `placement/worker-pool` component. Storage: default SC `longhorn`; full table → `longhorn` skill.
8. **Observability** — logs: JSON to stdout/stderr → Loki automatically. Traces: OTLP/HTTP →
   `http://alloy-gateway.observability.svc.cluster.local:4318`. Metrics: `ServiceMonitor`
   (vm-operator converts it; no `release:` label needed) or native VM CRs → `victoriametrics`
   skill. Alerts: `PrometheusRule` meeting the CI-gated annotation contract — summary ends with
   a `(scope)`, description carries a `Likely causes:` section
   ([alerting-principles](docs/techdocs/docs/general/alerting-principles.md)). Dashboards →
   `grafana-dashboard` skill.
9. **Provisioner Job** (bootstrap against an admin API) → `provisioner-job` skill.
10. **Validate** — `./scripts/run-flux-local-test.sh`; render/diff → `flux-validate` skill.

## Component catalog — `kubernetes/components/`, wired via `components:` in `app/kustomization.yaml` (skeleton §2)

| Component | Gives the app | Use when |
| --- | --- | --- |
| `placement/worker-pool` | post-render hard `nodeSelector` to `pool=worker` ([ADR-0002](docs/techdocs/docs/adr/adr-0002-application-workload-placement.md)) | chart has no native nodeSelector values |
| `cnpg-netpol` | DB-layer NetworkPolicy + CiliumNetworkPolicy | every CNPG cluster in a default-deny ns (avoids the `ClusterIsNotReady` deadlock) |
| `cnpg-backup` | `cnpg-backup-s3` ExternalSecret (+PushSecret) in the app ns | every CNPG cluster with barman backups |
| `cnpg-monitoring` | CNPG PodMonitor + alert-rule pack | every CNPG cluster |
| `cnpg-restore-test` | restore-drill CronJob + RBAC | per the DB's [backup tier](docs/techdocs/docs/general/database-backup-tiers.md) |
| `cnpg-disaster-recovery` | DR verify cluster + drill CronJob + queries | top-tier DBs per the same tiers doc |
| `gateway-egress` | identity-based egress allow to the envoy gateways | app does server-side OIDC discovery under default-deny ([ADR-0006](docs/techdocs/docs/adr/adr-0006-default-deny-network-policies.md)) |
| `observability-s3` / `security-s3` | Garage S3 credential ES for that namespace's workloads | S3-writing workloads in those namespaces |
| `resource-quota` | namespace ResourceQuota | every new app namespace |
| `sops` | SOPS-decrypted `cluster-secrets` in-ns | legacy only — new secrets go via ESO |

## dependsOn menu (`ks.yaml`)

`external-secrets-stores` (security) — app has any ExternalSecret · `cloudnative-pg`
(cnpg-system) — app has a CNPG DB · `grafana-operator` (observability) — app ships
dashboards/folders · `victoria-metrics` (observability) — app ships scrape/rule CRs · plus
app-specific Kustomizations (e.g. a split `<app>-db`).
