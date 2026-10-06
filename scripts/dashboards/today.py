from __future__ import annotations

import json
import pathlib
import re

import alerts
import forgejo_ci
from lib import APP, dashboard, doc_link, grid_pos, link, sql, target
from platform_walls import BOARD_PROJECTS, VIKUNJA

FOLDER = "walls"
DOC = "docs/techdocs/docs/general/information-radiators.md"
UID = "today"
WALL_DIR = pathlib.Path(__file__).resolve().parent / "today_wall"
GRAFANA_INSTANCE = APP / "grafana-instance.yaml"
BUSINESS_TEXT = "marcusolsson-dynamictext-panel"
BUSINESS_TEXT_VERSION = "6.3.0"
MIXED = {"type": "datasource", "uid": "-- Mixed --"}
FORGEJO_DB = {"type": "grafana-postgresql-datasource", "uid": "forgejo-db"}
PLOEG_DB = {"type": "grafana-postgresql-datasource", "uid": "ploeg-db"}
LITELLM_DB = {"type": "grafana-postgresql-datasource", "uid": "litellm-db"}
FORGEJO_URL = "https://forgejo.webgrip.dev"
VIKUNJA_URL = "https://vikunja.${SECRET_DOMAIN}"
ORG = "webgrip"
TZ = "Europe/Amsterdam"
AGENT_LOGINS = r"^(renovate.*|agent-.+|ploeg.*|glide.*|webgrip-ci|.+-bot|.+\[bot\])$"
FORGEJO_BOT_TYPE = 4
FEED_ROWS = 6
IMPORT_COMMITS = 100
AGENT_PR_LOGINS = ("agent-builder",)
LEAD_WINDOW_DAYS = 28
CONFIG_PLACEHOLDER = "/*CONFIG*/ null"
FONTS = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;"
         "12..96,800&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap")

RUN_SUCCESS, RUN_FAILURE, RUN_CANCELLED, RUN_SKIPPED, RUN_WAITING, RUN_RUNNING, RUN_BLOCKED = 1, 2, 3, 4, 5, 6, 7
OP_PUSH, OP_MERGE_PR, OP_RELEASE, OP_AUTO_MERGE_PR = 5, 11, 24, 27

WEEK_START = f"date_trunc('week', now() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}'"
WEEK_START_UNIX = f"extract(epoch FROM {WEEK_START})::bigint"
DAY_START = f"date_trunc('day', now() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}'"
ORG_REPO = f"r.owner_name = '{ORG}' AND NOT r.is_archived AND NOT r.is_mirror"
TRUNK_PUSH = f"a.op_type = {OP_PUSH} AND a.ref_name = 'refs/heads/' || r.default_branch AND a.content LIKE '{{%'"
OWNER_COPY = "a.user_id = r.owner_id"
AGENT = f"(u.type = {FORGEJO_BOT_TYPE} OR u.lower_name ~ '{AGENT_LOGINS}')"


def runs_verdict(where):
    return f"""
        (SELECT CASE WHEN count(*) = 0 THEN NULL
                     WHEN bool_or(x.status = {RUN_FAILURE}) THEN 'failure'
                     WHEN bool_or(x.status IN ({RUN_WAITING}, {RUN_RUNNING}, {RUN_BLOCKED})) THEN 'running'
                     WHEN bool_and(x.status IN ({RUN_SUCCESS}, {RUN_SKIPPED})) THEN 'success'
                     ELSE 'cancelled' END
         FROM (SELECT DISTINCT ON (ar.workflow_id) ar.status FROM action_run ar
               WHERE {where} ORDER BY ar.workflow_id, ar.status = {RUN_CANCELLED}, ar.id DESC) x)
    """


