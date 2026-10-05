from __future__ import annotations

from lib import (AMBER, NEUTRAL, SKY, VERMILLION, alarm_at, col, dashboard, grid_pos, link, number, sql, stat, table,
                 tag_links, target, text, timeseries)

RUNS_UID = "glide-runs"
KATA_UID = "glide-kata"
FOLDER = "boards"
TAGS = ["board", "glide", "ploeg"]
PLOEG_DB = {"type": "grafana-postgresql-datasource", "uid": "ploeg-db"}
MIXED = {"type": "datasource", "uid": "-- Mixed --"}

KSM = 'job="kube-state-metrics", exported_namespace="ploeg"'
CADVISOR = 'job="cadvisor", namespace="ploeg"'
POD_CGROUP = 'container="", id=~"/kubepods(/[a-z]+)?/pod[^/]+"'
RUN_POD = 'exported_pod=~"(sbx-)?ploeg-worker-($team)-.+"'
SANDBOX_POD = 'exported_pod=~"sbx-ploeg-worker-($team)-.+"'
RUNC_POD = 'exported_pod=~"ploeg-worker-($team)-.+"'
KATA_NODES = "worker-1|worker-2|fringe-workstation"
LIVE = 'phase=~"Pending|Running"'
KATA_RUN_CPU = 0.2
KATA_RUN_MEMORY = (768 + 160) * 2 ** 20

WORK_ITEM = ("CASE WHEN w.provider = 'vikunja' THEN 'vikunja #' || w.external_id WHEN w.provider = 'manual' "
             "THEN 'unfold ' || left(split_part(w.external_id, ':', 2), 8) ELSE w.provider || ' ' || w.external_id END")
WORK_ITEM_URL = ("CASE WHEN w.provider = 'vikunja' THEN 'https://vikunja.webgrip.dev/tasks/' || w.external_id "
                 "ELSE coalesce(nullif(w.url, ''), 'https://unfold.webgrip.dev') END")
QUEUED_AT = ("LEFT JOIN LATERAL (SELECT max(l.at) AS at FROM audit_log l "
             "WHERE l.action IN ('round.opened', 'round.reopened') AND l.detail->>'shift' = r.shift_id::text "
             "AND l.detail->>'round' = r.round::text AND l.at <= coalesce(r.started_at, now())) q ON true")
RUN_POD_ROW = ("LEFT JOIN LATERAL (SELECT c.node_name, c.pod_uid FROM checkpoints c "
               "WHERE c.work_item_id = r.work_item_id AND c.pod_uid <> '' AND c.created_at >= r.started_at "
               "AND c.created_at <= coalesce(r.finished_at, now()) ORDER BY c.created_at DESC LIMIT 1) cp ON true")
RUN_COST = ("COALESCE(a.reconciled_spend, a.observed_spend, CASE WHEN jsonb_typeof(r.usage->'costUsd') = 'number' "
            "THEN (r.usage->>'costUsd')::numeric END)")
IDLE_KILL = "r.failure_reason = 'timeout' AND r.summary ILIKE '%idle timeout%'"
HARNESS = "coalesce(substring(r.summary from '^([a-z0-9_-]+) run '), '')"

TEAM_VARIABLE = {
    "name": "team", "label": "Team", "type": "query", "datasource": PLOEG_DB,
    "query": "SELECT DISTINCT team FROM work_items WHERE team <> '' ORDER BY 1",
    "definition": "SELECT DISTINCT team FROM work_items WHERE team <> '' ORDER BY 1",
    "multi": True, "includeAll": True, "refresh": 1, "sort": 1, "hide": 0,
    "current": {"text": "All", "value": "$__all"}, "options": [],
}

OUTCOME_COLOURS = {"failed": VERMILLION, "stuck": AMBER, "pr_opened": SKY, "pr_updated": SKY}
RUNTIME_MAPPING = [{"type": "value", "options": {"kata": {"text": "kata", "color": SKY},
                                                 "runc": {"text": "runc", "color": NEUTRAL}}}]


def team_and_role(expr, source="pod"):
    with_team = f'label_replace({expr}, "team", "$1", "{source}", "(?:sbx-)?ploeg-worker-([a-z0-9]+)-.+")'
    return (f'label_replace({with_team}, "role", "$1", "{source}", '
            f'"(?:sbx-)?ploeg-worker-[a-z0-9]+-(.+)-[a-z0-9]{{5}}-[a-z0-9]{{5}}")')


def as_pod(expr):
    return f'label_replace({expr}, "pod", "$1", "exported_pod", "(.+)")'


def run_pods(window):
    kata = (f'label_replace(max by (exported_pod) (last_over_time(kube_pod_runtimeclass_name_info{{{KSM}, '
            f'{SANDBOX_POD}}}[{window}])), "runtime", "kata", "", "")')
    runc = (f'label_replace(max by (exported_pod) (last_over_time(kube_pod_container_info{{{KSM}, '
            f'exported_container="worker", {RUNC_POD}}}[{window}])), "runtime", "runc", "", "")')
    return team_and_role(as_pod(f"({kata} or {runc})"))


def per_pod(expr):
    return f"max by (pod) ({as_pod(expr)})"


def ksm_last(metric, pods=RUN_POD, window="$__range"):
    return f"last_over_time({metric}{{{KSM}, {pods}}}[{window}])"


def pod_cpu_cores():
    series = f'container_cpu_usage_seconds_total{{{CADVISOR}, {POD_CGROUP}, pod=~"(sbx-)?ploeg-worker-($team)-.+"}}'
    return (f"max by (pod) (max_over_time({series}[$__range])) / max by (pod) "
            f"(tlast_over_time({series}[$__range]) - tfirst_over_time({series}[$__range]) + 60)")


def pod_peak_memory():
    return (f'max by (pod) (max_over_time(container_memory_working_set_bytes{{{CADVISOR}, {POD_CGROUP}, '
            f'pod=~"(sbx-)?ploeg-worker-($team)-.+"}}[$__range]))')


