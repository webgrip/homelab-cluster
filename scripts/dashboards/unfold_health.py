from __future__ import annotations

from lib import (NEUTRAL, VERMILLION, alarm_at, bars, col, dashboard, grid_pos, kiosk_steps, link, logs_stats,
                 low_is_bad, number, sql, stat, table, tag_links, target)

UID = "unfold-health"
FOLDER = "boards"
TAGS = ["board", "glide", "unfold"]
GLIDE_DOCS = "https://docs.webgrip.dev/glide/"

KSM = 'job="kube-state-metrics", exported_namespace="ploeg"'
UNFOLD_POD = 'exported_pod=~"unfold-.+"'
UNFOLD_LOGS = "namespace:=ploeg container:=workbench pod:unfold*"
PLOEG_DB = {"type": "grafana-postgresql-datasource", "uid": "ploeg-db"}
HOUR = 3600
DEDUPED = ("Each line counts once per timestamp, because the log shipper sometimes delivers the same line more than "
           "once.")
NOT_RELEASED = ("Unfold's development branch logs this; the release running on the homelab (0.4.0-rc.125) does not "
                "yet, so the panel stays empty until a newer release is deployed.")


def events(selector, stats):
    return f"{UNFOLD_LOGS} {selector} | {stats}"


def counted(selector, name):
    return events(selector, f"stats count_uniq(_time) as {name}")


def counted_by(selector, by, name):
    return events(selector, f"stats by ({by}) count_uniq(_time) as {name}")


def logs_table(title, expr, *, order, rename, sort_field, desc, no_value, overrides=None):
    panel = table(title, [logs_stats(expr)], desc=desc, rename=rename, order=order, sort_field=sort_field,
                  no_value=no_value, overrides=overrides)
    panel["transformations"] = [{"id": "labelsToFields", "options": {"mode": "columns", "valueLabel": "__name__"}},
                                {"id": "merge", "options": {}}] + panel["transformations"]
    return panel


def with_time_from(panel, span):
    panel["timeFrom"] = span
    return panel


def unfold_up():
    return stat(
        "Unfold up", f'max(kube_deployment_status_replicas_available{{{KSM}, deployment="unfold"}}) or on() vector(0)',
        decimals=0, thresholds=kiosk_steps((VERMILLION, 0), (NEUTRAL, 1)), value_size=48,
        mappings=[{"type": "value", "options": {"0": {"text": "down"}}}],
        desc="How many Unfold pods are ready to answer right now, from Kubernetes. Unfold runs one pod, so 1 is "
             "healthy and 0 (red, shown as down) means nobody can open Unfold.")


def version_running():
    expr = events('event:="ploeg.contract_compatible"',
                  "first 1 by (_time desc) | stats by (unfold, ploeg) count() as pods")
    return with_time_from(stat(
        "Running release", None, text_mode="name", fixed_color=NEUTRAL, no_value="no start logged in 30 days",
        targets=[logs_stats(expr, legend="Unfold {{unfold}} · Ploeg {{ploeg}}")],
        desc="The Unfold release tag of the newest pod, and the Ploeg release it connected to, read from the "
             "line Unfold logs when it finds Ploeg compatible (ploeg.contract_compatible) shortly after it "
             "starts. Looks back 30 days, so a pod that has run longer than that shows nothing here."), "30d")


def healthz():
    return stat(
        "Reachable through the gateway",
        'avg_over_time(probe_success{endpoint="unfold"}[$__range])', unit="percentunit", decimals=2,
        thresholds=low_is_bad(0.99, 0.999),
        desc="Share of the 15-second blackbox checks of Unfold's /healthz, through the internal gateway, that "
             "succeeded in this time range. Amber below 99.9 %, red below 99 %.")


def pods_started():
    created = f"max by (exported_pod) (max_over_time(kube_pod_created{{{KSM}, {UNFOLD_POD}}}[$__range]))"
    return stat(
        "Pods started", f"count({created} > time() - $__range_s) or on() vector(0)", decimals=0,
        thresholds=alarm_at(amber=4, vermillion=10),
        desc="Unfold pods created in this time range. A release or a configuration change starts one or two; "
             "more means pods keep dying and being replaced, which a person sees as Unfold dropping out. Amber "
             "from 4, red from 10.")


def restarts():
    expr = (f"sum(increase(kube_pod_container_status_restarts_total{{{KSM}, {UNFOLD_POD}, "
            f'exported_container="workbench"}}[$__range])) or on() vector(0)')
    return stat(
        "Container restarts", f"round({expr})", decimals=0, thresholds=alarm_at(amber=1, vermillion=5),
        desc="Times Kubernetes restarted the Unfold container inside a pod in this time range, usually after a "
             "crash or a failed health check. Amber from 1, red from 5.")