def feed_sql():
    return f"""
        WITH pushes AS (
          SELECT a.id, a.created_unix, a.act_user_id, r.id AS repo_id, r.name AS repo, a.ref_name, a.content::json AS c
          FROM action a JOIN repository r ON r.id = a.repo_id
          WHERE {OWNER_COPY} AND {TRUNK_PUSH} AND {ORG_REPO}
            AND a.created_unix > extract(epoch FROM now() - interval '30 days')
          ORDER BY a.id DESC LIMIT {FEED_ROWS}
        )
        SELECT p.created_unix AS at, p.repo, cm.value->>'Sha1' AS sha, cm.value->>'Message' AS title,
          cm.value->>'AuthorName' AS author, u.lower_name AS pusher, coalesce({AGENT}, false) AS agent,
          cm.ordinality = 1 AS head,
          {runs_verdict("ar.repo_id = p.repo_id AND ar.commit_sha = cm.value->>'Sha1' AND ar.ref = p.ref_name")} AS ci
        FROM pushes p
        CROSS JOIN LATERAL json_array_elements(p.c->'Commits') WITH ORDINALITY cm
        LEFT JOIN "user" u ON u.id = p.act_user_id
        ORDER BY p.id DESC, cm.ordinality LIMIT {FEED_ROWS}
    """


def week_sql():
    commits = f"CASE WHEN a.op_type = {OP_PUSH} THEN (a.content::json->>'Len')::int ELSE 0 END"
    return f"""
        WITH b AS (SELECT {WEEK_START_UNIX} AS ws, extract(epoch FROM now())::bigint AS now_s),
        ev AS (
          SELECT a.op_type, a.repo_id, a.created_unix >= b.ws AS this_week,
            a.created_unix < b.ws AND a.created_unix < b.now_s - 604800 AS last_week_so_far,
            coalesce({AGENT}, false) AS agent, {commits} AS commits, {commits} > {IMPORT_COMMITS} AS import
          FROM action a JOIN repository r ON r.id = a.repo_id CROSS JOIN b
          LEFT JOIN "user" u ON u.id = a.act_user_id
          WHERE {OWNER_COPY} AND {ORG_REPO} AND a.created_unix >= b.ws - 604800
            AND ((({TRUNK_PUSH})) OR a.op_type IN ({OP_MERGE_PR}, {OP_RELEASE}, {OP_AUTO_MERGE_PR}))
        )
        SELECT (SELECT ws FROM b) AS week_start,
          coalesce(sum(commits) FILTER (WHERE this_week AND NOT import), 0) AS commits,
          coalesce(sum(commits) FILTER (WHERE last_week_so_far AND NOT import), 0) AS last_week,
          coalesce(sum(commits) FILTER (WHERE this_week AND agent AND NOT import), 0) AS agent_commits,
          coalesce(sum(commits) FILTER (WHERE this_week AND import), 0) AS imported,
          count(DISTINCT repo_id) FILTER (WHERE this_week AND op_type = {OP_PUSH}) AS repos,
          count(*) FILTER (WHERE this_week AND op_type IN ({OP_MERGE_PR}, {OP_AUTO_MERGE_PR})) AS merged,
          count(*) FILTER (WHERE this_week AND op_type = {OP_RELEASE}) AS releases
        FROM ev
    """


def wins_sql():
    trunk_runs = (f"ar.event = 'push' AND ar.ref = 'refs/heads/' || r.default_branch AND {ORG_REPO}")
    return f"""
        WITH graded AS (
          SELECT ar.repo_id, ar.workflow_id, ar.id, ar.status,
            max(ar.id) FILTER (WHERE ar.status = {RUN_FAILURE}) OVER (PARTITION BY ar.repo_id, ar.workflow_id) AS last_red
          FROM action_run ar JOIN repository r ON r.id = ar.repo_id
          WHERE {trunk_runs} AND ar.status IN ({RUN_SUCCESS}, {RUN_FAILURE})
        )
        SELECT 'streak' AS kind, r.name AS repo, g.workflow_id AS workflow, count(*) AS value
        FROM graded g JOIN repository r ON r.id = g.repo_id
        WHERE g.status = {RUN_SUCCESS} AND g.id > coalesce(g.last_red, 0)
        GROUP BY r.name, g.workflow_id ORDER BY value DESC, r.name LIMIT 1
    """


