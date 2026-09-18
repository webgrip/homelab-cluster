# Forgejo CI telemetry

How the cluster knows anything about its own CI, which of the numbers are measured and
which are modelled, and the three Forgejo API fields that do not mean what their names
suggest.

The board built on this is **Forgejo CI — Runners deep dive**
(`infra-forgejo-ci-runners`, Infrastructure folder). Its shallower sibling, **Forgejo CI —
Command Center** (`infra-forgejo-ci`), watches runner supply only.

## Glossary

| Term | What it is here |
| --- | --- |
| **Run** | One Forgejo Actions *workflow run* — the whole pipeline for one push. Has `created`, `started`, `stopped`. |
| **Task** | One *job* inside a run. The Actions API calls these `tasks`; Forgejo's own UI calls them jobs. |
| **Runner pod** | A `forgejo-runner-<jobid>-<podid>` pod created by the KEDA `ScaledJob`. Runs `forgejo-runner one-job`: takes exactly one task, then exits. |
| **Warm pool** | `minReplicaCount` runner pods sitting blocked on `one-job --wait` so a routine job starts with no cold start. |
| **dind** | The shared per-node docker daemon DaemonSet. Every runner on a node uses the daemon on that node, which keeps the image store warm between jobs. |

## Where each number comes from

| Source | Gives | Notes |
| --- | --- | --- |
| `forgejo-ci-exporter` | run + task timing, outcomes, the live queue | Polls the Actions API every 300s. Manifests in [`kubernetes/apps/observability/forgejo-ci-exporter/`](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/kubernetes/apps/observability/forgejo-ci-exporter). |
| VictoriaLogs | pod → task → repo, runner errors, job output | The runner's own stdout. |
| kube-state-metrics | pod phase, node placement, requests/limits, restarts | Label trap below. |
| cAdvisor | CPU, memory, throttling, network per container | Carries the real `namespace`. |
| KEDA | pending-job count, scaler health, scale decisions | The only component polling Forgejo on a fixed interval. |
| Kepler | **node** power (real) | Per-pod attribution is not working here — see below. |

## The pod-to-job join

Every runner pod registers with the **same** Forgejo runner UUID (`one-job --uuid`), so the
Actions API cannot tell you which pod is running which task. The authoritative mapping is a
line the runner prints when it picks work up:

```text
time="2026-09-18T05:30:39Z" level=info msg="task 38766 repo is webgrip/cloudflare ..."
```

`task 38766` is the same id as the Actions API's task id, and the log stream carries the
`pod` label. So the live table joins three sources:

```text
VictoriaLogs   pod  ── task ──┐
kube-state-metrics/cAdvisor   │ pod → node, CPU, memory, age
forgejo-ci-exporter           └─ task → repo, workflow, job, status, duration
```

That is why the panel uses the **Mixed** datasource and a `merge` transformation: there is
no single system that knows both halves.

## Three API fields that lie

Found by measurement against the live instance on 2026-09-18, and the reason the exporter
looks more defensive than it needs to.

### `limit` is ignored unless `page` is set

`/api/v1/repos/{owner}/{repo}/actions/runs?limit=30` returns **every** run, not 30.
`homelab-cluster` answered that call with **30 MB in 29 s**; adding `page=1` made the same
call **39 KB in 0.25 s**. Every run embeds its full `event_payload`, so the difference is
three orders of magnitude.

This is why the exporter used to be OOMKilled at a 320 Mi limit and now runs in ~21 MiB.
**Always send `page`.**

### `run_started_at` on a task is not when the task started

On every task record examined, `run_started_at == created_at` exactly. It is the *run's*
start stamped onto the task, not the moment a runner picked that task up. Per-task queue
wait therefore cannot be computed from the API and would silently read zero.

**Queue wait on the board is measured at RUN level**, from `started - created` on the run
record, which does vary and is real — a scheduled run waited 1386 s on 2026-09-18.

### `updated_at` on an old task is a cleanup timestamp

Forgejo's nightly log-retention job rewrites `updated` on old task rows. Tasks from
2026-09-14 carried `updated_at` of `2026-09-16T00:00:1x`, which makes
`updated_at - run_started_at` read as 25–43 hours of "job duration".

The exporter guards this two ways:

