#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import alerts
import forgejo_ci
import glide
import glide_runs
import platform_walls
import playlists
from lib import DASHBOARDS, check_args, dashboard_cr, screen_height, write_or_check

GENERATOR = "scripts/dashboards/generate.py"
MAX_WALL_PANELS = 12
SCREEN = 24

MODULES = {
    "alerts.generated.yaml": alerts,
    "forgejo-ci.generated.yaml": forgejo_ci,
    "glide.generated.yaml": glide,
    "glide-runs.generated.yaml": glide_runs,
    "walls.generated.yaml": platform_walls,
}


def check_wall(board):
    panels = board["panels"]
    problems = []
    if any(p.get("type") == "row" for p in panels):
        problems.append("has row panels")
    if screen_height(panels) != SCREEN:
        problems.append(f"is {screen_height(panels)} grid rows tall, not {SCREEN}")
    if len(panels) > MAX_WALL_PANELS:
        problems.append(f"has {len(panels)} panels, more than {MAX_WALL_PANELS}")
    for p in panels:
        g = p["gridPos"]
        if g["x"] + g["w"] > 24:
            problems.append(f"panel {p.get('title')!r} runs past column 24")
    return [f"{board['uid']} {m}" for m in problems]


def overlaps(board):
    cells = {}
    found = []
    for p in board["panels"]:
        if p.get("type") == "row":
            continue
        g = p["gridPos"]
        for x in range(g["x"], g["x"] + g["w"]):
            for y in range(g["y"], g["y"] + g["h"]):
                if (x, y) in cells:
                    found.append(f"{board['uid']}: {p.get('title')!r} overlaps {cells[(x, y)]!r}")
                    break
                cells[(x, y)] = p.get("title")
            else:
                continue
            break
    return found


def render():
    outputs, problems, uids = {}, [], set()
    for filename, module in MODULES.items():
        docs = []
        for board, folder in module.boards():
            if board["uid"] in uids:
                problems.append(f"{board['uid']} is generated twice")
            uids.add(board["uid"])
            if "wall" in board["tags"]:
                problems.extend(check_wall(board))
            problems.extend(overlaps(board))
            docs.append(dashboard_cr(board, folder=folder))
        outputs[DASHBOARDS / filename] = "".join(docs)
    for line in problems:
        print(line, file=sys.stderr)
    if problems:
        raise SystemExit(f"{len(problems)} board problem(s)")
    return outputs


def main(argv=None):
    args = check_args(argv)
    outputs = render()
    status = write_or_check(outputs, generator=GENERATOR, check=args.check)
    if status:
        return status
    return playlists.main(check=args.check, generator=GENERATOR)


if __name__ == "__main__":
    raise SystemExit(main())
