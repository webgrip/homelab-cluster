from __future__ import annotations

from lib import (AMBER, CAT, LOGS, NEUTRAL, SKY, VERMILLION, alarm_at, bars, col, color_overrides, dashboard,
                 doc_link, grid_pos, kiosk_steps, link, number, stat, table, tag_links, target, timeseries, var_query)
from forgejo_ci import lay_out_rows

UID = "glide-plant"
WALL_UID = "wall-glide"
FOLDER = "boards"
TAGS = ["board", "glide", "ploeg"]
GLIDE_DOCS = "https://docs.webgrip.dev/glide/"

KSM = 'job="kube-state-metrics", exported_namespace="ploeg"'
WORKER_POD = 'exported_pod=~"ploeg-worker-.+"'
SCALERS = 'scaledObject=~"ploeg-worker-.+"'
TEAM = 'team=~"$team"'
CHAT = 'model!~"MCP: .*"'
HOUR = 3600

VARIABLES = [var_query("team", "Team", "label_values(ploeg_work_items_count, team)", include_all=True, multi=True)]


def runs_now():
    running = f'sum(ploeg_agent_runs_count{{outcome="running", {TEAM}}}) or on() vector(0)'
    waiting = f"sum(keda_scaler_metrics_value{{{SCALERS}}}) or on() vector(0)"
    pods = f'sum(kube_pod_status_phase{{{KSM}, {WORKER_POD}, phase="Running"}}) or on() vector(0)'
    failed = f'sum(kube_pod_status_phase{{{KSM}, {WORKER_POD}, phase="Failed"}}) or on() vector(0)'
    panel = stat(
        "Runs, right now", None, decimals=0, text_mode="value_and_name", fixed_color=NEUTRAL,
        targets=[target(running, "A", "running", instant=True), target(waiting, "B", "waiting for a pod", instant=True),
                 target(pods, "C", "worker pods", instant=True), target(failed, "D", "failed pods", instant=True)],
        desc="Running is Runs Ploeg has started and not finished (the work-items exporter reads `finished_at IS "
             "NULL`). Waiting for a pod is KEDA's read of pending Runs across every ploeg-worker ScaledJob: above "
             "zero for long means the node pool has no room for a worker. Worker pods is pods in phase Running. "
             "Failed pods is worker pods left in phase Failed, amber from one: open the pod's events, it is "
             "usually an OOM kill or a sandbox that never started.")
    panel["fieldConfig"]["overrides"] = [col("waiting for a pod", thresholds=alarm_at(amber=1, vermillion=4)),
                                         col("failed pods", thresholds=alarm_at(amber=1))]
    return panel


def waiting_on_you():
    human = f'sum(ploeg_work_items_count{{state="needs_human", {TEAM}}}) or on() vector(0)'
    review = f'sum(ploeg_work_items_count{{state="awaiting_review", {TEAM}}}) or on() vector(0)'
    panel = stat(
        "Waiting on a person", None, decimals=0, text_mode="value_and_name",
        targets=[target(review, "A", "review", instant=True), target(human, "B", "needs a human", instant=True)],
        thresholds=alarm_at(amber=1),
        desc="Work Items no agent will move until a person does. Review is a pull request ready for you; needs a "
             "human is a Work Item an agent gave up on or could not start, with the reason in Unfold. Amber from "
             "one, because both are the queue in front of the owner, not in front of the machine.")
    return panel


def oldest_queued():
    return stat(
        "Oldest queued Work Item", None, unit="s", decimals=0, text_mode="value_and_name",
        targets=[target(f'max by (team) (ploeg_work_items_oldest_age_seconds{{state="queued", {TEAM}}})', "A",
                        "{{team}}", instant=True)],
        thresholds=alarm_at(amber=HOUR, vermillion=6 * HOUR), no_value="nothing queued",
        desc="Age of the oldest Work Item in state queued, per team. Queued means assigned and not yet leased: a "
             "worker should pick it up within minutes. Amber from an hour, vermillion from six. A Work Item Unfold "
             "owns (operator_owned) also counts here but is started from Unfold, not by KEDA, so an old one on "
             "the unfold team is a person who has not pressed start.")


