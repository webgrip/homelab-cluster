from __future__ import annotations

import alerts
from lib import NEUTRAL, alarm_at, dashboard, doc_link, link, low_is_bad, sql, stat, target
from platform_walls import backups_late, flux_not_ready, place, probes_failing, slo_worst

FOLDER = "executive"
DOC = "docs/techdocs/docs/general/information-radiators.md"
LITELLM_DB = {"type": "grafana-postgresql-datasource", "uid": "litellm-db"}
TZ = "Europe/Amsterdam"
MONTH_START = f"date_trunc('month', now() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}'"
EUR_PER_KWH = 0.30
HOURS_PER_MONTH = 730
UNFOLD = 'project="unfold"'


def drill(title, uid):
    return [{"title": title, "url": f"/d/{uid}", "targetBlank": False}]


def money(title, expr, *, unit, desc, uid, targets=None):
    return stat(title, expr, unit=unit, decimals=2, fixed_color=NEUTRAL, desc=desc, targets=targets,
                links=drill(f"Open {uid}", uid))


def homelab_cost():
    return money(
        "Homelab, modelled per month", f"opencost:node_hourly_cost:sum * {HOURS_PER_MONTH}", unit="currencyEUR",
        uid="exec-finops",
        desc="What the six nodes cost per month in OpenCost's model: power plus hardware amortisation at the hourly "
             "rates in the OpenCost HelmRelease. Grey at every value: it moves when nodes or rates change, and "
             "the FinOps dashboard shows which namespace pays for what.")


def electricity():
    return money(
        "Electricity per month, measured floor",
        f'sum(kepler_node_cpu_watts{{zone=~"package|dram"}}) / 1000 * {HOURS_PER_MONTH} * {EUR_PER_KWH}',
        unit="currencyEUR", uid="exec-finops",
        desc=f"Kepler's measured CPU and memory power at EUR {EUR_PER_KWH:.2f} per kWh. The wall socket draws more "
             "(power supplies, disks, fans), so this is the least the cluster costs to run. Each continuous watt "
             "is about EUR 3 a year.")


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
            (homelab_cost(), 0, 5, 6, 5), (electricity(), 6, 5, 6, 5), (hetzner_budget(), 12, 5, 6, 5),
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
