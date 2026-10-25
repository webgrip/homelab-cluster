from __future__ import annotations

import alerts
from lib import NEUTRAL, alarm_at, col, dashboard, doc_link, link, low_is_bad, sql, stat, target
from platform_walls import backups_late, flux_not_ready, place, probes_failing, slo_worst

FOLDER = "executive"
DOC = "docs/techdocs/docs/general/information-radiators.md"
LITELLM_DB = {"type": "grafana-postgresql-datasource", "uid": "litellm-db"}
TZ = "Europe/Amsterdam"
MONTH_START = f"date_trunc('month', now() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}'"
UNFOLD = 'project="unfold"'


def drill(title, uid):
    return [{"title": title, "url": f"/d/{uid}", "targetBlank": False}]


def money(title, expr, *, unit, desc, uid, targets=None):
    return stat(title, expr, unit=unit, decimals=2, fixed_color=NEUTRAL, desc=desc, targets=targets,
                links=drill(f"Open {uid}", uid))


def total_cost():
    panel = stat(
        "Homelab, total per month", None, text_mode="value_and_name", fixed_color=NEUTRAL,
        targets=[target("finops:monthly_total_eur", "A", "total", instant=True),
                 target("finops:monthly_cost_lines_missing", "B", "inputs missing", instant=True)],
        links=drill("Open exec-finops", "exec-finops"),
        desc="Everything the homelab costs per month in EUR: measured electricity, the Hetzner Cloud bill, "
             "model spend and the fixed costs kept in git (prometheusrule-finops.yaml). Inputs missing counts "
             "the cost lines that have no number yet; amber from one, because the total is then too low. The "
             "FinOps dashboard lists each line and its source.")
    panel["fieldConfig"]["overrides"] = [
        col("total", unit="currencyEUR", decimals=2),
        col("inputs missing", decimals=0, thresholds=alarm_at(amber=1)),
    ]
    return panel


def electricity():
    return money(
        "Electricity per month, measured floor",
        'finops:monthly_cost_eur{line="electricity"}',
        unit="currencyEUR", uid="exec-finops",
        desc="Kepler's measured CPU and memory power at the kWh price in prometheusrule-finops.yaml. The "
             "wall socket draws more (power supplies, disks, fans), so this is the least the cluster costs to "
             "run. Each continuous watt is about EUR 3 a year.")


def hetzner_budget():
    projected = f"sum(hcloud:projected_month_eur:sum{{{UNFOLD}}})"
    budget = f"scalar(max(hcloud:budget_month_eur{{{UNFOLD}}}))"
    return stat(
        "Unfold on Hetzner, projected share of budget", f"{projected} / {budget}", unit="percentunit", decimals=0,
        thresholds=alarm_at(amber=0.8, vermillion=1), links=drill("Open unfold-cloud-costs", "unfold-cloud-costs"),
        desc="This month's projected Hetzner Cloud bill for the Unfold project as a share of its monthly budget "
             "(recording rule hcloud:budget_month_eur). Amber from 80 %: find what is running on the Unfold cloud "
             "costs dashboard before the month ends. Vermillion over budget.")


def llm_spend():
    raw = f"""
        SELECT coalesce(sum(spend), 0) AS usd
        FROM "LiteLLM_SpendLogs"
        WHERE "startTime" >= {MONTH_START}
    """
    return money(
        "Model spend this month", None, unit="currencyUSD", uid="today", targets=[sql(LITELLM_DB, raw)],
        desc="What every agent and tool call through LiteLLM cost this calendar month, in USD as LiteLLM's ledger "
             "prices it. Claude Code sessions on the subscription are not in it. The Today wall splits it per "
             "project.")


def critical_cves():
    return stat(
        "Critical CVEs in running images", 'sum(trivy_image_vulnerabilities{severity="Critical"})', decimals=0,
        thresholds=alarm_at(amber=1), links=drill("Open exec-security-supply-chain", "exec-security-supply-chain"),
        desc="Critical vulnerabilities Trivy found in images running now. Amber from one: pick the image with the "
             "most and check whether a newer tag fixes it. No data means Trivy Operator is not being scraped, "
             "not that there are none.")


def memory_headroom():
    requested = 'sum(cluster:kube_pod_running_resource_requests:sum{resource="memory"})'
    allocatable = 'sum(cluster:kube_node_status_allocatable:sum{resource="memory"})'
    return stat(
        "Memory left to schedule", f"1 - {requested} / {allocatable}", unit="percentunit", decimals=0,
        thresholds=low_is_bad(0.10, 0.20), links=drill("Open exec-platform-efficiency", "exec-platform-efficiency"),
        desc="Allocatable memory that running pods have not requested yet. Memory is what runs out first here. "
             "Amber under 20 %: lower requests that sit far above use, or plan more RAM. Vermillion under 10 %: "
             "new pods will stay Pending.")


def firing():
    panel = alerts.firing(alerts.GROUPS[0])
    panel["title"] = "Needs a person: firing now, not silenced"
    return panel


def overview():
    everything = alerts.GROUPS[0]
    critical = alerts.critical(everything)
    critical["title"] = "Critical alerts firing"
    return dashboard(
        "exec-overview", "Executive / Overview", place([
            (critical, 0, 0, 6, 5), (probes_failing(), 6, 0, 6, 5), (flux_not_ready(), 12, 0, 6, 5),
            (backups_late(), 18, 0, 6, 5),
            (total_cost(), 0, 5, 6, 5), (electricity(), 6, 5, 6, 5), (hetzner_budget(), 12, 5, 6, 5),
            (llm_spend(), 18, 5, 6, 5),
            (slo_worst(), 0, 10, 8, 5), (critical_cves(), 8, 10, 8, 5), (memory_headroom(), 16, 10, 8, 5),
            (firing(), 0, 15, 24, 9),
        ]),
        tags=["wall", "executive"], kiosk=True, refresh="1m", time_from="now-24h",
        description="Everything that matters on one screen: is anything broken now, what it costs, how much risk "
                    "and room is left, and what needs a person. Click a tile for its dashboard.",
        links=[link("Scorecard", "/d/exec-kpi-scorecard"), link("FinOps", "/d/exec-finops"),
               link("Unfold cloud costs", "/d/unfold-cloud-costs"), link("Reliability", "/d/exec-reliability-sre"),
               link("Security", "/d/exec-security-supply-chain"), link("Platform", "/d/exec-platform-efficiency"),
               link("Delivery", "/d/exec-value-flow-delivery"), link("Homelab now", "/d/wall-now"),
               link("Today", "/d/today"), doc_link("Information radiators", DOC)])


def boards():
    return [(overview(), FOLDER)]
