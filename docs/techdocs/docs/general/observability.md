# Observability (LGTM + Profiles)

This cluster runs a Flux-managed, Grafana-centric observability platform in the `observability` namespace.

It provides:

- **Metrics**: VictoriaMetrics (vm-operator + VMSingle/VMAgent/VMAlert; see [ADR-0038](../adr/adr-0038-victoriametrics-metrics-backend.md))
- **Logs**: Loki
- **Traces**: Tempo
- **Profiles**: Pyroscope
- **Collection / routing**: Grafana Alloy (node agent + OTLP gateway)
- **Visualization**: Grafana
- **Alerting**: VMAlert + VMAlertmanager + Grafana Alerting UI

> Design goal: “top-tier OSS stack” with clean GitOps, SOPS-managed secrets, and Gateway API ingress.

---

## Where it lives

All manifests are GitOps-managed under:

- [kubernetes/apps/observability](../../../../kubernetes/apps/observability)

Entry points:

- [kubernetes/apps/observability/kustomization.yaml](../../../../kubernetes/apps/observability/kustomization.yaml)
- [kubernetes/apps/observability/namespace.yaml](../../../../kubernetes/apps/observability/namespace.yaml)

---

## Ingress URLs (internal)

These are exposed via `HTTPRoute` on the `envoy-internal` gateway:

- `https://grafana.<SECRET_DOMAIN>`
- `https://prometheus.<SECRET_DOMAIN>`
- `https://alertmanager.<SECRET_DOMAIN>`

---

## Components

### VictoriaMetrics (metrics backend)

Replaced kube-prometheus-stack on 2026-07-01 — see [ADR-0038](../adr/adr-0038-victoriametrics-metrics-backend.md) and the [VictoriaMetrics runbook](../runbooks/victoriametrics.md). Modular, grafana-operator-style:

- **`vm-operator`** HelmRelease — installs the VM CRDs and **converts** existing `ServiceMonitor`/`PodMonitor`/`Probe`/`PrometheusRule` CRs into VM CRDs, so app scrape/rule CRs are unchanged and the `release: kube-prometheus-stack` labels are harmless no-ops. (Its own `serviceMonitor` is intentionally disabled — enabling it races the VMServiceScrape CRD on first install; see the runbook.)
- **`prometheus-operator-crds`** HelmRelease — keeps the `monitoring.coreos.com` CRDs (needed for conversion + a from-scratch bootstrap).
- **`victoria-metrics/app/`** CRs:
  - **VMSingle** — TSDB + query + `remote_write` receiver, 15d / 50Gi Longhorn, at `vmsingle-vmsingle.observability.svc.cluster.local:8429` (`/api/v1/write`).
  - **VMAgent** — scrapes everything (`selectAllByDefault: true`), `remote_write` → VMSingle. Reproduces Prometheus's cluster-wide discovery; `externalLabels.cluster=homelab-cluster`.
  - **VMAlert** — evaluates the converted VMRules, notifies VMAlertmanager.
  - **VMAlertmanager** — `vmalertmanager-vmalertmanager.observability.svc.cluster.local:9093`.
- **`kube-state-metrics`** + **`node-exporter`** — standalone charts (were kube-prom subcharts).

Control-plane scrape coverage (kubelet, cAdvisor, kube-apiserver, CoreDNS, Talos etcd) is explicit under `victoria-metrics/app/scrapes/` — Talos etcd on `10.0.0.20/21/22:2381` (HTTP, `job=talos-etcd`), CoreDNS metrics on the pod port named `tcp-9153`.

**Long-term storage:** VMSingle *is* the store (no Mimir/Thanos). Mimir + its embedded Kafka were retired with this swap. Retention is 15d local; no object-store backup is configured (a future option).

> The app-instrumentation sections further down still reference the old Prometheus/Mimir endpoints in places — for scraping, emit a `ServiceMonitor`/`PodMonitor` (the operator converts it) or a native VM `*Scrape`; there is no separate long-term `remote_write` target anymore (VMSingle is the store).

