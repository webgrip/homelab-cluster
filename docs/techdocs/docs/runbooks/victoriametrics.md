# Runbook: VictoriaMetrics (metrics backend)

Use this when Grafana dashboards are empty/no-data, the `vm-operator` HelmRelease is failing, a scrape target is missing, or you're verifying the metrics backend after a change. Design + rationale: [ADR-0038](../adr/adr-0038-victoriametrics-metrics-backend.md). Authoring guardrails: the `victoriametrics` skill.

## Facts (ports, names)

- **VMSingle** — query + `remote_write` ingest at `:8429` (`/api/v1/write`). Service `vmsingle-vmsingle.observability.svc.cluster.local:8429`.
- **VMAlertmanager** — `:9093`. Service `vmalertmanager-vmalertmanager.observability.svc.cluster.local:9093`.
- Grafana datasources keep `uid: prometheus` / `uid: alertmanager`; only their URLs point at the above.
- Per-app Flux `Kustomization`s live in **their own namespaces**, not `flux-system` — use `kubectl get kustomization -A` (only the bootstrap set is in flux-system).

## Fast triage — dashboards empty / no data

```sh
# 1. Is the whole VM stack up? (operator + the 4 CRs' pods)
kubectl get hr -n observability -o custom-columns=NAME:.metadata.name,READY:'.status.conditions[?(@.type=="Ready")].status'
kubectl get pods -n observability | grep -E 'vm-operator|vmsingle|vmagent|vmalert|vmalertmanager'

# 2. Anything blocked in the dependency chain?
kubectl get kustomization -A | awk '$4!="True"'

# 3. Is data actually landing? (via the Grafana Prometheus datasource → VMSingle)
#    grafana MCP: query_prometheus datasourceUid=prometheus expr='count(up)'  and  'count(up == 0)'
```

`count(up)` should be triple digits and `count(up == 0)` empty. `count by (job)(up)` must include `kubelet`, `cadvisor`, `kubernetes` (apiserver), `talos-etcd`, `coredns`, `kube-state-metrics`, `prometheus-node-exporter` plus every app job.

## Namespace triage (pods not ready / restart storms / OOMKills in `observability`)

```sh
kubectl -n observability get pods -o wide
kubectl -n observability get deploy,sts -o wide
kubectl -n observability describe pod <pod>
kubectl -n observability logs <pod> -c <container> --tail=200            # add --previous if restarting
```

Common failure modes for Loki/Tempo/VM components: PVC full or degraded volumes
(`kubectl -n observability get pvc`, then the `longhorn` skill /
[longhorn-rebuild-wedge](longhorn-rebuild-wedge.md)), object-store connectivity/creds, DNS.
Fix the first failing dependency in that order: DNS → storage → network → app.

## Known failure modes

### vm-operator HelmRelease install fails: `no matches for kind "VMServiceScrape"`

**Root cause (took all dashboards down on the 2026-07-01 cutover):** the `victoria-metrics-operator` chart's `serviceMonitor.enabled: true` renders a **VMServiceScrape CR in the same Helm release that installs the VMServiceScrape CRD** — Helm applies the CR before the API server registers the CRD → install fails. Because `vm-operator` ks is `wait: true` and `victoria-metrics dependsOn vm-operator`, the *entire* VM stack never applies (no `vmsingle` service) while Flux has already pruned the old Prometheus → zero backend → every panel empty. It also blocks all ~17 apps that `dependsOn victoria-metrics`.

**Fix:** `serviceMonitor.enabled: false` in `vm-operator/app/helmrelease.yaml`. The operator still self-scrapes the VM components at runtime. Push the fix; Flux re-runs the failed install on the next 1m git poll (generation bumped) — no manual reconcile needed (imperative `flux reconcile` is blocked here). `helm template` does **not** catch this (renders but never applies).

### A scrape target is missing (e.g. no `coredns` job)

A VM `*Scrape` with a wrong `port` name matches nothing and produces **zero targets — not even a `down` series**, so it's silent. This cluster's CoreDNS names its metrics port `tcp-9153` (not the upstream `metrics`). Verify the real port and fix the scrape:

```sh
kubectl get pod -n kube-system -l k8s-app=kube-dns -o jsonpath='{.items[0].spec.containers[0].ports}'
# then set podMetricsEndpoints[].port to the real name
```

After editing a scrape CR, the operator regenerates VMAgent's config and the sidecar hot-reloads (no pod restart); allow ~1 scrape interval (60s) before the target appears.

### vmagent pod stuck `Pending` after a rollout

VMAgent is `replicaCount: 1` pinned to `pool=worker`; if the eligible nodes have no request headroom for a *second* pod, the default rollout (`maxSurge:1/maxUnavailable:0`) deadlocks — new pod `Pending`, old can't be removed. Scheduling is on **requests**, so `kubectl top` can look fine. Fix in `vmagent.yaml`: `rollingUpdate: { maxSurge: 0, maxUnavailable: 1 }` (terminate-then-recreate; a brief scrape gap is fine for a scraper).

## remote_write health

Tempo metrics-generator, alloy-gateway, and k6 push to VMSingle `:8429/api/v1/write`. VMAgent forwards scrapes there too. Check flow with `vmagent_remotewrite_requests_total` (climbing) and `vm_rows_inserted_total` on VMSingle. There is no Prometheus `remote_storage_*` alert anymore — those were removed with the swap.

## Verify after a change

`count(up)` / `count(up == 0)`; `count by (job)(up)` for scrape parity; `kubectl get vmrule -A | wc -l` should equal `kubectl get prometheusrule -A | wc -l` (operator converts 1:1, VMAlert evaluates them); all `kustomization`/`hr` Ready.
