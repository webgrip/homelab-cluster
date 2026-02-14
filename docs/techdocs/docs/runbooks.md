# Runbooks

This page is linked from alert annotations (`runbook_url`). It's optimized for quickly answering: “what do I do now?”

## Synthetic probes (blackbox)

Symptoms:

- Sloth-generated synthetic availability SLO burn alerts firing (e.g. `SyntheticGrafanaAvailability`, `SyntheticPrometheusAvailability`, `SyntheticAlertmanagerAvailability`).
- `SyntheticEndpointSlow` firing.

Checks:

- Confirm ingress/gateway is healthy:
  - `kubectl -n network get pods`
  - `kubectl -n network get gateway,httproute`
- Confirm DNS resolution inside cluster:
  - Run a debug pod and `nslookup grafana.${SECRET_DOMAIN}`
- Confirm blackbox exporter is up:
  - `kubectl -n observability get deploy,svc blackbox-exporter`

Where it's configured:

- [kubernetes/apps/observability/blackbox-exporter](../../kubernetes/apps/observability/blackbox-exporter)

## Flux

Symptoms:

- `FluxKustomizationNotReady` or `FluxHelmReleaseNotReady` firing.

Checks:

- `flux get kustomizations -A`
- `flux get helmreleases -A`
- `kubectl -n flux-system logs deploy/kustomize-controller --tail=200`
- `kubectl -n flux-system logs deploy/helm-controller --tail=200`

## Renovate

Symptoms:

- `RenovateOperatorDeploymentUnavailable`, `RenovateProjectRunFailed`, or `RenovateProjectDependencyIssues` firing.
- Renovate PRs stop showing up, or Dependency Dashboard indicates errors.

Runbook and configuration details live in [docs/techdocs/docs/renovate.md](renovate.md).

## Apps (baseline)

Symptoms:

- Deployments/StatefulSets unavailable, CrashLoopBackOff, PVC low free.

Checks:

- `kubectl get pods -A -o wide`
- `kubectl describe pod -n <ns> <pod>`
- `kubectl -n <ns> logs <pod> -c <container> --tail=200`
- PVC pressure: `kubectl -n <ns> get pvc` and check Longhorn UI for replicas/health.

## Observability stack

Symptoms:

- Pods not ready / restart storms / OOMKills in `observability`.

Checks:

- `kubectl -n observability get pods -o wide`
- `kubectl -n observability describe pod <pod>`
- Loki/Tempo/Mimir usually fail first on storage or object store connectivity.

## Prometheus remote_write

Symptoms:

- `PrometheusRemoteWriteBacklog` firing.
- Downstream symptoms can include missing long-term metrics (Grafana/Mimir queries look stale) or increasing `prometheus_remote_storage_*_dropped_total`.

What this means:

- Prometheus is unable to ship samples to the configured remote_write endpoint fast enough, so the queue is backing up.
- If the queue starts dropping samples, you're losing long-term metrics (in-cluster Prometheus may still look fine).

Fast checks (start here):

- Confirm which remote is impacted: the alert should include `remote_name`.
- Check if samples are failing/dropping:
  - `prometheus_remote_storage_samples_failed_total`
  - `prometheus_remote_storage_samples_dropped_total`
  - `prometheus_remote_storage_samples_pending`
- Check the remote write path from Prometheus:
  - `kubectl -n observability get pods -l app.kubernetes.io/name=prometheus`
  - `kubectl -n observability logs -l app.kubernetes.io/name=prometheus -c prometheus --tail=200 | egrep -i 'remote write|remote_storage|429|5..|timeout|context deadline|dns|no such host'`

Check Mimir ingestion (most common root cause here):

- Gateway health:
  - `kubectl -n observability get pods -l app.kubernetes.io/name=mimir-distributed -o wide`
  - `kubectl -n observability get pods | grep mimir-distributed-gateway`
- Look for overload signals:
  - HTTP 429s (rate limits / too many samples)
  - 5xx (gateway/backend unhealthy)
  - elevated request latency