def startup_failures():
    return stat(
        "Failed starts", None, decimals=0, thresholds=alarm_at(vermillion=1), no_value="0",
        targets=[logs_stats(counted('event:="startup.failed"', "failed"))],
        desc="Times Unfold gave up while starting (startup.failed), for example because its data volume or "
             "database could not be opened. Red from 1: read the message in VictoriaLogs with "
             '`namespace:=ploeg container:=workbench event:="startup.failed"`. ' + DEDUPED)


def server_errors():
    return stat(
        "Server errors", None, decimals=0, thresholds=alarm_at(amber=1, vermillion=20), no_value="0",
        targets=[logs_stats(counted('event:="error.reported" feature:=http', "errors"))],
        desc="Requests Unfold answered with a 5xx error in this time range, from the error report it logs for "
             "each one (error.reported, feature http). 4xx answers are not counted: Unfold does not log them. "
             "Amber from 1, red from 20. " + DEDUPED)


def errors_by_code():
    expr = counted_by('event:="error.reported" feature:=http', "code, route", "reports")
    return logs_table(
        "Server errors by code and route", expr, order=["Code", "Route", "Errors"],
        rename={"code": "Code", "route": "Route", "reports": "Errors"}, sort_field="Errors",
        no_value="No server errors in this range.",
        overrides=[col("Errors", decimals=0, width=80), col("Code", width=190)],
        desc="Every 5xx answer in this time range, grouped by the error code from Unfold's error catalogue and "
             "the route shape. A code that is not in the catalogue (for example ERR_SQLITE_ERROR) is a raw "
             "failure Unfold did not translate, usually its database or disk. " + DEDUPED)


def errors_by_area():
    expr = counted_by('event:="error.reported"', "feature", "reports")
    return bars(
        "Error reports by area", [logs_stats(expr, legend="{{feature}}")], decimals=0,
        no_value="No error reports in this range.",
        desc="Error reports by the part of Unfold that raised them: http is a failed request, ask a failed Ask, "
             "process an uncaught crash, store the database upkeep. Neutral bars: compare the mix, then read "
             "the table beside it. " + DEDUPED)


def ploeg_link():
    targets = [
        logs_stats(counted('event:="ploeg.contract_incompatible"', "incompatible"), "A", "contract refused"),
        logs_stats(counted('event:="ploeg.version_unreadable"', "unreadable"), "B", "version unreadable"),
        logs_stats(counted('event:="error.reported" code:=ploeg_unavailable', "unavailable"), "C",
                   "Ploeg unavailable"),
    ]
    panel = stat(
        "Ploeg link", None, decimals=0, text_mode="value_and_name", targets=targets, no_value="0",
        thresholds=alarm_at(amber=1),
        desc="How Unfold's connection to Ploeg went in this time range. Contract refused (red from 1) means "
             "Ploeg stopped serving a contract version this Unfold needs and Unfold refuses to act through it. "
             "Version unreadable (amber) means Unfold could not ask Ploeg which contracts it serves and kept "
             "its last answer. Ploeg unavailable (amber) counts requests that failed because Ploeg did not "
             "answer. " + DEDUPED)
    panel["fieldConfig"]["overrides"] = [col("contract refused", thresholds=alarm_at(vermillion=1))]
    return panel


def ask_outcomes():
    expr = 'sum by (outcome) (round(increase(ploeg_runs_finished_total{job="ploeg", role="ask"}[$__range]))) > 0'
    return bars(
        "Ask Runs by outcome", [target(expr, "A", "{{outcome}}", instant=True)], decimals=0,
        no_value="No Ask finished in this range.",
        desc="How the Ask Runs Ploeg finished in this time range ended, from ploegd's own counter. An answered "
             "Ask ends as other; failed is the one to read. Counts restart from zero when ploegd restarts, so "
             "read this as a floor.")


def ask_failures():
    return bars(
        "Asks Unfold could not answer", [logs_stats(counted_by("event:ask.*", "code", "asks"), legend="{{code}}")],
        decimals=0, fixed_color=VERMILLION, no_value="No Ask failed in this range.",
        desc="Asks that failed or were refused on Unfold's side in this time range, by failure code: "
             "not_admitted and allowance_used_up mean Ploeg refused to fund it, rate_limited and timeout mean "
             "the model provider was busy or slow. " + DEDUPED)


ASK_SPEND = ("COALESCE(a.reconciled_spend, a.observed_spend, CASE WHEN jsonb_typeof(r.usage->'costUsd') = 'number' "
             "THEN (r.usage->>'costUsd')::numeric END)")
ASK_RUNS = ("FROM agent_runs r LEFT JOIN run_llm_accounts a ON a.alias = r.trace_alias "
            "WHERE r.role = 'ask' AND $__timeFilter(coalesce(r.started_at, r.finished_at))")


