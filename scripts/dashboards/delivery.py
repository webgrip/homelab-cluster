from __future__ import annotations

import forgejo_ci
from lib import (AMBER, NEUTRAL, VERMILLION, alarm_at, bars, col, dashboard, doc_link, grid_pos, link, number, sql,
                 stat, table, tag_links, target)
from today import FORGEJO_DB, FORGEJO_URL, ORG, ORG_REPO, runs_verdict

UID = "delivery-estate"
FOLDER = "boards"
TAGS = ["board", "delivery", "renovate", "forgejo"]
DOC = "docs/techdocs/docs/general/delivery-estate.md"
INVENTORY = 'job="repo-config-inventory"'
LOOKBACK = "2h"
PUSH_SLACK = 900
WINDOW_DAYS = 30
RENOVATE = "u.lower_name LIKE 'renovate%'"
UPSTREAM = r"(@?webgrip/[A-Za-z0-9._-]+|webgrip dependencies)"
APPROVE = 1


def fresh(metric):
    last_push = (f"scalar(max(tlast_over_time(repo_config_inventory_last_success_timestamp_seconds"
                 f"{{{INVENTORY}}}[{LOOKBACK}])))")
    return (f"(last_over_time({metric}{{{INVENTORY}}}[{LOOKBACK}]) and "
            f"(tlast_over_time({metric}{{{INVENTORY}}}[{LOOKBACK}]) > {last_push} - {PUSH_SLACK}))")


def pr_link(title="Open the pull request"):
    return [{"title": title, "url": "${__data.fields.url}", "targetBlank": True}]


def open_pull_requests():
    url = f"'{FORGEJO_URL}/{ORG}/' || r.name || '/pulls/' || i.index"
    return f"""
        WITH open_prs AS (
          SELECT r.name AS repo, i.index AS number, i.name AS title, coalesce(u.lower_name, '?') AS author,
            {url} AS url, extract(epoch FROM now())::bigint - i.created_unix AS age,
            coalesce({RENOVATE}, false) AS renovate,
            EXISTS (SELECT 1 FROM issue_label il JOIN label l ON l.id = il.label_id
                    WHERE il.issue_id = i.id AND l.name = 'automerge') AS automerge,
            EXISTS (SELECT 1 FROM review rv WHERE rv.issue_id = i.id AND rv.type = {APPROVE} AND rv.official
                    AND NOT rv.dismissed) AS approved,
            {runs_verdict("ar.repo_id = r.id AND ar.ref = 'refs/pull/' || i.index || '/head'")} AS ci
          FROM issue i
          JOIN repository r ON r.id = i.repo_id
          LEFT JOIN "user" u ON u.id = i.poster_id
          WHERE i.is_pull AND NOT i.is_closed AND {ORG_REPO}
        )
        SELECT *, CASE
            WHEN ci = 'failure' THEN 'red checks'
            WHEN ci = 'running' THEN 'checks running'
            WHEN ci IS NULL THEN 'no checks ran'
            WHEN automerge AND renovate THEN 'automerge due'
            WHEN approved THEN 'approved, not merged'
            ELSE 'waiting for review' END AS waits_on
        FROM open_prs
    """


WAITS_ON_A_PERSON = "('waiting for review', 'approved, not merged', 'no checks ran')"


def count_open(where):
    return f"SELECT count(*) AS value FROM ({open_pull_requests()}) q WHERE {where}"


def active_repositories():
    return stat(
        "Active repositories", f"count({fresh('repo_config_repository_info')})", decimals=0, fixed_color=NEUTRAL,
        desc="Repositories in the webgrip organisation on Forgejo that are neither archived nor a pull mirror, as "
             "the repo-config inventory read them within the last two hours. Each is a row in the estate table.")


def behind_on_shared():
    return stat(
        "Repositories behind a shared package",
        f"count(count by (repository) ({fresh('repo_config_shared_pin_releases_behind')} > 0))",
        decimals=0, fixed_color=NEUTRAL, no_value="0",
        desc="Repositories whose oldest pin of workflows, renovate-config, agent-standards or "
             "semantic-release-config is older than that package's newest stable release. The estate table shows "
             "which pin and by how many releases. A large number here with few open Renovate PRs means the bumps "
             "are majors waiting for a person, or the repository has no Renovate.")