def pulls_sql():
    return f"""
        SELECT r.name AS repo, i.index AS number, i.name AS title, u.lower_name AS poster,
          coalesce({AGENT}, false) AS agent, i.created_unix AS opened,
          {runs_verdict("ar.repo_id = r.id AND ar.ref = 'refs/pull/' || i.index || '/head'")} AS ci
        FROM issue i
        JOIN repository r ON r.id = i.repo_id
        LEFT JOIN "user" u ON u.id = i.poster_id
        WHERE i.is_pull AND NOT i.is_closed AND {ORG_REPO}
        ORDER BY i.created_unix ASC LIMIT 200
    """


def stages_sql():
    ids = ", ".join(str(p) for p in BOARD_PROJECTS)
    return f"""
        WITH t AS (
          SELECT t.id, t.project_id, t.done, t.updated,
            coalesce(bool_or(l.title = 'review'), false) AS review,
            coalesce(bool_or(l.title LIKE 'agent/%'), false) AS claimed,
            coalesce(bool_or(l.title = 'ready'), false) AS ready,
            coalesce(bool_or(l.title = 'do-next'), false) AS do_next
          FROM tasks t
          LEFT JOIN label_tasks lt ON lt.task_id = t.id
          LEFT JOIN labels l ON l.id = lt.label_id
          WHERE t.project_id IN ({ids}) AND (NOT t.done OR t.done_at >= {WEEK_START})
          GROUP BY t.id, t.project_id, t.done, t.updated
        )
        SELECT project_id AS board,
          count(*) FILTER (WHERE NOT done AND NOT review AND NOT claimed AND NOT ready) AS backlog,
          count(*) FILTER (WHERE NOT done AND NOT review AND NOT claimed AND ready) AS todo,
          count(*) FILTER (WHERE NOT done AND NOT review AND claimed) AS doing,
          count(*) FILTER (WHERE NOT done AND review) AS reviewing,
          count(*) FILTER (WHERE done) AS done,
          count(*) FILTER (WHERE NOT done AND do_next) AS do_next,
          (min(extract(epoch FROM updated)) FILTER (WHERE NOT done AND review))::bigint AS oldest_review
        FROM t GROUP BY project_id ORDER BY project_id
    """


def flow_sql():
    ids = ", ".join(str(p) for p in BOARD_PROJECTS)
    window = f"t.done AND t.done_at >= now() - interval '{LEAD_WINDOW_DAYS} days'"
    lead = "extract(epoch FROM t.done_at - t.created)"
    return f"""
        SELECT t.project_id AS board,
          count(*) FILTER (WHERE t.created >= {WEEK_START}) AS arrived,
          count(*) FILTER (WHERE t.created >= {WEEK_START} - interval '7 days'
                           AND t.created < now() - interval '7 days') AS arrived_last,
          count(*) FILTER (WHERE t.done AND t.done_at >= {WEEK_START}) AS closed,
          count(*) FILTER (WHERE t.done AND t.done_at >= {WEEK_START} - interval '7 days'
                           AND t.done_at < now() - interval '7 days') AS closed_last,
          (percentile_cont(0.5) WITHIN GROUP (ORDER BY {lead}) FILTER (WHERE {window}))::bigint AS lead_p50,
          (percentile_cont(0.85) WITHIN GROUP (ORDER BY {lead}) FILTER (WHERE {window}))::bigint AS lead_p85,
          count(*) FILTER (WHERE {window}) AS lead_sample
        FROM tasks t WHERE t.project_id IN ({ids})
        GROUP BY t.project_id ORDER BY t.project_id
    """