def nl_dollars(amount):
    return (f"'US' || chr(36) || ' ' || translate(to_char(round(coalesce({amount}, 0)::numeric, 2), "
            f"'FM999G999G990D00'), ',.', '.,')")


def ask_spend_total():
    panel = stat(
        "Ask spend", None, fixed_color=NEUTRAL, no_value="nothing asked", fields="/.*/",
        targets=[sql(PLOEG_DB, f"SELECT {nl_dollars(f'sum({ASK_SPEND})')} AS spend {ASK_RUNS}")],
        desc="What every Ask Run in this time range cost, in US dollars: per Run the reconciled LiteLLM spend, "
             "else the observed spend, else what the Run reported. Read from Ploeg's database, like the Unfold "
             "Loop board's spend tiles.")
    panel["fieldConfig"]["defaults"]["unit"] = "string"
    return panel


def ask_spend_by_team():
    raw = (f'SELECT r.team AS "Team", count(*) AS "Asks", {nl_dollars(f"sum({ASK_SPEND})")} AS "Spend", '
           f'count(*) FILTER (WHERE a.reconciled_spend IS NULL) AS "Not settled" {ASK_RUNS} '
           "GROUP BY r.team ORDER BY count(*) DESC")
    return table(
        "Asks and spend per team", [sql(PLOEG_DB, raw)], no_value="No Ask in this range.",
        overrides=[col("Asks", decimals=0, width=70), col("Not settled", decimals=0, width=100,
                                                         thresholds=alarm_at(amber=1), colour_text=True)],
        desc="Ask Runs per team in this time range and what they cost in US dollars. Not settled counts Asks "
             "whose gateway spend is not reconciled yet, so the spend still reads low; amber from 1.")


def dead_jobs():
    return bars(
        "Jobs given up, by kind", [logs_stats(counted_by('event:="job.dead"', "kind", "jobs"), legend="{{kind}}")],
        decimals=0, fixed_color=VERMILLION, no_value="No job given up in this range.",
        desc="Background jobs Unfold stopped retrying in this time range (job.dead), by kind: notify.notice is a "
             "notification, outbound.delivery a webhook, billing.line a billing line, report.file a filed "
             "problem report. How many wait or retry is not logged; an administrator reads that at "
             "GET /api/admin/jobs. " + NOT_RELEASED)


def delivery_failures():
    selector = ('event:in("outbound.delivery_dead", "outbound.subscription_disabled", "outbound.loop_failed", '
                '"notify.loop_failed", "notify.vapid_invalid")')
    return bars(
        "Webhook and notification failures", [logs_stats(counted_by(selector, "event", "failures"),
                                                         legend="{{event}}")],
        decimals=0, fixed_color=VERMILLION, no_value="No delivery failure in this range.",
        desc="Webhook deliveries given up (outbound.delivery_dead), webhook subscriptions switched off because "
             "the receiver answered 410 Gone, the webhook or notification sender stopping on an error, and "
             "Web Push off because its keys are invalid. A single failed attempt that a retry fixed is not "
             "logged. " + NOT_RELEASED)


def checkpoint_age():
    expr = events('event:="audit.checkpoint"', "stats max(_time) as last, count() as written | filter written:>0 "
                  "| math round((now() - last) / 1e9) as age_seconds | fields age_seconds")
    return with_time_from(stat(
        "Last audit checkpoint", None, unit="s", decimals=0, no_value="none in 3 days",
        thresholds=alarm_at(amber=26 * HOUR, vermillion=48 * HOUR), targets=[logs_stats(expr)],
        desc="How long ago Unfold last signed the head of its audit chain and copied it off the box "
             "(audit.checkpoint). It does this once a day, so amber from 26 hours and red from 48, when "
             "GET /api/admin/audit/verify starts calling the chain stale. " + NOT_RELEASED), "3d")


def checkpoint_failures():
    return stat(
        "Audit checkpoint failures", None, decimals=0, no_value="0", thresholds=alarm_at(amber=1, vermillion=2),
        targets=[logs_stats(counted('event:="audit.checkpoint_failed"', "failures"))],
        desc="Times Unfold could not sign a checkpoint with OpenBao or store it in the bucket in this time range "
             "(audit.checkpoint_failed, logged at most once an hour). The UnfoldAuditCheckpointFailing alert "
             "fires from 2 in three hours. " + NOT_RELEASED)


def store_upkeep():
    return stat(
        "Database upkeep failures", None, decimals=0, no_value="0", thresholds=alarm_at(amber=1),
        targets=[logs_stats(counted('event:="store.upkeep_failed"', "failures"))],
        desc="Times Unfold's routine database upkeep failed in this time range (store.upkeep_failed). Together "
             "with ERR_SQLITE_ERROR in the server error table it says the SQLite file or its disk is in trouble. "
             + DEDUPED)


