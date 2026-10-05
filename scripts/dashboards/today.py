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
FORGEJO_URL = "https://forgejo.webgrip.dev"
VIKUNJA_URL = "https://vikunja.${SECRET_DOMAIN}"
ORG = "webgrip"
TZ = "Europe/Amsterdam"
AGENT_LOGINS = r"^(renovate.*|agent-.+|ploeg.*|glide.*|webgrip-ci|.+-bot|.+\[bot\])$"
FORGEJO_BOT_TYPE = 4
FEED_ROWS = 7
CONFIG_PLACEHOLDER = "/*CONFIG*/ null"
FONTS = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;"
         "12..96,800&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap")

RUN_SUCCESS, RUN_FAILURE, RUN_CANCELLED, RUN_SKIPPED, RUN_WAITING, RUN_RUNNING, RUN_BLOCKED = 1, 2, 3, 4, 5, 6, 7
OP_PUSH, OP_MERGE_PR, OP_RELEASE, OP_AUTO_MERGE_PR = 5, 11, 24, 27

WEEK_START = f"date_trunc('week', now() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}'"
WEEK_START_UNIX = f"extract(epoch FROM {WEEK_START})::bigint"
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
    return f"""
        WITH b AS (SELECT {WEEK_START_UNIX} AS ws),
        ev AS (
          SELECT a.op_type, a.repo_id, a.created_unix >= b.ws AS this_week, coalesce({AGENT}, false) AS agent,
            CASE WHEN a.op_type = {OP_PUSH} THEN (a.content::json->>'Len')::int ELSE 0 END AS commits
          FROM action a JOIN repository r ON r.id = a.repo_id CROSS JOIN b
          LEFT JOIN "user" u ON u.id = a.act_user_id
          WHERE {OWNER_COPY} AND {ORG_REPO} AND a.created_unix >= b.ws - 604800
            AND ((({TRUNK_PUSH})) OR a.op_type IN ({OP_MERGE_PR}, {OP_RELEASE}, {OP_AUTO_MERGE_PR}))
        )
        SELECT (SELECT ws FROM b) AS week_start,
          coalesce(sum(commits) FILTER (WHERE this_week), 0) AS commits,
          coalesce(sum(commits) FILTER (WHERE NOT this_week), 0) AS last_week,
          coalesce(sum(commits) FILTER (WHERE this_week AND agent), 0) AS agent_commits,
          count(DISTINCT repo_id) FILTER (WHERE this_week AND op_type = {OP_PUSH}) AS repos,
          count(*) FILTER (WHERE this_week AND op_type IN ({OP_MERGE_PR}, {OP_AUTO_MERGE_PR})) AS merged,
          count(*) FILTER (WHERE this_week AND op_type = {OP_RELEASE}) AS releases
        FROM ev
    """


def wins_sql():
    trunk_runs = (f"ar.event = 'push' AND ar.ref = 'refs/heads/' || r.default_branch AND {ORG_REPO}")
    return f"""
        WITH b AS (SELECT {WEEK_START_UNIX} AS ws),
        fastest AS (
          SELECT 'fastest' AS kind, r.name AS repo, ar.workflow_id AS workflow, ar.stopped - ar.created AS value
          FROM action_run ar JOIN repository r ON r.id = ar.repo_id CROSS JOIN b
          WHERE {trunk_runs} AND ar.status = {RUN_SUCCESS} AND ar.created >= b.ws AND ar.stopped > ar.created
          ORDER BY value ASC LIMIT 1
        ),
        graded AS (
          SELECT ar.repo_id, ar.workflow_id, ar.id, ar.status,
            max(ar.id) FILTER (WHERE ar.status = {RUN_FAILURE}) OVER (PARTITION BY ar.repo_id, ar.workflow_id) AS last_red
          FROM action_run ar JOIN repository r ON r.id = ar.repo_id
          WHERE {trunk_runs} AND ar.status IN ({RUN_SUCCESS}, {RUN_FAILURE})
        ),
        streak AS (
          SELECT 'streak' AS kind, r.name AS repo, g.workflow_id AS workflow, count(*) AS value
          FROM graded g JOIN repository r ON r.id = g.repo_id
          WHERE g.status = {RUN_SUCCESS} AND g.id > coalesce(g.last_red, 0)
          GROUP BY r.name, g.workflow_id ORDER BY value DESC, r.name LIMIT 1
        )
        SELECT kind, repo, workflow, value FROM fastest
        UNION ALL SELECT kind, repo, workflow, value FROM streak
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
    ]


def wall_config():
    return {
        "org": ORG,
        "tz": TZ,
        "forgejo": FORGEJO_URL,
        "boards": [{"id": pid, "name": name, "url": f"{VIKUNJA_URL}/projects/{pid}"}
                   for pid, name in BOARD_PROJECTS.items()],
        "links": {"ci": "/d/forgejo-ci", "glide": "/d/wall-glide", "roadmap": "/d/wall-roadmap",
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
        "description": ("What landed on the trunks this week, where the work on the boards is, and what could use a "
                        "hand. Commits, merges, releases and pull requests come from the Forgejo database "
                        "(datasource forgejo-db), stages from the Vikunja database, red trunks and freshness "
                        "from forgejo-ci-exporter, alerts from Alertmanager."),
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