def leases_expired():
    return stat(
        "Expired leases", f"sum(ploeg_leases_expired_not_reclaimed{{{TEAM}}}) or on() vector(0)", decimals=0,
        thresholds=alarm_at(vermillion=1), value_size=48,
        desc="Writer leases past their expiry that the sweep has not reclaimed. The sweep runs every 15 seconds, "
             "so one here means the sweep itself is stuck and a Work Item is locked against every other writer.")


def db_reachable():
    return stat(
        "Ploeg DB seen", 'max(pg_up{job="ploeg-work-items-exporter"}) or on() vector(0)', decimals=0,
        thresholds=kiosk_steps((VERMILLION, 0), (NEUTRAL, 1)), value_size=48,
        mappings=[{"type": "value", "options": {"0": {"text": "no"}, "1": {"text": "yes"}}}],
        desc="Whether ploeg-work-items-exporter can query the Ploeg database. At no every Ploeg number on this "
             "board is frozen at its last value.")


def demand():
    return timeseries(
        "Runs waiting for a pod, per ScaledJob",
        [target(f"sum by (scaledObject) (keda_scaler_metrics_value{{{SCALERS}}})", "A", "{{scaledObject}}"),
         target(f'sum(kube_pod_status_phase{{{KSM}, {WORKER_POD}, phase="Running"}})', "B", "worker pods running")],
        unit="short", decimals=0,
        overrides=color_overrides([("worker pods running", NEUTRAL)]),
        desc="Pending Runs per team and role as KEDA reads them, against running worker pods. A pool that stays "
             "above zero while pods do not rise is capacity: the node pool is full or the ScaledJob is paused.")


def failed_runs():
    base = f'ploeg_run_duration_seconds{{outcome=~"failed|stuck", {TEAM}}}'
    started = f'max by (key_alias) (ploeg_run_started_epoch{{outcome=~"failed|stuck", {TEAM}}}) * 1000'
    spend = 'max by (key_alias) (litellm_run_spend{key_alias=~"ploeg-.*"})'
    return table(
        "Failed and stuck Runs · 30 days",
        [target(f"max by (key_alias, team, outcome, ticket, provider) ({base})", "A", instant=True, fmt="table"),
         target(started, "B", instant=True, fmt="table"),
         target(f"{spend} and on (key_alias) max by (key_alias) ({base})", "C", instant=True, fmt="table")],
        rename={"team": "Team", "outcome": "Outcome", "ticket": "Ticket", "provider": "Tracker",
                "Value #A": "Ran for", "Value #B": "Started", "Value #C": "Spent", "key_alias": "Key"},
        order=["Started", "Team", "Outcome", "Tracker", "Ticket", "Ran for", "Spent", "Key"], sort_field="Started",
        no_value="No Run failed or got stuck in 30 days.", cell_height="md",
        overrides=[col("Started", unit="dateTimeFromNow", width=130), col("Ran for", unit="s", decimals=0, width=90),
                   col("Spent", unit="currencyUSD", decimals=2, width=80),
                   col("Outcome", colour_text=True, width=90, mappings=[{"type": "value", "options": {
                       "failed": {"text": "failed", "color": VERMILLION}, "stuck": {"text": "stuck", "color": AMBER}}}])],
        desc="Every Run in the exporter's 30-day window whose outcome was failed or stuck, newest first, with what "
             "its per-Run model key spent. The same ticket failing several times is a Work Item the agents cannot "
             "do as written: refine it or take it back. Failure reasons are in Ploeg's database (agent_runs."
             "failure_reason); the Unfold Loop board reads them.")


