---
name: add-app
description: Scaffold a new application in the Flux GitOps tree. Use when adding/creating a new app, service, workload, or deployment to the cluster (kubernetes/apps/<namespace>/<app>).
---

# Add an application

**Copy a comparable existing app** (`freshrss`, `searxng`) under `kubernetes/apps/<ns>/<app>/` — don't write from scratch. Files + the non-obvious wiring:

1. **`ks.yaml`** — Flux `Kustomization`: `targetNamespace: <ns>`, `path: ./kubernetes/apps/<ns>/<app>/app`, `sourceRef` flux-system GitRepository, `prune: true`, `wait: false`, `dependsOn` (DB/operators), `postBuild.substituteFrom` Secret `cluster-secrets` (gives `$${SECRET_DOMAIN}`). Do **not** add `decryption`/install-upgrade-rollback remediation — the root `cluster-apps` ks injects them (enforced by `guard-skills.sh`).
2. **`app/kustomization.yaml`** — lists `./helmrelease.yaml` (+ `./httproute.yaml`, `./database/`, secrets).
3. **`app/helmrelease.yaml`** — default chart is bjw-s **app-template** via an `OCIRepository` (`oci://ghcr.io/bjw-s-labs/helm/app-template`, pinned `ref.tag`); `HelmRelease.spec.chartRef` → that OCIRepository; values: `controllers`/`service`/`persistence`.
4. **Ingress** = `app/httproute.yaml`, **Gateway API not Ingress** (enforced). `parentRefs` → `envoy-internal` (LAN) or `envoy-external` (public via Cloudflare Tunnel), `namespace: network`, `sectionName: https`; `hostnames: ["<app>.$${SECRET_DOMAIN}"]`. TLS terminates at the gateway (wildcard cert) — HTTPRoutes don't manage certs.
5. **Database** → `cnpg-database` skill.
6. **New namespace?** add `namespace.yaml` + ensure the ns `kustomization.yaml` includes `../../components/sops`.
7. **Register** the app in `kubernetes/apps/<ns>/kustomization.yaml`.

## Storage (Longhorn)
`longhorn-general` = default RWO · `longhorn-rwx` = shared RWX (rarely) · `longhorn` = reserved for CNPG.

## Observability
- Logs: stdout/stderr (JSON) → Loki automatically. Traces: OTLP/HTTP → `http://alloy-gateway.observability.svc.cluster.local:4318`.
- Metrics: expose `/metrics` + `ServiceMonitor`; Alerts: `PrometheusRule` (symptom-based; labels `severity`/`owner`/`service`; annotations `summary`/`description`/`runbook_url`/`dashboard_url`). Both **need label `release: kube-prometheus-stack`** (enforced) and low cardinality (`app.kubernetes.io/name`).

## Secrets
Never write `*.sops.yaml`. Wire `existingSecret`/`envFromSecret`, leave a `<app>-secrets.template.yaml`, document Secret name/ns/keys for the human to encrypt.

## Validate
`./scripts/run-flux-local-test.sh` before committing.
