from __future__ import annotations

import re

from lib import (AMBER, CAT, LOGS, NEUTRAL, REPO, SKY, VERMILLION, alarm_at, bars, col, color_overrides, dashboard,
                 doc_link, grid_pos, heatmap, kiosk_steps, link, logs_stats, low_is_bad, number, stat, table,
                 tag_links, target, timeseries, var_query)

UID = "forgejo-ci"
WALL_UID = "wall-ci"
FOLDER = "boards"
TAGS = ["board", "ci", "forgejo"]
DOC = "docs/techdocs/docs/general/forgejo-ci-telemetry.md"
SCALEDJOB = REPO / "kubernetes/apps/forgejo/forgejo-runner/app/scaledjob.yaml"

KSM = 'job="kube-state-metrics", exported_namespace="forgejo"'
RUNNER_POD = 'exported_pod=~"forgejo-runner-[a-z0-9]{5}-[a-z0-9]{5}"'
RUNNER_POD_CADVISOR = 'namespace="forgejo", pod=~"forgejo-runner-[a-z0-9]{5}-[a-z0-9]{5}"'
DIND = 'namespace="forgejo", pod=~"forgejo-dind-.+", container="dind"'
SCALER = 'scaledObject="forgejo-runner"'
REPO_SEL = 'repo=~"$repo"'
WEEK = 604800
EXPORTER_POLL = 300


def scaledjob_capacity():
    text = SCALEDJOB.read_text()
    found = {k: int(re.search(rf"^  {k}:\s*(\d+)", text, re.M).group(1)) for k in ("minReplicaCount", "maxReplicaCount")}
    return found["minReplicaCount"], found["maxReplicaCount"]


WARM, CEILING = scaledjob_capacity()


def red_trunks(extra=""):
    red = f'max by (repo, workflow, ref) (forgejo_ci_last_run_status{{status="failure", {REPO_SEL}{extra}}}) == 1'
    recent = f"time() - max by (repo, workflow, ref) (forgejo_ci_last_run_timestamp_seconds) < {WEEK}"
    return f"({red}) and on (repo, workflow, ref) ({recent})"


VARIABLES = [
    var_query("repo", "Repository", "label_values(forgejo_ci_consecutive_failures, repo)", include_all=True,
              multi=True),
]


def runners_now():
    pods = f'sum(kube_pod_status_phase{{{KSM}, {RUNNER_POD}, phase="Running"}}) or on() vector(0)'
    pending = f'sum(kube_pod_status_phase{{{KSM}, {RUNNER_POD}, phase="Pending"}}) or on() vector(0)'
    busy = 'sum(forgejo_ci_tasks_active{status="running"}) or on() vector(0)'
    waiting = f"max(keda_scaler_metrics_value{{{SCALER}}}) or on() vector(0)"
    panel = stat(
        "Runners, right now", None,
        desc=(f"Busy is tasks Forgejo says are running (the exporter polls every {EXPORTER_POLL // 60} minutes, so "
              "it trails). Pods is runner pods in phase Running, busy or warm. Pending is runner pods the scheduler "
              f"could not place: the real ceiling is node room, not the ScaledJob's maxReplicaCount of {CEILING}, "
              "so a Pending runner is the capacity limit showing itself and turns amber. Waiting is KEDA's own "
              "read of queued docker-label jobs. Ceiling and the warm floor are read from the ScaledJob manifest "
              f"in git when this board is generated ({WARM} warm, {CEILING} max)."),
        targets=[target(busy, "A", "busy", instant=True), target(pods, "B", "pods", instant=True),
                 target(pending, "C", "pending", instant=True), target(waiting, "D", "waiting", instant=True),
                 target(f"vector({CEILING})", "E", "ceiling", instant=True)],
        fixed_color=NEUTRAL, text_mode="value_and_name", decimals=0)
    panel["fieldConfig"]["overrides"] = [col("pending", thresholds=alarm_at(amber=1)),
                                         col("waiting", thresholds=alarm_at(amber=1, vermillion=CEILING))]
    return panel