def pod_reserved(resource):
    overhead = "kube_pod_overhead_cpu_cores" if resource == "cpu" else "kube_pod_overhead_memory_bytes"
    requests = per_pod(f'sum by (exported_pod) (max_over_time(kube_pod_container_resource_requests{{{KSM}, '
                       f'resource="{resource}", {RUN_POD}}}[$__range]))')
    extra = per_pod(f"max_over_time({overhead}{{{KSM}, {RUN_POD}}}[$__range])")
    return f"{requests} + ({extra} or {requests} * 0)"


def seconds_between(later, earlier, pods=RUN_POD):
    return per_pod(f"{ksm_last(later, pods)} - {ksm_last(earlier, pods)}")


def sandbox_key(expr):
    return f'max by (run_pod) (label_replace({expr}, "run_pod", "$1", "exported_pod", "(?:sbx-)?(.+)"))'


def sql_stat_rows(panel):
    panel["options"]["reduceOptions"] = {"calcs": ["lastNotNull"], "fields": "/^(count|kills)$/", "values": True}
    return panel


def mixed_table(title, targets, *, join_on, keep_if, rename, order, overrides, sort_field, desc, no_value):
    panel = table(title, targets, rename=rename, order=order, overrides=overrides, desc=desc, no_value=no_value,
                  cell_height="md", merge=False)
    organize = panel["transformations"][0]
    panel["datasource"] = MIXED
    panel["transformations"] = [
        {"id": "filterFieldsByName", "options": {"exclude": {"pattern": "^Time$"}}},
        {"id": "joinByField", "options": {"byField": join_on, "mode": "outer"}},
        {"id": "filterByValue", "options": {"type": "exclude", "match": "any", "filters": [
            {"fieldName": keep_if, "config": {"id": "isNull", "options": {}}}]}},
        organize,
        {"id": "sortBy", "options": {"sort": [{"field": sort_field, "desc": True}]}},
    ]
    return panel


def work_item_link():
    return col("Work Item", width=120, links=[{"title": "Open the ticket", "url": "${__data.fields.work_item_url}",
                                               "targetBlank": True}])


def outcome_column(name="Outcome"):
    return col(name, colour_text=True, width=130, mappings=[{"type": "value", "options": {
        k: {"text": k, "color": v} for k, v in OUTCOME_COLOURS.items()}}])


def runs_now():
    return stat(
        "Runs right now", None, decimals=0, text_mode="value_and_name", fixed_color=NEUTRAL,
        targets=[sql(PLOEG_DB, """
            SELECT count(*) FILTER (WHERE state = 'running') AS "running",
                   count(*) FILTER (WHERE state = 'pending') AS "waiting for a worker"
            FROM agent_runs WHERE state IN ('running', 'pending') AND team IN ($team)""")],
        desc="Straight from Ploeg's database. Running is a Run a worker has claimed and not finished. Waiting for a "
             "worker is a Run Ploeg has queued (a Round opened) that no worker pod has picked up yet. Each team and "
             "role has one worker slot, so a second Run for the same slot waits here by design.")


def pods_waiting_for_room():
    unschedulable = f"sum(kube_pod_status_unschedulable{{{KSM}, {RUN_POD}}}) or on() vector(0)"
    pending = f'sum(kube_pod_status_phase{{{KSM}, {RUN_POD}, phase="Pending"}}) or on() vector(0)'
    panel = stat(
        "Worker pods waiting for room", None, decimals=0, text_mode="value_and_name", fixed_color=NEUTRAL,
        targets=[target(unschedulable, "A", "no node has room", instant=True),
                 target(pending, "B", "pending, any reason", instant=True)],
        desc="Worker and sandbox pods Kubernetes has not started yet. No node has room means the scheduler looked "
             "at every node and none had enough unreserved CPU or memory (or the right Kata label): the Run waits "
             "until something finishes. Pending, any reason also counts pods that are only pulling their image. "
             "Amber from one pod without room.")
    panel["fieldConfig"]["overrides"] = [col("no node has room", thresholds=alarm_at(amber=1, vermillion=3))]
    return panel


def idle_timeout_kills():
    return stat(
        "Idle-timeout kills · 24 h", None, decimals=0, text_mode="value_and_name",
        thresholds=alarm_at(amber=1, vermillion=3),
        targets=[sql(PLOEG_DB, f"""
            SELECT count(*) FILTER (WHERE {IDLE_KILL}) AS "no output for too long",
                   count(*) FILTER (WHERE r.failure_reason = 'timeout' AND NOT ({IDLE_KILL})) AS "hit the hard limit"
            FROM agent_runs r WHERE r.finished_at > now() - interval '24 hours' AND r.team IN ($team)""")],
        desc="Runs the worker stopped in the last 24 hours because the agent went quiet. No output for too long is "
             "PLOEG_HARNESS_IDLE_TIMEOUT (45 minutes on the builders): the harness printed nothing, so the worker "
             "killed it. Hit the hard limit is PLOEG_HARNESS_TIMEOUT, the total time cap. Both are failure_reason "
             "timeout; the split reads the Run's summary text. Every kill still spent money on the model.")


def failures_by_reason():
    return sql_stat_rows(stat(
        "Failed Runs by reason · this range", None, decimals=0, text_mode="value_and_name", fixed_color=VERMILLION,
        targets=[sql(PLOEG_DB, """
            SELECT coalesce(nullif(failure_reason, ''), 'unclassified') AS reason, count(*) AS count
            FROM agent_runs WHERE outcome = 'failed' AND team IN ($team) AND $__timeFilter(finished_at)
            GROUP BY 1 ORDER BY 2 DESC""")],
        no_value="no failed Run",
        desc="Why failed Runs ended, over the selected time range. infra_node: the pod or node went away. "
             "infra_llm: the model gateway failed. timeout: the idle or total time limit. agent_error: the agent "
             "program crashed. budget: the Run hit its token ceiling. lease_lost: the Run stopped renewing its "
             "lock and the sweeper took it back."))


