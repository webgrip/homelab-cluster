# VictoriaMetrics replaces kube-prometheus-stack as the metrics backend

* Status: accepted
* Date: 2026-07-02

## Context and Problem Statement

The metrics backend was `kube-prometheus-stack` (Prometheus + Alertmanager + prometheus-operator +
kube-state-metrics + node-exporter). Mimir + its embedded Kafka (the intended long-term store) were
**already disabled** in-repo, so effective retention was just Prometheus's 15d local TSDB.
VictoriaMetrics is materially lighter (RAM/disk/component footprint) than the Prometheus(+Mimir)
stack while staying Prometheus-API-compatible, which directly eases the cluster's recurring
RAM/Longhorn pressure.

## Considered Options

* A modular VictoriaMetrics stack (vm-operator + hand-written CRs)
* The `victoria-metrics-k8s-stack` umbrella chart

## Decision Outcome

Chosen option: "A modular VictoriaMetrics stack (vm-operator + hand-written CRs)", because
VictoriaMetrics is materially lighter (RAM/disk/component footprint) than the Prometheus(+Mimir)
stack while staying Prometheus-API-compatible, and the modular layout mirrors the repo's
`grafana-operator → grafana-CRs` house pattern.

Replace kube-prometheus-stack with a **modular VictoriaMetrics** stack, mirroring the repo's
`grafana-operator → grafana-CRs` house pattern (not the `victoria-metrics-k8s-stack` umbrella
chart):

* [`observability/vm-operator/`](../../../../kubernetes/apps/observability/vm-operator) — the
  operator HelmRelease. It **converts** the cluster's existing
  `ServiceMonitor`/`PodMonitor`/`Probe`/`PrometheusRule` CRs into VM CRDs, so those CRs (and their
  `release: kube-prometheus-stack` labels) stay untouched as no-ops.
* [`observability/victoria-metrics/`](../../../../kubernetes/apps/observability/victoria-metrics)
  — hand-written `VMSingle` (15d / 50Gi Longhorn, ingest+query at `:8429`), `VMAgent`
  (`selectAllByDefault: true`), `VMAlert`, `VMAlertmanager` (`:9093`), the control-plane scrape
  CRs, and the relocated rules/dashboards/HTTPRoutes.
* `observability/prometheus-operator-crds/` — keeps the `monitoring.coreos.com` CRDs alive (the VM
  operator converts those CRs but does not install their CRDs; needed for conversion **and** a
  from-scratch bootstrap).
* `observability/kube-state-metrics/` + `observability/node-exporter/` — standalone charts
  replacing the subcharts kube-prom bundled (unchanged behaviour).

Retention stays **15d / 50Gi** to match the outgoing Prometheus. Grafana datasources keep
`uid: prometheus` / `uid: alertmanager` and only repoint their URLs → VMSingle `:8429` /
VMAlertmanager `:9093`, so **no dashboard edits** were needed. Operational detail:
[runbooks/victoriametrics.md](../runbooks/victoriametrics.md).

### Positive Consequences

* **Lighter footprint / headroom.** VMSingle's actual usage runs well under the
  (Prometheus-mirrored) requests, giving room to right-size and better high-cardinality tolerance.
* **Fewer conceptual moving parts** for long-term storage (VMSingle is the store; no
  Thanos/Mimir/Kafka).

### Negative Consequences

* **Scrape coverage is now our responsibility.** Any new control-plane/infra target must get an
  explicit VM scrape CR; a wrong port name yields *zero* targets silently (see the CoreDNS
  `targetPort: 9153` gotcha in the runbook).
* **A first-install CRD race bit us** (see runbook): never enable the operator chart's own
  `serviceMonitor` — it creates a VMServiceScrape CR in the same release that installs that CRD.
* Source-of-truth is local Longhorn (not S3/object-store); no `vmbackup` configured (matches
  Prometheus, which had no backup). A backup target is a future option.

## Pros and Cons of the Options

### A modular VictoriaMetrics stack (vm-operator + hand-written CRs)

* Good, because it mirrors the repo's `grafana-operator → grafana-CRs` house pattern — the
  operator + explicit CRs are all Flux-managed manifests.
* Bad, because we hand-maintain the scrape-coverage layer — exactly where a silent gap can hide.

### The `victoria-metrics-k8s-stack` umbrella chart

Ships the control-plane scrapes and default rules for free and would have been a closer 1:1 swap.
Rejected at cutover for house-style fidelity (operator + explicit CRs), accepting that we
hand-maintain the scrape-coverage layer — exactly where a silent gap can hide.

**Re-evaluated 2026-07-02** (rendered `victoria-metrics-k8s-stack 0.85.9` with matching values,
diffed against the modular tree) — **stayed modular:**

* **Its default rules/dashboards are not GitOps.** `defaultRules` (and default dashboards when
  Grafana is external) are **not chart manifests** — a post-install/post-upgrade `sync-job`
  writes VMRule objects via the Kubernetes API at runtime (RBAC grants it `vmrules` write).
  Flux never sees, prunes, or diffs them; flux-local/CI can't validate them; under
  [ADR-0039](adr-0039-default-deny-network-policies.md) default-deny it's another
  silently-failable moving part. This nullifies the umbrella's main advantage for this repo.
* **Switching would be a third cutover.** All CRs take the chart fullname (e.g. `vmks`) → every
  generated Service changes (`vmsingle-vmsingle` → `vmsingle-vmks`) → re-repoint datasources,
  Tempo, alloy-gateway, k6, OpenCost, HTTPRoutes; the VMSingle PVC name changes (15d history
  lost or PVC surgery). The operator admission webhook is enabled by default (we deliberately
  run without), and the release carries the same same-release CRD+CR structure that caused the
  2026-07-01 outage.
* **Credit where due:** its control-plane scrapes are upstream-maintained and well-engineered
  (e.g. CoreDNS is scraped via a chart-owned Service with `targetPort: 9153` by number, immune
  to this cluster's `tcp-9153` port-name quirk).
* **What we actually lost with kube-prom was measured, not assumed:** the kubernetes-mixin
  default rule pack is gone, but zero repo dashboards/rules reference its recording rules
  (`node_namespace_pod_container:*`, `apiserver_request:availability30d` = 0 series, 0
  consumers). Follow-ups applied instead of switching: vendored a curated house-format rule set
  for the real gaps (Watchdog deadman — the VMAlertmanager `alertname="Watchdog"` → null route
  had lost its feeding alert — plus KubeNodeNotReady and KubeJobFailed), and dropped the
  now-orphaned `apiserver_request_sli_duration_seconds_bucket` from the apiserver scrape (its
  consumer — kube-prom's built-in SLO rules — no longer exists;
  `apiserver_request_duration_seconds_bucket` stays, the cluster-health dashboard uses it).

## Links

* 2026-07-01 — accepted; cutover landed (b9b187d2)
* 2026-07-02 — re-evaluated the `victoria-metrics-k8s-stack` umbrella against the running modular
  stack; stayed modular (5ec8e4fa — findings folded into Pros and Cons of the Options)
* Supersedes the kube-prometheus-stack metrics backend (no prior ADR)