def aging_sql():
    ids = ", ".join(str(p) for p in BOARD_PROJECTS)
    return f"""
        WITH held AS (
          SELECT t.project_id AS board, t.id, t.title,
            CASE WHEN bool_or(l.title = 'review') THEN 'reviewing' ELSE 'doing' END AS stage,
            extract(epoch FROM now() - min(lt.created))::bigint AS in_stage
          FROM tasks t
          JOIN label_tasks lt ON lt.task_id = t.id
          JOIN labels l ON l.id = lt.label_id
          WHERE NOT t.done AND t.project_id IN ({ids}) AND (l.title = 'review' OR l.title LIKE 'agent/%')
          GROUP BY t.project_id, t.id, t.title
        )
        SELECT DISTINCT ON (board, stage) board, stage, in_stage AS oldest, id AS ticket, title
        FROM held ORDER BY board, stage, in_stage DESC
    """


def agents_sql():
    return f"""
        SELECT coalesce(r.role, 'other') AS role,
          count(*) AS runs,
          count(*) FILTER (WHERE r.state = 'running') AS running,
          count(*) FILTER (WHERE r.outcome IN ('pr_opened', 'pr_updated')) AS delivered,
          count(*) FILTER (WHERE r.outcome IN ('failed', 'stuck')) AS failed,
          count(*) FILTER (WHERE r.state = 'finished') AS finished,
          count(DISTINCT r.work_item_id) AS work_items
        FROM agent_runs r
        WHERE r.started_at >= {WEEK_START} OR r.state = 'running'
        GROUP BY 1 ORDER BY runs DESC
    """


def run_keys_sql():
    return f"""
        SELECT 'ploeg-' || left(r.run_token, 12) AS alias, r.team,
          coalesce(nullif(w.target_repo, ''), r.team) AS project
        FROM agent_runs r JOIN work_items w ON w.id = r.work_item_id
        WHERE r.run_token IS NOT NULL AND (r.started_at >= {WEEK_START} - interval '1 day' OR r.state = 'running')
    """


def spend_sql():
    return f"""
        SELECT coalesce(metadata->>'user_api_key_alias', '(none)') AS alias,
          coalesce(sum(spend), 0) AS usd,
          coalesce(sum(spend) FILTER (WHERE "startTime" >= {DAY_START}), 0) AS usd_today,
          coalesce(sum(total_tokens), 0) AS tokens,
          count(*) AS calls,
          count(*) FILTER (WHERE coalesce(metadata->>'status', 'success') <> 'success') AS failed
        FROM "LiteLLM_SpendLogs"
        WHERE "startTime" >= {WEEK_START}
        GROUP BY 1
    """


def agent_prs_sql():
    logins = ", ".join(f"'{login}'" for login in AGENT_PR_LOGINS)
    return f"""
        WITH b AS (SELECT {WEEK_START_UNIX} AS ws),
        prs AS (
          SELECT i.created_unix, i.is_closed, pr.has_merged, pr.merged_unix, r.name AS repo, i.index, i.name AS title
          FROM issue i
          JOIN pull_request pr ON pr.issue_id = i.id
          JOIN "user" u ON u.id = i.poster_id
          JOIN repository r ON r.id = i.repo_id
          WHERE u.lower_name IN ({logins}) AND {ORG_REPO}
        )
        SELECT count(*) FILTER (WHERE created_unix >= b.ws) AS opened,
          count(*) FILTER (WHERE has_merged AND merged_unix >= b.ws) AS merged,
          count(*) FILTER (WHERE has_merged AND merged_unix >= b.ws - 604800 AND merged_unix < b.ws) AS merged_last,
          count(*) FILTER (WHERE NOT is_closed) AS open_now,
          count(*) FILTER (WHERE has_merged AND merged_unix >= b.ws - 2419200) AS merged_28d,
          count(*) FILTER (WHERE is_closed AND NOT has_merged AND created_unix >= b.ws - 2419200) AS closed_28d,
          (SELECT repo || ' #' || index || ' ' || title FROM prs WHERE has_merged ORDER BY merged_unix DESC LIMIT 1) AS last_merged
        FROM prs CROSS JOIN b GROUP BY b.ws
    """


