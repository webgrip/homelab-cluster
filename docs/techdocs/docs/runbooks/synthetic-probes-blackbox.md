# Runbook: Synthetic probes (blackbox)

Use this when Sloth-generated synthetic availability / latency alerts are firing (for example `SyntheticGrafanaAvailability`, `SyntheticPrometheusAvailability`, `SyntheticAlertmanagerAvailability`, or `SyntheticEndpointSlow`).

## What this usually means

- The blackbox exporter is failing to reach an ingress endpoint, or
- The network/gateway layer is unhealthy, or
- DNS inside the cluster is broken, or
- The target app is down / returning non-2xx.

## Fast triage

1) Confirm the network/gateway layer

- Pods:
  - `kubectl -n network get pods -o wide`
- Gateway + routes:
  - `kubectl -n network get gateway,httproute -o wide`
- Look for `Accepted: False` or missing addresses.

2) Confirm blackbox exporter health

- `kubectl -n observability get deploy,svc blackbox-exporter -o wide`
- `kubectl -n observability get pods -l app.kubernetes.io/name=blackbox-exporter -o wide`
- `kubectl -n observability logs deploy/blackbox-exporter --tail=200`

3) Confirm DNS from inside the cluster

- Start a disposable shell:
  - `kubectl -n default run -it --rm netshoot --image=nicolaka/netshoot -- sh`
- Then:
  - `nslookup grafana.${SECRET_DOMAIN}`
  - `nslookup prometheus.${SECRET_DOMAIN}`

4) Confirm HTTP from inside the cluster

From the same shell:

- `curl -vk https://grafana.${SECRET_DOMAIN}/login`
- If TLS fails, check cert-manager and Gateway.

## Common causes

- Gateway pods restarting / out of resources.
- DNS outages (CoreDNS crashloop, upstream resolver changes).
- App-level outage (Grafana/Prometheus down) misinterpreted as “probe failure”.

## Where it’s configured

- [kubernetes/apps/observability/blackbox-exporter](../../../kubernetes/apps/observability/blackbox-exporter)