def runs_in_flight():
    return table(
        "Runs in flight",
        [sql(PLOEG_DB, f"""
            SELECT r.id AS "Run", r.team AS "Team", coalesce(nullif(r.role, ''), 'pre-Shift') AS "Role",
                   r.round AS "Round", {WORK_ITEM} AS "Work Item", {WORK_ITEM_URL} AS work_item_url,
                   left(w.title, 60) AS "Title", r.state AS "State",
                   extract(epoch FROM now() - q.at) AS "Queued for",
                   extract(epoch FROM coalesce(r.started_at, now()) - q.at) AS "Waited for a worker",
                   extract(epoch FROM now() - r.started_at) AS "Running for",
                   coalesce(cp.node_name, '') AS "Node", r.authorized AS "Authorized",
                   'ploeg-' || left(r.run_token, 12) AS "Key"
            FROM agent_runs r JOIN work_items w ON w.id = r.work_item_id {QUEUED_AT} {RUN_POD_ROW}
            WHERE r.state IN ('pending', 'running') AND r.team IN ($team)
            ORDER BY r.state DESC, q.at""")],
        overrides=[work_item_link(), col("work_item_url", hidden=True),
                   col("State", colour_text=True, width=90, mappings=[{"type": "value", "options": {
                       "running": {"text": "running", "color": SKY}, "pending": {"text": "waiting", "color": AMBER}}}]),
                   col("Queued for", unit="s", decimals=0, width=100),
                   col("Waited for a worker", unit="s", decimals=0, width=150,
                       thresholds=alarm_at(amber=600, vermillion=3600), colour_text=True),
                   col("Running for", unit="s", decimals=0, width=110),
                   col("Authorized", unit="currencyUSD", decimals=2, width=100),
                   col("Run", width=60), col("Round", width=70), col("Team", width=80)],
        no_value="No Run is running or waiting.", cell_height="md",
        desc="Every Run Ploeg has queued or started and not finished. Waited for a worker is from the Round opening "
             "to a worker claiming the Run: it covers the KEDA poll, pod scheduling, the pod booting and the worker "
             "starting. Node comes from the checkpoint the worker writes once it has cloned the repository, so a Run "
             "still starting shows none yet. Authorized is the most this Run may spend; the live spend per key is in the "
             "table beside Worker pods now, matched by Key. Harness is not stored per Run in Ploeg.")


def worker_pods_now():
    live = f"(max by (exported_pod) (kube_pod_status_phase{{{KSM}, {RUN_POD}, {LIVE}}}) == 1)"
    info = team_and_role(as_pod(f"max by (exported_pod, node) (kube_pod_info{{{KSM}, {RUN_POD}}}) and on (exported_pod) {live}"))
    phase = as_pod(f"max by (exported_pod, phase) (kube_pod_status_phase{{{KSM}, {RUN_POD}, {LIVE}}} == 1)")
    runtime = as_pod(
        f'label_replace(max by (exported_pod) (kube_pod_runtimeclass_name_info{{{KSM}, {SANDBOX_POD}}}), '
        f'"runtime", "kata", "", "") and on (exported_pod) {live}')
    age = per_pod(f"time() - kube_pod_created{{{KSM}, {RUN_POD}}} and on (exported_pod) {live}")
    no_room = per_pod(f"kube_pod_status_unschedulable{{{KSM}, {RUN_POD}}}")
    memory = (f'max by (pod) (container_memory_working_set_bytes{{{CADVISOR}, {POD_CGROUP}, '
              f'pod=~"(sbx-)?ploeg-worker-($team)-.+"}})')
    return table(
        "Worker pods now",
        [target(f"max by (pod, team, role, node) ({info})", "A", instant=True, fmt="table"),
         target(f"max by (pod, phase) ({phase})", "B", instant=True, fmt="table"),
         target(f"max by (pod, runtime) ({runtime})", "C", instant=True, fmt="table"),
         target(age, "D", instant=True, fmt="table"),
         target(no_room, "E", instant=True, fmt="table"),
         target(f"{memory} and on (pod) {as_pod(live)}", "F", instant=True, fmt="table")],
        rename={"pod": "Pod", "team": "Team", "role": "Role", "node": "Node", "phase": "Phase", "runtime": "Runtime",
                "Value #D": "Age", "Value #E": "No room", "Value #F": "Memory now"},
        order=["Pod", "Team", "Role", "Runtime", "Phase", "Node", "Age", "No room", "Memory now"],
        hide=["Value #A", "Value #B", "Value #C"], sort_field="Age",
        overrides=[col("Age", unit="s", decimals=0, width=80), col("Memory now", unit="bytes", decimals=0, width=100),
                   col("Runtime", width=80, colour_text=True, mappings=RUNTIME_MAPPING),
                   col("No room", width=80, colour_text=True, thresholds=alarm_at(vermillion=1),
                       mappings=[{"type": "value", "options": {"0": {"text": "no"}, "1": {"text": "yes"}}}]),
                   col("Phase", width=85, colour_text=True, mappings=[{"type": "value", "options": {
                       "Pending": {"text": "Pending", "color": AMBER}, "Running": {"text": "Running", "color": SKY}}}])],
        no_value="No worker pod is pending or running.", cell_height="md",
        desc="Worker pods that are pending or running now. A Run on a Kata team uses two pods: a small launcher "
             "(ploeg-worker-...) on the normal runtime and the sandbox (sbx-ploeg-worker-...) that does the work in "
             "a Kata virtual machine. Runtime is blank for normal (runc) pods. No room is yes while the scheduler "
             "cannot find a node with enough unreserved CPU or memory. Memory now is what the pod's cgroup holds; "
             "for a Kata sandbox that is the whole virtual machine.")


