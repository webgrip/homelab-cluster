---
name: add-app
description: Scaffold a new application in the Flux GitOps tree — ks.yaml + bjw-s app-template HelmRelease + HTTPRoute (Gateway API) + secrets/DB wiring.
when_to_use: Use when adding/creating a new app, service, workload, or deployment to the cluster under kubernetes/apps/<namespace>/<app>.
---

# Add an application

**Copy a comparable existing app** (`freshrss`, `searxng`) under `kubernetes/apps/<ns>/<app>/` — don't write from scratch. Files + the non-obvious wiring:

1. **`ks.yaml`** — Flux `Kustomization`: `targetNamespace: <ns>`, `path: ./kubernetes/apps/<ns>/<app>/app`, `sourceRef` flux-system GitRepository, `prune: true`, `wait: false`, `dependsOn` (DB/operators), `postBuild.substituteFrom` Secret `cluster-secrets` (gives `$${SECRET_DOMAIN}`). Do **not** add `decryption`/install-upgrade-rollback remediation — the root `cluster-apps` ks injects them (enforced by `guard-skills.sh`).
2. **`app/kustomization.yaml`** — lists `./helmrelease.yaml` (+ `./httproute.yaml`, `./database/`, secrets).
3. **`app/helmrelease.yaml`** — default chart is bjw-s **app-template** via an `OCIRepository` (`oci://ghcr.io/bjw-s-labs/helm/app-template`, pinned `ref.tag`); `HelmRelease.spec.chartRef` → that OCIRepository; values: `controllers`/`service`/`persistence`.
4. **Ingress** = `app/httproute.yaml`, **Gateway API not Ingress** (enforced). `parentRefs` → `envoy-internal` (LAN) or `envoy-external` (public via Cloudflare Tunnel), `namespace: network`, `sectionName: https`; `hostnames: ["<app>.$${SECRET_DOMAIN}"]`. TLS terminates at the gateway (wildcard cert) — HTTPRoutes don't manage certs.
5. **Database** → `cnpg-database` skill.
6. **New namespace?** add `namespace.yaml` + ensure the ns `kustomization.yaml` includes `../../components/sops`. For zero-trust (default-deny + per-app netpols) → the `network-policy` skill.
7. **Register** the app in `kubernetes/apps/<ns>/kustomization.yaml`.

## Placement
Apps **hard-pin to the worker pool** — add one line to `app/kustomization.yaml`:
`components: [../../../../components/placement/worker-pool]`. See the `workload-placement` skill for the
tier model + the stateful sequencing gotcha (only `WaitForFirstConsumer` volumes like `longhorn-general`
are node-locked to pre-worker-1 nodes; `longhorn`/`Immediate` volumes — incl. CNPG DBs — pin freely).

## Storage (Longhorn)
Default SC is `longhorn` (SSD, 2-replica). Full StorageClass table + when to use each → the `longhorn` skill ([ADR-0029](docs/techdocs/docs/adr/adr-0029-storageclass-consolidation.md)).

## Observability
- Logs: JSON to stdout/stderr → Loki automatically. Traces: OTLP/HTTP → `http://alloy-gateway.observability.svc.cluster.local:4318`.
- Metrics/alerts: `ServiceMonitor` + `PrometheusRule`, both **need label `release: kube-prometheus-stack`** (enforced) + low cardinality. Dashboard/alert specifics → the `grafana-dashboard` skill.

## Secrets
**ESO + OpenBao, never a new `*.sops.yaml`** — use the `external-secrets` skill (random entropy → generate in-cluster; provided value → OpenBao). Consume via `existingSecret`/`envFromSecret`/`secretKeyRef`.

## In-cluster provisioner Job/CronJob (optional)
App needs a bootstrap/reconcile Job that hits an admin API or writes a Secret/ConfigMap → the `provisioner-job` skill.

## Validate
`./scripts/run-flux-local-test.sh` before committing.