def outcomes():
    return bars(
        "Run outcomes · 30 days",
        [target(f'sum by (outcome) (ploeg_agent_runs_count{{outcome!="running", {TEAM}}})', "A", "{{outcome}}",
                instant=True)],
        decimals=0,
        desc="How the Runs of the last 30 days ended. pr_opened and pr_updated are the product; no_change_needed "
             "is an honest answer that still cost money; failed and stuck are the ones to read. Neutral bars: this "
             "is a mix to watch drift in, not a tile to act on.")


def spend_today():
    return stat(
        "Model spend today, per provider", "sum by (provider) (litellm_provider_today_spend) > 0", unit="currencyUSD",
        decimals=2, text_mode="value_and_name", fixed_color=NEUTRAL,
        targets=[target("sum by (provider) (litellm_provider_today_spend) > 0", "A", "{{provider}}", instant=True)],
        desc="What LiteLLM has recorded as spent today per provider, every caller included (Unfold, Omnigraph, "
             "chat). Grey: Unfold's own per-Run budgets are enforced in Ploeg, and the SLO rules alert on budget "
             "hits.", no_value="nothing spent today")


def spend_by_team():
    expr = (f'sum by (team) (litellm_run_spend{{key_alias=~"ploeg-.*"}} * on (key_alias) group_left(team) '
            f"(max by (key_alias, team) (ploeg_run_started_epoch{{{TEAM}}}) >= bool 0))")
    return stat(
        "Unfold spend per team · 30 days", expr, unit="currencyUSD", decimals=2, text_mode="value_and_name",
        fixed_color=NEUTRAL, targets=[target(expr, "A", "{{team}}", instant=True)],
        desc="What the per-Run model keys of each team's Runs spent over the exporter's 30-day window, from "
             "LiteLLM's ledger joined to Ploeg's Runs on the key alias. Settled spend per Work Item, with "
             "reconciliation, is on the Unfold Loop board.")


def model_health():
    served = f"(sum by (model) (litellm_recent_requests{{{CHAT}}}) > 0)"
    ratio = f"sum by (model) (litellm_recent_failures{{{CHAT}}}) / {served}"
    p95 = f"max by (model) (litellm_latency_p95_seconds{{{CHAT}}}) and on (model) {served}"
    return table(
        "Models · last 24 hours",
        [target(served, "A", instant=True, fmt="table"),
         target(ratio, "B", instant=True, fmt="table"),
         target(p95, "C", instant=True, fmt="table")],
        rename={"model": "Model", "Value #A": "Requests", "Value #B": "Failed", "Value #C": "p95"},
        order=["Model", "Requests", "Failed", "p95"], sort_field="Requests", cell_height="md",
        overrides=[col("Requests", decimals=0, width=90),
                   col("Failed", unit="percentunit", decimals=1, width=80, colour_text=True,
                       thresholds=alarm_at(amber=0.02, vermillion=0.1)),
                   col("p95", unit="s", decimals=1, width=70, colour_text=True,
                       thresholds=alarm_at(amber=30, vermillion=90))],
        no_value="LiteLLM served nothing in 24 hours.",
        desc="Every model LiteLLM served in the trailing 24 hours: requests, the share that failed, and the 95th "
             "percentile latency. MCP tool calls LiteLLM logs as pseudo-models are left out. Failed is amber from "
             "2 % and vermillion from 10 %: at that rate an agent Run on that model burns retries and budget. "
             "Swap the model in the team's plan or check the provider's status page.")


def first_screen():
    placed = [
        (runs_now(), 0, 0, 8, 5), (waiting_on_you(), 8, 0, 5, 5), (oldest_queued(), 13, 0, 5, 5),
        (leases_expired(), 18, 0, 3, 5), (db_reachable(), 21, 0, 3, 5),
        (failed_runs(), 0, 5, 14, 10), (demand(), 14, 5, 10, 10),
        (outcomes(), 0, 15, 7, 9), (spend_today(), 7, 15, 7, 4), (spend_by_team(), 7, 19, 7, 5),
        (model_health(), 14, 15, 10, 9),
    ]
    panels = []
    for panel, x, y, w, h in placed:
        panel["gridPos"] = grid_pos(x, y, w, h)
        panels.append(panel)
    return panels