def spend_so_far():
    running = f'max by (key_alias) (ploeg_run_started_epoch{{outcome="running", team=~"$team"}})'
    spent = f'max by (key_alias) (litellm_key_spend{{key_alias=~"ploeg-.+"}}) and on (key_alias) {running}'
    budget = f'max by (key_alias) (litellm_key_max_budget{{key_alias=~"ploeg-.+"}}) and on (key_alias) {running}'
    return table(
        "Spend so far vs authorized",
        [target(f'max by (key_alias, team, ticket) (ploeg_run_started_epoch{{outcome="running", team=~"$team"}}) '
                "* 1000", "A", instant=True, fmt="table"),
         target(spent, "B", instant=True, fmt="table"),
         target(budget, "C", instant=True, fmt="table"),
         target(f"({spent}) / ({budget})", "D", instant=True, fmt="table")],
        rename={"key_alias": "Key", "team": "Team", "ticket": "Ticket", "Value #A": "Started", "Value #B": "Spent",
                "Value #C": "Authorized", "Value #D": "Used"},
        order=["Key", "Team", "Ticket", "Started", "Spent", "Authorized", "Used"], sort_field="Used",
        overrides=[col("Started", unit="dateTimeFromNow", width=110),
                   col("Spent", unit="currencyUSD", decimals=2, width=80),
                   col("Authorized", unit="currencyUSD", decimals=2, width=95),
                   col("Used", unit="percentunit", decimals=0, gauge=True, gauge_max=1)],
        no_value="No Run is spending right now.", cell_height="md",
        desc="What each running Run's model key has spent so far, from LiteLLM's own ledger, against the budget the "
             "key was minted with (the Run's authorized amount). At 100 % LiteLLM refuses the next model call and "
             "the Run fails. Key matches the Key column in Runs in flight. The Run list comes from Ploeg's exporter, "
             "so a Run appears here up to a minute after it starts.")


def recent_runs():
    runtime = (f'max by (uid, runtime) (label_replace({ksm_last("kube_pod_runtimeclass_name_info", SANDBOX_POD)}, '
               f'"runtime", "kata", "", "")) or on (uid) max by (uid, runtime) (label_replace('
               f'{ksm_last("kube_pod_container_info", RUNC_POD)}, "runtime", "runc", "", ""))')
    scheduling = (f'max by (uid) ({ksm_last("kube_pod_status_scheduled_time")} - '
                  f'{ksm_last("kube_pod_created")})')
    booting = (f'max by (uid) ({ksm_last("kube_pod_status_ready_time")} - '
               f'{ksm_last("kube_pod_status_scheduled_time")})')
    return mixed_table(
        "Recent Runs",
        [sql(PLOEG_DB, f"""
            SELECT r.finished_at AS "Finished", r.id AS "Run", r.team AS "Team",
                   coalesce(nullif(r.role, ''), 'pre-Shift') AS "Role", r.round AS "Round",
                   {WORK_ITEM} AS "Work Item", {WORK_ITEM_URL} AS work_item_url, {HARNESS} AS "Harness",
                   coalesce(r.outcome, '') AS "Outcome", coalesce(r.failure_reason, '') AS "Failure reason",
                   coalesce(cp.node_name, '') AS "Node", coalesce(cp.pod_uid, 'run-' || r.id) AS uid,
                   extract(epoch FROM r.started_at - q.at) AS "Queued → claimed",
                   extract(epoch FROM r.finished_at - r.started_at) AS "Ran for",
                   {RUN_COST} AS "Spent", r.authorized AS "Authorized", left(r.summary, 140) AS "Summary"
            FROM agent_runs r JOIN work_items w ON w.id = r.work_item_id
            LEFT JOIN run_llm_accounts a ON a.run_token = r.run_token {QUEUED_AT} {RUN_POD_ROW}
            WHERE r.state = 'finished' AND r.team IN ($team) AND $__timeFilter(r.finished_at)
            ORDER BY r.finished_at DESC LIMIT 100""", ref="A"),
         target(runtime, "B", instant=True, fmt="table"),
         target(scheduling, "C", instant=True, fmt="table"),
         target(booting, "D", instant=True, fmt="table")],
        join_on="uid", keep_if="Run",
        rename={"runtime": "Runtime", "Value #C": "Pod scheduling", "Value #D": "Pod boot"},
        order=["Finished", "Run", "Team", "Role", "Round", "Work Item", "Harness", "Runtime", "Node", "Outcome",
               "Failure reason", "Queued → claimed", "Pod scheduling", "Pod boot", "Ran for", "Spent", "Authorized",
               "Summary"],
        sort_field="Finished",
        overrides=[work_item_link(), col("work_item_url", hidden=True), col("uid", hidden=True),
                   col("Value #B", hidden=True), outcome_column(),
                   col("Finished", unit="dateTimeAsLocal", width=160),
                   col("Failure reason", width=120),
                   col("Runtime", width=80, colour_text=True, mappings=RUNTIME_MAPPING),
                   col("Queued → claimed", unit="s", decimals=0, width=130),
                   col("Pod scheduling", unit="s", decimals=0, width=115),
                   col("Pod boot", unit="s", decimals=0, width=85),
                   col("Ran for", unit="s", decimals=0, width=85),
                   col("Spent", unit="currencyUSD", decimals=2, width=75),
                   col("Authorized", unit="currencyUSD", decimals=2, width=95),
                   col("Run", width=60), col("Round", width=65), col("Team", width=75), col("Harness", width=90)],
        no_value="No Run finished in this range.",
        desc="The last 100 Runs that finished in the selected range, newest first. The timeline reads left to "
             "right: Queued → claimed is from the Round opening to a worker claiming the Run; inside that, Pod "
             "scheduling is how long Kubernetes looked for a node and Pod boot is from placement to the pod being "
             "ready (image pull, and for Kata the virtual machine start). Ran for is claim to finish. Runtime, "
             "Node and the two pod columns come from the pod the worker recorded in its checkpoint; a Run that died "
             "before its first checkpoint (about 1 in 15) shows blanks there. Harness is read from the start of the Run's summary (\"openhands "
             "run ...\") because Ploeg does not store it; a blank means the summary did not say. Spent is the "
             "settled model cost; Authorized is the Run's ceiling.")


