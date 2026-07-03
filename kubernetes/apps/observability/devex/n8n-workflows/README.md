# DevEx measurement — n8n workflows

n8n is the **survey frontend + ETL runtime** for the Engineering Experience program. These
four workflows are **not GitOps-managed** (n8n stores workflows in its own database), so the
JSON here is a version-controlled **starting template + backup**. Build/import them in the
n8n UI, attach credentials, then **export back over these files** whenever you change them.

```
W1 Survey intake   Form Trigger  ──▶ Postgres (raw survey_response + survey_answer + free-text)
W2 Aggregate       Schedule      ──▶ Postgres  SELECT refresh_dimension_scores()
W3 Telemetry snap  Schedule      ──▶ HTTP (Prometheus + Forgejo API) ──▶ Postgres monthly_*_metrics
W4 Incident intake Webhook       ──▶ Postgres incidents   (Alertmanager → alert-derived MTTR)
```

Warehouse: **`devex-db`** (CNPG, `observability` namespace). All paths write into the schema in
[`../app/schema.configmap.yaml`](../app/schema.configmap.yaml). Dashboards read it via the
read-only `grafana_ro` role; n8n writes as the owner role `devex`.

> The dashboards work **without** n8n — the demo seed populates everything. n8n is what makes
> the **live** collection + telemetry loop run. Test order: demo seed first (instant), then
> wire n8n and watch real rows appear alongside (or after teardown, alone).

---

## One-time setup

### 1. n8n credentials (n8n UI → Credentials)

| Credential | Type | Values |
|---|---|---|
| `devex-db` | Postgres | Host `devex-db-rw.observability.svc.cluster.local`, Port `5432`, Database `devex`, User `devex`, Password = `kubectl -n observability get secret devex-db-secret -o jsonpath='{.data.password}' \| base64 -d`, SSL `require` |
| `forgejo-api` | Header Auth | Header `Authorization`, Value `token <PAT>` — a Forgejo PAT with `read:repository`/`read:issue`. Store the PAT in OpenBao (`devex/forgejo`) and paste here. |

Prometheus needs no auth (in-cluster).

### 2. NetworkPolicy (n8n namespace is default-deny)

n8n must egress to the warehouse, Prometheus and Forgejo; Alertmanager must reach n8n's
webhook. Apply this once (commit it under `kubernetes/apps/n8n/n8n/app/` if you prefer GitOps):

```yaml
---
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: n8n-devex-egress
  namespace: n8n
spec:
  endpointSelector:
    matchLabels:
      app.kubernetes.io/name: n8n
  egress:
    # devex-db (CNPG) in observability
    - toEndpoints:
        - matchLabels:
            io.kubernetes.pod.namespace: observability
            cnpg.io/cluster: devex-db
      toPorts: [{ports: [{port: "5432", protocol: TCP}]}]
    # Prometheus + Forgejo (same namespace selectors; identity-based — see network-policy skill)
    - toEndpoints:
        - matchLabels:
            io.kubernetes.pod.namespace: observability
            app.kubernetes.io/name: prometheus
      toPorts: [{ports: [{port: "9090", protocol: TCP}]}]
    - toEndpoints:
        - matchLabels:
            io.kubernetes.pod.namespace: forgejo
      toPorts: [{ports: [{port: "3000", protocol: TCP}]}]
```

> Cilium egress is enforced on the **post-DNAT backend identity**, not a VIP (see the
> `cilium-service-vip-egress-identity` memory + ADR-0005). Select the backend pods by label as
> above, not the service IP. Confirm the exact pod labels with
> `kubectl -n observability get pod -l cnpg.io/cluster=devex-db --show-labels`.

For W4, allow Alertmanager → n8n webhook (ingress to n8n from observability on the n8n port).

---

## W1 — Survey intake (Form Trigger → Postgres)

**Form Trigger** node, anonymous, served at `https://n8n.${SECRET_DOMAIN}/form/<path>` (already
on envoy-internal — no new route). Fields:

- `team` — dropdown (your real team names)
- `role_family` — dropdown: backend, frontend, platform, sre, qa
- `tenure_band` — dropdown: `<1y`, `1-3y`, `3-5y`, `5y+`
- `Q1`…`Q18` — number (or 1–7 rating). Question text is in the schema seed / the program doc.
- 3 optional long-text: "What slowed you down most?", "What should the platform team fix
  next?", "Which change helped most?"

**Postgres → Execute Query** node (one parameterized statement; maps form fields to `$1..$21`):

```sql
WITH s AS (
  INSERT INTO survey (name, framework, month)
  VALUES ('Monthly pulse', 'SPACE+DevEx', date_trunc('month', now())::date)
  ON CONFLICT (month, synthetic) DO UPDATE SET name = survey.name
  RETURNING id
), r AS (
  INSERT INTO survey_response (survey_id, team, role_family, tenure_band)
  SELECT id, $1, $2, $3 FROM s
  RETURNING id
)
INSERT INTO survey_answer (response_id, question_id, score)
SELECT r.id, q.id, v.score
FROM r
JOIN (VALUES
  ('Q1',$4::int),('Q2',$5::int),('Q3',$6::int),('Q4',$7::int),('Q5',$8::int),
  ('Q6',$9::int),('Q7',$10::int),('Q8',$11::int),('Q9',$12::int),('Q10',$13::int),
  ('Q11',$14::int),('Q12',$15::int),('Q13',$16::int),('Q14',$17::int),('Q15',$18::int),
  ('Q16',$19::int),('Q17',$20::int),('Q18',$21::int)
) AS v(code, score) ON true
JOIN survey_question q ON q.code = v.code;
```

