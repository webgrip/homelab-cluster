# Engineering Experience (DevEx / SPACE / DORA) measurement program

A layered, OSS-only program that measures developer experience and software-delivery health for
the platform team and the development teams it enables. It blends four lenses — **DORA**
(delivery throughput + instability), **SRE** (reliability + incident economics), **SPACE**
(multi-dimensional productivity), and **DevEx** (feedback loops, cognitive load, flow) — and
deliberately measures **systems, services and value streams, never individuals**.

It is built as **two separable systems sharing one queryable warehouse**:

1. **Survey collection** — a monthly anonymous pulse (n8n Form) writing raw answers to Postgres.
2. **Telemetry correlation** — monthly engineering-telemetry rollups in the same Postgres,
   joined to the survey scores and surfaced in Grafana.

> Principle (from SPACE + DORA): metrics live in **tension**, are read at the **service/team**
> level, and every dashboard is an **improvement instrument, not a ranking tool**.

## Architecture

```
n8n (survey + ETL)                         devex-db (CNPG, observability)
  W1 Form   ──▶ raw survey_response/answer ─┐
  W2 sched  ──▶ refresh_dimension_scores()  ├─▶  monthly_dimension_score + grafana_* views
  W3 sched  ──▶ Prometheus + Forgejo API ───┤    monthly_*_metrics (delivery/ci/pr/reliability/cost)
  W4 hook   ──▶ Alertmanager ───────────────┘    incidents
                                                     │ grafana_ro (SELECT on views only)
                                                     ▼
                          Grafana  →  "Engineering Experience" folder
                                       devex-scorecard · devex-dimensions · devex-telemetry-correlation
                                       └─▶ feeds the exec-kpi-scorecard "developer experience" tile
```

- **Warehouse:** `kubernetes/apps/observability/devex/` — CNPG `devex-db`, schema ConfigMap +
  idempotent migration Job, generated ESO secrets, demo seed/teardown Jobs.
- **Grafana:** native `postgres` datasource `postgres-devex` (read-only `grafana_ro`) + the
  `engineering-experience` folder + three dashboards.
- **n8n:** four workflows (templates + build guide in
  `kubernetes/apps/observability/devex/n8n-workflows/`). Workflows are not GitOps-managed.

Privacy is enforced at the database grant layer: `grafana_ro` can read only the `grafana_*`
views and the metric tables — **never** the raw `survey_response` / `survey_answer` /
`survey_freetext`. Team rows with fewer than 5 responses are suppressed in `grafana_survey_scores`.

## Demo data & self-testing

The dashboards ship populated. The opt-in `devex-db-demo-seed` Job generates **~21 synthetic
respondents × 3 teams × 6 months** plus telemetry rollups **anti-correlated** to experience
(worse scores ⇒ slower CI, longer PR waits, more incidents) so the correlation board shows real
signal before any human answers. Synthetic teams are prefixed `demo-` and every row is
`synthetic = true`.

- **See it:** the seed runs on first deploy — open the three dashboards.
- **Re-seed:** bump the `seed-rev` annotation on `app/demo/demo-seed.job.yaml` and commit.
- **Wipe:** set `spec.suspend: false` on `app/demo/demo-teardown.job.yaml` and commit (or run
  `DELETE … WHERE synthetic`). Real responses are untouched — demo and live data coexist.
- **Disable entirely:** remove `- demo` from `app/kustomization.yaml`.

## Survey — question bank & scoring

Monthly pulse, **1–7 agreement scale**, anonymous, ~3 minutes. **Stable core** every month:
Q1, Q4, Q10, Q12, Q17; the rest rotate by theme (calendar below). Full Q1–Q18 text lives in the
schema seed (`app/schema.configmap.yaml`).

**Dimensions** (a question can feed several, via `dimension_map`):

| Dimension | Items |
|---|---|
| Satisfaction | Q1, Q2, Q17, Q18 |
| Feedback loops | Q3, Q4, Q5, Q6, Q7, Q16 |
| Cognitive load (clarity) | Q2, Q8, Q9, Q13, Q15 |
| Flow state | Q10, Q11, Q12 |
| Collaboration / operability | Q5, Q14, Q15 |

**Scoring** (in `refresh_dimension_scores()`): per respondent, mean of a dimension's items →
averaged across respondents → normalized `((mean − 1) / 6) × 100` to 0–100. Composite:

```
DevEx index = 0.25·Satisfaction + 0.30·Feedback loops + 0.20·Cognitive load
            + 0.15·Flow + 0.10·Collaboration        (0–100)
```

**Bands:** 🟥 <55 critical/weak · 🟧 55–69 watch · 🟩 ≥70 healthy/strong.

**Statistics & ethics rules:**

- Include a respondent only if they answered ≥70% of items.
- Publish a team/role segment only at **n ≥ 5** (caution 5–7, normal ≥8); suppress below.
- Report response rate **and** the response mix by team/role — response rate alone is not quality.
- Monthly = descriptive trend; quarterly = significance (paired/Welch t-test, bootstrap CI).
  Treat a change as meaningful only at p < 0.05 **and** a moderate effect size (|d| ≳ 0.35).
