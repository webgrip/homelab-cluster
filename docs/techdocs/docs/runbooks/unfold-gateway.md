# Unfold gateway

The homelab stores and alerts on the Unfold cluster's metrics and logs. Unfold's vmagent and Vector send them over Unfold's Headscale tailnet to the `unfold-gateway` pod in `observability`, and Unfold's External Secrets reads the homelab OpenBao through the same pod. Unfold's KEDA reads the number of waiting `unfold-ci` jobs through it too. The full path, how the policy and the key are delivered by the Unfold `infra` apply, and the queries that prove it works are in unfold-cluster [`docs/observability.md`](https://forgejo.webgrip.dev/webgrip/unfold-cluster/src/branch/main/docs/observability.md).

## Pieces in this repository

| Object | Path | Role |
| --- | --- | --- |
| `unfold-gateway` Deployment | `kubernetes/apps/observability/unfold/app/gateway/` | Tailscale (userspace, `tag:homelab-gateway`) forwards tailnet port 8427 to vmauth in the same pod, port 8200 to `openbao.security`, port 9150 to `forgejo-runner-queue.forgejo`, and port 443 to `envoy-internal.network`, which only Unfold's Headscale server (`tag:headscale`) may open: it is how Headscale reaches Authentik for the tailnet's browser login, with TLS end to end against the real host name (unfold-cluster `docs/runbooks/headscale-browser-login.md`). vmauth accepts `/api/v1/write`, `/insert/jsonline` and `/audit/insert/jsonline` only, and stamps `cluster=unfold` on every log line. |
| `forgejo-runner-queue` Deployment | `kubernetes/apps/forgejo/runner-queue/` | Tailnet port 9150 of the gateway forwards here. `GET /waiting-jobs/unfold-ci` answers `{"label":"unfold-ci","waiting":N}`: the `webgrip` jobs in status `waiting` whose `runs-on` is `unfold-ci`, read per request from Forgejo's `/api/v1/admin/actions/runners/jobs` with the homelab KEDA scaler's existing token (`forgejo-runner-scaler-token`). Any other label is a 404, any other method a 501, and an unreadable queue a 502, never a zero. The token stays in the homelab; Unfold holds no Forgejo token for scaling. `scripts/test-runner-queue.sh` tests it with mutations. |
| `unfold-gateway-tailnet-key` ExternalSecret | same | The single-use Headscale pre-auth key that the Unfold `infra` apply mints and writes to OpenBao `secret/unfold/tailnet-homelab-gateway`, key `authkey`. Needed for the first login only; the node identity lives in the `unfold-gateway-tailscale-state` Secret afterwards. |
| `unfold-gateway-address` CronJob | `kubernetes/apps/observability/unfold/app/address/` | Publishes the gateway's tailnet IPv4 address as `unfold-gateway.<domain>` through a DNSEndpoint, every 5 minutes. |
| `vmsingle-unfold`, `vmalert-unfold`, VMRule `unfold-cluster` | `kubernetes/apps/observability/unfold/app/` | Unfold's metrics, kept apart from the homelab's, and the alerts on them. The main vmalert skips rules with a `rules` label. `scripts/vmalert-tests/unfold-cluster.test.yaml` tests the no-data alert. |
| `vmalert-unfold-runtime`, VMRule `unfold-runtime` | `kubernetes/apps/observability/unfold/app/` | Unfold's runtime detections: LogsQL rules over the Tetragon events Unfold's Vector ships (`source=tetragon`), evaluated against `vlsingle-victorialogs` because `vmalert-unfold` reads only VictoriaMetrics. Alert state goes to `vmsingle-unfold`. Every rule carries `stage: observe` and `severity: warning` until the unfold-cluster enforcement plan raises it (unfold-cluster `docs/runbooks/runtime-security.md`). `scripts/test-vlogs-rules.sh --mutation-test` runs each case in `scripts/vlogs-rule-tests/unfold-runtime.test.yaml` through a real VictoriaLogs and vmalert. The Tetragon DaemonSet's health (`UnfoldTetragonNotOnEveryNode`, `UnfoldTetragonGone`) is PromQL and lives in VMRule `unfold-cluster`. |
| Grafana | `grafana/app/dashboards/unfold-cluster.yaml`, `datasources/unfold-prometheus.yaml`, `folders/unfold.yaml` | The **Unfold cluster** folder and dashboard, datasource uid `unfold-prometheus`. |

Logs go to the existing `vlsingle-victorialogs` (field `cluster=unfold`) and audit events to `vlsingle-victorialogs-audit`.

## When `UnfoldMetricsAbsent` fires

It fires only after Unfold has sent data in the last 7 days, so a gateway that never came up stays quiet; check the pod then too.

1. `kubectl -n observability get pods -l app.kubernetes.io/name=unfold-gateway`. A `CreateContainerConfigError` means the key Secret is missing: OpenBao has no `unfold/tailnet-homelab-gateway` yet, so the Unfold `infra` apply has not run since the gateway was added.
2. `kubectl -n observability logs deploy/unfold-gateway -c tailscale --tail=50`: a login loop means the key expired unused or Headscale was rebuilt. Raise `homelab_gateway_key_generation` in unfold-cluster and apply. After a Headscale rebuild nothing is needed: the apply that made the new server wrote a new key, the ExternalSecret picks it up within 5 minutes, Reloader restarts the pod, and the old identity being refused makes the container log in with the new key (`TS_AUTH_ONCE`).
3. `kubectl -n observability get dnsendpoint unfold-gateway -o yaml` must hold a `100.64.0.0/10` address, and the CronJob's last Job must have succeeded.
4. `kubectl -n observability logs deploy/unfold-gateway -c vmauth` shows refused paths and backend errors.
5. Nothing wrong here: look at Unfold. `vmagent_remotewrite_pending_data_bytes` grows there while the path is broken, and the data arrives once it is fixed.

