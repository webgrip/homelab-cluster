# Observability

Flux-managed, Grafana-centric observability platform in the `observability` namespace.

Current stack:

- **Metrics**: VictoriaMetrics (vm-operator + VMSingle/VMAgent/VMAlert/VMAlertmanager; [ADR-0034](../adr/adr-0034-victoriametrics-metrics-backend.md))
- **Logs**: VictoriaLogs (VLSingle via vm-operator; Loki read-only during the migration grace period)
- **Traces**: VictoriaTraces (VTSingle via vm-operator; replaced Tempo — [ADR-0042](../adr/adr-0042-victoriatraces-tracing-backend.md))
- **Collection / routing**: Grafana Alloy (node agent + OTLP gateway; the gateway also generates span metrics + service graphs)
- **Visualization**: Grafana via **grafana-operator** CRDs
- **Alerting**: VMAlert + VMAlertmanager + Grafana Alerting
- **Suspended**: Pyroscope (profiles), Beyla, k6 — see [Suspended components](#suspended-components)

All manifests live under `kubernetes/apps/observability/` (entry point:
`kubernetes/apps/observability/kustomization.yaml`).

## Ingress URLs (internal, via `envoy-internal`)

- `https://grafana.${SECRET_DOMAIN}`
- `https://prometheus.${SECRET_DOMAIN}` (VMSingle UI/query)
- `https://alertmanager.${SECRET_DOMAIN}` (VMAlertmanager)

---

## VictoriaMetrics (metrics backend)

Replaced kube-prometheus-stack on 2026-07-01 — see [ADR-0034](../adr/adr-0034-victoriametrics-metrics-backend.md) and the [VictoriaMetrics runbook](../runbooks/victoriametrics.md). Modular, operator-style:

- **`vm-operator`** HelmRelease — installs the VM CRDs and **converts** existing `ServiceMonitor`/`PodMonitor`/`Probe`/`PrometheusRule` CRs into VM CRDs, so app scrape/rule CRs are unchanged and the `release: kube-prometheus-stack` labels are harmless no-ops. (Its own `serviceMonitor` is intentionally disabled — enabling it races the VMServiceScrape CRD on first install; see the runbook.)
- **`prometheus-operator-crds`** HelmRelease — keeps the `monitoring.coreos.com` CRDs (needed for conversion + a from-scratch bootstrap).
- **`victoria-metrics/app/`** CRs:
  - **VMSingle** — TSDB + query + `remote_write` receiver, 15d / 50Gi Longhorn, at `vmsingle-vmsingle.observability.svc.cluster.local:8429` (`/api/v1/write`).
  - **VMAgent** — scrapes everything (`selectAllByDefault: true`), `remote_write` → VMSingle. Reproduces Prometheus's cluster-wide discovery; `externalLabels.cluster=homelab-cluster`.
  - **VMAlert** — evaluates the converted VMRules, notifies VMAlertmanager.
  - **VMAlertmanager** — `vmalertmanager-vmalertmanager.observability.svc.cluster.local:9093`.
  - **rules/** — the cluster's PrometheusRule set (`victoria-metrics/app/rules/prometheusrule-*.yaml`).
- **`kube-state-metrics`** + **`node-exporter`** — standalone charts (were kube-prom subcharts).

Control-plane scrape coverage (kubelet, cAdvisor, kube-apiserver, CoreDNS, Talos etcd) is explicit under `victoria-metrics/app/scrapes/` — Talos etcd on `10.0.0.20/21/22:2381` (HTTP, `job=talos-etcd`), CoreDNS metrics on the pod port named `tcp-9153`.

**Long-term storage:** VMSingle *is* the store (no Mimir/Thanos — Mimir and its embedded Kafka
were retired with this swap). Retention is 15d local; no object-store backup is configured (a
future option). There is no separate long-term `remote_write` target.

**Authoring scrapes:** emit a `ServiceMonitor`/`PodMonitor`/`Probe` (the operator converts it)
or a native `VMServiceScrape`/`VMPodScrape`/`VMNodeScrape`/`VMStaticScrape` — the
**`victoriametrics` skill** owns the how-to and target-selection guidance.

## Grafana

Grafana is managed by **grafana-operator** — instance, datasources, folders, dashboards, and
alert rules are all CRDs (no ConfigMap sidecar):

- Instance: `kubernetes/apps/observability/grafana/app/grafana-instance.yaml` (+ chart-managed image renderer)
- Datasources: `grafana/app/datasources/` — prometheus → VMSingle `:8429`, alertmanager → VMAlertmanager `:9093`, victorialogs → VLSingle `:9428`, victoriatraces (type `jaeger`) → VTSingle `:10428/select/jaeger`, loki (read-only history, grace period), plus pyroscope (no-data while suspended) and opencost/github/devex extras
- Folders / dashboards / alerting: `grafana/app/folders/`, `grafana/app/dashboards/`, `grafana/app/alerting/` — authoring recipe = **`grafana-dashboard` skill**
- Database: CNPG `grafana-db` in-namespace (dashboards/datasources are CRDs in Git; the DB holds sessions/prefs — Tier 4 in [backup tiers](database-backup-tiers.md))

Secrets are **ESO-managed** (no SOPS): `grafana-admin.externalsecret.yaml` (admin credentials),
`grafana-oauth.externalsecret.yaml` (Authentik OIDC client), `grafana-db-secret`,
`grafana-github-api`. Authentik login callback: `https://grafana.${SECRET_DOMAIN}/login/generic_oauth`;
wiring/troubleshooting → `authentik-oidc` skill + [Authentik OIDC login runbook](../runbooks/authentik-oidc-login.md)
(DNS resolution of `authentik.${SECRET_DOMAIN}` from the pod is the usual failure — [split-DNS runbook](../runbooks/dns-split-dns.md)).

## VictoriaLogs

- VLSingle CR: `kubernetes/apps/observability/victorialogs/app/vlsingle.yaml` (managed by vm-operator; apiVersion `operator.victoriametrics.com/v1`).
- Query + ingest endpoint `vlsingle-victorialogs.observability.svc:9428`; vmui at `https://victorialogs.${SECRET_DOMAIN}/select/vmui` (LAN-only).
- Retention 30d on a 20Gi Longhorn PVC (no object storage — Garage is off the logging path); safety valve `retention.maxDiskSpaceUsageBytes: 18GiB`.
- Ingest speaks the **Loki push protocol** (`/insert/loki/api/v1/push`), so shippers use plain `loki.write`; query language is **LogsQL** (not LogQL). Grafana datasource uid `victorialogs` (`victoriametrics-logs-datasource` plugin); agent access via **mcp-victorialogs** (`.mcp.json`).
- Alerts: `victorialogs/app/prometheusrule-victorialogs.yaml` (down / no-ingest / disk / http errors). Triage → [victorialogs runbook](../runbooks/victorialogs.md). Decision: [ADR-0041](../adr/adr-0041-victorialogs-logging-backend.md).
- **Loki (grace period, until ~2026-08-07)**: still deployed read-only (`kubernetes/apps/observability/loki/`) so the pre-migration 30d of history stays queryable via the `loki` datasource in Explore; receives no new writes. Removal commit deletes the app dir + datasource **and the `observability-s3` component (Loki is its last consumer — Tempo, the other one, is gone)**; PVC `storage-loki-0` and Garage buckets `loki-chunks`/`loki-ruler`/`loki-admin` are cleaned up out-of-repo (the stale `tempo` bucket can go in the same sweep).

## VictoriaTraces

- VTSingle CR: `kubernetes/apps/observability/victoriatraces/app/vtsingle.yaml` (managed by vm-operator; apiVersion `operator.victoriametrics.com/v1`, like VLSingle).
- Endpoint `vtsingle-victoriatraces.observability.svc:10428` — OTLP/HTTP ingest under `/insert/opentelemetry`, **Jaeger query API** under `/select/jaeger` (no TraceQL).
- Retention 14d (Tempo's 336h equivalent) on a 10Gi Longhorn PVC; safety valve `retention.maxDiskSpaceUsageBytes: 8GiB`. No object storage — Garage is off the tracing path.
- Grafana datasource uid `victoriatraces`, type **`jaeger`**; trace panels use Jaeger `search` queries. Trace-to-logs → `victorialogs`, trace-to-metrics → span metrics.
- **Span metrics / service graphs** no longer come from a backend metrics-generator: the **alloy-gateway** `otelcol.connector.spanmetrics` + `servicegraph` connectors produce them and remote_write to VMSingle. Names: `traces_spanmetrics_calls_total` (unchanged), `traces_spanmetrics_duration_seconds_bucket` (was `..._latency_bucket`), label `service_name` (was `service`); `traces_service_graph_*` unchanged. Dashboard: `traces-service-graphs`. Decision: [ADR-0042](../adr/adr-0042-victoriatraces-tracing-backend.md).

## Suspended components

| Component | State | Why + gate |
| --- | --- | --- |
| **Pyroscope** (profiles) | `suspend: true` in its ks.yaml | gate = owner-run etcd defrag, then flip per [ADR-0037](../adr/adr-0037-reenable-pyroscope-worker-pool.md) (re-enable on the worker pool) |
| **Beyla** (eBPF auto-instrumentation) | `suspend: true` | disabled temporarily for stability |
| **k6** (operator + canaries) | commented out 2026-06-19 | freed fringe resources; synthetic-check annotations on routes are no-ops until restored |

(Tempo was in this table from 2026-06-19 until 2026-07-11, when VictoriaTraces replaced it —
[ADR-0042](../adr/adr-0042-victoriatraces-tracing-backend.md).)

## Grafana Alloy

Two installations:

1. **alloy-agent** (DaemonSet) — collects pod logs from each node (`/var/log/pods/...`) and pushes to VictoriaLogs (Loki push protocol). No per-app log agents needed; stdout/stderr is collected automatically.
2. **alloy-gateway** (Deployment) — stable OTLP endpoint for applications:
   - OTLP gRPC `alloy-gateway.observability.svc.cluster.local:4317`, HTTP `:4318`
   - **Metrics** → `remote_write` to VMSingle (`:8429/api/v1/write`)
   - **Logs** → VictoriaLogs
   - **Traces** → VictoriaTraces (OTLP/HTTP, `vtsingle-victoriatraces:10428/insert/opentelemetry`); the same stream feeds the `spanmetrics`/`servicegraph` connectors → VMSingle
   - **Faro** browser telemetry receiver: `http://alloy-gateway.observability.svc.cluster.local:12347/api/faro/receiver`
   - Also routed at `https://otlp.${SECRET_DOMAIN}` for off-cluster clients.

Gotcha: Alloy server blocks take `listen_address` (host only) + `listen_port` — an address with a
port (`"0.0.0.0:12347"`) fails at runtime ("too many colons") while the pod stays Running/Ready.
The Faro receiver was silently dead this way until 2026-07-11. After any Alloy config change,
grep the new pod's logs for `level=error`; readiness alone proves nothing.

---

## Application instrumentation

For most apps:

1. **Logs**: write structured JSON to stdout/stderr (collected automatically; include `trace_id` when tracing).
2. **Metrics**: expose `/metrics` and add a `ServiceMonitor` (or native VM `*Scrape`) in the app namespace — see the **`victoriametrics` skill**. The operator discovers CRs cluster-wide; no special label is required.
3. **OTLP** (metrics/traces from SDKs): standard env vars against the Alloy gateway:

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

### Alerts (PrometheusRule → VMRule)

Alerting is driven by `PrometheusRule` objects (converted to VMRules by the operator), evaluated
by VMAlert, routed by VMAlertmanager. Cluster rules live in
`kubernetes/apps/observability/victoria-metrics/app/rules/`; app-local rules can sit in the app
namespace. Keep the `release: kube-prometheus-stack` label on PrometheusRules — it is a vestigial
lint/policy requirement (`require-prometheusrule-labels`), a no-op for the VM operator. Label and
annotation contract, severity rules, and the copy/paste template: [Alerting principles](alerting-principles.md).

## SLOs (Sloth)

Sloth generates recording + burn-rate rules from `PrometheusServiceLevel` CRs:

- Install: `kubernetes/apps/observability/sloth/app/`
- SLO CRs: `kubernetes/apps/observability/sloth/slos/` — `slo-app-availability`,
  `slo-garage-availability`, `slo-platform-etcd`, `slo-synthetic-availability`,
  `slo-synthetic-k6-canary` (dormant while k6 is suspended)
- Dashboards: `sloth-slo-high-level` / `sloth-slo-detail` (Grafana)

## Synthetic monitoring (blackbox)

Blackbox exporter + `Probe` CRs for ingress-level uptime checks
(`kubernetes/apps/observability/blackbox-exporter/app/`). Current probes:

- `https://grafana.${SECRET_DOMAIN}`
- `https://prometheus.${SECRET_DOMAIN}`
- `https://alertmanager.${SECRET_DOMAIN}`
- Garage S3 (`10.0.0.110:3900` — off-cluster; own PrometheusRule + SLO)

## Validation checklist

After Flux reconciles:

- Grafana reachable; prometheus (VMSingle), victorialogs, alertmanager datasources connect
- VMAgent targets healthy (`https://prometheus.${SECRET_DOMAIN}` → vmagent targets)
- Alloy agent writing logs to VictoriaLogs (`vl_rows_ingested_total` increasing); blackbox probes green
- VMAlert evaluating rules; test alert reaches VMAlertmanager