def unversioned_pins():
    return stat(
        "Unversioned shared pins", f"count({fresh('repo_config_shared_pin_unversioned')})", decimals=0,
        thresholds=alarm_at(amber=1), no_value="0",
        desc="Pins of a shared package with no version Renovate can read: a workflow call by SHA without a "
             "`# vX.Y.Z` comment, a branch name, or a preset without `#vX.Y.Z`. Renovate never moves these. "
             "Amber from one: add the version comment or the tag.")


def waiting_on_a_person():
    return stat(
        "Open PRs waiting on a person", None, decimals=0, thresholds=alarm_at(amber=5, vermillion=15),
        targets=[sql(FORGEJO_DB, count_open(f"waits_on IN {WAITS_ON_A_PERSON}"))],
        desc="Open pull requests whose checks passed (or never ran) and that will not merge by themselves: no "
             "approval yet, approved but not merged, or no CI on pull requests at all. Renovate PRs with the "
             "automerge label are not counted; Renovate merges them on its next run. Amber from 5, vermillion "
             "from 15: review or close from the queue table below.")


def red_pull_requests():
    return stat(
        "Open PRs with red checks", None, decimals=0, thresholds=alarm_at(amber=1, vermillion=10),
        targets=[sql(FORGEJO_DB, count_open("waits_on = 'red checks'"))],
        desc="Open pull requests whose latest run of some workflow failed on the PR head. A red Renovate PR "
             "blocks its whole group branch. Amber from one, vermillion from ten.")


def oldest_renovate_pr():
    return stat(
        "Oldest open Renovate PR", None, unit="s", decimals=0, thresholds=alarm_at(amber=7 * 86400,
                                                                                    vermillion=14 * 86400),
        targets=[sql(FORGEJO_DB, f"SELECT max(age) AS value FROM ({open_pull_requests()}) q WHERE renovate")],
        no_value="none open",
        desc="Age of the oldest open pull request Renovate opened. Amber from a week, vermillion from two: a "
             "dependency PR that old is either blocked on a person or abandoned and keeps the repository behind.")


def ci_queue():
    panel = forgejo_ci.queue_wait()
    panel["title"] = "CI queue wait p95"
    panel["links"] = [{"title": "Open Forgejo CI", "url": "/d/forgejo-ci"}]
    return panel


ESTATE_COLUMNS = ["repository", "kind", "branching", "core", "github_mirror", "renovate_gate", "releases", "ships",
                  "workflows", "renovate_config", "agent_standards", "semantic_release_config", "workflow_calls"]


def estate():
    behind = [{"type": "regex", "options": {"pattern": ".*behind$", "result": {"color": AMBER}}},
              {"type": "regex", "options": {"pattern": "^unversioned.*", "result": {"color": VERMILLION}}}]
    pins = [col(name, colour_text=True, mappings=behind) for name in
            ("workflows", "renovate_config", "agent_standards", "semantic_release_config")]
    kinds = [{"type": "value", "options": {"unmodelled": {"color": AMBER}, "unset": {"color": AMBER}}}]
    gates = [{"type": "value", "options": {"none": {"color": AMBER}}}]
    return table(
        "Estate: how each repository builds, releases and ships",
        [target(f"max by ({', '.join(ESTATE_COLUMNS)}) ({fresh('repo_config_repository_info')})",
                instant=True, fmt="table")],
        hide=["Value"], order=ESTATE_COLUMNS, sort_field="repository", sort_desc=False,
        rename={"github_mirror": "GitHub mirror", "renovate_gate": "Renovate gate",
                "renovate_config": "renovate-config", "agent_standards": "agent-standards",
                "semantic_release_config": "semantic-release-config", "workflow_calls": "shared workflows called"},
        overrides=[*pins, col("kind", colour_text=True, mappings=kinds),
                   col("Renovate gate", colour_text=True, mappings=gates)],
        desc="One row per active repository. kind, branching (staged or trunk), core and GitHub mirror come from "
             "the repo-config model; everything else is read from the repository's default branch every hour. "
             "Renovate gate is the profile its renovate.json extends (app, site, library, image-set), presets when "
             "it composes presets without a profile, own when it has config but no shared preset, none without "
             "a config. releases says whether a workflow calls the shared semantic-release workflow, runs "
             "semantic-release itself, or neither. ships lists what the workflows publish (cloudflare, image, "
             "chart, npm, docs), from shared workflow calls and well-known publish steps. Pins show every version "
             "found; amber when the oldest is behind the newest stable release, vermillion when one has no "
             "version at all.")


