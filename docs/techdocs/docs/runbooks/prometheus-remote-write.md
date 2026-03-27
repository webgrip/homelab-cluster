# Runbook: Prometheus remote_write

Use this when `PrometheusRemoteWriteBacklog` is firing or long-term metrics look stale.

## What this means

- Prometheus can’t ship samples to the remote_write endpoint fast enough.
- If it starts dropping samples, you’re losing long-term metrics.

## Fast triage

1) Identify which remote is impacted

- The alert should include `remote_name`.

2) Check failure / drop metrics

- `prometheus_remote_storage_samples_failed_total`
- `prometheus_remote_storage_samples_dropped_total`
- `prometheus_remote_storage_samples_pending`

3) Check Prometheus logs for transport errors

- `kubectl -n observability get pods -l app.kubernetes.io/name=prometheus`
- `kubectl -n observability logs -l app.kubernetes.io/name=prometheus -c prometheus --tail=200 | egrep -i 'remote write|remote_storage|429|5..|timeout|context deadline|dns|no such host'`

4) Check Mimir ingestion path (common root cause)

- Mimir gateway pods:
  - `kubectl -n observability get pods -l app.kubernetes.io/name=mimir-distributed -o wide`
- Look for overload:
  - HTTP 429s / 5xx
  - elevated latency

5) DNS/network from inside the cluster

- `kubectl -n observability run -it --rm netshoot --image=nicolaka/netshoot -- sh`
- `nslookup mimir-distributed-gateway.observability.svc.cluster.local`
- `curl -sS -o /dev/null -w '%{http_code}\n' http://mimir-distributed-gateway.observability.svc.cluster.local/ready`

## Mitigations (safe + reversible)

- Scale up/out the Mimir gateway (and any overloaded ingesters) if it’s the bottleneck.
- Temporarily reduce scrape load / cardinality regressions.
- As a last resort: disable remote_write briefly to stabilize Prometheus (accepts loss of long-term continuity).