def row_dispatch():
    job_failed = (f'sum by (job_name) (increase(kube_job_status_failed{{{KSM}, job_name=~"ploeg-worker-.*"}}'
                  f"[$__range])) > 0")
    return [
        (timeseries("Worker pods by phase", [target(
            f'sum by (phase) (kube_pod_status_phase{{{KSM}, {WORKER_POD}}} == 1)', "A", "{{phase}}")],
            unit="short", decimals=0, stack=True,
            overrides=color_overrides([("Running", SKY), ("Pending", AMBER), ("Failed", VERMILLION),
                                       ("Succeeded", NEUTRAL)]),
            desc="Worker pods over time by phase."), 0, 12, 8),
        (bars("KEDA scaler errors per ScaledJob, this range", [target(
            f"sum by (scaledJob) (increase(keda_scaled_job_errors_total{{scaledJob=~\"ploeg-worker-.+\"}}[$__range]))",
            "A", "{{scaledJob}}", instant=True)], decimals=0, thresholds=alarm_at(amber=1),
            desc="Errors KEDA hit while scaling each worker pool. A pool with errors and no plan behind it is an "
                 "orphaned ScaledJob."), 12, 12, 8),
        (bars("Failed worker Jobs, this range", [target(job_failed, "A", "{{job_name}}", instant=True)],
              decimals=0, fixed_color=AMBER, no_value="No worker Job failed.",
              desc="Worker Jobs Kubernetes marked failed. Each is a Run whose pod died: its Run is failed with "
                   "reason infra_node unless Ploeg's sweep caught it first."), 0, 12, 8),
        (bars("OOM kills in worker pods, this range", [target(
            'sum by (pod) (increase(container_oom_events_total{namespace="ploeg", pod=~"ploeg-worker-.+"}[$__range])) > 0',
            "A", "{{pod}}", instant=True)], decimals=0, fixed_color=VERMILLION, no_value="No worker was OOM-killed.",
            desc="Out-of-memory kills per worker pod. OpenHands builders were raised to 1.5 GiB on 2026-09-28 for "
                 "exactly this."), 12, 12, 8),
    ]


def row_work():
    return [
        (bars("Work Items by state", [target(f"sum by (state) (ploeg_work_items_count{{{TEAM}}})", "A", "{{state}}",
                                            instant=True)], decimals=0,
              desc="Every Work Item Ploeg knows, by state."), 0, 8, 8),
        (bars("Retried Work Items per team", [target(f"sum by (team) (ploeg_attempts_retried_items{{{TEAM}}})", "A",
                                                    "{{team}}", instant=True)], decimals=0,
              desc="Work Items that needed more than one attempt."), 8, 8, 8),
        (bars("Checkpoint funnel · 30 days", [target("sum by (phase) (ploeg_checkpoints_count)", "A", "{{phase}}",
                                                    instant=True)], decimals=0,
              desc="Checkpoints written per phase: branch created, pull request opened, pull request updated. The "
                   "drop from branch to pull request is work that started and never reached review."), 16, 8, 8),
        (bars("Stuck Runs by reason · 30 days", [target(f"sum by (stuck_reason) (ploeg_stuck_count{{{TEAM}}})", "A",
                                                       "{{stuck_reason}}", instant=True)], decimals=0,
              fixed_color=AMBER, no_value="No Run got stuck.", desc="Why agents declared themselves stuck."),
         0, 12, 7),
        (table("Longest Runs per outcome · 30 days", [target(
            f"max by (outcome) (ploeg_run_duration_seconds{{outcome!=\"running\", {TEAM}}})", "A", instant=True,
            fmt="table"), target(
            f"avg by (outcome) (ploeg_run_duration_seconds{{outcome!=\"running\", {TEAM}}})", "B", instant=True,
            fmt="table")],
            rename={"outcome": "Outcome", "Value #A": "Longest", "Value #B": "Average"},
            overrides=[col("Longest", unit="s", decimals=0), col("Average", unit="s", decimals=0)],
            desc="How long Runs take to reach each outcome."), 12, 12, 7),
    ]


