from __future__ import annotations

import json
import re
import sys

from lib import APP, INSTANCE_SELECTOR, unescape, write_or_check

OUTPUT = APP / "playlists" / "playlists.generated.yaml"

PLAYLISTS = [
    {"uid": "wall-homelab", "title": "Wall · Homelab", "interval": "1m",
     "items": ["wall-now", "today", "alerts-all", "wall-ci", "wall-now", "wall-glide", "wall-gitops", "wall-now",
               "wall-data", "wall-nodes"]},
    {"uid": "wall-delivery", "title": "Wall · Delivery", "interval": "1m",
     "items": ["today", "wall-ci", "wall-glide", "today", "alerts-delivery", "wall-gitops", "alerts-ai"]},
    {"uid": "incident", "title": "Incident · Platform", "interval": "30s",
     "items": ["alerts-all", "wall-now", "wall-nodes", "wall-edge", "wall-data"]},
    {"uid": "weekly-review", "title": "Weekly · Review", "interval": "2m",
     "items": ["today", "wall-roadmap", "wall-ci", "wall-glide", "wall-gitops", "wall-data", "wall-edge", "wall-nodes",
               "alerts-security"]},
]
SCREEN = 24
UID = re.compile(r"^[a-z0-9]([-a-z0-9]{0,38}[a-z0-9])?$")
INTERVAL = re.compile(r"^[0-9]+[smh]$")


def dashboard_files():
    text = (APP / "kustomization.yaml").read_text()
    return [APP / m for m in re.findall(r"^\s*-\s*\./(dashboards/\S+\.yaml)\s*$", text, re.M)]


def json_block(doc):
    marker = re.search(r"^  json: \|-?\n", doc, re.M)
    if not marker:
        return None
    lines = []
    for line in doc[marker.end():].split("\n"):
        if line and not line.startswith("    "):
            break
        lines.append(line[4:])
    return json.loads(unescape("\n".join(lines)))


def rendered_boards():
    boards = {}
    for path in dashboard_files():
        for doc in re.split(r"^---\s*$", path.read_text(), flags=re.M):
            if not re.search(r"^kind:\s*GrafanaDashboard\s*$", doc, re.M):
                continue
            board = json_block(doc)
            if board and board.get("uid"):
                boards[board["uid"]] = (path.name, board)
    return boards


def not_one_screen(uid, source, board):
    panels = board.get("panels") or []
    rows = sum(1 for p in panels if p.get("type") == "row")
    height = max((p["gridPos"]["y"] + p["gridPos"]["h"] for p in panels), default=0)
    if rows or height > SCREEN:
        return f"{uid} ({source}) is {height} grid rows tall with {rows} row panel(s)"
    return None


def verify(playlists):
    boards = rendered_boards()
    problems = []
    names = set()
    for playlist in playlists:
        uid = playlist["uid"]
        if not UID.match(uid):
            problems.append(f"{uid}: not a valid playlist uid (lowercase, digits, dashes, at most 40)")
        if uid in names:
            problems.append(f"{uid}: declared twice")
        names.add(uid)
        if not INTERVAL.match(playlist["interval"]):
            problems.append(f"{uid}: interval {playlist['interval']!r} is not a Grafana duration")
        if not playlist["items"]:
            problems.append(f"{uid}: has no items")
        for item in playlist["items"]:
            if item not in boards:
                problems.append(f"{uid}: {item} is not a dashboard the grafana app renders")
                continue
            too_tall = not_one_screen(item, *boards[item])
            if too_tall:
                problems.append(f"{uid}: {too_tall}; a playlist item is at most {SCREEN} rows and no rows")
    for line in problems:
        print(line, file=sys.stderr)
    if problems:
        raise SystemExit(f"{len(problems)} playlist problem(s)")


def manifest(playlist):
    items = "".join(f"        - type: dashboard_by_uid\n          value: {uid}\n" for uid in playlist["items"])
    return (
        "---\n"
        "apiVersion: grafana.integreatly.org/v1beta1\n"
        "kind: GrafanaManifest\n"
        "metadata:\n"
        f"  name: playlist-{playlist['uid']}\n"
        "spec:\n"
        f"{INSTANCE_SELECTOR}"
        "  resyncPeriod: 10m\n"
        "  template:\n"
        "    apiVersion: playlist.grafana.app/v1\n"
        "    kind: Playlist\n"
        "    metadata:\n"
        f"      name: {playlist['uid']}\n"
        "    spec:\n"
        f"      title: {json.dumps(playlist['title'], ensure_ascii=False)}\n"
        f"      interval: {playlist['interval']}\n"
        "      items:\n"
        f"{items}"
    )


def main(*, check, generator):
    verify(PLAYLISTS)
    text = "".join(manifest(p) for p in PLAYLISTS)
    items = sum(len(p["items"]) for p in PLAYLISTS)
    print(f"{len(PLAYLISTS)} playlists, {items} items, every item a rendered one-screen board")
    return write_or_check({OUTPUT: text}, generator=generator, check=check)