def queue_wait():
    return stat(
        "Queue wait p95, last hour",
        "histogram_quantile(0.95, sum by (le) (rate(forgejo_ci_run_queue_seconds_bucket[1h])))",
        unit="s", decimals=0, spark=True,
        desc=("How long the slowest twentieth of runs waited between Forgejo creating them and a runner starting "
              "them, trailing hour. Run level: Forgejo stamps a task with its run's start, so there is no honest "
              "per-job queue number. Amber from one minute, vermillion from five, when a push has stopped feeling "
              "like CI and started feeling like waiting. The buckets end at 30 minutes, so a p95 past that reads "
              "as 30 minutes."),
        thresholds=alarm_at(amber=60, vermillion=300), no_value="no runs queued in the last hour")


def trunks_red():
    return stat(
        "Trunks red", f"count({red_trunks()}) or on() vector(0)", decimals=0, value_size=56,
        desc=("Default-branch workflows (main, master, development) whose latest run failed and that ran in the "
              "last seven days. A red trunk is a broken main: everything merged on top of it ships unverified. "
              "Vermillion from one; the table beside it names them and how many runs in a row failed."),
        thresholds=alarm_at(vermillion=1))


def run_duration():
    p50 = "histogram_quantile(0.5, sum by (le) (rate(forgejo_ci_run_duration_seconds_bucket{repo=~\"$repo\"}[7d])))"
    p95 = "histogram_quantile(0.95, sum by (le) (rate(forgejo_ci_run_duration_seconds_bucket{repo=~\"$repo\"}[7d])))"
    panel = stat(
        "Run wall-clock · 7 days", None, unit="s", decimals=0, text_mode="value_and_name",
        desc=("Median and 95th percentile wall-clock of a whole workflow run, created to stopped, trailing seven "
              "days, every outcome and every event: the exporter's run histogram carries repo and workflow only, "
              "so this is not a success-only time to green. Grey: it is a trend to read, not an alarm."),
        targets=[target(p50, "A", "p50", instant=True), target(p95, "B", "p95", instant=True)], fixed_color=NEUTRAL)
    return panel


def data_age():
    return stat(
        "CI data age", "time() - max(forgejo_ci_last_refresh_timestamp_seconds)", unit="s", decimals=0,
        desc=(f"Seconds since forgejo-ci-exporter last finished a poll of the Actions API. It polls every "
              f"{EXPORTER_POLL} s, so up to about {EXPORTER_POLL + 60} s is normal. Amber from 15 minutes, "
              "vermillion from 30, where ForgejoCIOutcomeExporterStale fires: every outcome number on this board "
              "is that old."),
        thresholds=alarm_at(amber=900, vermillion=1800), no_value="exporter not reporting")


def red_trunk_table():
    consecutive = (f"max by (repo, workflow, ref) (forgejo_ci_consecutive_failures) "
                   f"* on (repo, workflow, ref) group_left() ({red_trunks()})")
    since_green = (f"(time() - (max by (repo, workflow, ref) (forgejo_ci_last_success_timestamp_seconds) > 0)) "
                   f"and on (repo, workflow, ref) ({red_trunks()})")
    return table(
        "Red trunks", [target(consecutive, "A", instant=True, fmt="table"),
                       target(since_green, "B", instant=True, fmt="table")],
        rename={"repo": "Repository", "workflow": "Workflow", "ref": "Branch", "Value #A": "Failed in a row",
                "Value #B": "Red for"},
        order=["Repository", "Workflow", "Branch", "Failed in a row", "Red for"], sort_field="Failed in a row",
        no_value="Every trunk that ran this week is green.", cell_height="md",
        overrides=[col("Failed in a row", thresholds=alarm_at(amber=1, vermillion=3), colour_text=True, width=130),
                   col("Red for", unit="s", decimals=0, width=110)],
        desc=("Each red trunk, how many runs in a row failed, and how long since its last green run. An empty "
              "Red for means the last green run is older than the exporter's window: red longer than it can see. "
              "ForgejoCITrunkPipelineFailing fires at three in a row. Fix or revert on the trunk first; anything "
              "merged meanwhile is untested."))


