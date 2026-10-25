# Hetzner Cloud costs (Unfold project)

The Unfold production cluster (`unfold-cluster`) runs in the Hetzner Cloud project **Unfold**
(project id 16441010): three `cx23` control planes, the `cx33` worker `unfold-app-1`, the `cx23`
`unfold-headscale`, one primary IPv4 per server and a Talos snapshot. The homelab watches what that
costs. Hetzner has no billing or usage API, so `hcloud-cost-exporter` reads the inventory and the
list prices from the Cloud API and recomputes the bill the way Hetzner does. The invoice carries
0% VAT (EU reverse charge), so every figure here is net EUR.

| Piece | Where |
| --- | --- |
| Exporter (Deployment, Service, VMServiceScrape, egress policy) | `kubernetes/apps/observability/hcloud-cost-exporter/` |
| Exporter code and its tests | `app/hcloud_cost_exporter.py`, `scripts/test_hcloud_cost_exporter.py`, `scripts/test-hcloud-cost-exporter.sh` (mutations, run in CI `e2e`) |
| Alerts and their tests | `victoria-metrics/app/rules/prometheusrule-platform-hetzner-costs.yaml`, `scripts/vmalert-tests/platform-hetzner-costs.test.yaml` |
| Dashboard | Grafana, folder Executive, **Unfold cloud costs** (`/d/unfold-cloud-costs`) |
| Token | OpenBao `secret/hetzner/unfold-readonly`, key `HCLOUD_TOKEN` (level 1, provided) → `ExternalSecret/hcloud-unfold-readonly` |

## Billing model the exporter reproduces

- A resource is billed for every **started hour** at its hourly price, and never more than its
  **monthly price** in one calendar month. A server created at 08:00 and read at 12:30 has 5
  billable hours.
- The month runs on UTC. A resource that existed before the 1st starts billing at 00:00 on the 1st.
- **Month to date** per resource = `min(started hours this month × hourly, monthly)`.
- **Projected end of month** per resource = the same formula with the hours up to the 1st of next
  month, assuming the resource keeps running.
- Servers bill while stopped. A primary IPv4 bills while it exists, assigned or not; IPv6 is free.
  Enabled backups add the backup percentage (20%) of the server price.
- Snapshots, backups and volumes are priced per GB per month; their hourly rate is that monthly
  price divided by 730.
- Prices come from `GET /v1/pricing` and from each server type's per-location prices, so a
  Hetzner price change lands without a code change.

Known gaps: a resource deleted earlier in the month is on the invoice but no longer in the API,
so month to date undercounts it. Traffic beyond the included volume is not counted. Primary IPs,
volumes and floating IPs take `role` and `cluster` from their own labels; a primary IP without
them inherits the labels of the server it is assigned to. Snapshots show role `image`.

Reference figures from the Usage page for October 2026: `cx23` €0.0088/h, max €5.49/mo; `cx33`
€0.0136/h, max €8.49/mo; IPv4 €0.0008/h, max €0.50/mo; snapshot €0.0143/GB/mo (0.4289 GB).
A full month of the current inventory is about €32.96.

## Metrics

All carry `project="unfold"`. The per-resource series also carry `kind` (`server`,
`server_backup`, `primary_ip`, `snapshot`, `backup`, `volume`, `load_balancer`, `floating_ip`),
`id`, `name`, `role`, `hcloud_cluster` (the Hetzner label `cluster`; a plain `cluster` label would be renamed `exported_cluster` by the scrape, which adds its own `cluster`), `location` and `type`.

| Metric | Meaning |
| --- | --- |
| `hcloud_cost_resource_hourly_eur` | hourly list price |
| `hcloud_cost_resource_monthly_cap_eur` | monthly price, the cap |
| `hcloud_cost_resource_billable_hours` | started hours billed this month |
| `hcloud_cost_resource_month_to_date_eur` | month to date |
| `hcloud_cost_resource_projected_month_eur` | projected for the whole month |
| `hcloud_cost_resource_created_timestamp_seconds` | creation time |
| `hcloud_cost_token_configured` | 1 when a token is mounted |
| `hcloud_cost_api_authorized` | 0 when Hetzner answers 401/403 |
| `hcloud_cost_refresh_success`, `hcloud_cost_last_success_timestamp_seconds` | last refresh (every 300 s) |

## Alerts

| Alert | Fires when |
| --- | --- |
| `HetznerProjectedMonthOverBudget` | projected month > €50 for 15 min |
| `HetznerServerOutsideCluster` | a server without `cluster=unfold-main` is older than 2 h, such as a leftover `hcloud-upload-image` temp server |
| `HetznerCostExporterDown` | no successful scrape of `hcloud-cost-exporter` for 15 min |
| `HetznerApiTokenRejected` | a token is mounted and Hetzner rejects it for 10 min |
| `HetznerCostRefreshFailing` | an accepted token stops refreshing for 30 min (egress, API outage) |
| `HetznerApiTokenNotSeeded` | info: no token mounted for 1 h |

The budget is the literal `50` in the rule; change it there and in its vmalert test.

## Seed or rotate the read-only token

The exporter needs a token that can only read. Create it in the **Unfold** project, not another one.

1. Hetzner Cloud console → project **Unfold** → **Security** → **API tokens** → **Generate API token**.
2. Description `homelab-cost-exporter-readonly`, permission **Read**. Copy the token; Hetzner shows
   it once.
3. In a zsh shell, from a homelab-cluster checkout:

    ```sh
    export BAO_ADDR="$(mise exec -- just bao-addr)"
    mise exec -- just bao-login
    read -s "v?Hetzner Unfold read-only token: "; echo
    echo "length ${#v}"
    printf '%s' "$v" | mise exec -- bao kv put secret/hetzner/unfold-readonly HCLOUD_TOKEN=-
    unset v
    mise exec -- kubectl -n observability annotate externalsecret hcloud-unfold-readonly force-sync="$(date +%s)" --overwrite
    ```

    The length should be 64. `HCLOUD_TOKEN=-` makes `bao` read the value from stdin, so it never
    appears in the shell history or the process list.
4. Within 5 minutes `hcloud_cost_api_authorized` turns 1 and the dashboard fills. The exporter
   rereads the mounted file on every refresh, so a rotation needs no restart. After a rotation,
   delete the old token in the console.

## Checks

```sh
mise exec -- kubectl -n observability get externalsecret hcloud-unfold-readonly
mise exec -- kubectl -n observability get pods -l app.kubernetes.io/name=hcloud-cost-exporter
mise exec -- kubectl -n observability logs deploy/hcloud-cost-exporter
```

Until the token is seeded the ExternalSecret reports `SecretSyncedError` and the pod still runs:
the secret volume is optional, the exporter logs `no Hetzner token mounted` and serves
`hcloud_cost_token_configured 0`.

## Network

`CiliumNetworkPolicy/hcloud-cost-exporter-egress` allows the pod DNS through kube-dns and HTTPS
to `api.hetzner.cloud` only. A refresh that fails with a timeout while the token is accepted
points at that policy or at DNS.

## Why a self-written exporter

`promhippie/hcloud_exporter` exports per-server hourly and monthly prices, images and volumes,
but not Hetzner's server labels (no `role` or `cluster` breakdown, so no leftover-server alert)
and no per-primary-IP inventory (only the price list). The exporter here is a few hundred lines of
standard-library Python on the estate's pinned `python:3.14-alpine` image, the same pattern as
`forgejo-ci-exporter`, and computes month to date and projection in code where tests pin them.