def outcomes_per_team():
    return table(
        "Runs per outcome per team · this range",
        [sql(PLOEG_DB, """
            SELECT team AS "Team", count(*) AS "Runs",
                   count(*) FILTER (WHERE outcome = 'pr_opened') AS "pr_opened",
                   count(*) FILTER (WHERE outcome = 'pr_updated') AS "pr_updated",
                   count(*) FILTER (WHERE outcome = 'no_change_needed') AS "no_change_needed",
                   count(*) FILTER (WHERE outcome = 'failed') AS "failed",
                   count(*) FILTER (WHERE outcome = 'stuck') AS "stuck",
                   count(*) FILTER (WHERE outcome NOT IN ('pr_opened', 'pr_updated', 'no_change_needed', 'failed',
                                                          'stuck')) AS "other",
                   count(*) FILTER (WHERE outcome = 'failed')::numeric / NULLIF(count(*), 0) AS "Failed share"
            FROM agent_runs WHERE state = 'finished' AND team IN ($team) AND $__timeFilter(finished_at)
            GROUP BY team ORDER BY team""")],
        overrides=[col("failed", colour_text=True, thresholds=alarm_at(vermillion=1)),
                   col("stuck", colour_text=True, thresholds=alarm_at(amber=1)),
                   col("Failed share", unit="percentunit", decimals=0, colour_text=True,
                       thresholds=alarm_at(amber=0.2, vermillion=0.5))],
        no_value="No Run finished in this range.",
        desc="How every Run that finished in the selected range ended, per team. pr_opened and pr_updated are the "
             "product. no_change_needed is a reviewer's approval or a builder that found nothing to do. failed and "
             "stuck bought nothing. Failed share is amber from 20 % and vermillion from 50 %.")


def failures_per_team():
    return table(
        "Failures by reason per team · this range",
        [sql(PLOEG_DB, f"""
            SELECT r.team AS "Team", coalesce(nullif(r.role, ''), 'pre-Shift') AS "Role",
                   coalesce(nullif(r.failure_reason, ''), 'unclassified') AS "Reason",
                   count(*) AS "Runs", count(*) FILTER (WHERE {IDLE_KILL}) AS "Idle kills",
                   sum({RUN_COST}) AS "Spent"
            FROM agent_runs r LEFT JOIN run_llm_accounts a ON a.run_token = r.run_token
            WHERE r.outcome = 'failed' AND r.team IN ($team) AND $__timeFilter(r.finished_at)
            GROUP BY 1, 2, 3 ORDER BY 4 DESC""")],
        overrides=[col("Spent", unit="currencyUSD", decimals=2), col("Reason", width=130)],
        no_value="No Run failed in this range.",
        desc="Failed Runs split by team, role and failure_reason, with how many were idle-timeout kills and what "
             "the failed Runs spent on the model. A reason that repeats for one role is a pattern: timeout on "
             "builders usually means the agent loops without printing, infra_node means pods are being evicted.")


def wait_per_slot():
    return table(
        "Where the wait goes, per team and role · this range",
        [sql(PLOEG_DB, f"""
            SELECT r.team AS "Team", coalesce(nullif(r.role, ''), 'pre-Shift') AS "Role", count(*) AS "Runs",
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM r.started_at - q.at)) AS "Queued p50",
                   max(extract(epoch FROM r.started_at - q.at)) AS "Queued max",
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM r.finished_at - r.started_at))
                     AS "Ran p50",
                   max(extract(epoch FROM r.finished_at - r.started_at)) AS "Ran max"
            FROM agent_runs r {QUEUED_AT}
            WHERE r.state = 'finished' AND r.team IN ($team) AND $__timeFilter(r.finished_at)
            GROUP BY 1, 2 ORDER BY 1, 2""")],
        overrides=[col("Queued p50", unit="s", decimals=0), col("Queued max", unit="s", decimals=0),
                   col("Ran p50", unit="s", decimals=0), col("Ran max", unit="s", decimals=0)],
        no_value="No Run finished in this range.",
        desc="How long Runs waited between being queued and a worker claiming them, and how long they then ran, "
             "per team and role (p50 is the median). A long queue on one slot usually means the previous Run of "
             "the same slot was still running: each slot runs one Run at a time. Pod-level detail is on Unfold · "
             "Kata overhead.")


def pods_without_room_over_time():
    return timeseries(
        "Worker pods without room, over time",
        [target(f'sum by (team) ({team_and_role(as_pod(f"kube_pod_status_unschedulable{{{KSM}, {RUN_POD}}}"))})',
                "A", "{{team}}")],
        unit="short", decimals=0, draw="bars", stack=True,
        desc="Worker and sandbox pods the scheduler could not place, per team, over the selected range. Bars that "
             "keep coming back mean the Kata nodes are full: see node headroom on Unfold · Kata overhead.")


LINKS = [link("Unfold · Plant", "/d/glide-plant"), link("Unfold · Kata overhead", f"/d/{KATA_UID}"),
         link("Unfold Loop", "/d/glide-loop"), tag_links(["board"], "Boards")]


def place(items):
    panels = []
    for panel, x, y, w, h in items:
        panel["gridPos"] = grid_pos(x, y, w, h)
        panels.append(panel)
    return panels


def runs_board():
    panels = place([
        (runs_now(), 0, 0, 5, 5), (pods_waiting_for_room(), 5, 0, 6, 5), (idle_timeout_kills(), 11, 0, 6, 5),
        (failures_by_reason(), 17, 0, 7, 5),
        (runs_in_flight(), 0, 5, 24, 7),
        (worker_pods_now(), 0, 12, 14, 7), (spend_so_far(), 14, 12, 10, 7),
        (recent_runs(), 0, 19, 24, 12),
        (outcomes_per_team(), 0, 31, 12, 6), (failures_per_team(), 12, 31, 12, 6),
        (wait_per_slot(), 0, 37, 14, 7), (pods_without_room_over_time(), 14, 37, 10, 7),
    ])
    return dashboard(
        RUNS_UID, "Unfold · Runs", number(panels), tags=TAGS, variables=[TEAM_VARIABLE], links=LINKS,
        time_from="now-24h",
        description="Per-Run view of Unfold: what is running now, what just finished and how, where the time went "
                    "from queued to finished, and why Runs fail. Built from Ploeg's database and Kubernetes.")


def sandbox_counts():
    kata = f"count({per_pod(ksm_last('kube_pod_runtimeclass_name_info', SANDBOX_POD))}) or on() vector(0)"
    runc_workers = per_pod(ksm_last("kube_pod_container_info", f'exported_container="worker", {RUNC_POD}'))
    runc = f"count({runc_workers}) or on() vector(0)"
    return stat(
        "Run pods in this range", None, decimals=0, text_mode="value_and_name", fixed_color=NEUTRAL,
        targets=[target(kata, "A", "kata sandboxes", instant=True), target(runc, "B", "runc workers", instant=True)],
        desc="How many Run pods each runtime ran in the selected range. Kata sandboxes are the sbx-ploeg-worker "
             "pods: each Run gets its own small virtual machine. runc workers are ordinary containers sharing the "
             "node's kernel. The launcher pods Kata teams also start are not counted.")


