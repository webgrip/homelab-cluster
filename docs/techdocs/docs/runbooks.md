# Runbooks

This page is linked from alert annotations (`runbook_url`). It’s optimized for quickly answering: “what do I do now?”

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

Where it’s configured:

- [kubernetes/apps/observability/blackbox-exporter](../../kubernetes/apps/observability/blackbox-exporter)

## Flux

Symptoms:

- `FluxKustomizationNotReady` or `FluxHelmReleaseNotReady` firing.

Checks:

- `flux get kustomizations -A`
- `flux get helmreleases -A`
- `kubectl -n flux-system logs deploy/kustomize-controller --tail=200`
- `kubectl -n flux-system logs deploy/helm-controller --tail=200`

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

## k6 canaries

Symptoms:

- k6 results look bad (errors/latency) in dashboards.

Checks:

- CronJob and recent Jobs:
  - `kubectl -n observability get cronjob k6-ingress-canary`
  - `kubectl -n observability get jobs --sort-by=.metadata.creationTimestamp | tail`
- Recent TestRuns:
  - `kubectl -n observability get testruns.k6.io --sort-by=.metadata.creationTimestamp | tail`

Where it’s configured:

- [kubernetes/apps/observability/k6-canaries](../../kubernetes/apps/observability/k6-canaries)
