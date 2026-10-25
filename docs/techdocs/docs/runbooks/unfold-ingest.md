# Unfold ingest

The homelab stores and alerts on the Unfold cluster's metrics and logs. Unfold's vmagent and Vector send them over Unfold's Headscale tailnet to the `unfold-ingest` pod in `observability`. The full path, the owner's one-time setup and the queries that prove it works are in unfold-cluster [`docs/observability.md`](https://forgejo.webgrip.dev/webgrip/unfold-cluster/src/branch/main/docs/observability.md).

## Pieces in this repository

| Object | Path | Role |
| --- | --- | --- |
| `unfold-ingest` Deployment | `kubernetes/apps/observability/unfold/app/ingest/` | Tailscale (userspace, `tag:homelab-ingest`) forwards tailnet port 8427 to vmauth in the same pod. vmauth accepts `/api/v1/write`, `/insert/jsonline` and `/audit/insert/jsonline` only, and stamps `cluster=unfold` on every log line. |
| `unfold-ingest-tailnet-key` ExternalSecret | same | The single-use Headscale pre-auth key from OpenBao `secret/unfold/tailnet-homelab-ingest`, key `authkey`. Needed for the first login only; the node identity lives in the `unfold-ingest-tailscale-state` Secret afterwards. |
| `unfold-ingest-address` CronJob | `kubernetes/apps/observability/unfold/app/address/` | Publishes the ingest's tailnet IPv4 address as `unfold-ingest.<domain>` through a DNSEndpoint, every 5 minutes. |
| `vmsingle-unfold`, `vmalert-unfold`, VMRule `unfold-cluster` | `kubernetes/apps/observability/unfold/app/` | Unfold's metrics, kept apart from the homelab's, and the alerts on them. The main vmalert skips rules with a `rules` label. |
| Grafana | `grafana/app/dashboards/unfold-cluster.yaml`, `datasources/unfold-prometheus.yaml`, `folders/unfold.yaml` | The **Unfold cluster** folder and dashboard, datasource uid `unfold-prometheus`. |

Logs go to the existing `vlsingle-victorialogs` (field `cluster=unfold`) and audit events to `vlsingle-victorialogs-audit`.

## When `UnfoldMetricsAbsent` fires

1. `kubectl -n observability get pods -l app.kubernetes.io/name=unfold-ingest`. A `CreateContainerConfigError` means the key Secret is missing: OpenBao has no `unfold/tailnet-homelab-ingest`.
2. `kubectl -n observability logs deploy/unfold-ingest -c tailscale --tail=50`: a login loop means the key expired or was used; mint a new one (unfold-cluster `docs/observability.md`, steps 3 and 4) and delete the `unfold-ingest-tailscale-state` Secret so the node logs in again.
3. `kubectl -n observability get dnsendpoint unfold-ingest -o yaml` must hold a `100.64.0.0/10` address, and the CronJob's last Job must have succeeded.
4. `kubectl -n observability logs deploy/unfold-ingest -c vmauth` shows refused paths and backend errors.
5. Nothing wrong here: look at Unfold. `vmagent_remotewrite_pending_data_bytes` grows there while the path is broken, and the data arrives once it is fixed.