def ci_now_expr():
    ksm = 'job="kube-state-metrics", exported_namespace="forgejo", exported_pod=~"forgejo-runner-[a-z0-9]{5}-[a-z0-9]{5}"'
    parts = {
        "running": 'sum(forgejo_ci_tasks_active{status="running"})',
        "queued": f"max(keda_scaler_metrics_value{{{forgejo_ci.SCALER}}})",
        "runners": f'sum(kube_pod_status_phase{{{ksm}, phase="Running"}})',
        "pending": f'sum(kube_pod_status_phase{{{ksm}, phase="Pending"}})',
    }
    return " or ".join(f'label_replace(({expr}) or on() vector(0), "k", "{name}", "", "")'
                       for name, expr in parts.items())


def ci_failed_expr():
    jobs = "forgejo_ci_jobs_total"
    return (f'sum(increase({jobs}{{status="failure"}}[7d])) '
            f'/ sum(increase({jobs}{{status=~"success|failure"}}[7d]))')


def red_trunks_expr():
    red = forgejo_ci.red_trunks(repo="")
    return (f"(time() - (max by (repo, workflow, ref) (forgejo_ci_last_success_timestamp_seconds) > 0)"
            f" or max by (repo, workflow, ref) (forgejo_ci_consecutive_failures) * 0 - 1)"
            f" and on (repo, workflow, ref) ({red})")


def alert_counts():
    everything = next(g for g in alerts.GROUPS if g["slug"] == "all")
    real = alerts.in_group(everything)
    root = (f'[{{ "critical": $count($[{real} and labels.severity = "critical"]), '
            f'"warning": $count($[{real} and labels.severity = "warning"]) }}]')
    return alerts.am_target(alerts.FIRING, root, [("critical", "critical", "number"), ("warning", "warning", "number")],
                            ref="ALERTS")


def prom(ref, expr):
    return target(expr, ref, instant=True)


def wall_targets():
    return [
        sql(FORGEJO_DB, feed_sql(), ref="FEED"),
        sql(FORGEJO_DB, week_sql(), ref="WEEK"),
        sql(FORGEJO_DB, wins_sql(), ref="WINS"),
        sql(FORGEJO_DB, pulls_sql(), ref="PULLS"),
        sql(VIKUNJA, stages_sql(), ref="STAGES"),
        prom("TRUNK_RED", red_trunks_expr()),
        prom("CI_AGE", "time() - max(forgejo_ci_last_refresh_timestamp_seconds)"),
        prom("PROBES", "min(probe_success) or on() vector(-1)"),
        prom("FLUX", 'count(flux_resource_info{ready="False", suspended="False"}) or on() vector(0)'),
        prom("GLIDE", 'sum by (state) (ploeg_work_items_count{state=~"needs_human|awaiting_review"})'),
        alert_counts(),
        sql(VIKUNJA, flow_sql(), ref="FLOW"),
        sql(VIKUNJA, aging_sql(), ref="AGING"),
        sql(PLOEG_DB, agents_sql(), ref="AGENTS"),
        sql(PLOEG_DB, run_keys_sql(), ref="RUN_KEYS"),
        sql(LITELLM_DB, spend_sql(), ref="SPEND"),
        sql(FORGEJO_DB, agent_prs_sql(), ref="AGENT_PRS"),
        prom("CI_NOW", ci_now_expr()),
        prom("CI_FAILED", ci_failed_expr()),
    ]


