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

## Garage S3 (CNPG backup / WAL target) unavailable

Fires as `GarageDown` / `GarageProbeSlow` / `GarageS3Availability` when the blackbox probe to `http://10.0.0.110:3900` (endpoint `garage`) fails.

**Why this matters:** Garage S3 is the barman-cloud WAL-archive and backup target for **every** CloudNativePG database, and it runs **outside** this cluster (no app/namespace; not Flux-managed). When it is unreachable, WAL archiving fails cluster-wide, Postgres cannot recycle `pg_wal`, and database data volumes fill until they CrashLoop with `no free disk space for WALs` (heavy writers like `grafana-db` / `dependency-track-db` fill first). See also [[cnpg-garage-wal-spof]].

Triage:

1. Confirm reachability (403 = healthy — it's an unsigned S3 request):
   - From a pod: `curl -sS -o /dev/null -w '%{http_code}\n' http://10.0.0.110:3900/`
   - `connection refused` / timeout ⇒ Garage host or process is down, or a network/firewall issue.
2. Restore Garage on its host (`10.0.0.110:3900`) — this is the root fix and unblocks every database.
3. Confirm recovery from inside the cluster: a healthy DB's barman sidecar should log `Archived WAL file`:
   - `kubectl -n authentik logs authentik-db-1 -c plugin-barman-cloud --tail=20`
4. Check for fallout — any CNPG instance `1/2 CrashLoopBackOff` with `no free disk space for WALs`:
   - `kubectl get pods -A -l cnpg.io/podRole=instance`
   - A 100%-full volume won't start even after Garage returns; give it headroom by bumping `spec.storage.size` in `<app>/app/database/cluster.yaml`, then `flux reconcile kustomization <app>-db -n flux-system --with-source`.

## Where it’s configured

- [kubernetes/apps/observability/blackbox-exporter](../../../kubernetes/apps/observability/blackbox-exporter)
- SLO: [kubernetes/apps/observability/sloth/slos/slo-garage-availability.yaml](../../../kubernetes/apps/observability/sloth/slos/slo-garage-availability.yaml)