def demand_vs_capacity():
    return timeseries(
        "Demand against runner capacity",
        [target("sum(forgejo_ci_tasks_active{status=\"running\"})", "A", "busy (Forgejo)"),
         target(f"max(keda_scaler_metrics_value{{{SCALER}}})", "B", "waiting (KEDA)"),
         target(f'sum(kube_pod_status_phase{{{KSM}, {RUNNER_POD}, phase="Running"}})', "C", "runner pods"),
         target(f'sum(kube_pod_status_phase{{{KSM}, {RUNNER_POD}, phase="Pending"}})', "D", "pending pods"),
         target(f"vector({CEILING})", "E", "ceiling")],
        unit="short", decimals=0, legend_mode="list",
        overrides=color_overrides([("busy (Forgejo)", SKY), ("waiting (KEDA)", AMBER), ("runner pods", NEUTRAL),
                                   ("pending pods", VERMILLION), ("ceiling", "#5b5a56")]) + [
            {"matcher": {"id": "byName", "options": "ceiling"},
             "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 6]}},
                            {"id": "custom.lineWidth", "value": 1}]}],
        desc=("Busy tasks, queued jobs, runner pods and Pending pods over the range, against the ScaledJob's "
              "ceiling. Waiting above zero while pods sit at the same level for long stretches, with Pending pods "
              "under it, is the node pool out of room: the fix is less CI work per push or another node, not a "
              "higher maxReplicaCount."))


def running_now():
    info = f'max by (task, repo, workflow, ci_job, event, ref, url) (forgejo_ci_task_info{{status="running", {REPO_SEL}}})'
    running = "max by (task) (forgejo_ci_task_running_seconds)"
    typical = "max by (repo, workflow, ci_job) (forgejo_ci_job_duration_p50_seconds)"
    elapsed = f"{running} * on (task) group_right() ({info} * 0 + 1)"
    against = f"({elapsed}) / on (repo, workflow, ci_job) group_left() {typical}"
    return table(
        "Running now", [target(elapsed, "A", instant=True, fmt="table"),
                        target(against, "B", instant=True, fmt="table")],
        rename={"repo": "Repository", "ci_job": "Job", "event": "Event", "ref": "Ref", "Value #A": "Running",
                "Value #B": "vs usual"},
        order=["Repository", "Job", "Event", "Ref", "Running", "vs usual"], hide=["task", "workflow", "url"],
        sort_field="Running", no_value="No job is running.", cell_height="md",
        overrides=[col("Running", unit="s", decimals=0, width=90),
                   col("vs usual", unit="percentunit", decimals=0, width=90, colour_text=True,
                       thresholds=alarm_at(amber=1.5, vermillion=3)),
                   col("Job", links=[{"title": "Open the run in Forgejo", "url": "${__data.fields.url}",
                                      "targetBlank": True}])],
        desc=("Every task Forgejo reports as running, how long it has run, and that time as a share of the job's "
              "usual (its median over the exporter's window). Amber from one and a half times usual, vermillion "
              "from three: a job that far past its median is usually hung on a network call or a lock, and "
              "cancelling it frees a runner. Click a job to open its run."))


def outcomes():
    panel = stat(
        "Jobs by outcome, this range",
        None, decimals=0, text_mode="value_and_name",
        targets=[target(f'sum by (status) (increase(forgejo_ci_jobs_total{{{REPO_SEL}}}[$__range]))', "A",
                        "{{status}}", instant=True)],
        desc=("Finished jobs in the dashboard range, by the outcome Forgejo recorded. Failure is amber from one: "
              "each is a push somebody has to look at. Success, skipped and cancelled stay grey; a cancelled job "
              "is usually a newer push superseding an older one."),
        fixed_color=NEUTRAL)
    panel["fieldConfig"]["overrides"] = [col("failure", thresholds=alarm_at(amber=1))]
    return panel


def dind_ready():
    ready = f'sum(kube_daemonset_status_number_ready{{{KSM}, daemonset="forgejo-dind"}})'
    wanted = f'sum(kube_daemonset_status_desired_number_scheduled{{{KSM}, daemonset="forgejo-dind"}})'
    return stat(
        "dind daemons missing", f"({wanted} - {ready})", decimals=0,
        desc=("Nodes where the shared forgejo-dind daemon is wanted but not ready. Every docker build and every "
              "`container:` job on that node talks to it, so a missing daemon fails those jobs with a docker "
              "socket error that names no cluster component. Vermillion from one."),
        thresholds=alarm_at(vermillion=1), no_value="dind not reported")


