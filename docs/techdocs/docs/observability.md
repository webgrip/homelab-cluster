# Observability (LGTM + Profiles)

This cluster runs a Flux-managed, Grafana-centric observability platform in the `observability` namespace.

It provides:

- **Metrics**: Prometheus (via kube-prometheus-stack)
- **Logs**: Loki
- **Traces**: Tempo
- **Profiles**: Pyroscope
- **Collection / routing**: Grafana Alloy (node agent + OTLP gateway)
- **Visualization**: Grafana
- **Alerting**: Alertmanager (kube-prometheus-stack) + Grafana Alerting UI

> Design goal: “top-tier OSS stack” with clean GitOps, SOPS-managed secrets, and Gateway API ingress.

---

## Where it lives

All manifests are GitOps-managed under:

- [kubernetes/apps/observability](../../kubernetes/apps/observability)

Entry points:

- [kubernetes/apps/observability/kustomization.yaml](../../kubernetes/apps/observability/kustomization.yaml)
- [kubernetes/apps/observability/namespace.yaml](../../kubernetes/apps/observability/namespace.yaml)

---

## Ingress URLs (internal)

These are exposed via `HTTPRoute` on the `envoy-internal` gateway:

- `https://grafana.<SECRET_DOMAIN>`
- `https://prometheus.<SECRET_DOMAIN>`
- `https://alertmanager.<SECRET_DOMAIN>`

---

## Components

### Prometheus + Alertmanager (kube-prometheus-stack)

- HelmRelease: [kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml](../../kubernetes/apps/observability/kube-prometheus-stack/app/helmrelease.yaml)
- Storage: Longhorn-backed PVCs for Prometheus TSDB and Alertmanager

Key decisions:

- `kubeProxy.enabled=false` because this cluster is kube-proxy-free (Cilium).
- Control-plane scrapes are disabled by default (`kubeEtcd`, `kubeControllerManager`, `kubeScheduler`) to avoid noisy failures in environments where endpoints are not exposed.
- Prometheus is configured to **discover ServiceMonitors/PodMonitors/Rules cluster-wide** (selectors empty + `*SelectorNilUsesHelmValues=false`).

### Mimir (long-term metrics)

- HelmRelease: [kubernetes/apps/observability/mimir-distributed/app/helmrelease.yaml](../../kubernetes/apps/observability/mimir-distributed/app/helmrelease.yaml)

Endpoints (in-cluster):

- Prometheus `remote_write` target: `http://mimir-distributed-gateway.observability.svc.cluster.local/api/v1/push`
- Prometheus-compatible query endpoint: `http://mimir-distributed-gateway.observability.svc.cluster.local/prometheus`

Tenant:

- This setup uses Mimir multi-tenancy with `X-Scope-OrgID: homelab`.

Storage:

- Object storage: S3-compatible backend via `cnpg-backup-s3` env vars
- Local persistence: Longhorn PVCs for ingester/store-gateway/compactor

### Grafana

- HelmRelease: [kubernetes/apps/observability/grafana/app/helmrelease.yaml](../../kubernetes/apps/observability/grafana/app/helmrelease.yaml)
- Admin secret (SOPS): [kubernetes/apps/observability/grafana/app/admin-secret.sops.yaml](../../kubernetes/apps/observability/grafana/app/admin-secret.sops.yaml)
- Persistence: Longhorn PVC

Provisioned datasources:

- Prometheus (kube-prometheus-stack)
- Mimir (long-term metrics)
- Loki
- Tempo
- Pyroscope
- Alertmanager

Dashboards:

- Grafana sidecar watches for ConfigMaps/Secrets labelled `grafana_dashboard=1` across namespaces. Some apps (e.g. CNPG) already ship dashboards in that format.

### Loki

- HelmRelease: [kubernetes/apps/observability/loki/app/helmrelease.yaml](../../kubernetes/apps/observability/loki/app/helmrelease.yaml)

This deploys Loki in **SimpleScalable** mode with S3-compatible object storage.

Bucket requirements (create these in your S3 backend):