- durations above `MAX_JOB_SECONDS` (default 21600 — Forgejo's own job-timeout ceiling)
  are discarded outright, so they never reach a gauge;
- the duration **histogram** only accepts tasks that finished within
  `FRESH_WINDOW_SECONDS` (default 3600), so a rewritten row can never enter it.

A blank duration in the jobs table is this guard firing, not a missing metric.

## The kube-state-metrics label trap

KSM is scraped from the `observability` namespace with `honor_labels` off. Every KSM series
therefore carries **the scrape target's own identity** in `namespace`, `pod` and
`container`, and the workload's real identity in `exported_namespace`, `exported_pod` and
`exported_container`:

```text
kube_pod_info{
  namespace="observability", pod="kube-state-metrics-58f8d8d7c4-dtz95",  # the scraper
  exported_namespace="forgejo", exported_pod="forgejo-runner-4b4ll-wc879" # the workload
}
```

Two consequences, both of which produce a panel that looks healthy and is not:

1. **A matcher on `pod` matches nothing.** `kube_pod_status_phase{exported_namespace="forgejo",
   pod=~"forgejo-runner-.*"}` is always empty. Paired with the usual `or vector(0)`, the
   panel renders a confident `0` forever.
2. **A join on `(namespace, pod)` against cAdvisor never matches**, because cAdvisor's
   `namespace` is `forgejo` and KSM's is `observability`.

The deep-dive board handles this by wrapping every KSM selector so the real labels are
restored before any join:

```promql
label_replace(label_replace(label_replace(
  kube_pod_info{exported_namespace="forgejo", exported_pod=~"forgejo-runner-[a-z0-9]{5}-[a-z0-9]{5}"},
  "pod", "$1", "exported_pod", "(.+)"),
  "namespace", "$1", "exported_namespace", "(.+)"),
  "container", "$1", "exported_container", "(.+)")
```

If KSM ever gets `honorLabels: true`, every one of these wrappers becomes a no-op and can be
deleted — the matchers would then need to go back to plain `namespace`/`pod`. See the
deferred decision in the `victoriametrics` skill.

## Energy is modelled, not measured, per workload

Kepler reports **real** per-node package power (`kepler_node_cpu_watts`, joined on
`node_name`). It is **not** producing per-pod attribution on this cluster:
`kepler_container_cpu_watts` last carried samples around 2026-09-15 and has none now, and
`kepler_process_cpu_watts` only ever reports `namespace="kepler"`.

So the energy row estimates CI draw as:

```text
CI watts on a node = (CI CPU seconds on that node / node allocatable CPU) × measured node package watts
```

Every panel in that row says so in its description. The cluster-total figure beside it is
measured and can be trusted; only the CI split is a model. Fixing Kepler's attribution would
let these panels become measurements — it is not done here.

## Metrics the exporter publishes

Aggregates are safe to build alerts on. Per-task series are for tables only: the `task`
label churns by design and is bounded to the newest `TASK_DETAIL` (200) tasks plus
everything currently live.

| Metric | Type | Labels |
| --- | --- | --- |
| `forgejo_ci_job_duration_seconds` | histogram | `repo`, `workflow` |
| `forgejo_ci_run_duration_seconds` | histogram | `repo`, `workflow` |
| `forgejo_ci_run_queue_seconds` | histogram | `repo`, `workflow` |
| `forgejo_ci_jobs_total` | counter | `repo`, `workflow`, `ci_job`, `status` |
| `forgejo_ci_runs_total` | counter | `repo`, `workflow`, `event`, `status` |
| `forgejo_ci_job_duration_{p50,p95,max}_seconds` | gauge | `repo`, `workflow`, `ci_job` |
| `forgejo_ci_task_info` | gauge | `task`, `repo`, `workflow`, `ci_job`, `status`, `event`, `ref`, `run`, `url`, `sha` |
| `forgejo_ci_task_{duration,running,waiting}_seconds` | gauge | `task` |
| `forgejo_ci_tasks_active` | gauge | `status` |
| `forgejo_ci_last_run_status`, `forgejo_ci_consecutive_failures` | gauge | `repo`, `workflow`, `event`, `ref` |
| `forgejo_ci_runner_info`, `forgejo_ci_runners` | gauge | runner identity; needs a token |

### Counters do not backfill

On its first poll the exporter records every task it sees as *seen* but does **not** count
it. That keeps `rate()` honest — without it, a restart would ramp every counter from zero to
the whole window in one scrape and invent a burst of CI that never happened.
`forgejo_ci_seeded` is `0` during that first cycle.

The consequence: **histogram-backed panels need jobs to finish after the exporter started.**
Per-job p50/p95/max gauges do not — they are seeded from history, because a gauge has no
reset semantics to protect. A fresh exporter therefore shows a populated "typical vs worst"
table and empty percentile panels, and the percentiles fill within a day.

### The CI job name is `ci_job`, not `job`

`job` is a reserved Prometheus label: vmagent stamps the *scrape job* onto every series it
collects, so an exporter that publishes its own `job` label has it overwritten and finds the
original moved to `exported_job`. This was shipped that way for one commit and caught live —
`forgejo_ci_task_info` read `job="forgejo-ci-exporter"` for every CI job in the estate.

The label is therefore `ci_job`. Same family of trap as the kube-state-metrics section above,
and the same cure: check one live series' labels before trusting a query you wrote against a
new exporter.

## The token

Without `FORGEJO_TOKEN` the exporter polls anonymously and sees **public repositories
only**, and the runner-inventory endpoint returns 401 (handled: it logs and sets
`forgejo_ci_runner_inventory_up 0`). Compare `forgejo_ci_repos_tracked` against the org's
real repo count to see whether anything is invisible.

The token is read from the `forgejo-ci-exporter-token` Secret, provisioned by an
ExternalSecret from OpenBao at `forgejo/ci-exporter`, property `token`. It needs read
access to repositories and organisation only. Per
[ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md) the value enters OpenBao once,
by a person over OIDC.

## When a panel says nothing

| Symptom | Likely cause |
| --- | --- |
| Percentile panels empty, tables populated | Exporter restarted recently; histograms have not refilled. Check `forgejo_ci_seeded`. |
| A repo missing everywhere | Private, and no token. Check `forgejo_ci_repos_tracked`. |
| Live table has pods but no task columns | No job running — warm-pool runners blocked on `--wait` legitimately hold no task. |
| Live table has tasks but no pod columns | The pick-up log line aged out of the dashboard range while the pod is gone. |
| Duration blank on one row | The cleanup-timestamp guard rejected it. |
| Queue deep, runners stuck below max | Node capacity, not `maxReplicaCount`. Check the Pending line on "Runner pods by phase". |
| Everything from the API stale | Check "Exporter freshness" and `forgejo_ci_refresh_errors_total`. |