def dind_cpu():
    usage = f"sum by (pod) (rate(container_cpu_usage_seconds_total{{{DIND}}}[5m]))"
    limit = (f'max by (exported_pod) (kube_pod_container_resource_limits{{{KSM}, exported_pod=~"forgejo-dind-.+", '
             f'exported_container="dind", resource="cpu"}})')
    expr = f'max({usage} / on (pod) label_replace({limit}, "pod", "$1", "exported_pod", "(.+)"))'
    return stat(
        "Busiest dind against its CPU limit", expr, unit="percentunit", decimals=0, spark=True,
        desc=("The busier docker daemon's CPU as a share of its own limit, five-minute rate. Builds run inside "
              "dind, not in the runner pod, so this is where image builds queue on CPU. Amber from 80 %, "
              "vermillion from 95 %, where builds slow for every repository on that node."),
        thresholds=alarm_at(amber=0.8, vermillion=0.95))


def hub_bypass():
    expr = ('namespace:forgejo container:dind "image pulled" -"harbor.webgrip.dev" '
            '| extract_regexp "remote=\\"(?P<reg>[^/\\"]+)/" from _msg | stats count() as pulls')
    return stat(
        "Pulls around Harbor, this range", None, decimals=0,
        targets=[logs_stats(expr)],
        desc=("Image pulls dind made from a registry other than harbor.webgrip.dev, counted from dind's own "
              "`image pulled` log lines. Each one skips the proxy cache and spends the anonymous Docker Hub rate "
              "limit; the usual culprit is buildx pulling `moby/buildkit` for a docker-container builder. Amber "
              "from one. Log lines are duplicated when the node agent restarts, so read this as a floor on the "
              "problem, not an exact count."),
        thresholds=alarm_at(amber=1), no_value="0", fields="/^pulls$/")


def first_screen():
    placed = [
        (runners_now(), 0, 0, 7, 5), (queue_wait(), 7, 0, 5, 5), (trunks_red(), 12, 0, 3, 5),
        (run_duration(), 15, 0, 5, 5), (data_age(), 20, 0, 4, 5),
        (red_trunk_table(), 0, 5, 12, 9), (demand_vs_capacity(), 12, 5, 12, 9),
        (running_now(), 0, 14, 12, 10), (outcomes(), 12, 14, 6, 5), (dind_ready(), 18, 14, 3, 5),
        (dind_cpu(), 21, 14, 3, 5), (hub_bypass(), 12, 19, 12, 5),
    ]
    panels = []
    for panel, x, y, w, h in placed:
        panel["gridPos"] = grid_pos(x, y, w, h)
        panels.append(panel)
    return panels