def running_pods():
    running = f'(max by (exported_pod) (kube_pod_status_phase{{{KSM}, {UNFOLD_POD}, phase="Running"}}) == 1)'
    ready = f'max by (exported_pod) (kube_pod_status_ready{{{KSM}, {UNFOLD_POD}, condition="true"}})'
    restarted = (f"max by (exported_pod) (kube_pod_container_status_restarts_total{{{KSM}, {UNFOLD_POD}, "
                 f'exported_container="workbench"}})')
    started = f"max by (exported_pod) (kube_pod_start_time{{{KSM}, {UNFOLD_POD}}}) * 1000"
    return table(
        "Unfold pods now",
        [target(f"{ready} and on (exported_pod) {running}", "A", instant=True, fmt="table"),
         target(f"{restarted} and on (exported_pod) {running}", "B", instant=True, fmt="table"),
         target(f"{started} and on (exported_pod) {running}", "C", instant=True, fmt="table")],
        rename={"exported_pod": "Pod", "Value #A": "Ready", "Value #B": "Restarts", "Value #C": "Started"},
        order=["Pod", "Ready", "Restarts", "Started"], no_value="No Unfold pod is running.",
        overrides=[col("Ready", width=80, colour_text=True, mappings=[{"type": "value", "options": {
                       "0": {"text": "no", "color": VERMILLION}, "1": {"text": "yes", "color": NEUTRAL}}}]),
                   col("Restarts", decimals=0, width=90, colour_text=True, thresholds=alarm_at(amber=1)),
                   col("Started", unit="dateTimeFromNow", width=130)],
        desc="Each running Unfold pod: whether Kubernetes counts it ready, how often its container restarted, "
             "and when it started.")


def versions_seen():
    expr = events('event:="ploeg.contract_compatible"',
                  "stats by (unfold, ploeg) count_uniq(pod) as pods, max(_time) as last "
                  "| math round(last / 1e6) as last_ms | fields unfold, ploeg, pods, last_ms")
    return logs_table(
        "Releases started in this range", expr, order=["Unfold", "Ploeg", "Pods", "Last start"],
        rename={"unfold": "Unfold", "ploeg": "Ploeg", "pods": "Pods", "last_ms": "Last start"},
        sort_field="Last start", no_value="No Unfold pod started in this range.",
        overrides=[col("Pods", decimals=0, width=70), col("Last start", unit="dateTimeFromNow", width=130)],
        desc="Each Unfold release that started in this time range, the Ploeg release it found, how many pods "
             "ran it and when the last of them started. Many pods on one release means that release kept being "
             "replaced; compare with Pods started.")


def placed():
    return [
        (unfold_up(), 0, 0, 3, 5), (version_running(), 3, 0, 5, 5), (healthz(), 8, 0, 4, 5),
        (pods_started(), 12, 0, 3, 5), (restarts(), 15, 0, 3, 5), (startup_failures(), 18, 0, 3, 5),
        (server_errors(), 21, 0, 3, 5),
        (errors_by_code(), 0, 5, 12, 8), (ploeg_link(), 12, 5, 6, 8), (errors_by_area(), 18, 5, 6, 8),
        (ask_outcomes(), 0, 13, 6, 7), (ask_failures(), 6, 13, 6, 7), (ask_spend_total(), 12, 13, 4, 7),
        (ask_spend_by_team(), 16, 13, 8, 7),
        (dead_jobs(), 0, 20, 6, 6), (delivery_failures(), 6, 20, 6, 6), (checkpoint_age(), 12, 20, 4, 6),
        (checkpoint_failures(), 16, 20, 4, 6), (store_upkeep(), 20, 20, 4, 6),
        (running_pods(), 0, 26, 10, 7), (versions_seen(), 10, 26, 14, 7),
    ]


LINKS = [link("Unfold · Plant", "/d/glide-plant"), link("Unfold Loop", "/d/glide-loop"),
         link("Unfold · Needs-you insight", "/d/unfold-insight"),
         link("Unfold docs", GLIDE_DOCS, icon="doc", blank=True), tag_links(["board"], "Boards")]


def health():
    panels = []
    for panel, x, y, w, h in placed():
        panel["gridPos"] = grid_pos(x, y, w, h)
        panels.append(panel)
    return dashboard(
        UID, "Unfold · Health", number(panels), tags=TAGS, links=LINKS, time_from="now-24h",
        description="Is the Unfold application itself healthy: up, which release, crashes, server errors, the "
                    "Ploeg link, Asks and their cost, background deliveries and audit checkpoints. Ploeg's Runs "
                    "and workers are on Unfold · Plant. Unfold logs no rate-limit refusals and no job queue "
                    "depth yet, so neither is shown.")


def boards():
    return [(health(), FOLDER)]
