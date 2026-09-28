from __future__ import annotations

import json
import urllib.parse

from lib import (ALERTMANAGER_API, AMBER, NEUTRAL, VERMILLION, Grid, col, dashboard, doc_link, kiosk_steps, link,
                 number, stat, state_timeline, table, target, value_map)

FOLDER = "walls"
TAGS = ["wall", "alerts"]
DOC = "docs/techdocs/docs/general/information-radiators.md"
AM_ALERTS = "http://vmalertmanager-vmalertmanager.observability.svc.cluster.local:9093/api/v2/alerts"
HEARTBEAT = "Watchdog"
DUPLICATE_SCRAPE = "opencost"
TILE_SIZE = 64

GROUPS = [
    {"slug": "all", "name": "Everything", "services": None, "folders": None},
    {"slug": "platform", "name": "Platform",
     "services": ["kubernetes", "kubernetes-api", "apiserver", "etcd", "nodes", "scheduling", "cilium", "network",
                  "envoy-gateway", "kube-state-metrics", "observability", "synthetics", "talos"],
     "folders": ["Kubernetes", "Networking", "Observability", "Synthetics", "Platform"]},
    {"slug": "delivery", "name": "Delivery",
     "services": ["flux", "renovate", "forgejo", "forgejo-ci", "harbor"],
     "folders": ["Infrastructure"]},
    {"slug": "data", "name": "Data",
     "services": ["cnpg", "longhorn", "garage", "garage-s3", "openbao"],
     "folders": ["Storage", "Data"]},
    {"slug": "security", "name": "Security",
     "services": ["trivy-operator", "external-secrets", "authentik", "kyverno", "dependency-track-metrics-exporter",
                  "cert-manager"],
     "folders": ["Security"]},
    {"slug": "ai", "name": "AI and Glide",
     "services": ["omnigraph", "omnigraph-explorer", "open-webui", "tei-embeddings", "litellm", "ploeg"],
     "folders": ["AI"]},
]

FIRING = {"active": "true", "silenced": "false", "inhibited": "false", "unprocessed": "false"}
MUTED = {"active": "false", "silenced": "true", "inhibited": "true", "unprocessed": "false"}


def url(flags):
    return AM_ALERTS + "?" + urllib.parse.urlencode(list(flags.items()))


def in_group(group):
    real = (f'labels.alertname != "{HEARTBEAT}" and '
            f'($not($exists(labels.job)) or labels.job != "{DUPLICATE_SCRAPE}")')
    if group["services"] is None:
        return real
    services = json.dumps(group["services"])
    folders = json.dumps(group["folders"])
    return f"{real} and (labels.service in {services} or labels.grafana_folder in {folders})"


def scoped(group):
    return f"$[{in_group(group)}]"


def count_where(group, extra):
    return f'[{{ "n": $count($[{in_group(group)} and {extra}]) }}]'


RANK = ('$rank := function($a) { $a.labels.severity = "critical" ? 0 : '
        '($a.labels.severity = "warning" ? 1 : 2) }')
ABOUT = ('$join([$a.labels.service, $a.labels.node, '
         '$exists($a.labels.exported_namespace) ? $a.labels.exported_namespace : $a.labels.namespace, '
         '$a.labels.name, $a.labels.repo], " · ")')


def rows_selector(group):
    return ("( " + RANK + "; $in := " + scoped(group) + "; "
            "[$map($sort($in, function($l, $r) { $rank($l) = $rank($r) ? $l.startsAt > $r.startsAt "
            ": $rank($l) > $rank($r) }), function($a) { { "
            '"severity": $a.labels.severity, "alert": $a.labels.alertname, '
            '"summary": $a.annotations.summary, "about": ' + ABOUT + ", "
            '"since": $a.startsAt, "runbook": $a.annotations.runbook_url } })] )')


def am_target(flags, root, columns, ref="A"):
    return {
        "refId": ref, "datasource": ALERTMANAGER_API, "type": "json", "source": "url", "format": "table",
        "parser": "backend", "url": url(flags), "url_options": {"method": "GET", "data": ""},
        "root_selector": root,
        "columns": [{"selector": s, "text": t, "type": k} for s, t, k in columns],
    }


def am_stat(title, flags, root, thresholds, desc):
    return stat(title, None, unit="none", decimals=0, value_size=TILE_SIZE, no_value="0",
                thresholds=thresholds, targets=[am_target(flags, root, [("n", "n", "number")])], desc=desc)


def critical(group):
    return am_stat(
        "Critical firing", FIRING, count_where(group, 'labels.severity = "critical"'),
        kiosk_steps((VERMILLION, 1)),
        "Critical alerts firing now in this group, as Alertmanager holds them. Silenced and inhibited alerts "
        "are not counted, and neither are the copies OpenCost's scrape of kube-state-metrics series produces. "
        "Vermillion from one: a critical alert means someone acts now.")