def row_pipelines():
    streak = f"max by (repo, workflow, ref) (forgejo_ci_consecutive_failures{{{REPO_SEL}}}) > 0"
    by_event = f"sum by (event, status) (increase(forgejo_ci_runs_total{{{REPO_SEL}}}[1h]))"
    failing_repos = (f'sum by (repo) (increase(forgejo_ci_jobs_total{{status="failure", {REPO_SEL}}}[$__range])) '
                     f"> 0")
    last_trunk = (f"max by (repo, workflow, ref) (forgejo_ci_last_run_timestamp_seconds{{{REPO_SEL}}}) * 1000")
    last_status = f"max by (repo, workflow, ref, status) (forgejo_ci_last_run_status{{{REPO_SEL}}}) == 1"
    return [
        (table("Failure streaks, every branch the exporter grades", [target(streak, "A", instant=True, fmt="table")],
               rename={"repo": "Repository", "workflow": "Workflow", "ref": "Branch", "Value": "Failed in a row"},
               order=["Repository", "Workflow", "Branch", "Failed in a row"], sort_field="Failed in a row",
               no_value="No workflow is on a failure streak.",
               overrides=[col("Failed in a row", thresholds=alarm_at(amber=1, vermillion=3), colour_text=True)],
               desc="Every graded workflow whose latest runs failed, including ones older than the seven days the "
                    "trunk tiles count. A long streak on a scheduled workflow (nightly drift, link rot) is a check "
                    "nobody reads any more: fix it or delete it."), 0, 12, 10),
        (timeseries("Runs per hour, by event and outcome", [target(by_event, "A", "{{event}} · {{status}}")],
                    unit="short", draw="bars", stack=True, decimals=0,
                    desc="Finished runs per hour by trigger and outcome. A block of push failures right after a "
                         "merge is a broken trunk; a block of pull_request failures is somebody iterating, which is "
                         "what pull requests are for."), 12, 12, 10),
        (bars("Repositories with failed jobs, this range", [target(failing_repos, "A", "{{repo}}", instant=True)],
              decimals=0, fixed_color=AMBER, no_value="No job failed in this range.",
              desc="Failed jobs per repository over the dashboard range, largest first. Open the repository's "
                   "Actions tab to see which job and why; Forgejo records no failure reason the exporter can "
                   "read."), 0, 12, 9),
        (table("Latest trunk run per workflow",
               [target(last_status, "A", instant=True, fmt="table"), target(last_trunk, "B", instant=True, fmt="table")],
               rename={"repo": "Repository", "workflow": "Workflow", "ref": "Branch", "status": "Status",
                       "Value #B": "Ran"},
               order=["Repository", "Workflow", "Branch", "Status", "Ran"], hide=["Value #A"], sort_field="Ran",
               overrides=[col("Ran", unit="dateTimeFromNow", width=140),
                          col("Status", colour_text=True, mappings=[{"type": "value", "options": {
                              "failure": {"text": "failure", "color": VERMILLION},
                              "success": {"text": "success", "color": NEUTRAL},
                              "cancelled": {"text": "cancelled", "color": NEUTRAL}}}])],
               desc="The newest default-branch run of every workflow the exporter grades, and when it ran. Pull "
                    "requests are left out by design: a red pull request is work in progress, a red trunk is a "
                    "defect."), 12, 12, 9),
    ]


def row_time():
    slowest = (f"max by (repo, workflow, ci_job) (forgejo_ci_job_duration_p50_seconds{{{REPO_SEL}}})",
               f"max by (repo, workflow, ci_job) (forgejo_ci_job_duration_p95_seconds{{{REPO_SEL}}})",
               f"max by (repo, workflow, ci_job) (forgejo_ci_job_duration_max_seconds{{{REPO_SEL}}})",
               f"max by (repo, workflow, ci_job) (forgejo_ci_job_runs_sampled{{{REPO_SEL}}})")
    run_q = "histogram_quantile({q}, sum by (le) (rate(forgejo_ci_run_duration_seconds_bucket{{repo=~\"$repo\"}}[6h])))"
    queue_q = "histogram_quantile({q}, sum by (le) (rate(forgejo_ci_run_queue_seconds_bucket[1h])))"
    return [
        (table("Slowest jobs: a typical day against a bad one",
               [target(e, r, instant=True, fmt="table") for e, r in zip(slowest, "ABCD")],
               rename={"repo": "Repository", "workflow": "Workflow", "ci_job": "Job", "Value #A": "Typical (p50)",
                       "Value #B": "Bad day (p95)", "Value #C": "Worst", "Value #D": "Runs"},
               order=["Repository", "Workflow", "Job", "Typical (p50)", "Bad day (p95)", "Worst", "Runs"],
               sort_field="Typical (p50)",
               overrides=[col("Typical (p50)", unit="s", decimals=0, gauge=True),
                          col("Bad day (p95)", unit="s", decimals=0), col("Worst", unit="s", decimals=0),
                          col("Runs", decimals=0)],
               desc="Every job the exporter samples, by its median duration, with its 95th percentile and worst run. "
                    "The top of this list is where CI minutes go; a p95 far above its p50 is a job whose speed "
                    "depends on the node or a cache, not on the change."), 0, 24, 12),
        (timeseries("Run wall-clock p50 and p95", [target(run_q.format(q=0.5), "A", "p50"),
                                                   target(run_q.format(q=0.95), "B", "p95")],
                    unit="s", overrides=color_overrides([("p50", CAT[0]), ("p95", CAT[1])]),
                    desc="Run duration percentiles over a trailing six hours, all outcomes and events."), 0, 12, 8),
        (timeseries("Queue wait p50 and p95", [target(queue_q.format(q=0.5), "A", "p50"),
                                               target(queue_q.format(q=0.95), "B", "p95")],
                    unit="s", thresholds=alarm_at(amber=60, vermillion=300),
                    overrides=color_overrides([("p50", CAT[0]), ("p95", CAT[1])]),
                    desc="Run queue wait percentiles over a trailing hour, against the same one and five minute "
                         "lines the first screen uses."), 12, 12, 8),
        (heatmap("Job durations", [target(f'sum by (le) (increase(forgejo_ci_job_duration_seconds_bucket{{{REPO_SEL}}}'
                                          f'[$__rate_interval]))', "A", "{{le}}", fmt="heatmap")],
                 desc="How long finished jobs took, per time bucket. Two bands is normal (fast checks and slow image "
                      "builds); a band that climbs over days is a job getting slower."), 0, 24, 8),
    ]


