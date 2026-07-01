# ADR-0038: VictoriaMetrics replaces kube-prometheus-stack as the metrics backend

- **Status:** Accepted (2026-07-01)
- **Supersedes:** the metrics half of the kube-prometheus-stack deployment
- **Related:** [runbooks/victoriametrics.md](../runbooks/victoriametrics.md), [general/observability.md](../general/observability.md), ADR-0028 (workload placement)

## Context

The metrics backend was `kube-prometheus-stack` (Prometheus + Alertmanager + prometheus-operator + kube-state-metrics + node-exporter). Mimir + its embedded Kafka (the intended long-term store) were **already disabled** in-repo, so effective retention was just Prometheus's 15d local TSDB. VictoriaMetrics is materially lighter (RAM/disk/component footprint) than the Prometheus(+Mimir) stack while staying Prometheus-API-compatible, which directly eases the cluster's recurring RAM/Longhorn pressure.

## Decision

Replace kube-prometheus-stack with a **modular VictoriaMetrics** stack, mirroring the repo's `grafana-operator → grafana-CRs` house pattern (not the `victoria-metrics-k8s-stack` umbrella chart):

- `observability/vm-operator/` — the operator HelmRelease. It **converts** the cluster's existing `ServiceMonitor`/`PodMonitor`/`Probe`/`PrometheusRule` CRs into VM CRDs, so those ~50 CRs (and their `release: kube-prometheus-stack` labels) stay untouched as no-ops.
- `observability/victoria-metrics/` — hand-written `VMSingle` (15d / 50Gi Longhorn, ingest+query at `:8429`), `VMAgent` (`selectAllByDefault: true`), `VMAlert`, `VMAlertmanager` (`:9093`), the control-plane scrape CRs, and the relocated rules/dashboards/HTTPRoutes.
- `observability/prometheus-operator-crds/` — keeps the `monitoring.coreos.com` CRDs alive (the VM operator converts those CRs but does not install their CRDs; needed for conversion **and** a from-scratch bootstrap).
- `observability/kube-state-metrics/` + `observability/node-exporter/` — standalone charts replacing the subcharts kube-prom bundled (unchanged behaviour).

Retention stays **15d / 50Gi** to match the outgoing Prometheus. Grafana datasources keep `uid: prometheus` / `uid: alertmanager` and only repoint their URLs → VMSingle `:8429` / VMAlertmanager `:9093`, so **no dashboard edits** were needed.

### Rejected: the `victoria-metrics-k8s-stack` umbrella chart

The umbrella ships the control-plane scrapes and default rules for free and would have been a closer 1:1 swap. We chose modular for house-style fidelity (operator + explicit CRs). The trade-off is that we hand-maintain the scrape-coverage layer (kubelet, cAdvisor, kube-apiserver, CoreDNS, Talos etcd) — which is exactly where a silent gap can hide (see the CoreDNS port gotcha in the runbook).

## Consequences

- **Lighter footprint / headroom.** VMSingle's actual usage runs well under the (Prometheus-mirrored) requests, giving room to right-size and better high-cardinality tolerance.
- **Fewer conceptual moving parts** for long-term storage (VMSingle is the store; no Thanos/Mimir/Kafka).
- **Scrape coverage is now our responsibility.** Any new control-plane/infra target must get an explicit VM scrape CR; a wrong port name yields *zero* targets silently.
- **A first-install CRD race bit us** (see runbook): never enable the operator chart's own `serviceMonitor` — it creates a VMServiceScrape CR in the same release that installs that CRD.
- Source-of-truth is local Longhorn (not S3/object-store); no `vmbackup` configured (matches Prometheus, which had no backup). A backup target is a future option.