Add a second Execute Query for free-text (insert one row per non-empty answer into
`survey_freetext(response_id, prompt, body)`; `theme` is coded later). Anonymity: do **not**
store name/email; leave `respondent_hash` NULL (or set it to an irreversible hash of a
rotating token if you need dedupe).

## W2 — Monthly aggregation (Schedule → Postgres)

**Schedule Trigger** (monthly, a day or two after the survey closes) → **Postgres Execute
Query**:

```sql
SELECT refresh_dimension_scores();
```

That's the whole job — all scoring/normalization/suppression logic lives in the SQL function
(same one the demo seed calls). Run it ad-hoc too whenever you want to refresh.

## W3 — Telemetry snapshot (Schedule → HTTP → Postgres)

**Schedule Trigger** (weekly or monthly). For each metric, an **HTTP Request** node queries the
source, a **Code/Set** node shapes `(month, team|service, value…)`, and a **Postgres** node
upserts. Use `date_trunc('month', now())::date` as `month`.

Prometheus instant queries (`GET http://vmsingle-vmsingle.observability.svc.cluster.local:8429/api/v1/query?query=…`):

| Target table.column | PromQL |
|---|---|
| delivery.deploy_freq | `count(count by (revision) (max_over_time(flux_resource_info{kind="Kustomization",suspended="False"}[30d])))` |
| delivery.lead_time_p50_h | `histogram_quantile(0.5, sum by (le) (rate(gotk_reconcile_duration_seconds_bucket{kind="Kustomization"}[30d]))) / 3600` |
| reliability.slo_attainment_pct | `avg(avg_over_time(probe_success[30d])) * 100` (or Sloth `slo:current_burn_rate`) |
| reliability.error_budget_burn | `(1 - avg(avg_over_time(probe_success[30d]))) / 0.001` |
| cost (service unit cost) | derive from `node_total_hourly_cost` + OpenCost `/allocation` per namespace |

Forgejo REST API (`GET https://forgejo.<domain>/api/v1`, header-auth credential) — closes the
"Forgejo→Prom blind spot" by pulling PR/Actions data directly and computing monthly rollups in
a Code node:

| Target table.column | Endpoint → compute |
|---|---|
| pr.first_review_p50_h | `/repos/{o}/{r}/pulls?state=all&sort=recentupdate` → median(first review/comment − created) |
| pr.cycle_time_p50_h / p90 | same → median/p90(merged_at − created_at) |
| ci.ci_p50_min / p95 | `/repos/{o}/{r}/actions/tasks` (or runs) → percentiles of run duration |
| ci.ci_success_pct | same → successful ÷ completed |

Upsert pattern (per row):

```sql
INSERT INTO monthly_ci_metrics (month, team, ci_p50_min, ci_p95_min, ci_success_pct)
VALUES ($1,$2,$3,$4,$5)
ON CONFLICT (month, team) DO UPDATE SET
  ci_p50_min=EXCLUDED.ci_p50_min, ci_p95_min=EXCLUDED.ci_p95_min,
  ci_success_pct=EXCLUDED.ci_success_pct;
```

Map each repo to a `team`/`service` so the correlation dashboard can JOIN survey↔telemetry.

## W4 — Incident intake (Webhook → Postgres) + Alertmanager

**Webhook** node (path e.g. `/devex-incident`) → **Postgres** upsert. Then point Alertmanager
at it (apply once the webhook exists — adding a dangling receiver makes Alertmanager error):

```yaml
# VMAlertmanager config (alertmanager.config shape)
receivers:
  - name: devex-incidents
    webhook_configs:
      - url: http://n8n.n8n.svc.cluster.local:80/webhook/devex-incident
        send_resolved: true
route:
  routes:
    - receiver: devex-incidents
      continue: true        # mirror everything; keep existing routing
```

Upsert (firing creates the row; the `send_resolved` callback closes it → alert-derived MTTR):

```sql
INSERT INTO incidents (fingerprint, triggered_at, resolved_at, severity, service)
SELECT a->>'fingerprint',
       (a->>'startsAt')::timestamptz,
       NULLIF(a->>'endsAt','0001-01-01T00:00:00Z')::timestamptz,
       a->'labels'->>'severity',
       coalesce(a->'labels'->>'service', a->'labels'->>'namespace')
FROM jsonb_array_elements($1::jsonb->'alerts') a
ON CONFLICT (fingerprint, triggered_at) DO UPDATE SET resolved_at = EXCLUDED.resolved_at;
```

> **Deferred:** true **MTTA** — Alertmanager has no human-ack concept, so `acknowledged_at`
> stays NULL. We report alert-duration MTTR only.

---

## Verifying the live loop

1. Submit a test response on the form → `SELECT count(*) FROM survey_response WHERE NOT synthetic;`
2. Run W2 → `SELECT * FROM grafana_devex_org ORDER BY month DESC LIMIT 6;` → DevEx scorecard tile lights.
3. Run W3 → `SELECT * FROM monthly_ci_metrics WHERE NOT synthetic;` → correlation board fills.
4. Fire a test alert → row in `incidents` → MTTR updates.