def row_fleet():
    pods_by_node = (f'count by (node) (kube_pod_info{{{KSM}, {RUNNER_POD}}} * on (exported_pod) group_left() '
                    f'(kube_pod_status_phase{{{KSM}, {RUNNER_POD}, phase="Running"}} == 1))')
    cpu = f"sum by (pod) (rate(container_cpu_usage_seconds_total{{{RUNNER_POD_CADVISOR}, image!=\"\"}}[5m]))"
    mem = f"max by (pod) (container_memory_working_set_bytes{{{RUNNER_POD_CADVISOR}, image!=\"\"}})"
    return [
        (timeseries("Runner pods per node", [target(pods_by_node, "A", "{{node}}")], unit="short", stack=True,
                    decimals=0, desc="Running runner pods on each node. All of them on one node means every job "
                                     "competes for that node's disk and one dind."), 0, 8, 8),
        (timeseries("Runner CPU per pod", [target(cpu, "A", "{{pod}}")], unit="short", legend_mode="hidden",
                    desc="CPU of each runner pod, cores. Host-mode steps only: builds run in dind."), 8, 8, 8),
        (timeseries("Runner memory per pod", [target(mem, "A", "{{pod}}")], unit="bytes", legend_mode="hidden",
                    desc="Working set of each runner pod against its limit (6 GiB when this board was written); a "
                         "pod climbing to the limit is killed without a Forgejo error."), 16, 8, 8),
        (stat("Runner and dind OOM kills, this range",
              'sum(increase(container_oom_events_total{namespace="forgejo", pod=~"forgejo-(runner|dind)-.+"}[$__range]))',
              decimals=0, thresholds=alarm_at(amber=1), no_value="0",
              desc="Out-of-memory kills in runner and dind containers. A killed runner leaves its job hanging "
                   "until Forgejo times it out; amber from one."), 0, 6, 5),
        (stat("KEDA scaler errors, this range",
              f"sum(increase(keda_scaler_detail_errors_total{{{SCALER}}}[$__range])) or on() vector(0)", decimals=0,
              thresholds=alarm_at(amber=1, vermillion=20),
              desc="Failed reads of the Forgejo job queue by KEDA. While they fail only the warm floor runs jobs; "
                   "the July 2026 cause was the keda namespace missing from forgejo-allow-ingress."), 6, 6, 5),
        (stat("KEDA scaler read latency", f"max(keda_scaler_metrics_latency_seconds{{{SCALER}}})", unit="s",
              decimals=2, spark=True, thresholds=alarm_at(amber=2, vermillion=10),
              desc="How long KEDA's last read of the Forgejo job queue took."), 12, 6, 5),
        (stat("Runner restarts, this range",
              f'sum(increase(kube_pod_container_status_restarts_total{{{KSM}, exported_pod=~"forgejo-(runner|dind)-.+"}}[$__range]))',
              decimals=0, thresholds=alarm_at(amber=1), no_value="0",
              desc="Container restarts in runner and dind pods. A restarted dind drops every build running on "
                   "that node."), 18, 6, 5),
    ]