def queue_table():
    query = f"SELECT repo, number, title, author, waits_on, age, url FROM ({open_pull_requests()}) q"
    order = ["repo", "number", "title", "author", "waits_on", "age"]
    states = {"red checks": VERMILLION, "no checks ran": AMBER, "waiting for review": AMBER,
              "approved, not merged": AMBER}
    return table(
        "Bottleneck queue: open pull requests, oldest first", [sql(FORGEJO_DB, query)],
        hide=["url"], order=order, sort_field="age",
        rename={"waits_on": "waits on", "number": "#"},
        overrides=[col("age", unit="s", decimals=0, width=90),
                   col("waits on", colour_text=True, width=170,
                       mappings=[{"type": "value", "options": {k: {"color": v} for k, v in states.items()}}]),
                   col("title", links=pr_link()), col("repo", width=170), col("#", width=60),
                   col("author", width=120)],
        desc="Every open pull request in the organisation and what it is waiting on: red checks (fix or close), "
             "checks running, no checks ran (the repository runs no CI on pull requests, so a person must judge "
             "it), automerge due (Renovate merges it on its next run), approved but not merged, or waiting for "
             "review. Core repositories need a second person's approval (ADR-0083). Click a title to open it.")


def pile_up():
    query = f"""
        SELECT repo, count(*) AS open,
          count(*) FILTER (WHERE waits_on IN {WAITS_ON_A_PERSON}) AS person,
          count(*) FILTER (WHERE waits_on = 'red checks') AS red,
          count(*) FILTER (WHERE renovate) AS renovate,
          max(age) AS oldest
        FROM ({open_pull_requests()}) q GROUP BY repo
    """
    return table(
        "Where pull requests pile up", [sql(FORGEJO_DB, query)], sort_field="open",
        order=["repo", "open", "person", "red", "renovate", "oldest"],
        rename={"person": "on a person", "renovate": "from Renovate"},
        overrides=[col("oldest", unit="s", decimals=0), col("red", thresholds=alarm_at(amber=1), colour_text=True),
                   col("on a person", thresholds=alarm_at(amber=3), colour_text=True)],
        desc="Open pull requests per repository: how many wait on a person, how many are red, how many Renovate "
             "opened, and the age of the oldest. A repository near the top is where the next hour of review "
             "unblocks the most.")


def first_screen():
    placed = [
        (active_repositories(), 0, 0, 3, 4), (behind_on_shared(), 3, 0, 3, 4), (unversioned_pins(), 6, 0, 3, 4),
        (waiting_on_a_person(), 9, 0, 4, 4), (red_pull_requests(), 13, 0, 4, 4), (oldest_renovate_pr(), 17, 0, 4, 4),
        (ci_queue(), 21, 0, 3, 4),
        (estate(), 0, 4, 24, 12),
        (queue_table(), 0, 16, 16, 10), (pile_up(), 16, 16, 8, 10),
    ]
    panels = []
    for panel, x, y, w, h in placed:
        panel["gridPos"] = grid_pos(x, y, w, h)
        panels.append(panel)
    return panels


def window(column):
    return f"{column} > extract(epoch FROM now() - interval '{WINDOW_DAYS} days')"


def fan_out():
    query = f"""
        SELECT coalesce(substring(i.name from '{UPSTREAM}'), 'third-party') AS upstream,
          count(*) AS opened, count(DISTINCT i.repo_id) AS repositories,
          count(*) FILTER (WHERE pr.has_merged) AS merged,
          count(*) FILTER (WHERE NOT i.is_closed) AS still_open,
          count(*) FILTER (WHERE i.is_closed AND NOT pr.has_merged) AS closed_unmerged,
          percentile_cont(0.5) WITHIN GROUP (ORDER BY pr.merged_unix - i.created_unix)
            FILTER (WHERE pr.has_merged) AS median_to_merge
        FROM issue i
        JOIN pull_request pr ON pr.issue_id = i.id
        JOIN repository r ON r.id = i.repo_id
        JOIN "user" u ON u.id = i.poster_id
        WHERE i.is_pull AND {RENOVATE} AND {window('i.created_unix')} AND {ORG_REPO}
        GROUP BY 1
    """
    return table(
        f"Renovate pull requests per upstream, last {WINDOW_DAYS} days", [sql(FORGEJO_DB, query)],
        sort_field="opened", order=["upstream", "opened", "repositories", "merged", "still_open", "closed_unmerged",
                                    "median_to_merge"],
        rename={"still_open": "still open", "closed_unmerged": "closed unmerged",
                "median_to_merge": "median time to merge"},
        overrides=[col("median time to merge", unit="s", decimals=0),
                   col("closed unmerged", thresholds=alarm_at(amber=5), colour_text=True)],
        desc="Each release of a shared package reaches its consumers as one Renovate pull request per repository, "
             "and each runs that repository's full CI. This counts that fan-out: pull requests Renovate opened "
             "per upstream (taken from the title), in how many repositories, how many merged, and how long they "
             "took. webgrip dependencies is the grouped first-party branch; renovate-config and agent-standards "
             "bumps get a branch of their own on purpose (see the doc). Closed unmerged usually means superseded "
             "by a newer release before the old one merged.")


