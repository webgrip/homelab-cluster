# Runbook: Synthetic probes (blackbox)

Use this when Sloth-generated synthetic availability / latency alerts are firing (for example `SyntheticGrafanaAvailability`, `SyntheticPrometheusAvailability`, `SyntheticAlertmanagerAvailability`, or `SyntheticEndpointSlow`).

> The `prometheus.*`/`alertmanager.*` probe targets now land on the VictoriaMetrics services (`vmsingle-vmsingle` / `vmalertmanager-vmalertmanager`) behind the same hostnames — see [victoriametrics](victoriametrics.md).

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

## Route probes

Fires as `SyntheticRouteDown` (warning, 10m) or `SyntheticOidcGateOpen` (critical, 5m). One
`Probe` per route, named `blackbox-<endpoint>`; the route's
`monitoring.webgrip.io/synthetic-check` annotation names it.

1. Reproduce the probe with its own module (read-only):
   - `kubectl -n observability get probe blackbox-<endpoint> -o jsonpath='{.spec.module}{" "}{.spec.targets.staticConfig.static}'`
   - `kubectl -n observability exec deploy/blackbox-exporter -- wget -qO- 'http://127.0.0.1:9115/probe?debug=true&module=<module>&target=<target>'`
   - The debug log shows the status code, the `Location` header and which regexp failed.
2. Read the status code:
   - `503` → envoy has no ready backend: check the app's pods and events.
   - `404` from a route that normally answers `200` → the HTTPRoute is gone or no longer attached;
     `kubectl get httproute -A` and its `status.parents` conditions.
   - `200` with `probe_failed_due_to_regex 1` → the health endpoint answers but reports a failed
     dependency (database, cache), or the path now falls through to a SPA.
   - Gate probes: `2xx` = the OIDC `SecurityPolicy` no longer applies (the route is open to anyone);
     `500` = the policy exists but its client Secret is missing (envoy fails closed).
3. Every route probe failing at once → the envoy gateway itself; start with `kubectl -n network get pods`.

Adding a probe for a new route: a module in `helmrelease.yaml` (`Host` header,
`insecure_skip_verify`, `follow_redirects: false`, exact `valid_status_codes`, a body regexp), a
`probe-<endpoint>.yaml` with labels `endpoint` + `synthetic: route` (+ `gate: oidc` for
OIDC-gated routes), the file in `kustomization.yaml`, and the Probe name as the route's
annotation value.

## Garage S3 (CNPG backup / WAL target) unavailable

Fires as `GarageDown` / `GarageProbeSlow` / `GarageS3Availability` when the blackbox probe to `https://s3-offsite.webgrip.dev` (endpoint `garage-offsite`) fails.

**Why this matters:** Garage S3 is the barman-cloud WAL-archive and backup target for **every** CloudNativePG database, and it runs **off-site** on a Hetzner box in Falkenstein (`garage-fsn1`; no app/namespace, not Flux-managed). Since 2026-08-02 it is reached over the public internet through Caddy on 443 — so a failure can be the host, the Garage process, TLS/cert renewal, DNS, or your own uplink, not simply "the box is down". When it is unreachable, WAL archiving fails cluster-wide, Postgres cannot recycle `pg_wal`, and database data volumes fill until they CrashLoop with `no free disk space for WALs` (heavy writers like `grafana-db` / `dependency-track-db` fill first). The backup/WAL wiring behind this single point of failure is documented in the [CNPG backups runbook](cnpg-backups.md).

Triage:

1. Confirm reachability (403 = healthy — it's an unsigned S3 request):
   - From a pod: `curl -sS -o /dev/null -w '%{http_code}\n' https://s3-offsite.webgrip.dev/`
   - `connection refused` / timeout ⇒ host, Caddy, or the network path is down.
   - TLS error ⇒ the Let's Encrypt certificate failed to renew; check `journalctl -u caddy` on the box.
   - NXDOMAIN **from a pod only** ⇒ CoreDNS lost its longest-match zone for this name. k8s-gateway is authoritative for the domain and NXDOMAINs anything it does not itself host, so off-cluster names need an explicit zone (`kubernetes/apps/kube-system/coredns`) plus k8s-gateway `fallthrough`.
2. Recover the off-site host: `ssh root@116.202.53.185`, then `systemctl status garage caddy`. Garage binds to 127.0.0.1 only and Caddy on 443 is the sole public path, so check both. This is the root fix and unblocks every database.
3. Confirm recovery from inside the cluster: a healthy DB's barman sidecar should log `Archived WAL file`:
   - `kubectl -n authentik logs authentik-db-1 -c plugin-barman-cloud --tail=20`
4. Check for fallout — any CNPG instance `1/2 CrashLoopBackOff` with `no free disk space for WALs`:
   - `kubectl get pods -A -l cnpg.io/podRole=instance`
   - A 100%-full volume won't start even after Garage returns; give it headroom by bumping `spec.storage.size` in `<app>/app/database/cluster.yaml`, then `flux reconcile kustomization <app>-db -n flux-system --with-source` (human step — hook-blocked for agents; Flux also picks it up on the next git poll).

## Where it’s configured

- [kubernetes/apps/observability/blackbox-exporter](../../../../kubernetes/apps/observability/blackbox-exporter)
- SLO: [kubernetes/apps/observability/sloth/slos/slo-garage-availability.yaml](../../../../kubernetes/apps/observability/sloth/slos/slo-garage-availability.yaml)