def row_builders():
    dind_cpu_ts = f"sum by (pod) (rate(container_cpu_usage_seconds_total{{{DIND}}}[5m]))"
    throttled = (f"max by (pod) (rate(container_cpu_cfs_throttled_periods_total{{{DIND}}}[5m]) "
                 f"/ clamp_min(rate(container_cpu_cfs_periods_total{{{DIND}}}[5m]), 1e-9))")
    harbor = "sum by (code) (rate(harbor_core_http_request_total[5m]))"
    pulls = "sum by (project_name) (increase(harbor_artifact_pulled[1h])) > 0"
    registry = ('namespace:forgejo container:dind "image pulled" '
                '| extract_regexp "remote=\\"(?P<registry>[^/\\"]+)/" from _msg | stats by (registry) count() as pulls')
    return [
        (timeseries("dind CPU per node", [target(dind_cpu_ts, "A", "{{pod}}")], unit="short",
                    desc="Cores each docker daemon uses: this is where image builds and job containers run."),
         0, 8, 8),
        (timeseries("dind CPU throttling", [target(throttled, "A", "{{pod}}")], unit="percentunit",
                    thresholds=alarm_at(amber=0.25),
                    desc="Share of CFS periods in which dind hit its CPU limit. Sustained above a quarter, builds are "
                         "waiting on the limit rather than on work."), 8, 8, 8),
        (bars("Image pulls by dind, this range, per registry", [logs_stats(registry, legend="{{registry}}")],
              decimals=0, no_value="no pulls logged",
              desc="Pulls dind logged, by the registry host. Anything other than harbor.webgrip.dev bypasses the "
                   "proxy cache."), 16, 8, 8),
        (timeseries("Harbor requests by status", [target(harbor, "A", "{{code}}")], unit="reqps",
                    desc="Harbor core requests per second by HTTP status. 401s are anonymous token handshakes and "
                         "normal; 5xx is Harbor failing pulls for every build."), 0, 12, 8),
        (timeseries("Harbor pulls per hour, by project", [target(pulls, "A", "{{project_name}}")], unit="short",
                    draw="bars", stack=True, decimals=0,
                    desc="Artifacts pulled per hour per Harbor project; the proxy projects (dockerhub, ghcr, quay) "
                         "are the caches CI leans on."), 12, 12, 8),
    ]


def row_nodes():
    psi = ("max by (nodename) (rate(node_pressure_{kind}_waiting_seconds_total[5m]) * on (instance) "
           "group_left(nodename) node_uname_info)")
    ci_share = ('sum by (node) (rate(container_cpu_usage_seconds_total{namespace="forgejo", image!=""}[5m]) '
                '* on (namespace, pod) group_left(node) max by (namespace, pod, node) '
                '(label_replace(label_replace(kube_pod_info{job="kube-state-metrics", exported_namespace="forgejo"}, '
                '"namespace", "$1", "exported_namespace", "(.+)"), "pod", "$1", "exported_pod", "(.+)")))')
    return [
        (timeseries("I/O pressure per node", [target(psi.format(kind="io"), "A", "{{nodename}}")],
                    unit="percentunit", thresholds=alarm_at(amber=0.2, vermillion=0.5),
                    desc="Share of time tasks on each node waited on I/O (PSI). CI is disk-bound here: the "
                         "flux-local render and image layer unpacking both saturate it."), 0, 8, 8),
        (timeseries("CPU pressure per node", [target(psi.format(kind="cpu"), "A", "{{nodename}}")],
                    unit="percentunit", thresholds=alarm_at(amber=0.2, vermillion=0.5),
                    desc="Share of time runnable tasks waited for a CPU."), 8, 8, 8),
        (timeseries("Forgejo namespace CPU per node", [target(ci_share, "A", "{{node}}")], unit="short",
                    desc="Cores the forgejo namespace (runners, dind, server) uses on each node."), 16, 8, 8),
    ]