- Check internal consistency (Cronbach α; investigate < 0.70) when revising the bank.
- **Never** publish person-level scores or leaderboards; **never** infer individual productivity
  from commits/PR counts/online time. Every dashboard states it is for system improvement.

## Telemetry KPI dictionary

Written monthly into the warehouse by n8n W3/W4 from **OSS systems of record already in the
cluster**. Starting thresholds are for a small org — recalibrate after two clean months.

| Table.column | KPI | Source | Target band |
|---|---|---|---|
| delivery.deploy_freq | Deployment frequency | Flux `flux_resource_info` | ≥ weekly tier-1 |
| delivery.lead_time_p50_h/p90_h | Lead time | Flux `gotk_reconcile_duration_seconds` (apply tail) | p50 < 24h |
| delivery.cfr_pct | Change failure rate | Flux not-Ready proxy / incident join | < 10% |
| ci.ci_p50_min / p95_min | CI duration | Forgejo Actions API | p50 < 10m, p95 < 20m |
| ci.ci_success_pct | CI success rate | Forgejo Actions API | > 90% |
| pr.first_review_p50_h | PR first-review wait | Forgejo pulls API | p50 < 8h |
| pr.cycle_time_p50_h / p90_h | PR cycle time | Forgejo pulls API | p50 < 24h |
| reliability.slo_attainment_pct | SLO attainment | Sloth / `probe_success` | tier-1 99.9%+ |
| reliability.error_budget_burn | Error-budget burn | Sloth burn-rate rules | multi-window alert |
| reliability.mttr_min | MTTR (alert-derived) | Alertmanager → incidents | Sev1/2 p50 < 60m |
| cost.unit_cost_eur | Unit cloud cost | OpenCost (EUR model) | −10…20% per unit |

**Known gaps (honest):** true **MTTA** has no source (Alertmanager has no human-ack) →
`acknowledged_at` stays NULL. A full Forgejo→Prometheus exporter is **not** built; W3 pulls the
Forgejo REST API directly for monthly rollups, which is sufficient for this cadence.

## Twelve-month program (stable core + rotating theme)

Stable core survey items Q1/Q4/Q10/Q12/Q17 and telemetry deploy-freq/lead-time/CFR/CI/SLO/MTTR
every month; the theme rotates the focus and the improvement work.

| Month | Theme | Improvement focus |
|---|---|---|
| 1 | Baseline & instrumentation | tag services, stand up dashboards, first pulse |
| 2 | CI feedback loops | shared Dockerfiles, caching, kill flaky tests |
| 3 | Review flow & batching | PR size guidance, review SLA, reviewer ownership |
| 4 | Release safety | release templates, canary, rollback runbooks |
| 5 | Reliability & SLOs | SLIs for top journeys, burn-rate alerts |
| 6 | Incident response & toil | postmortem tracker, automate top toil |
| 7 | Self-service platform adoption | golden-path bootstrap, portal success logs |
| 8 | Documentation & discoverability | central docs landing, owner metadata |
| 9 | Local dev & onboarding | one-command setup, instrument bootstrap |
| 10 | Security in flow | shift gates into templates, reduce false positives |
| 11 | Cost & unit economics | cost tags, unit-cost model, idle savings |
| 12 | Consolidation & next-year plan | rebaseline, retire weak metrics, annual scorecard |

## Monthly operating cycle

1. **Week 1:** open the pulse (W1 form link, internal); one reminder on day 2; close after 3–4 days.
2. **Close + 1–2 days:** run W2 (`refresh_dimension_scores()`); W3 snapshots telemetry.
3. **Review:** team review → leadership review using the templates below.
4. **Backlog:** lowest dimension × strongest telemetry correlation × top free-text theme → one
   platform action + one team action + one leadership decision, each with an owner and due date.

### Monthly report template

```
1. Headline   2. Exec summary (3 sentences)
3. Delivery (deploy freq / lead time / CFR / recovery)
4. Reliability (SLO / burn / MTTA-n/a / MTTR)
5. Platform/DevEx (self-service / tickets / toil / DevEx dimensions)
6. Cost (unit cost)   7. What changed   8. Risks   9. Next-month actions+owners+dates
```

### One-page leadership summary

```
Business impact: <one sentence linking platform work to speed/reliability/risk/cost>
DevEx index • Deployment frequency • Lead time • Change failure rate • SLO attainment •
MTTR • Self-service success • Unit cost     (each: value + trend arrow)
Key wins (2) • Largest risk • Decision needed
```

## Four non-negotiables for this to be an operating system (not a dashboard)

1. Service tagging + ownership are mandatory. 2. Deployment events are first-class data.
3. Survey results are protected and never used for individual evaluation. 4. Improvement work
gets explicit capacity each month.

## See also

- n8n build guide: `kubernetes/apps/observability/devex/n8n-workflows/README.md`
- Warehouse schema: `kubernetes/apps/observability/devex/app/schema.configmap.yaml`
- Dashboards: Grafana → **Engineering Experience** folder (`devex-scorecard` and links)
- Executive integration: the `exec-kpi-scorecard` "developer experience" tile now reads the real
  DevEx index. See [Observability](observability.md) and [Alerting principles](alerting-principles.md).