def overhead_reserved():
    newest = f"topk(1, max by (uid) ({ksm_last('kube_pod_created', SANDBOX_POD)}))"
    cpu = f"max(max by (uid) ({ksm_last('kube_pod_overhead_cpu_cores', SANDBOX_POD)}) and on (uid) {newest})"
    memory = f"max(max by (uid) ({ksm_last('kube_pod_overhead_memory_bytes', SANDBOX_POD)}) and on (uid) {newest})"
    panel = stat(
        "Kata overhead reserved per pod", None, text_mode="value_and_name", fixed_color=NEUTRAL,
        targets=[target(cpu, "A", "CPU cores", instant=True), target(memory, "B", "memory", instant=True)],
        no_value="no sandbox in range",
        desc="What Kubernetes added to the newest Kata sandbox's reservation on top of its own requests, read from "
             "the pod's spec.overhead, which the kata RuntimeClass sets (100m CPU and 160 MiB since 2026-09-29; "
             "older sandboxes carried 250m CPU, and the per-pod table shows each pod's own). The scheduler counts it "
             "when it looks for room, so a Kata Run needs this much more free space than the same Run on runc.")
    panel["fieldConfig"]["overrides"] = [col("CPU cores", decimals=2), col("memory", unit="bytes", decimals=0)]
    return panel


def vmm_cpu_share():
    outside = (f'sum(max by (id) (max_over_time(container_cpu_usage_seconds_total{{{CADVISOR}, id=~"/kata_overhead/.+", '
               f'pod=~"sbx-ploeg-worker-($team)-.+"}}[$__range])))')
    inside = (f'sum(max by (pod) (max_over_time(container_cpu_usage_seconds_total{{{CADVISOR}, {POD_CGROUP}, '
              f'pod=~"sbx-ploeg-worker-($team)-.+"}}[$__range])))')
    return stat(
        "Kata CPU spent outside the pod", f"{outside} / {inside}", unit="percentunit", decimals=1,
        fixed_color=NEUTRAL, no_value="no sandbox in range",
        desc="CPU time Kata's own helper processes (the shim and the hypervisor threads, in the host cgroup "
             "/kata_overhead) used, as a share of the CPU time used inside the sandbox pods. This is overhead the "
             "pod's own numbers do not show. The memory those helpers hold cannot be measured here: cAdvisor "
             "reports zero memory for /kata_overhead because the memory controller is not enabled on it.")


def runtime_comparison():
    pods = run_pods("$__range")
    joined = "* on (pod) group_left (runtime, role) " + pods

    def by(expr, how="avg"):
        return f"{how} by (runtime, role) ({expr} {joined})"

    return table(
        "kata vs runc per role · this range",
        [target(f"count by (runtime, role) ({pods})", "A", instant=True, fmt="table"),
         target(by(pod_cpu_cores()), "B", instant=True, fmt="table"),
         target(by(pod_peak_memory()), "C", instant=True, fmt="table"),
         target(by(pod_peak_memory(), "max"), "D", instant=True, fmt="table"),
         target(by(f"({pod_reserved('memory')})"), "E", instant=True, fmt="table"),
         target(by(seconds_between("kube_pod_status_scheduled_time", "kube_pod_created")), "F", instant=True,
                fmt="table"),
         target(by(seconds_between("kube_pod_status_ready_time", "kube_pod_status_scheduled_time")), "G",
                instant=True, fmt="table")],
        rename={"runtime": "Runtime", "role": "Role", "Value #A": "Pods", "Value #B": "Avg CPU cores",
                "Value #C": "Avg peak memory", "Value #D": "Max peak memory", "Value #E": "Reserved memory",
                "Value #F": "Avg scheduling wait", "Value #G": "Avg boot"},
        order=["Role", "Runtime", "Pods", "Avg CPU cores", "Avg peak memory", "Max peak memory", "Reserved memory",
               "Avg scheduling wait", "Avg boot"],
        overrides=[col("Runtime", colour_text=True, mappings=RUNTIME_MAPPING, width=90),
                   col("Avg CPU cores", decimals=2), col("Avg peak memory", unit="bytes", decimals=0),
                   col("Max peak memory", unit="bytes", decimals=0), col("Reserved memory", unit="bytes", decimals=0),
                   col("Avg scheduling wait", unit="s", decimals=0), col("Avg boot", unit="s", decimals=0)],
        no_value="No Run pod in this range.",
        desc="The same Roles side by side on each runtime. Avg CPU cores is CPU time divided by how long the pod "
             "lived. Peak memory is the pod cgroup's highest working set: for runc that is the container, for Kata "
             "it is the guest virtual machine's memory as the host sees it (guest kernel and page cache included), "
             "so it is the fairer cost number, not a bug. Reserved memory is requests plus Kata's overhead. Avg boot "
             "is from placement to ready. Only compare rows with several pods; the team plans differ, so a role's "
             "work is similar, not identical.")


