from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
APP = REPO / "kubernetes/apps/observability/grafana/app"
DASHBOARDS = APP / "dashboards"
INSTANCE_SELECTOR = "  instanceSelector:\n    matchLabels:\n      grafana.internal/instance: grafana\n"
JSON_MARKER = "  json: |-\n"
FORGEJO = "https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main"


FLUX_VARIABLES = ("SECRET_DOMAIN",)


def escape(text):
    text = text.replace("$", "$$")
    for name in FLUX_VARIABLES:
        text = text.replace("$${" + name + "}", "${" + name + "}")
    return text


def unescape(text):
    return text.replace("$$", "$")


def link(title, url, *, icon="dashboard", blank=False):
    return {"title": title, "type": "link", "icon": icon, "url": url, "targetBlank": blank,
            "asDropdown": False, "includeVars": False, "keepTime": False, "tags": [], "tooltip": ""}


def tag_links(tags, title):
    return {"type": "dashboards", "tags": tags, "title": title, "asDropdown": True,
            "keepTime": True, "includeVars": False, "icon": "external link", "targetBlank": False,
            "tooltip": "", "url": ""}


def doc_link(title, path):
    return link(title, f"{FORGEJO}/{path}", icon="doc", blank=True)


def dashboard(uid, title, panels, *, tags, description="", variables=None, links=None, kiosk=False,
              refresh="1m", time_from="now-24h"):
    board = {
        "uid": uid, "title": title, "description": description, "tags": list(tags),
        "schemaVersion": 39, "editable": not kiosk, "graphTooltip": 0 if kiosk else 1, "refresh": refresh,
        "time": {"from": time_from, "to": "now"}, "timezone": "browser",
    }
    if kiosk:
        board["timepicker"] = {"hidden": True}
    board["links"] = links or []
    board["templating"] = {"list": variables or []}
    board["panels"] = panels
    return board


def dashboard_cr(dash, *, folder):
    body = escape(json.dumps(dash, indent=2, ensure_ascii=False))
    json.loads(unescape(body))
    indented = "\n".join("    " + line if line else "" for line in body.splitlines())
    return (
        "---\n"
        "apiVersion: grafana.integreatly.org/v1beta1\n"
        "kind: GrafanaDashboard\n"
        "metadata:\n"
        f"  name: {dash['uid']}\n"
        "spec:\n"
        f"{INSTANCE_SELECTOR}"
        f"  folderRef: {folder}\n"
        f"{JSON_MARKER}"
        f"{indented}\n"
    )


def check_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="fail if a committed file differs from what the generator writes")
    return ap.parse_args(argv)


def write_or_check(outputs, *, generator, check):
    stale = []
    for path, text in outputs.items():
        path = pathlib.Path(path)
        rel = path.relative_to(REPO)
        if check:
            if not path.exists() or path.read_text() != text:
                stale.append(rel)
            continue
        path.write_text(text)
        print(f"wrote {rel}")
    for rel in stale:
        print(f"{rel} is stale -- re-run {generator}", file=sys.stderr)
    if stale:
        return 1
    if check:
        print(f"{len(outputs)} generated file(s) up to date")
    return 0