- `loki-chunks`
- `loki-ruler`
- `loki-admin`

S3 credentials:

- Sourced from the existing SOPS-managed secret `cnpg-backup-s3` (injected via `extraEnvFrom`).

### Tempo

- HelmRelease: [kubernetes/apps/observability/tempo/app/helmrelease.yaml](../../kubernetes/apps/observability/tempo/app/helmrelease.yaml)

Tempo is deployed in single-binary mode and configured for S3-compatible trace storage.

Bucket requirement:

- `tempo`

Tempo receivers:

- OTLP gRPC `4317`
- OTLP HTTP `4318`

### Pyroscope

- HelmRelease: [kubernetes/apps/observability/pyroscope/app/helmrelease.yaml](../../kubernetes/apps/observability/pyroscope/app/helmrelease.yaml)

Pyroscope is initially deployed with Longhorn-backed persistence for reliability.

### Grafana Alloy

There are **two** Alloy installations:

1. **alloy-agent** (DaemonSet)
   - Collects Kubernetes pod logs from each node and writes to Loki.
   - HelmRelease: [kubernetes/apps/observability/alloy-agent/app/helmrelease.yaml](../../kubernetes/apps/observability/alloy-agent/app/helmrelease.yaml)

2. **alloy-gateway** (Deployment)
   - Provides a stable, load-balanced **OTLP endpoint** for applications.
   - Receives OTLP and forwards traces to Tempo.
   - HelmRelease: [kubernetes/apps/observability/alloy-gateway/app/helmrelease.yaml](../../kubernetes/apps/observability/alloy-gateway/app/helmrelease.yaml)

---

## Secrets + SOPS

This repo uses Age-encrypted SOPS secrets. Observability reuses the existing `cnpg-backup` component to render a namespace-local `cnpg-backup-s3` secret.

- Component: [kubernetes/components/cnpg-backup](../../kubernetes/components/cnpg-backup)

Grafana admin credentials are stored in:

- [kubernetes/apps/observability/grafana/app/admin-secret.sops.yaml](../../kubernetes/apps/observability/grafana/app/admin-secret.sops.yaml)

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

**Example: Service + ServiceMonitor**

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

- If the ServiceMonitor doesn’t appear in Prometheus targets, check selector/labels and whether the operator expects a specific label.
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
- You don’t need per-app log agents.

Best practices:

- Prefer structured JSON logs.
- Include `trace_id` / `span_id` fields in logs when you have tracing enabled.
- Avoid secrets/credentials/PII in logs.

If an app writes logs to files inside the container instead of stdout/stderr, those logs will not be collected by default.

### Traces (OpenTelemetry → Alloy gateway → Tempo)

All application traces should be exported to the in-cluster Alloy gateway:

- OTLP gRPC: `alloy-gateway.observability.svc.cluster.local:4317`
- OTLP HTTP: `http://alloy-gateway.observability.svc.cluster.local:4318`

**Kubernetes env var recipe (works for most OTel SDKs)**

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
```

Notes:

- Some SDKs want signal-specific endpoints. For traces, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is typically `http://alloy-gateway.observability.svc.cluster.local:4318/v1/traces`.
- Keep `OTEL_SERVICE_NAME` stable; use attributes for instance/environment detail.

### Profiles (Pyroscope)

Pyroscope is deployed, but profiling onboarding is runtime-specific.

Most common approach:

- Add the Pyroscope SDK/client for your language and point it at `http://pyroscope.observability.svc.cluster.local:4040`.

If you tell me the language/runtime for a specific app (Go/Java/.NET/Python/Node), I can add a minimal, correct snippet for that runtime.

### Alerts (PrometheusRule + Alertmanager)

Alerting is driven by `PrometheusRule` objects and routed by Alertmanager.

**Example: a simple alert rule**

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

Routing policy (who gets paged, inhibition rules, etc.) can be expressed as code with `AlertmanagerConfig` when you’re ready.

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
- Enforce **multi-tenancy** in Loki/Tempo when you’re ready