### Grafana

- HelmRelease: [kubernetes/apps/observability/grafana/app/helmrelease.yaml](../../../../kubernetes/apps/observability/grafana/app/helmrelease.yaml)
- Admin secret (SOPS): kubernetes/apps/observability/grafana/app/admin-secret.sops.yaml
- Persistence: Longhorn PVC

Plugins:

- `grafana-pyroscope-app` (profiles integration)
- `grafana-clock-panel`, `grafana-piechart-panel`, `grafana-polystat-panel` (useful dashboard panels)

Rendering:

- Grafana is configured with a **remote image renderer** (chart-managed `grafana-image-renderer` deployment) for reliable panel rendering in alerts/reports.

Authentik login:

- Grafana is configured for Authentik OIDC login.
- Callback URL: `https://grafana.<SECRET_DOMAIN>/login/generic_oauth`
- **DNS dependency**: The Grafana pod must be able to resolve `authentik.<SECRET_DOMAIN>`. If login fails with "Failed to get token from provider", check CoreDNS zone forwarding first — see the [split-horizon DNS runbook](../runbooks/dns-split-dns.md) and the [Authentik OIDC login runbook](../runbooks/authentik-oidc-login.md).

To enable it, a human must create a SOPS-encrypted Secret containing the Authentik OAuth client credentials.

Secret details:

- Namespace: `observability`
- Name: `grafana-oauth`
- Keys: `GF_AUTH_GENERIC_OAUTH_CLIENT_ID`, `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET`

Template (encrypt with SOPS before committing):

```yaml
apiVersion: v1
kind: Secret
metadata:
   name: grafana-oauth
   namespace: observability
type: Opaque
stringData:
   GF_AUTH_GENERIC_OAUTH_CLIENT_ID: "<authentik oauth client id>"
   GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET: "<authentik oauth client secret>"
```

Note:

- If you commit this Secret to Git, add it to [kubernetes/apps/observability/grafana/app/kustomization.yaml](../../../../kubernetes/apps/observability/grafana/app/kustomization.yaml) so Flux applies it.
- Alternatively, create it out-of-band with `kubectl` (but then it's no longer fully GitOps-managed).

Authentik provider settings:

- Provider: `Grafana OIDC` (created via the Authentik blueprint)
- Redirect URI: `https://grafana.<SECRET_DOMAIN>/login/generic_oauth`

Provisioned datasources:

- Prometheus (kube-prometheus-stack)
- Mimir (long-term metrics)
- Loki
- Tempo
- Pyroscope
- Alertmanager

Dashboards:

- Grafana sidecar watches for ConfigMaps/Secrets labelled `grafana_dashboard=1` across namespaces.
- This repo also ships a small starter pack in [kubernetes/apps/observability/grafana/app/dashboards](../../../../kubernetes/apps/observability/grafana/app/dashboards).

### Loki

- HelmRelease: [kubernetes/apps/observability/loki/app/helmrelease.yaml](../../../../kubernetes/apps/observability/loki/app/helmrelease.yaml)

This deploys Loki in **SingleBinary** mode with S3-compatible object storage.

Notes on local storage:

- Even with S3 for chunks/index, Loki still needs **local disk** for things like WAL/TSDB scratch data, compaction/retention work, and temporary files.
- This repo explicitly enables a Longhorn-backed PVC for the SingleBinary pod so Loki can restart safely without losing local state.

Retention:

- Configured for ~30 days (`720h`) via `compactor` + `limits_config.retention_period`.

Meta-monitoring:

- ServiceMonitor + built-in dashboards/rules are enabled via the Loki Helm chart.

Bucket requirements (create these in your S3 backend):

- `loki-chunks`
- `loki-ruler`
- `loki-admin`

S3 credentials:

- Sourced from the existing SOPS-managed secret `observability-s3` (injected via `extraEnvFrom`).

### Tempo

- HelmRelease: [kubernetes/apps/observability/tempo/app/helmrelease.yaml](../../../../kubernetes/apps/observability/tempo/app/helmrelease.yaml)

Tempo is deployed in single-binary mode and configured for S3-compatible trace storage.

Retention:

- Configured for 14 days (`336h`).

Bucket requirement:

- `tempo`

Tempo receivers:

- OTLP gRPC `4317`
- OTLP HTTP `4318`

Note:

- `metricsGenerator` is enabled and remote-writes generated metrics to Prometheus.
- This unlocks Grafana Tempo UI features like **service map** and **traces → metrics** (span metrics).

Related settings:

- Tempo Helm values: `tempo.metricsGenerator.enabled=true`
- Prometheus Helm values: `prometheus.prometheusSpec.enableRemoteWriteReceiver=true`

### Pyroscope

- HelmRelease: [kubernetes/apps/observability/pyroscope/app/helmrelease.yaml](../../../../kubernetes/apps/observability/pyroscope/app/helmrelease.yaml)

Pyroscope is initially deployed with Longhorn-backed persistence for reliability.

### Grafana Alloy

There are **two** Alloy installations:

1. **alloy-agent** (DaemonSet)
   - Collects Kubernetes pod logs from each node and writes to Loki.
   - HelmRelease: [kubernetes/apps/observability/alloy-agent/app/helmrelease.yaml](../../../../kubernetes/apps/observability/alloy-agent/app/helmrelease.yaml)

2. **alloy-gateway** (Deployment)
   - Provides a stable, load-balanced **OTLP endpoint** for applications.
   - Receives OTLP and forwards traces to Tempo.
   - HelmRelease: [kubernetes/apps/observability/alloy-gateway/app/helmrelease.yaml](../../../../kubernetes/apps/observability/alloy-gateway/app/helmrelease.yaml)

---

## Secrets + SOPS

This repo uses Age-encrypted SOPS secrets. Observability uses a dedicated `observability-s3` secret for S3-compatible credentials/endpoints.

- Secret: kubernetes/components/observability-s3/observability-s3.sops.yaml

Grafana admin credentials are stored in:

- kubernetes/apps/observability/grafana/app/admin-secret.sops.yaml

To update the Grafana admin password:

- `sops kubernetes/apps/observability/grafana/app/admin-secret.sops.yaml`

---

## Application instrumentation

This section explains how to wire other apps running in the cluster into the observability platform.

### Quick start (recommended defaults)

For most apps, do these three things:

1. **Logs**: log to stdout/stderr (JSON if possible).
2. **Traces**: add OpenTelemetry SDK and set OTLP exporter env vars to Alloy gateway.
3. **Metrics**: expose a `/metrics` endpoint and create a `ServiceMonitor`.

### Metrics (Prometheus)

Prometheus scraping is driven by Prometheus Operator CRDs (installed by kube-prometheus-stack):

- `ServiceMonitor` (common)
- `PodMonitor`

Because Prometheus is configured to discover monitors cluster-wide, you can create these in the same namespace as the app.

#### Example: Service + ServiceMonitor

Expose metrics from your workload on a stable `Service`:

```yaml
apiVersion: v1
kind: Service
metadata:
   name: myapp
   namespace: myapp
   labels:
      app.kubernetes.io/name: myapp
spec:
   selector:
      app.kubernetes.io/name: myapp
   ports:
      - name: http-metrics
         port: 8080
         targetPort: 8080
```

Then create a `ServiceMonitor`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
   name: myapp
   namespace: myapp
   labels:
      release: kube-prometheus-stack
spec:
   selector:
      matchLabels:
         app.kubernetes.io/name: myapp
   endpoints:
      - port: http-metrics
         path: /metrics
         interval: 30s
```

Tips:

- If the ServiceMonitor doesn't appear in Prometheus targets, check selector/labels and whether the operator expects a specific label.
- If your metrics endpoint needs auth/TLS, use `endpoints[].bearerTokenSecret`, `basicAuth`, `tlsConfig`, etc.

### Long-term metrics (Mimir)

In this cluster, Prometheus scrapes locally and also remote-writes to Mimir for long-term storage.

If you operate a separate Prometheus (or anything that can remote_write directly), use:

- URL: `http://mimir-distributed-gateway.observability.svc.cluster.local/api/v1/push`
- Header: `X-Scope-OrgID: homelab`

### Logs (Loki via Alloy agent)

Logs are collected automatically from Kubernetes pod log files (`/var/log/pods/...`) by `alloy-agent`.

That means:

- If your container writes to stdout/stderr, logs will show up in Loki automatically.
- You don't need per-app log agents.

Best practices:

- Prefer structured JSON logs.
- Include `trace_id` / `span_id` fields in logs when you have tracing enabled.
- Avoid secrets/credentials/PII in logs.

If an app writes logs to files inside the container instead of stdout/stderr, those logs will not be collected by default.

### Traces (OpenTelemetry → Alloy gateway → Tempo)

All application traces should be exported to the in-cluster Alloy gateway:

- OTLP gRPC: `alloy-gateway.observability.svc.cluster.local:4317`
- OTLP HTTP: `http://alloy-gateway.observability.svc.cluster.local:4318`

Tempo metrics generation (span-metrics + service-graphs) is enabled and remote-writes generated metrics to Prometheus.

#### Kubernetes env var recipe (works for most OTel SDKs)

Add these to your Deployment/StatefulSet container:

```yaml
env:
   - name: OTEL_SERVICE_NAME
      value: myapp
   - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: http://alloy-gateway.observability.svc.cluster.local:4318
   - name: OTEL_EXPORTER_OTLP_PROTOCOL
      value: http/protobuf
   - name: OTEL_RESOURCE_ATTRIBUTES
      value: service.namespace=myapp,k8s.cluster.name=homelab-cluster

### Metrics (OpenTelemetry → Alloy gateway → Mimir)

The Alloy gateway also accepts **OTLP metrics** and forwards them to Mimir via Prometheus remote_write.

- OTLP gRPC: `alloy-gateway.observability.svc.cluster.local:4317`
- OTLP HTTP: `http://alloy-gateway.observability.svc.cluster.local:4318`

Most OpenTelemetry SDKs will export metrics automatically when configured with the standard OTLP env vars.

Suggested baseline:

```yaml
env:
   - name: OTEL_SERVICE_NAME
      value: myapp
   - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: http://alloy-gateway.observability.svc.cluster.local:4318
   - name: OTEL_EXPORTER_OTLP_PROTOCOL
      value: http/protobuf
   - name: OTEL_RESOURCE_ATTRIBUTES
      value: service.namespace=myapp,k8s.cluster.name=homelab-cluster
```

Notes:

- Some SDKs want signal-specific endpoints. For traces, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is typically `http://alloy-gateway.observability.svc.cluster.local:4318/v1/traces`.
- Keep `OTEL_SERVICE_NAME` stable; use attributes for instance/environment detail.

### Frontend (Faro)

The Alloy gateway exposes a Faro receiver for browser telemetry:

- Faro receiver: `http://alloy-gateway.observability.svc.cluster.local:12347/api/faro/receiver`

In the Grafana Faro Web SDK, set the collector URL to the above endpoint.

### Profiles (Pyroscope)

Pyroscope is deployed, but profiling onboarding is runtime-specific.

Most common approach:

- Add the Pyroscope SDK/client for your language and point it at `http://pyroscope.observability.svc.cluster.local:4040`.

If you tell me the language/runtime for a specific app (Go/Java/.NET/Python/Node), I can add a minimal, correct snippet for that runtime.

### Alerts (PrometheusRule + Alertmanager)

Alerting is driven by `PrometheusRule` objects and routed by Alertmanager.

#### Example: a simple alert rule

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
   name: myapp-alerts
   namespace: myapp
   labels:
      release: kube-prometheus-stack
spec:
   groups:
      - name: myapp.alerts
         rules:
            - alert: MyAppHighErrorRate
               expr: |
                  sum(rate(http_requests_total{job="myapp",status=~"5.."}[5m]))
                  /
                  sum(rate(http_requests_total{job="myapp"}[5m]))
                  > 0.02
               for: 10m
               labels:
                  severity: warning
               annotations:
                  summary: MyApp elevated 5xx rate
                  description: MyApp 5xx rate has been >2% for 10 minutes.
```

Routing policy (who gets paged, inhibition rules, etc.) can be expressed as code with `AlertmanagerConfig` when you're ready.

---

## Validation checklist

After Flux reconciles:

- Grafana is reachable and datasources connect
- Prometheus targets are healthy and collecting
- Alloy agent is writing logs to Loki
- Alloy gateway accepts OTLP and Tempo shows traces

- Prometheus shows `remote_write` is healthy
- Mimir query endpoint responds (Grafana `Mimir` datasource connects)

---

## Next upgrades ("top of top")

If you want to push this from “excellent” to “elite”:

- Add **recording rules** + SLO burn alerts per critical app
- Add **AlertmanagerConfig** resources (routing, inhibition, silences)
- Add a dedicated **metrics long-term store** (Mimir) + Prometheus remote_write
- Add **Tempo metrics-generator** (service graphs + span metrics)
- Enforce **multi-tenancy** in Loki/Tempo when you're ready

---

## SLOs (Sloth)

This cluster includes **Sloth** to define SLOs as code and generate Prometheus recording + burn-rate alert rules.

- Sloth install: [kubernetes/apps/observability/sloth](../../kubernetes/apps/observability/sloth)

SLO CRs:

- [kubernetes/apps/observability/sloth/app/slos/slo-app-availability.yaml](../../kubernetes/apps/observability/sloth/app/slos/slo-app-availability.yaml)
- [kubernetes/apps/observability/sloth/app/slos/slo-synthetic-availability.yaml](../../kubernetes/apps/observability/sloth/app/slos/slo-synthetic-availability.yaml)
- [kubernetes/apps/observability/sloth/app/slos/slo-synthetic-k6-canary.yaml](../../kubernetes/apps/observability/sloth/app/slos/slo-synthetic-k6-canary.yaml)

Workflow:

1. Add a `PrometheusServiceLevel` for your service.
2. Sloth generates `PrometheusRule` resources.
3. Prometheus evaluates them and Alertmanager routes them.

---

## Synthetic monitoring (blackbox)

This cluster runs a Prometheus Operator **blackbox exporter + Probe CRs** for ingress-level uptime checks.

- Blackbox exporter: [kubernetes/apps/observability/blackbox-exporter](../../kubernetes/apps/observability/blackbox-exporter)
- Probes: [kubernetes/apps/observability/blackbox-exporter/app](../../kubernetes/apps/observability/blackbox-exporter/app)

Current probes target:

- `https://grafana.${SECRET_DOMAIN}`
- `https://prometheus.${SECRET_DOMAIN}`
- `https://alertmanager.${SECRET_DOMAIN}`

---

## Synthetic traffic (k6)

The cluster runs scheduled **k6 canary** tests to generate a small amount of real traffic and export results to Prometheus.

- Manifests: [kubernetes/apps/observability/k6-canaries](../../kubernetes/apps/observability/k6-canaries)
- Script: [kubernetes/apps/observability/k6-canaries/app/script-configmap.yaml](../../kubernetes/apps/observability/k6-canaries/app/script-configmap.yaml)

Implementation notes:

- A CronJob creates a `k6.io/v1alpha1` `TestRun` every 30 minutes.
- k6 remote-writes metrics to Prometheus (`/api/v1/write`) via the `experimental-prometheus-rw` output.
