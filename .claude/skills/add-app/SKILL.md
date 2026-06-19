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

## Placement
Apps **hard-pin to the worker pool** — add one line to `app/kustomization.yaml`:
`components: [../../../../components/placement/worker-pool]`. See the `workload-placement` skill for the
tier model + the stateful sequencing gotcha (existing Longhorn PVs exclude newly-added nodes → pin
stateful apps only after the storage migration).

## Storage (Longhorn)
`longhorn` = default SSD/general (2-replica; reserved for CNPG too) · `longhorn-general` = current app RWO (folding into `longhorn`) · `longhorn-rwx` = shared RWX (rarely) · `longhorn-cold` = HDD bulk (not for DBs) · `longhorn-gitops` = forgejo/openbao only. See the `longhorn` skill / [ADR-0029](docs/techdocs/docs/adr/adr-0029-storageclass-consolidation.md).

## Observability
- Logs: stdout/stderr (JSON) → Loki automatically. Traces: OTLP/HTTP → `http://alloy-gateway.observability.svc.cluster.local:4318`.
- Metrics: expose `/metrics` + `ServiceMonitor`; Alerts: `PrometheusRule` (symptom-based; labels `severity`/`owner`/`service`; annotations `summary`/`description`/`runbook_url`/`dashboard_url`). Both **need label `release: kube-prometheus-stack`** (enforced) and low cardinality (`app.kubernetes.io/name`).

## Secrets
Cluster is migrating SOPS → **External Secrets Operator + OpenBao** — use the `external-secrets` skill. Don't write new `*.sops.yaml`. Quick path for a new app secret:
- **Random/session entropy:** `ExternalSecret` `dataFrom.sourceRef.generatorRef` → `ClusterGenerator/password-generator`, `refreshInterval: "0"` (generate-once). No human, no SOPS.
- **Provided value** (token/password/key): put it in OpenBao KV `secret/<app>/<name>` (UI `openbao.$${SECRET_DOMAIN}` or `bao kv put`), then an `ExternalSecret` (store `openbao`, `creationPolicy: Owner`, per-key `remoteRef` or `dataFrom: [{extract: {key: <path>}}]` for all keys).
- Consume via `existingSecret`/`envFromSecret`/`secretKeyRef`. SOPS floor that stays: age key, `cluster-secrets`, `talsecret`, `github-deploy-key`, openbao unseal.

## In-cluster provisioner Job/CronJob (optional)
For an app that needs a Job/CronJob hitting an admin API or writing a Secret/ConfigMap (e.g. `forgejo-ci-provisioner`, `cosign-pubkey`):
- **Least-privilege RBAC:** if it only `kubectl get` + `kubectl apply`s ONE object, scope `get,update,patch` with `resourceNames: [<that-object>]` and put `create` in a **separate** rule (RBAC can't scope `create` by name) — not blanket `secrets`/`configmaps`.
- **`secretKeyRef` env is injected by the kubelet, not the SA** — consuming a Secret via env needs **zero** RBAC; only direct API calls (`kubectl`) do. Set `automountServiceAccountToken: false` if it never calls the k8s API.
- **Fail-soft + idempotent:** mark inputs `optional: true`, guard missing values (`exit 0`, retry next tick), and make writes create-or-update so re-runs converge.
- Harden the pod: `runAsNonRoot`, `seccompProfile: {type: RuntimeDefault}`, `readOnlyRootFilesystem: true`, `capabilities: {drop: [ALL]}`.

## Validate
`./scripts/run-flux-local-test.sh` before committing.