def wall_config():
    return {
        "org": ORG,
        "tz": TZ,
        "forgejo": FORGEJO_URL,
        "boards": [{"id": pid, "name": name, "url": f"{VIKUNJA_URL}/projects/{pid}"}
                   for pid, name in BOARD_PROJECTS.items()],
        "importCommits": IMPORT_COMMITS,
        "leadWindowDays": LEAD_WINDOW_DAYS,
        "links": {"ci": "/d/forgejo-ci", "glide": "/d/wall-glide", "plant": "/d/glide-plant",
                  "roadmap": "/d/wall-roadmap",
                  "alerts": "/d/alerts-all", "gitops": "/d/wall-gitops", "now": "/d/wall-now",
                  "pulls": f"{FORGEJO_URL}/pulls", "activity": f"{FORGEJO_URL}/{ORG}"},
    }


def installed_plugins():
    found = re.search(r"- name: GF_INSTALL_PLUGINS\n\s+value: >-\n((?:\s{20}\S.*\n)+)", GRAFANA_INSTANCE.read_text())
    if not found:
        raise SystemExit(f"{GRAFANA_INSTANCE} sets no GF_INSTALL_PLUGINS; the Today wall's panel would never install")
    return [p.strip() for p in found.group(1).replace("\n", "").split(",") if p.strip()]


def asset(name):
    text = (WALL_DIR / name).read_text()
    if "$" in text:
        raise SystemExit(f"{WALL_DIR / name} contains a $: Grafana would read it as a dashboard variable")
    return text


def wall_panel():
    if f"{BUSINESS_TEXT} {BUSINESS_TEXT_VERSION}" not in installed_plugins():
        raise SystemExit(f"{GRAFANA_INSTANCE}: GF_INSTALL_PLUGINS does not install {BUSINESS_TEXT} "
                         f"{BUSINESS_TEXT_VERSION}, which the Today wall is built for. Bump both together.")
    helpers = asset("wall.js")
    if helpers.count(CONFIG_PLACEHOLDER) != 1:
        raise SystemExit(f"{WALL_DIR / 'wall.js'} must carry {CONFIG_PLACEHOLDER!r} exactly once")
    helpers = helpers.replace(CONFIG_PLACEHOLDER, json.dumps(wall_config(), ensure_ascii=False))
    template = asset("wall.hbs")
    return {
        "id": 1, "type": BUSINESS_TEXT, "title": "", "pluginVersion": BUSINESS_TEXT_VERSION, "transparent": True,
        "description": ("What landed on the trunks this week, where the work on the boards is and how fast it flows, "
                        "what the machine did, and what could use a hand. Commits, merges, releases, pull requests "
                        "and Ploeg's pull requests come from the Forgejo database (forgejo-db); stages, flow, lead "
                        "times and aging from the Vikunja database; agent Runs from the Ploeg database; model "
                        "spend, tokens and failures from the LiteLLM ledger; CI from forgejo-ci-exporter and KEDA; "
                        "alerts from Alertmanager."),
        "gridPos": grid_pos(0, 0, 24, 24),
        "datasource": MIXED,
        "options": {
            "renderMode": "data",
            "editors": ["helpers", "styles"],
            "editor": {"language": "html", "format": "none"},
            "wrap": False,
            "contentPartials": [],
            "content": template,
            "defaultContent": template,
            "helpers": helpers,
            "afterRender": "",
            "styles": asset("wall.css"),
            "externalStyles": [{"id": "wall-fonts", "url": FONTS}],
            "status": "",
        },
        "fieldConfig": {"defaults": {}, "overrides": []},
        "targets": wall_targets(),
    }


def today_wall():
    return dashboard(
        UID, "Today", [wall_panel()], tags=["wall", "today"], kiosk=True, time_from="now-7d",
        description="What landed this week, where the work is, and what could use a hand.",
        links=[link("Forgejo CI", "/d/forgejo-ci"), link("Roadmap", "/d/wall-roadmap"),
               doc_link("Information radiators", DOC)])


def boards():
    return [(today_wall(), FOLDER)]