def adoption():
    latest = table(
        "Shared packages: newest release and who runs it",
        [target(f"max by (package, version) ({fresh('repo_config_shared_latest')})", "A", instant=True,
                fmt="table"),
         target(f"count by (package) ({fresh('repo_config_shared_pin_releases_behind')} == 0)", "B",
                instant=True, fmt="table"),
         target(f"count by (package) ({fresh('repo_config_shared_pin_releases_behind')} > 0)", "C",
                instant=True, fmt="table"),
         target(f"max by (package) ({fresh('repo_config_shared_pin_releases_behind')})", "D", instant=True,
                fmt="table")],
        hide=["Value #A"], order=["package", "version", "Value #B", "Value #C", "Value #D"],
        rename={"version": "newest stable", "Value #B": "repositories current", "Value #C": "repositories behind",
                "Value #D": "most releases behind"},
        overrides=[col("most releases behind", thresholds=alarm_at(amber=5), colour_text=True)],
        desc="Per shared package: its newest stable tag, how many repositories pin it, how many are behind and "
             "the worst lag in releases. Repositories with no versioned pin of a package are not counted.")
    calls = bars(
        "Shared workflows: how many repositories call each",
        [target(f"sort_desc(count by (workflow) ({fresh('repo_config_workflow_call')}))", legend="{{workflow}}",
                instant=True)],
        decimals=0,
        desc="How many repositories call each reusable workflow of webgrip/workflows. A workflow few repositories "
             "call is a candidate to fold in or retire; one nearly all call is the de-facto recipe.")
    shape = table(
        "Estate shape",
        [target(f"count by (kind, releases) ({fresh('repo_config_repository_info')})", instant=True, fmt="table")],
        order=["kind", "releases", "Value"], rename={"Value": "repositories"}, sort_field="repositories",
        desc="Repositories per kind (from the model) and release path (from the workflows). ADR-0078 says every "
             "service, image set, package and site releases with semantic-release; a row with releases none for "
             "those kinds is a repository not yet on the recipe.")
    return [(latest, 0, 12, 8), (shape, 12, 12, 8), (calls, 0, 24, 9)]


def merge_flow():
    query = f"""
        SELECT r.name AS repo,
          count(*) FILTER (WHERE {RENOVATE}) AS renovate_merged,
          percentile_cont(0.5) WITHIN GROUP (ORDER BY pr.merged_unix - i.created_unix)
            FILTER (WHERE {RENOVATE}) AS renovate_median,
          count(*) FILTER (WHERE NOT {RENOVATE}) AS people_merged,
          percentile_cont(0.5) WITHIN GROUP (ORDER BY pr.merged_unix - i.created_unix)
            FILTER (WHERE NOT {RENOVATE}) AS people_median
        FROM issue i
        JOIN pull_request pr ON pr.issue_id = i.id
        JOIN repository r ON r.id = i.repo_id
        JOIN "user" u ON u.id = i.poster_id
        WHERE i.is_pull AND pr.has_merged AND {window('pr.merged_unix')} AND {ORG_REPO}
        GROUP BY r.name
    """
    merged = table(
        f"Time to merge per repository, last {WINDOW_DAYS} days", [sql(FORGEJO_DB, query)],
        sort_field="renovate_median",
        order=["repo", "renovate_merged", "renovate_median", "people_merged", "people_median"],
        rename={"renovate_merged": "Renovate merged", "renovate_median": "Renovate median",
                "people_merged": "others merged", "people_median": "others median"},
        overrides=[col("Renovate median", unit="s", decimals=0, thresholds=alarm_at(amber=3 * 86400),
                       colour_text=True),
                   col("others median", unit="s", decimals=0)],
        desc="Merged pull requests per repository and the median time from opening to merge, split into "
             "Renovate's and everyone else's. A Renovate median over three days means the repository's gate "
             "(review, red CI, no automerge) is the bottleneck, not Renovate.")
    approvals_query = f"""
        SELECT r.name AS repo,
          (SELECT count(*) FROM regexp_matches(i.content, 'approve-branch=', 'g')) AS pending_approval,
          i.updated_unix * 1000 AS dashboard_updated,
          '{FORGEJO_URL}/{ORG}/' || r.name || '/issues/' || i.index AS url
        FROM issue i
        JOIN repository r ON r.id = i.repo_id
        WHERE NOT i.is_pull AND NOT i.is_closed AND i.name LIKE '%Dependency Dashboard%' AND {ORG_REPO}
    """
    approvals = table(
        "Updates waiting for a dashboard tick", [sql(FORGEJO_DB, approvals_query)], sort_field="pending_approval",
        hide=["url"], order=["repo", "pending_approval", "dashboard_updated"],
        rename={"pending_approval": "pending approval", "dashboard_updated": "dashboard updated"},
        overrides=[col("dashboard updated", unit="dateTimeFromNow"),
                   col("repo", links=[{"title": "Open the Dependency Dashboard", "url": "${__data.fields.url}",
                                       "targetBlank": True}])],
        desc="Updates Renovate found but will not open a pull request for until someone ticks them on the "
             "repository's Dependency Dashboard issue: third-party majors and the always-review list. Read from "
             "the dashboard issue's text, so it is only as fresh as Renovate's last run on that repository "
             "(dashboard updated).")
    return [(merged, 0, 14, 10), (approvals, 14, 10, 10)]


