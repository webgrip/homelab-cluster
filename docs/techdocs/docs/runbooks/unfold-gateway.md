# Unfold gateway

The homelab stores and alerts on the Unfold cluster's metrics and logs. Unfold's vmagent and Vector send them over Unfold's Headscale tailnet to the `unfold-gateway` pod in `observability`, and Unfold's External Secrets reads the homelab OpenBao through the same pod. Unfold's KEDA reads the number of waiting `unfold-ci` jobs through it too. The full path, how the policy and the key are delivered by the Unfold `infra` apply, and the queries that prove it works are in unfold-cluster [`docs/observability.md`](https://forgejo.webgrip.dev/webgrip/unfold-cluster/src/branch/main/docs/observability.md).

## Pieces in this repository

| Object | Path | Role |
| --- | --- | --- |
| `unfold-gateway` Deployment | `kubernetes/apps/observability/unfold/app/gateway/` | Tailscale (userspace, `tag:homelab-gateway`) forwards tailnet port 8427 to vmauth in the same pod, port 8200 to `openbao.security` and port 9150 to `forgejo-runner-queue.forgejo`. vmauth accepts `/api/v1/write`, `/insert/jsonline` and `/audit/insert/jsonline` only, and stamps `cluster=unfold` on every log line. |
| `forgejo-runner-queue` Deployment | `kubernetes/apps/forgejo/runner-queue/` | Tailnet port 9150 of the gateway forwards here. `GET /waiting-jobs/unfold-ci` answers `{"label":"unfold-ci","waiting":N}`: the `webgrip` jobs in status `waiting` whose `runs-on` is `unfold-ci`, read per request from Forgejo's `/api/v1/admin/actions/runners/jobs` with the homelab KEDA scaler's existing token (`forgejo-runner-scaler-token`). Any other label is a 404, any other method a 501, and an unreadable queue a 502, never a zero. The token stays in the homelab; Unfold holds no Forgejo token for scaling. `scripts/test-runner-queue.sh` tests it with mutations. |
| `unfold-gateway-tailnet-key` ExternalSecret | same | The single-use Headscale pre-auth key that the Unfold `infra` apply mints and writes to OpenBao `secret/unfold/tailnet-homelab-gateway`, key `authkey`. Needed for the first login only; the node identity lives in the `unfold-gateway-tailscale-state` Secret afterwards. |
| `unfold-gateway-address` CronJob | `kubernetes/apps/observability/unfold/app/address/` | Publishes the gateway's tailnet IPv4 address as `unfold-gateway.<domain>` through a DNSEndpoint, every 5 minutes. |
| `vmsingle-unfold`, `vmalert-unfold`, VMRule `unfold-cluster` | `kubernetes/apps/observability/unfold/app/` | Unfold's metrics, kept apart from the homelab's, and the alerts on them. The main vmalert skips rules with a `rules` label. `scripts/vmalert-tests/unfold-cluster.test.yaml` tests the no-data alert. |
| Grafana | `grafana/app/dashboards/unfold-cluster.yaml`, `datasources/unfold-prometheus.yaml`, `folders/unfold.yaml` | The **Unfold cluster** folder and dashboard, datasource uid `unfold-prometheus`. |

Logs go to the existing `vlsingle-victorialogs` (field `cluster=unfold`) and audit events to `vlsingle-victorialogs-audit`.

## When `UnfoldMetricsAbsent` fires

It fires only after Unfold has sent data in the last 7 days, so a gateway that never came up stays quiet; check the pod then too.

1. `kubectl -n observability get pods -l app.kubernetes.io/name=unfold-gateway`. A `CreateContainerConfigError` means the key Secret is missing: OpenBao has no `unfold/tailnet-homelab-gateway` yet, so the Unfold `infra` apply has not run since the gateway was added.
2. `kubectl -n observability logs deploy/unfold-gateway -c tailscale --tail=50`: a login loop means the key expired unused or Headscale was rebuilt. Raise `homelab_gateway_key_generation` in unfold-cluster and apply. After a Headscale rebuild nothing is needed: the apply that made the new server wrote a new key, the ExternalSecret picks it up within 5 minutes, Reloader restarts the pod, and the old identity being refused makes the container log in with the new key (`TS_AUTH_ONCE`).
3. `kubectl -n observability get dnsendpoint unfold-gateway -o yaml` must hold a `100.64.0.0/10` address, and the CronJob's last Job must have succeeded.
4. `kubectl -n observability logs deploy/unfold-gateway -c vmauth` shows refused paths and backend errors.
5. Nothing wrong here: look at Unfold. `vmagent_remotewrite_pending_data_bytes` grows there while the path is broken, and the data arrives once it is fixed.

## The Headscale name

`headscale.${SECRET_DOMAIN}`, the Unfold tailnet's coordination server, is published by the CronJob `network/unfold-headscale-address` (every 2 minutes) from OpenBao `secret/unfold/headscale-address`, which the Unfold `infra` apply writes (`ipv4`). A rebuild into a new Hetzner project, whose primary IP differs, therefore needs no commit here. The same secret's `drill_ipv4` publishes `headscale-drill.${SECRET_DOMAIN}` while the Unfold rebuild drill runs and is cleared by its teardown. A missing or invalid `ipv4` keeps the published record; the job never removes the production name. Check: `kubectl -n network logs job/<newest unfold-headscale-address job>` says `unchanged` or `published`, and `kubectl -n network get dnsendpoint unfold-headscale -o yaml` lists the address.