## Reading Unfold's own stack from the homelab

Unfold now runs its own VictoriaMetrics, VictoriaLogs, vmalert, Alertmanager and Grafana (unfold-cluster `docs/observability.md`). The homelab reads them through the same gateway, the other way round:

| Object | Path | Role |
| --- | --- | --- |
| `unfold-query` container and Service | `kubernetes/apps/observability/unfold/app/gateway/`, `query/` | vmauth on `:8481` (`unfold-query.yaml`) sends every request to `https://query.ops.unfoldhq.dev`, Unfold's ops Gateway, with the bearer token from `unfold-query-token` added, through the tailscale container's outbound HTTP proxy (`127.0.0.1:1055`, `TS_OUTBOUND_HTTP_PROXY_LISTEN`). Tailscale resolves the name from Headscale's DNS records itself (so `--accept-dns=false` does not matter) and reaches the API address `10.64.0.10` through the control planes' subnet route (`--accept-routes`). The tailnet policy lets `tag:homelab-gateway` open only `10.64.0.10:443`; the Gateway routes that name to Unfold's `vmauth-query`, which answers read paths only. TLS is checked against the real name. |
| CiliumNetworkPolicy `unfold-gateway-ingress` | `query/networkpolicy.yaml` | Only the homelab Grafana and the blackbox exporter reach `8481`; vmagent keeps its scrape of `8427` and `9002`. |
| `unfold-query-token` ExternalSecret and PushSecret | `query/` | A generated bearer token, pushed to OpenBao `secret/unfold-main/observability/query-token` (`token`), where Unfold's External Secrets reads it for `vmauth-query`. Both sides hold the same value and nobody types it. |
| GrafanaDatasources `unfold-metrics`, `unfold-logs` | `grafana/app/datasources/` | Read-only: Unfold's VictoriaMetrics and its logs store (14 days), with the token as an `Authorization` header. vmauth-query on Unfold passes only query paths. Unfold's audit log is deliberately not here: every homelab Grafana Editor can query every data source (see [the audit trail](kubernetes-audit-trail.md)), so the audit trail stays in Unfold's own Grafana, which only `unfold-viewers` and `unfold-admins` open. |
| Probe `blackbox-unfold-watchdog`, PrometheusRule `blackbox-unfold-watchdog` | `blackbox-exporter/app/` | The homelab half of the dead-man's switch: every minute the blackbox exporter asks Unfold's VictoriaMetrics for its always-firing `Watchdog` alert. `UnfoldAlertingSilent` (critical) fires after 15 minutes without it, but only once the probe has succeeded in the last 7 days, so it stays quiet until Unfold's stack runs. The off-site uptime-kuma push monitor is the other half. |
| `unfold-alertmanager-ntfy` ExternalSecret and PushSecret | `kubernetes/apps/observability/unfold/app/notifications/` | Copies the homelab Alertmanager's write-only ntfy token to OpenBao `secret/unfold-main/alertmanager/ntfy`, so Unfold's Alertmanager can publish to `alerts-critical` and `alerts-warning` on the public `ntfy.${SECRET_DOMAIN}` while the off-site ntfy does not exist. It is the interim route and still depends on the homelab being up. |
| Authentik application `unfold-grafana` | `kubernetes/apps/security/access-plane/`, `kubernetes/apps/authentik/app/unfold-grafana-oidc-client.*` | Login to Unfold's Grafana for `unfold-viewers` and `unfold-admins`; the client secret is generated here and pushed to both `secret/authentik/unfold-grafana-oidc` and `secret/unfold-main/grafana/oidc`. |

During the move Unfold also keeps writing to `vmsingle-unfold` and the homelab VictoriaLogs, so vmauth here accepts the Loki push paths `/insert/loki/api/v1/push` and `/audit/insert/loki/api/v1/push` next to the old ones. The homelab copy, its rules and the 8427 ingest go away once Unfold's own stack has proven itself.

### When `UnfoldAlertingSilent` fires

1. Explore **VictoriaMetrics (Unfold)**: `ALERTS{alertname="Watchdog"}`. An error means the read path; an empty result means Unfold's alerting itself.
2. `kubectl -n observability logs deploy/unfold-gateway -c unfold-query --tail=20` shows a refused proxy CONNECT (tailnet policy or the Unfold node is down); `-c tailscale` shows the proxy's own errors.
3. A 401 in the blackbox debug output means the token differs: the PushSecret has not written it, or Unfold's ExternalSecret has not refreshed.
4. On Unfold: `kubectl -n observability get pods`; vmalert-metrics, alertmanager and vmsingle must be Running.

## The Headscale name

`headscale.${SECRET_DOMAIN}`, the Unfold tailnet's coordination server, is published by the CronJob `network/unfold-headscale-address` (every 2 minutes) from OpenBao `secret/unfold/headscale-address`, which the Unfold `infra` apply writes (`ipv4`). A rebuild into a new Hetzner project, whose primary IP differs, therefore needs no commit here. The same secret's `drill_ipv4` publishes `headscale-drill.${SECRET_DOMAIN}` while the Unfold rebuild drill runs and is cleared by its teardown. A missing or invalid `ipv4` keeps the published record; the job never removes the production name. Check: `kubectl -n network logs job/<newest unfold-headscale-address job>` says `unchanged` or `published`, and `kubectl -n network get dnsendpoint unfold-headscale -o yaml` lists the address.