def row_spend():
    per_key = ('topk(15, 100 * max by (key_alias) (litellm_key_spend{key_alias=~"ploeg-.*"}) '
               '/ (max by (key_alias) (litellm_key_max_budget{key_alias=~"ploeg-.*"}) > 0))')
    by_outcome = ('sum by (outcome) (litellm_run_spend{key_alias=~"ploeg-.*"} * on (key_alias) group_left(outcome) '
                  f"(max by (key_alias, outcome) (ploeg_run_started_epoch{{{TEAM}}}) >= bool 0))")
    return [
        (bars("Per-Run key budget used, top 15", [target(per_key, "A", "{{key_alias}}", instant=True)],
              unit="percent", decimals=0, maximum=100, thresholds=alarm_at(amber=80, vermillion=100),
              desc="The Run keys closest to their budget. A key at 100 % blocked its Run mid-work."), 0, 8, 9),
        (bars("Unfold spend by Run outcome · 30 days", [target(by_outcome, "A", "{{outcome}}", instant=True)],
              unit="currencyUSD", decimals=2,
              desc="Where Unfold's model money went, by how the Run ended. Spend on failed, stuck and "
                   "no_change_needed Runs bought no pull request."), 8, 8, 9),
        (timeseries("Model spend per model", [target(
            f"sum by (model) (increase(litellm_model_spend{{{CHAT}}}[1h])) > 0", "A", "{{model}}")],
            unit="currencyUSD", draw="bars", stack=True, decimals=2,
            desc="Spend per model per hour, every LiteLLM caller."), 16, 8, 9),
    ]


def row_gateway():
    calls = 'traces_spanmetrics_calls_total{service_name="litellm", span_kind="SPAN_KIND_SERVER"}'
    err_ratio = (f'sum(rate({calls[:-1]}, status_code="STATUS_CODE_ERROR"}}[5m])) / sum(rate({calls}[5m]))')
    p95 = ('histogram_quantile(0.95, sum by (le) (rate(traces_spanmetrics_duration_seconds_bucket'
           '{service_name="litellm", span_kind="SPAN_KIND_SERVER"}[5m])))')
    return [
        (timeseries("LiteLLM error ratio, live", [target(err_ratio, "A", "errors")], unit="percentunit",
                    thresholds=alarm_at(amber=0.02, vermillion=0.1),
                    overrides=color_overrides([("errors", VERMILLION)]),
                    desc="Share of LiteLLM server spans that ended in error, five-minute rate, from trace span "
                         "metrics."), 0, 12, 8),
        (timeseries("LiteLLM p95 latency, live", [target(p95, "A", "p95")], unit="s",
                    overrides=color_overrides([("p95", CAT[0])]),
                    desc="95th percentile LiteLLM server span duration. Long agent completions dominate it."),
         12, 12, 8),
        (stat("Time to first token p95 · 24 h", "max(litellm_ttft_p95_seconds)", unit="s", decimals=1,
              thresholds=alarm_at(amber=30, vermillion=90),
              desc="95th percentile time to the first streamed token, trailing 24 hours."), 0, 6, 5),
        (stat("Kata sandboxes started cold · 7 days",
              "sum(increase(agent_sandbox_claim_creation_total[7d])) or on() vector(0)", decimals=0,
              fixed_color=NEUTRAL, desc="Sandbox claims the copper team's Runs created."), 6, 6, 5),
        (stat("Sandbox startup p95 · 7 days",
              "histogram_quantile(0.95, sum by (le) (rate(agent_sandbox_claim_controller_startup_latency_ms_bucket[7d])))",
              unit="ms", decimals=0, fixed_color=NEUTRAL,
              desc="95th percentile time from claim to a started kata sandbox. The histogram's buckets are coarse, "
                   "so read this as the bucket bound."), 12, 6, 5),
        (stat("Unfold up", f'max(kube_deployment_status_replicas_available{{{KSM}, deployment="unfold"}}) '
                             "or on() vector(0)", decimals=0, thresholds=kiosk_steps((VERMILLION, 0), (NEUTRAL, 1)),
              desc="Available Unfold replicas."), 18, 6, 5),
    ]