def per_pod_table():
    pods = run_pods("$__range")

    def only_runs(expr):
        return f"({expr}) and on (pod) max by (pod) ({pods})"

    node = f'max by (pod, node) ({as_pod(ksm_last("kube_pod_info"))})'
    vmm = (f'max by (pod) (max_over_time(container_cpu_usage_seconds_total{{{CADVISOR}, id=~"/kata_overhead/.+", '
           f'pod=~"sbx-ploeg-worker-($team)-.+"}}[$__range]))')
    return table(
        "Every Run pod · used vs reserved",
        [target(f"max by (pod, runtime, team, role) ({pods})", "A", instant=True, fmt="table"),
         target(only_runs(node), "B", instant=True, fmt="table"),
         target(only_runs(pod_cpu_cores()), "C", instant=True, fmt="table"),
         target(only_runs(pod_reserved("cpu")), "D", instant=True, fmt="table"),
         target(only_runs(pod_peak_memory()), "E", instant=True, fmt="table"),
         target(only_runs(pod_reserved("memory")), "F", instant=True, fmt="table"),
         target(only_runs(f"({pod_peak_memory()}) / ({pod_reserved('memory')})"), "G", instant=True, fmt="table"),
         target(vmm, "H", instant=True, fmt="table"),
         target(only_runs(per_pod(f"{ksm_last('kube_pod_created')} * 1000")), "I", instant=True, fmt="table")],
        rename={"pod": "Pod", "runtime": "Runtime", "team": "Team", "role": "Role", "node": "Node",
                "Value #C": "CPU used", "Value #D": "CPU reserved", "Value #E": "Peak memory",
                "Value #F": "Memory reserved", "Value #G": "Peak / reserved", "Value #H": "Kata helper CPU",
                "Value #I": "Created"},
        order=["Created", "Pod", "Team", "Role", "Runtime", "Node", "CPU used", "CPU reserved", "Peak memory",
               "Memory reserved", "Peak / reserved", "Kata helper CPU"],
        hide=["Value #A", "Value #B"], sort_field="Created",
        overrides=[col("Created", unit="dateTimeFromNow", width=110),
                   col("Runtime", colour_text=True, mappings=RUNTIME_MAPPING, width=80),
                   col("CPU used", unit="none", decimals=2, width=85), col("CPU reserved", decimals=2, width=100),
                   col("Peak memory", unit="bytes", decimals=0, width=105),
                   col("Memory reserved", unit="bytes", decimals=0, width=125),
                   col("Peak / reserved", unit="percentunit", decimals=0, gauge=True, gauge_max=2),
                   col("Kata helper CPU", unit="s", decimals=0, width=120)],
        no_value="No Run pod in this range.", cell_height="md",
        desc="One row per Run pod in the range. CPU used is average cores over the pod's life; CPU reserved is its "
             "request plus Kata's overhead. Peak memory against Memory reserved shows whether the reservation fits: "
             "above 100 % the pod used more than it reserved (allowed up to its limit, but the node was promised "
             "less). Kata helper CPU is seconds the Kata shim and hypervisor used outside the pod. What is not "
             "visible: memory of those helpers, and per-container numbers inside a Kata sandbox (cAdvisor sees the "
             "virtual machine as one pod).")


def node_headroom():
    nodes = f'node=~"{KATA_NODES}"'
    live_uid = f'(max by (uid) (kube_pod_status_phase{{job="kube-state-metrics", {LIVE}}}) == 1)'

    def allocatable(resource):
        return f'max by (node) (kube_node_status_allocatable{{job="kube-state-metrics", {nodes}, resource="{resource}"}})'

    def reserved(resource, overhead):
        requests = (f'sum by (node) (kube_pod_container_resource_requests{{job="kube-state-metrics", {nodes}, '
                    f'resource="{resource}"}} * on (uid) group_left () {live_uid})')
        extra = (f'sum by (node) ({overhead}{{job="kube-state-metrics"}} * on (uid) group_left (node) '
                 f'max by (uid, node) (kube_pod_info{{job="kube-state-metrics", {nodes}}}) * on (uid) group_left () '
                 f'{live_uid})')
        return f"({requests} + ({extra} or {requests} * 0))"

    cpu_used = f'sum by (node) (rate(container_cpu_usage_seconds_total{{job="cadvisor", {nodes}, id="/"}}[5m]))'
    memory_used = f'sum by (node) (container_memory_working_set_bytes{{job="cadvisor", {nodes}, id="/"}})'
    cpu_free = f"({allocatable('cpu')} - {reserved('cpu', 'kube_pod_overhead_cpu_cores')})"
    memory_free = f"({allocatable('memory')} - {reserved('memory', 'kube_pod_overhead_memory_bytes')})"
    by_cpu = f"floor(clamp_min({cpu_free} / {KATA_RUN_CPU}, 0))"
    by_memory = f"floor(clamp_min({memory_free} / {KATA_RUN_MEMORY}, 0))"
    return table(
        "Kata node headroom, right now",
        [target(allocatable("cpu"), "A", instant=True, fmt="table"),
         target(reserved("cpu", "kube_pod_overhead_cpu_cores"), "B", instant=True, fmt="table"),
         target(cpu_used, "C", instant=True, fmt="table"),
         target(allocatable("memory"), "D", instant=True, fmt="table"),
         target(reserved("memory", "kube_pod_overhead_memory_bytes"), "E", instant=True, fmt="table"),
         target(memory_used, "F", instant=True, fmt="table"),
         target(f"({by_cpu} <= {by_memory}) or {by_memory}", "G", instant=True, fmt="table")],
        rename={"node": "Node", "Value #A": "CPU allocatable", "Value #B": "CPU reserved", "Value #C": "CPU used",
                "Value #D": "Memory allocatable", "Value #E": "Memory reserved", "Value #F": "Memory used",
                "Value #G": "Kata Runs that still fit"},
        order=["Node", "CPU allocatable", "CPU reserved", "CPU used", "Memory allocatable", "Memory reserved",
               "Memory used", "Kata Runs that still fit"],
        overrides=[col("CPU allocatable", decimals=2), col("CPU reserved", decimals=2), col("CPU used", decimals=2),
                   col("Memory allocatable", unit="bytes", decimals=1), col("Memory reserved", unit="bytes", decimals=1),
                   col("Memory used", unit="bytes", decimals=1),
                   col("Kata Runs that still fit", decimals=0, colour_text=True,
                       thresholds={"mode": "absolute", "steps": [{"color": VERMILLION, "value": None},
                                                                 {"color": AMBER, "value": 1},
                                                                 {"color": NEUTRAL, "value": 2}]})],
        cell_height="md",
        desc="The three nodes that can run Kata sandboxes. Allocatable is what Kubernetes may hand out. Reserved "
             "is the sum of requests of every pending or running pod on the node, plus Kata overhead: this, not "
             "real use, decides whether a new pod fits. Used is what the whole machine uses now, system services "
             "included. Kata Runs that still fit divides the unreserved room by one Kata Run (100m CPU and 768 MiB "
             "requested, plus 100m and 160 MiB overhead, from the Ploeg HelmRelease on 2026-09-29) and takes the "
             "smaller of CPU and memory. Zero on all three means the next sandbox waits.")