def row_logs():
    by_repo = ('namespace:forgejo container:runner "repo is" '
               '| extract_regexp "task (?P<task>[0-9]+) repo is (?P<repo>[^ ]+)" from _msg '
               '| stats by (repo) count_uniq(task) as tasks')
    problems = 'namespace:forgejo container:runner ("level=error" OR "level=warning" OR RESULT_CANCELLED)'
    panel = {
        "type": "logs", "title": "Runner warnings, errors and cancellations", "datasource": LOGS,
        "gridPos": grid_pos(0, 0, 16, 10),
        "description": "The runner agent's own warning and error lines, and every task it reported cancelled. Job "
                       "step output never reaches pod stdout here; open the run in Forgejo for that.",
        "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True,
                    "dedupStrategy": "exact"},
        "targets": [{"refId": "A", "expr": problems, "queryType": "instant", "datasource": LOGS}],
    }
    return [
        (panel, 0, 16, 10),
        (bars("Tasks picked up per repository, this range", [logs_stats(by_repo, legend="{{repo}}")], decimals=0,
              desc="Distinct tasks runners picked up per repository, from the runner's `task N repo is` line. "
                   "Distinct task ids, so the duplicate lines of an agent restart do not inflate it."), 16, 8, 10),
    ]


def row_exporter():
    return [
        (stat("Repositories tracked", "max(forgejo_ci_repos_tracked)", decimals=0, fixed_color=NEUTRAL,
              desc="Repositories forgejo-ci-exporter polls."), 0, 4, 4),
        (stat("Refresh errors, this range", "sum(increase(forgejo_ci_refresh_errors_total[$__range]))", decimals=0,
              thresholds=alarm_at(amber=5, vermillion=50),
              desc="Failed Actions API calls during polls. A few a day are Forgejo restarts."), 4, 5, 4),
        (stat("Poll duration", "max(forgejo_ci_refresh_duration_seconds)", unit="s", decimals=0, spark=True,
              thresholds=alarm_at(amber=120, vermillion=240),
              desc="How long the last poll of every tracked repository took. Past the poll interval, polls "
                   "overlap and data ages."), 9, 5, 4),
        (stat("Runner inventory readable", "max(forgejo_ci_runner_inventory_up)", decimals=0,
              mappings=[{"type": "value", "options": {"0": {"text": "no: token lacks runner scope"},
                                                     "1": {"text": "yes"}}}],
              fixed_color=NEUTRAL,
              desc="Whether the exporter's token can list runners. At 0 the runner inventory series are absent; "
                   "this board does not depend on them."), 14, 10, 4),
    ]


def rows():
    sections = [
        ("Trunks and pipelines", row_pipelines()),
        ("Where job time goes", row_time()),
        ("Runner fleet", row_fleet()),
        ("Builders and registries", row_builders()),
        ("Nodes under CI", row_nodes()),
        ("Runner logs", row_logs()),
        ("Exporter health", row_exporter()),
    ]
    return sections


def lay_out_rows(top, sections):
    from lib import row as row_panel
    panels = []
    y = top
    for title, placed in sections:
        section = row_panel(title, y, collapsed=True)
        y += 1
        band_y, band_x, band_h = y, 0, 0
        for panel, x, w, h in placed:
            if x == 0 and band_x:
                band_y += band_h
                band_h = 0
            panel["gridPos"] = grid_pos(x, band_y, w, h)
            band_x = x + w
            band_h = max(band_h, h)
            section["panels"].append(panel)
        y = band_y + band_h
        panels.append(section)
    return panels


LINKS = [link("Forgejo Actions", "https://forgejo.webgrip.dev/webgrip/homelab-cluster/actions", icon="external link",
              blank=True),
         link("Runner deep dive", "/d/infra-forgejo-ci-runners"),
         doc_link("CI telemetry", DOC),
         tag_links(["board"], "Boards")]


def desk():
    screen = first_screen()
    panels = number(screen + lay_out_rows(24, rows()))
    return dashboard(
        UID, "Forgejo CI", panels, tags=TAGS, variables=VARIABLES, links=LINKS, time_from="now-24h",
        description="Is CI keeping up, is trunk green, and where does the time go. Runners, queue, red trunks and "
                    "the builders on the first screen; pipelines, durations, fleet, builders, nodes, logs and the "
                    "exporter in the collapsed rows.")


def wall():
    screen = number(first_screen())
    return dashboard(
        WALL_UID, "Wall · Forgejo CI", screen, tags=["wall", "ci"], kiosk=True, time_from="now-24h",
        variables=[{**VARIABLES[0], "hide": 2}],
        description="The Forgejo CI board's first screen, for a TV.", links=[link("Forgejo CI", f"/d/{UID}")])


def boards():
    return [(desk(), FOLDER), (wall(), "walls")]