def row_logs():
    return [({
        "type": "logs", "title": "ploegd warnings and errors", "datasource": LOGS,
        "description": "Ploeg's controller at WARN and ERROR.",
        "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True,
                    "dedupStrategy": "exact"},
        "targets": [{"refId": "A", "expr": '{namespace="ploeg", container="ploegd"} ~"level=(WARN|ERROR)"',
                     "queryType": "instant", "datasource": LOGS}],
    }, 0, 24, 10)]


def row_native():
    return [
        (stat("Longest idle open Shift", f"max(ploeg_shift_idle_seconds_max{{{TEAM}}})", unit="s", decimals=0,
              thresholds=alarm_at(amber=2 * HOUR, vermillion=6 * HOUR), no_value="ploegd not scraped",
              desc="The open Shift that has gone longest without a Run starting, finishing or checkpointing, "
                   "from ploegd's own gauge. Lease renewals are not progress."), 0, 6, 5),
        (stat("Model keys past their TTL", "sum(ploeg_llm_keys_past_ttl) or on() vector(0)", decimals=0,
              thresholds=alarm_at(vermillion=1), no_value="ploegd not scraped",
              desc="Per-Run model accounts still issued or unknown after their key TTL: a gateway key that may "
                   "still be live. A blocked key is settlement evidence, not a leak, so it is not counted."),
         6, 6, 5),
        (stat("Settled spend, last hour", "sum(ploeg_settled_spend_usd_last_hour)", unit="currencyUSD", decimals=2,
              fixed_color=NEUTRAL, spark=True, no_value="ploegd not scraped",
              desc="Model spend Ploeg settled in the trailing hour."), 12, 6, 5),
        (stat("Tracker webhooks missing", "sum(ploeg_tracker_webhooks_missing) or on() vector(0)", decimals=0,
              thresholds=alarm_at(amber=1), no_value="ploegd not scraped",
              desc="Tracker projects Ploeg expects a webhook from and cannot find one for. Without it, a new "
                   "ticket never reaches Ploeg."), 18, 6, 5),
    ]


LINKS = [link("Unfold Loop", "/d/glide-loop"), link("Unfold · Runs", "/d/glide-runs"),
         link("Unfold · Kata overhead", "/d/glide-kata"), link("Unfold docs", GLIDE_DOCS, icon="doc", blank=True),
         tag_links(["board"], "Boards")]


def desk():
    sections = [("Dispatch and workers", row_dispatch()), ("Work Items and Runs", row_work()),
                ("Spend", row_spend()), ("Model gateway, sandboxes and Unfold", row_gateway()),
                ("ploegd gauges", row_native()), ("Ploeg logs", row_logs())]
    panels = number(first_screen() + lay_out_rows(24, sections))
    return dashboard(
        UID, "Unfold · Plant", panels, tags=TAGS, variables=VARIABLES, links=LINKS, time_from="now-24h",
        description="Is the Unfold machine keeping up: Runs, workers, leases, what waits on a person, what failed "
                    "and what it cost. The product KPIs are on Unfold Loop; this is the plant under it.")


def wall():
    return dashboard(
        WALL_UID, "Wall · Unfold", number(first_screen()), tags=["wall", "glide"], kiosk=True,
        variables=[{**VARIABLES[0], "hide": 2}], description="The Unfold plant board's first screen, for a TV.",
        links=[link("Unfold · Plant", f"/d/{UID}")])


def boards():
    return [(desk(), FOLDER), (wall(), "walls")]
