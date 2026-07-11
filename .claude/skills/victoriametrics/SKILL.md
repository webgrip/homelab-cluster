---
name: victoriametrics
description: Author and operate the VictoriaMetrics metrics backend — vm-operator + VMSingle/VMAgent/VMAlert/VMAlertmanager CRs, the control-plane scrape CRs (VMServiceScrape/VMPodScrape/VMNodeScrape/VMStaticScrape), and the operator's ServiceMonitor/PrometheusRule conversion.
when_to_use: Use when adding/editing a VM CR or a scrape, choosing scrape coverage for a new target, debugging a failed vm-operator install or a missing scrape target, or repointing something at the metrics backend. NOT Grafana dashboards/datasource CRs (grafana-dashboard skill) nor incident triage (runbooks/victoriametrics.md).
---

# VictoriaMetrics — the metrics backend

Metrics backend = **modular VictoriaMetrics** (ADR-0034), grafana-operator-style: `observability/vm-operator/` (operator HR) + `observability/victoria-metrics/app/` (the CRs). Runbook for firefighting: `docs/techdocs/docs/runbooks/victoriametrics.md`. Logs backend (VLSingle, LogsQL, ingest) → the `victorialogs` skill — note VLSingle is apiVersion **v1**, unlike the v1beta1 CRs here.

## The one rule that took the cluster down

**Never enable the operator chart's own `serviceMonitor`** (`vm-operator/app/helmrelease.yaml` → `serviceMonitor.enabled: false`). It renders a `VMServiceScrape` CR in the *same* Helm release that installs the `VMServiceScrape` CRD → `helm install` fails `no matches for kind "VMServiceScrape"`. `vm-operator` is `wait:true` and everything `dependsOn` it, so this stalls the whole stack while Prometheus is already pruned → empty dashboards. **`helm template` / flux-local can't catch this** (they render, never apply). Applies to any operator chart that ships a CR of its own CRD.

## CR shapes (validated against datreeio CRDs-catalog by the write hook)

- **VMSingle** — `retentionPeriod: "15d"`; `spec.storage` is a bare PVC spec (`accessModes`/`resources`/`storageClassName` directly, **no** `volumeClaimTemplate`). **No `externalLabels`** here (that's VMAgent). Query+ingest `:8429`, service `vmsingle-vmsingle`.
- **VMAgent** — `selectAllByDefault: true` (scrape every converted + native scrape CR cluster-wide), `externalLabels`, `remoteWrite[].url → vmsingle-vmsingle...:8429/api/v1/write`. Single-replica on `pool=worker`: set `rollingUpdate: { maxSurge: 0, maxUnavailable: 1 }` or the rollout deadlocks (no room for a surge pod).
- **VMAlert** — `selectAllByDefault: true`, `datasource`/`remoteRead`/`remoteWrite` each `.url → vmsingle:8429`, `notifiers[].url → vmalertmanager:9093`. `remoteWrite` is required for recording rules to persist.
- **VMAlertmanager** — `configRawYaml: |` (port the routing verbatim; not defaulted), `spec.storage.volumeClaimTemplate` (StorageSpec, unlike VMSingle), `:9093`.
- Relabel keys are camelCase: `sourceLabels`, `targetLabel`, `metricRelabelConfigs`.

## Scrape coverage is OUR job (modular has no umbrella)

A `*Scrape` with a **wrong `port` name matches nothing and emits zero targets — no `down` series, fully silent.** Always verify the real container/service port. Exception: the operator **auto-creates** `VMServiceScrape`s for its own managed CRs (vmsingle, vmagent, vlsingle, …; `job` = service name) — don't author those. Coverage lives in `victoria-metrics/app/scrapes/`:

- **kubelet + cAdvisor** — two `VMNodeScrape` (https, `insecureSkipVerify`, bearer token); cAdvisor is the same target with `path: /metrics/cadvisor`.
- **kube-apiserver** — `VMServiceScrape` on the `kubernetes` service in `default` (port `https`); keep the metric-drop list.
- **CoreDNS** — `VMPodScrape` on `k8s-app=kube-dns` pods; **this cluster's port is named `tcp-9153`**, not `metrics`.
- **Talos etcd** — `VMStaticScrape`, `scheme: http`, `10.0.0.20/21/22:2381`, `jobName: talos-etcd` (rules key on `up{job="talos-etcd"}`).

## Conversion + CRDs

The operator converts existing `ServiceMonitor`/`PodMonitor`/`Probe`/`PrometheusRule` CRs → VM CRDs, so keep those as-is; the `release: kube-prometheus-stack` labels are harmless no-ops under `selectAllByDefault`. This needs the `monitoring.coreos.com` CRDs present → the standalone `prometheus-operator-crds` HelmRelease owns them (removing kube-prom drops them). `kubectl get vmrule -A | wc -l` should equal `kubectl get prometheusrule -A`.

## Repointing the backend

Consumers to grep for (endpoint string, not just `dependsOn`): the Grafana **HelmRelease `values.datasources`** (a duplicate of the datasource CRs), OpenCost `prometheus.internal.serviceName`, Tempo/alloy-gateway/k6 `remote_write`. Keep datasource `uid: prometheus`/`alertmanager`, change only the URL → dashboards need no edits.