def releases():
    query = f"""
        SELECT r.name AS repo,
          count(*) FILTER (WHERE NOT rl.is_prerelease) AS stable,
          count(*) FILTER (WHERE rl.is_prerelease) AS candidates,
          (array_agg(rl.tag_name ORDER BY rl.created_unix DESC))[1] AS last_tag,
          max(rl.created_unix) * 1000 AS last_at
        FROM release rl
        JOIN repository r ON r.id = rl.repo_id
        WHERE NOT rl.is_draft AND {window('rl.created_unix')} AND {ORG_REPO}
        GROUP BY r.name
    """
    return [(table(
        f"Releases per repository, last {WINDOW_DAYS} days", [sql(FORGEJO_DB, query)], sort_field="last_at",
        order=["repo", "stable", "candidates", "last_tag", "last_at"],
        rename={"last_tag": "last tag", "last_at": "last release"},
        overrides=[col("last release", unit="dateTimeFromNow")],
        desc="Tags and releases cut per repository, stable and release candidate (-rc) apart. A staged "
             "repository with many candidates and no stable is waiting on a promotion, which is a person's "
             "step by design (ADR-0078)."), 0, 24, 9)]


def inventory_health():
    age = stat(
        "Inventory last read", f"time() - max(repo_config_inventory_last_success_timestamp_seconds{{{INVENTORY}}})",
        unit="s", decimals=0, thresholds=alarm_at(amber=3 * 3600, vermillion=6 * 3600),
        desc="Time since the repo-config inventory last pushed. It runs hourly; past three hours every table on "
             "this board that reads repo_config_* goes empty.")
    failed = stat(
        "Repositories it could not read", f"max({fresh('repo_config_inventory_scan_failed_repositories')})",
        decimals=0, thresholds=alarm_at(amber=1), no_value="0",
        desc="Repositories whose workflow, Renovate or agent files the inventory could not read on its last run; "
             "their estate row says unread. The CronJob's log names them.")
    return [(age, 0, 6, 4), (failed, 6, 6, 4)]


def rows():
    return [
        ("Dissemination: one release, many pull requests", fan_out_row()),
        ("Merge flow and approvals", merge_flow()),
        ("Releases", releases()),
        ("Inventory health", inventory_health()),
    ]


def fan_out_row():
    return [(fan_out(), 0, 24, 9), *adoption()]


LINKS = [link("Forgejo CI", "/d/forgejo-ci"), link("Renovate operator", "/d/platform-renovate-operator"),
         link("Agent standard estate", "/d/agent-standards-estate"), link("Today", "/d/today"), doc_link("Delivery estate", DOC), tag_links(["board"], "Boards")]


def desk():
    panels = number(first_screen() + forgejo_ci.lay_out_rows(26, rows()))
    return dashboard(
        UID, "Delivery estate", panels, tags=TAGS, links=LINKS, time_from="now-24h", refresh="5m",
        description="How each repository builds, releases and ships, which version of each shared package it "
                    "runs, and where pull requests wait. Repository facts come from the repo-config inventory; "
                    "pull requests, merges and releases from the Forgejo database.")


def boards():
    return [(desk(), FOLDER)]
