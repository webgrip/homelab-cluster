---
name: add-app
description: Scaffold a new application in the Flux GitOps tree. Use when adding/creating a new app, service, workload, or deployment to the cluster (kubernetes/apps/<namespace>/<app>).
---

# Add an application

Canonical recipe for a new app under `kubernetes/apps/<ns>/<app>/`. Copy an existing comparable app (e.g. `freshrss`, `searxng`) rather than writing from scratch.

## Files to create

1. **`kubernetes/apps/<ns>/<app>/ks.yaml`** — the Flux `Kustomization` (wiring layer):
   ```yaml
   ---
   apiVersion: kustomize.toolkit.fluxcd.io/v1
   kind: Kustomization
   metadata:
     name: <app>
   spec:
     targetNamespace: <ns>
     path: ./kubernetes/apps/<ns>/<app>/app
     sourceRef: { kind: GitRepository, name: flux-system, namespace: flux-system }
     interval: 1h
     prune: true
     wait: false
     dependsOn: []          # e.g. the CNPG cluster, grafana-operator
     postBuild:
       substituteFrom:
         - { kind: Secret, name: cluster-secrets }   # provides ${SECRET_DOMAIN}
   ```
   Do NOT re-add install/upgrade/rollback remediation or `decryption` — the root `cluster-apps` Kustomization injects those into every child.

2. **`kubernetes/apps/<ns>/<app>/app/kustomization.yaml`** — lists the resources:
   ```yaml
   ---
   apiVersion: kustomize.config.k8s.io/v1beta1
   kind: Kustomization
   resources:
     - ./helmrelease.yaml
     - ./httproute.yaml        # if web-facing
   ```

3. **`kubernetes/apps/<ns>/<app>/app/helmrelease.yaml`** — workloads. Default chart is **bjw-s app-template** via an `OCIRepository`:
   ```yaml
   ---
   apiVersion: source.toolkit.fluxcd.io/v1
   kind: OCIRepository
   metadata: { name: <app> }
   spec:
     interval: 1h
     url: oci://ghcr.io/bjw-s-labs/helm/app-template
     ref: { tag: <pinned-version> }
   ---
   apiVersion: helm.toolkit.fluxcd.io/v2
   kind: HelmRelease
   metadata: { name: <app> }
   spec:
     interval: 1h
     chartRef: { kind: OCIRepository, name: <app> }
     values:
       controllers: { ... }
       service: { ... }
       persistence: { ... }   # see Storage below
   ```

4. **Ingress** (web apps) — `app/httproute.yaml`, Gateway API (not Ingress):
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1
   kind: HTTPRoute
   metadata: { name: <app> }
   spec:
     parentRefs:
       - { name: envoy-internal, namespace: network, sectionName: https }   # or envoy-external for public
     hostnames: ["<app>.${SECRET_DOMAIN}"]
     rules: [ ... ]
   ```
   - `envoy-internal` = LAN-only; `envoy-external` = public via Cloudflare Tunnel. TLS is terminated at the gateway (wildcard `${SECRET_DOMAIN/./-}-production-tls`) — HTTPRoutes don't manage certs.

5. **Database** (if needed) → use the `cnpg-database` skill.

6. **New namespace?** add `kubernetes/apps/<ns>/namespace.yaml` and ensure the namespace's `kustomization.yaml` includes `../../components/sops`.

7. **Register** the app: add it to `kubernetes/apps/<ns>/kustomization.yaml`.

## Storage (Longhorn)
- `longhorn-general` = default RWO. `longhorn-rwx` = shared RWX (only when truly needed). `longhorn` = reserved for CNPG.

## Instrument it (observability)
- **Logs:** stdout/stderr, JSON preferred — auto-collected to Loki.
- **Traces:** OTLP/HTTP → `http://alloy-gateway.observability.svc.cluster.local:4318`.
- **Metrics:** expose `/metrics`; add a `ServiceMonitor` in the app namespace **labelled `release: kube-prometheus-stack`**. Keep label cardinality low (`app.kubernetes.io/name`).
- **Alerts:** `PrometheusRule` in the app namespace, **labelled `release: kube-prometheus-stack`**; symptom-based; labels `severity`+`owner`+`service`; annotations `summary`/`description`/`runbook_url`/`dashboard_url`.

## Secrets
Never write `*.sops.yaml` directly. Wire via `existingSecret`/`envFromSecret`, leave a `<app>-secrets.template.yaml`, and document the Secret name/namespace/keys for the human to encrypt.

## Validate
Run `./scripts/run-flux-local-test.sh` before committing.