- If Mimir is unhealthy, fix that first (it's downstream of Prometheus).

Network/DNS checks:

- From inside the cluster, validate DNS + connectivity to the gateway:
  - `kubectl -n observability run -it --rm netshoot --image=nicolaka/netshoot -- sh`
  - `nslookup mimir-distributed-gateway.observability.svc.cluster.local`
  - `curl -sS -o /dev/null -w '%{http_code}\n' http://mimir-distributed-gateway.observability.svc.cluster.local/ready`

Capacity / tuning checks:

- If Mimir is healthy but backlog persists:
  - Ensure Prometheus has enough CPU/memory (remote_write is CPU-heavy under load)
  - Consider tuning remote_write queue settings (shards/batch) in the kube-prometheus-stack HelmRelease.

Mitigations (prefer safe + reversible):

- Scale up/out Mimir gateway (and any overloaded ingesters) if it's the bottleneck.
- Temporarily reduce scrape load / cardinality regressions if the cluster just had a metrics explosion.
- Only as a last resort: disable remote_write briefly to stabilize Prometheus, but accept loss of long-term continuity.

## Platform: Cilium

Symptoms:

- `CiliumAgentDown` firing.

Checks:

- `kubectl -n kube-system get pods -l k8s-app=cilium -o wide`
- `kubectl -n kube-system logs ds/cilium --tail=200`
- Validate node networking + Cilium status in the Cilium UI/CLI if you use it.

## Platform: Longhorn

Symptoms:

- Longhorn volume degraded/fault, node not ready.

Checks:

- `kubectl -n longhorn-system get pods -o wide`
- Use Longhorn UI: look for replica rebuilds, failed disks, node pressure.
- Confirm storage connectivity and node health.

## Platform: Envoy Gateway

Symptoms:

- `EnvoyProxyDown` firing, ingress failures.

Checks:

- `kubectl -n network get pods -o wide`
- `kubectl -n network get svc envoy-internal envoy-external -o wide`
- `kubectl get httproute -A` and validate routes are Accepted.

## Platform: cert-manager

Symptoms:

- Certificates expiring soon or controller errors.

Checks:

- `kubectl -n cert-manager get pods`
- `kubectl get certificates,certificaterequests,orders,challenges -A`
- If using ACME DNS01, validate DNS provider creds and challenge records.

## Mimir Kafka

Symptoms:

- `MimirKafkaCrashLooping` or Kafka PVC usage alerts.

Checks:

- `kubectl -n observability get pods -l app.kubernetes.io/name=kafka -o wide`
- `kubectl -n observability logs -c kafka <pod> --previous --tail=200`
- Verify PVC usage and expand if needed (Longhorn usually supports online expansion).

### Shrink Kafka PVC (delete/recreate)

Kubernetes does **not** support shrinking an existing PVC. To go from (for example) 40Gi -> 10Gi you must delete the PVC and let it be recreated.

This is disruptive and will wipe the embedded Kafka data.

Workflow (GitOps-first):

- Update the HelmRelease values in Git so `values.kafka.persistence.size` is the new desired size.
- Temporarily suspend reconciliation so Flux/Helm does not race your manual deletes:
  - `flux suspend helmrelease mimir-distributed -n observability`
  - (kubectl alternative) `kubectl -n observability patch helmrelease mimir-distributed --type=merge -p '{"spec":{"suspend":true}}'`
- Delete Kafka and its claim:
  - `kubectl -n observability delete statefulset mimir-distributed-kafka --wait=true`
  - `kubectl -n observability delete pvc kafka-data-mimir-distributed-kafka-0`
- Resume and force a reconcile to recreate with the new size:
  - `flux resume helmrelease mimir-distributed -n observability`
  - `flux reconcile helmrelease mimir-distributed -n observability --with-source`
  - (kubectl alternative) `kubectl -n observability patch helmrelease mimir-distributed --type=merge -p '{"spec":{"suspend":false}}'`
  - (kubectl alternative) `kubectl -n observability annotate helmrelease mimir-distributed reconcile.fluxcd.io/requestedAt="$(date -Iseconds)" --overwrite`
- Verify:
  - `kubectl -n observability get pvc kafka-data-mimir-distributed-kafka-0 -o wide`
  - `kubectl -n observability get pods -l app.kubernetes.io/name=kafka -o wide`

## k6 canaries

Symptoms:

- k6 results look bad (errors/latency) in dashboards.

Checks:

- CronJob and recent Jobs:
  - `kubectl -n observability get cronjob k6-ingress-canary`
  - `kubectl -n observability get jobs --sort-by=.metadata.creationTimestamp | tail`
- Recent TestRuns:
  - `kubectl -n observability get testruns.k6.io --sort-by=.metadata.creationTimestamp | tail`

Where it's configured:

- [kubernetes/apps/observability/k6-canaries](../../kubernetes/apps/observability/k6-canaries)