def reservation_over_time():
    nodes = f'node=~"{KATA_NODES}"'
    live_uid = f'(max by (uid) (kube_pod_status_phase{{job="kube-state-metrics", {LIVE}}}) == 1)'
    requests = (f'sum by (node) (kube_pod_container_resource_requests{{job="kube-state-metrics", {nodes}, '
                f'resource="memory"}} * on (uid) group_left () {live_uid})')
    alloc = f'max by (node) (kube_node_status_allocatable{{job="kube-state-metrics", {nodes}, resource="memory"}})'
    cpu_requests = requests.replace('resource="memory"', 'resource="cpu"')
    cpu_alloc = alloc.replace('resource="memory"', 'resource="cpu"')
    return timeseries(
        "Kata nodes: share of allocatable reserved",
        [target(f"{requests} / {alloc}", "A", "{{node}} memory"),
         target(f"{cpu_requests} / {cpu_alloc}", "B", "{{node}} CPU")],
        unit="percentunit", decimals=0, thresholds=alarm_at(amber=0.85, vermillion=0.95),
        desc="How full each Kata node's reservation book was over time (requests of pending and running pods, "
             "without Kata overhead, divided by allocatable). Near 100 % a new sandbox cannot be placed even if "
             "the machine is idle.")


def sandbox_start():
    sbx_created = sandbox_key(ksm_last("kube_pod_created", SANDBOX_POD))
    launcher_created = sandbox_key(ksm_last("kube_pod_created", RUNC_POD))
    scheduled = sandbox_key(ksm_last("kube_pod_status_scheduled_time", SANDBOX_POD))
    ready = sandbox_key(ksm_last("kube_pod_status_ready_time", SANDBOX_POD))
    no_room = sandbox_key(f"max_over_time(kube_pod_status_unschedulable{{{KSM}, {SANDBOX_POD}}}[$__range])")
    node = f'max by (run_pod, node) (label_replace({ksm_last("kube_pod_info", SANDBOX_POD)}, "run_pod", "$1", "exported_pod", "sbx-(.+)"))'
    return table(
        "Sandbox start, step by step",
        [target(f"{launcher_created} * 1000", "A", instant=True, fmt="table"),
         target(node, "B", instant=True, fmt="table"),
         target(f"{sbx_created} - {launcher_created}", "C", instant=True, fmt="table"),
         target(f"{scheduled} - {sbx_created}", "D", instant=True, fmt="table"),
         target(f"{ready} - {scheduled}", "E", instant=True, fmt="table"),
         target(no_room, "F", instant=True, fmt="table")],
        rename={"run_pod": "Run pod", "node": "Node", "Value #A": "Launcher created", "Value #C": "Sandbox requested",
                "Value #D": "Waited for a node", "Value #E": "VM boot to ready", "Value #F": "Was without room"},
        order=["Launcher created", "Run pod", "Node", "Sandbox requested", "Waited for a node", "VM boot to ready",
               "Was without room"],
        hide=["Value #B"], sort_field="Launcher created",
        overrides=[col("Launcher created", unit="dateTimeFromNow", width=130),
                   col("Sandbox requested", unit="s", decimals=0), col("Waited for a node", unit="s", decimals=0,
                                                                       colour_text=True,
                                                                       thresholds=alarm_at(amber=60, vermillion=600)),
                   col("VM boot to ready", unit="s", decimals=0),
                   col("Was without room", colour_text=True, thresholds=alarm_at(amber=1),
                       mappings=[{"type": "value", "options": {"0": {"text": "no"}, "1": {"text": "yes"}}}])],
        no_value="No sandbox in this range.", cell_height="md",
        desc="Each Kata Run starts in three steps. The launcher pod starts on runc and asks the agent-sandbox "
             "controller for a sandbox: Sandbox requested is the gap until the sandbox pod exists. Waited for a node "
             "is how long the scheduler needed to find room for it. VM boot to ready is from placement until the "
             "pod is ready: pulling the image and starting the Kata virtual machine. Was without room is yes if the "
             "scheduler reported no node with room at any point in the range. A missing launcher (blank Sandbox "
             "requested) means the launcher pod was already cleaned up.")


def blind_spots():
    return text("What this board cannot see", (
        "- **Kata helper memory.** The shim and hypervisor run in the host cgroup `/kata_overhead`; cAdvisor reports "
        "CPU for it but zero memory, because the memory controller is not enabled there. The 160 MiB reserved "
        "overhead is a promise, not a measurement.\n"
        "- **Containers inside a sandbox.** cAdvisor sees a Kata pod as one virtual machine. Per-container CPU and "
        "memory inside the guest would need an exporter inside the sandbox.\n"
        "- **Guest memory is host memory.** A Kata pod's working set counts the guest kernel and guest page cache. "
        "That is the real cost to the node, but it is not what the agent process itself used.\n"
        "- **Which Run a pod served** is known only through the checkpoint a worker writes after cloning; a Run that "
        "dies before that has no pod on record. The per-Run join lives on Unfold · Runs."))


def kata_board():
    items = [
        (sandbox_counts(), 0, 0, 6, 5), (overhead_reserved(), 6, 0, 6, 5), (vmm_cpu_share(), 12, 0, 5, 5),
        (blind_spots(), 17, 0, 7, 10),
        (runtime_comparison(), 0, 5, 17, 6),
        (node_headroom(), 0, 11, 24, 6),
        (reservation_over_time(), 0, 17, 10, 8), (sandbox_start(), 10, 17, 14, 8),
        (per_pod_table(), 0, 25, 24, 12),
    ]
    return dashboard(
        KATA_UID, "Unfold · Kata overhead", number(place(items)), tags=TAGS + ["kata"], variables=[TEAM_VARIABLE],
        links=[link("Unfold · Runs", f"/d/{RUNS_UID}"), link("Unfold · Plant", "/d/glide-plant"),
               tag_links(["board"], "Boards")],
        time_from="now-7d",
        description="What running Unfold's agents inside Kata virtual machines costs compared with plain runc "
                    "containers: CPU and memory used against what is reserved, node room on the three Kata nodes, and "
                    "how long a sandbox takes to start. Each panel says what it cannot measure.")


def boards():
    return [(runs_board(), FOLDER), (kata_board(), FOLDER)]