def warning(group):
    return am_stat(
        "Warning firing", FIRING, count_where(group, 'labels.severity = "warning"'),
        kiosk_steps((AMBER, 1)),
        "Warning alerts firing now in this group, silenced, inhibited and duplicate-scrape alerts left out. "
        "Amber from one: someone should look today.")


def silenced(group):
    return am_stat(
        "Silenced now", MUTED, count_where(group, "$count(status.silencedBy) > 0"), kiosk_steps(),
        "Alerts in this group that are firing but held back by a silence, so the room knows something is muted "
        "rather than fixed. Grey at every value: a silence is a decision somebody already made. Who set it and "
        "until when is in Alertmanager's silence list.")


def heartbeat():
    return am_stat(
        "Alerting pipeline", FIRING, f'[{{ "n": $count($[labels.alertname = "{HEARTBEAT}"]) }}]',
        kiosk_steps((VERMILLION, 0), (NEUTRAL, 1)),
        "The Watchdog heartbeat as Alertmanager receives it: 1 means vmalert evaluates rules and Alertmanager "
        "receives them. Vermillion at 0, because then every other number on this wall is silent for the wrong "
        "reason: check vmalert and Alertmanager in the observability namespace.")


def firing(group):
    who = "anything" if group["services"] is None else f"the {group['name'].lower()} group"
    panel = table(
        "Firing now", [am_target(FIRING, rows_selector(group), [
            ("severity", "severity", "string"), ("alert", "alert", "string"),
            ("summary", "summary", "string"), ("about", "about", "string"),
            ("since", "since", "timestamp"), ("runbook", "runbook", "string")])],
        no_value=f"Nothing is firing for {who}.", cell_height="lg",
        overrides=[
            col("runbook", hidden=True),
            col("severity", width=120, colour_text=True, mappings=value_map(
                critical={"text": "critical", "color": VERMILLION, "index": 0},
                warning={"text": "warning", "color": AMBER, "index": 1},
                info={"text": "info", "color": NEUTRAL, "index": 2})),
            col("alert", width=320, links=[{
                "title": "Open the runbook for this alert", "url": "${__data.fields.runbook}",
                "targetBlank": True}]),
            col("about", width=320),
            col("since", width=160, unit="dateTimeFromNow"),
        ],
        desc="Every alert firing now for this wall, read from Alertmanager's API with silenced and inhibited "
             "alerts left out, so a silence clears the wall at the next refresh. Critical first, then warning, "
             "then the rest, newest first within each. `about` is the service, node, namespace, object and repo "
             "the alert names, whichever it carries. Click an alert name to open its runbook.")
    panel["fieldConfig"]["defaults"]["custom"] = {"align": "left", "cellOptions": {"type": "auto"}}
    panel["transformations"] = []
    return panel


def history(group):
    sel = f'alertstate="firing", alertname!="{HEARTBEAT}", job!="{DUPLICATE_SCRAPE}"'
    if group["services"] is not None:
        sel += ', service=~"' + "|".join(group["services"]) + '"'
    expr = (f'max by (alertname) (3 * ALERTS{{{sel}, severity="critical"}} '
            f'or 2 * ALERTS{{{sel}, severity="warning"}} '
            f'or ALERTS{{{sel}, severity!~"critical|warning"}})')
    return state_timeline(
        "Fired · last 24 h (vmalert rules only, silences not applied)", [target(expr, legend="{{alertname}}")],
        thresholds=kiosk_steps(), row_height=0.8,
        mappings=value_map(**{"3": "critical", "2": "warning", "1": "info"}),
        desc="Which vmalert rules fired in the last 24 hours, one row per alert name, from the `ALERTS` series. "
             "That series knows nothing about Alertmanager silences and never carries Grafana-managed SLO "
             "alerts, so this is history in grey and the live list above is the one to act on. The bar names "
             "the worst severity it fired at.")


def board(group):
    grid = Grid()
    first = heartbeat() if group["services"] is None else silenced(group)
    grid.place(critical(group), 0, 8, 4)
    grid.place(warning(group), 8, 8, 4)
    grid.place(first, 16, 8, 4)
    grid.place(firing(group), 0, 24, 12)
    grid.place(history(group), 0, 24, 8)
    if grid.height != 24:
        raise SystemExit(f"alerts-{group['slug']} is {grid.height} rows tall; a wall is exactly 24")
    number(grid.panels)
    scope = ("every alert except the heartbeat" if group["services"] is None
             else "alerts whose service is " + ", ".join(group["services"]))
    return dashboard(
        f"alerts-{group['slug']}", f"Alerts · {group['name']}", grid.panels,
        tags=TAGS, kiosk=True, refresh="30s", time_from="now-24h",
        description=f"What is firing that nobody has silenced: {scope}.",
        links=[link("Alerting", "/alerting/list"), doc_link("Information radiators", DOC)])


def boards():
    return [(board(g), FOLDER) for g in GROUPS]
