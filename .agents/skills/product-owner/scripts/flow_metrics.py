#!/usr/bin/env python3
"""Flow metrics and board invariants for any board — two input modes, one engine.

Offline and credential-free by design: feed it JSON a board MCP already
returned (or a normalized conversion of it); nothing here talks to a network.

ClickUp mode — raw MCP payloads, no normalization step:

    python3 flow_metrics.py --tasks open.json done.json \\
        --status-history history.json --wip-limit 3 --percentile 85

    --tasks           output of clickup_filter_tasks ({"tasks": [...]} or a list)
    --status-history  output of clickup_get_bulk_tasks_time_in_status
                      (map of task-id -> {current_status, status_history}, or a list)

Normalized mode — any other tracker; convert per your adapter's recipe:

    python3 flow_metrics.py --items board.json --wip-limit 3

    {"id": "42", "title": "ci: bring pipeline under 8 minutes",
     "state": "doing",              // open | ready | doing | review | done | dropped
     "started": "2026-08-01T09:00:00Z",   // entered doing — ISO8601 or epoch ms; absent if never started
     "finished": null,                    // reached the team's REAL done
     "created": "2026-07-01T09:00:00Z",   // optional; only for the labeled lead-time proxy
     "priority": "P0"}                    // optional: P0|urgent|P1..P3

Metrics follow the Kanban Guide (v2025.5): WIP is items started but not
finished, Work Item Age is start -> now, Cycle Time is start -> finish, and a
Service Level Expectation is an elapsed period WITH a probability attached.
"Started" defaults to doing + review states (started-but-not-finished); a
contract whose WIP cap governs doing alone passes --started-states doing.

Where no start is measured the script falls back to created -> finished and
labels the result a LEAD TIME PROXY: created is when someone wrote the ticket,
not when anyone started it. It refuses to state an SLE below --min-samples
finished items, because a percentile over five tickets is theatre.

Board-agreement knobs (instance facts live in your Board contract, not here):
    --started-states / --done-state    the contract's Definition of Workflow
    --not-done          done-TYPED statuses the agreement treats as intermediate
                        (default: merged testing carryover — a common ClickUp trap)
    --area-tags         the board's area-tag set; enables the exactly-one-tag check
    --pullable          statuses at/past which priority is expected (ClickUp mode)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

MINUTES_PER_DAY = 60 * 24
STARTED_STATES = ("doing", "review", "for review")
DONE_STATE = "done"
NOT_REALLY_DONE = ("merged", "testing", "carryover")
PULLABLE = ("to do", "doing", "for review")
DROPPED_STATES = ("dropped", "rejected")


class DataError(Exception):
    """Input that cannot be interpreted as board data."""


# --------------------------------------------------------------------------- io


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise DataError(f"{path}: no such file")
    except UnicodeDecodeError as exc:
        raise DataError(f"{path}: not text ({exc})")
    except json.JSONDecodeError as exc:
        raise DataError(f"{path}: invalid JSON — {exc}")


def read_normalized(paths: list[Path]) -> list[dict]:
    """Normalized work items, deduped by id (later files win)."""
    by_id: dict[str, dict] = {}
    for path in paths:
        data = load_json(path)
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise DataError(f"{path}: expected an array or {{\"items\": [...]}}")
        for item in items:
            if not isinstance(item, dict) or "id" not in item:
                raise DataError(f"{path}: entry without an 'id' — not a normalized item list")
            by_id[str(item["id"])] = item
    if not by_id:
        raise DataError("no items found in the supplied files")
    return list(by_id.values())


def read_tasks(paths: list[Path]) -> list[dict]:
    """Tasks from one or more clickup_filter_tasks payloads, deduped by id."""
    by_id: dict[str, dict] = {}
    for path in paths:
        data = load_json(path)
        if isinstance(data, dict):
            items = data.get("tasks")
            if items is None:
                raise DataError(f"{path}: object has no 'tasks' key — is this filter_tasks output?")
        elif isinstance(data, list):
            items = data
        else:
            raise DataError(f"{path}: expected an object or array, got {type(data).__name__}")
        if not isinstance(items, list):
            raise DataError(f"{path}: 'tasks' is not an array")
        for task in items:
            if not isinstance(task, dict) or "id" not in task:
                raise DataError(f"{path}: entry without an 'id' — not a task list")
            by_id[str(task["id"])] = task
    if not by_id:
        raise DataError("no tasks found in the supplied files")
    return list(by_id.values())


def read_history(paths: list[Path]) -> dict[str, dict]:
    """Status history keyed by task id, from bulk-time-in-status payloads."""
    history: dict[str, dict] = {}
    for path in paths:
        data = load_json(path)
        entries: list[dict] = []
        if isinstance(data, dict):
            # Three shapes in the wild: {"tasks": {"<id>": {...}}} (what
            # get_bulk_tasks_time_in_status actually returns), {"tasks": [...]},
            # and a bare {"<id>": {...}} map.
            source: object = data
            for key in ("tasks", "results", "data"):
                if key in data:
                    source = data[key]
                    break
            if isinstance(source, list):
                entries = [e for e in source if isinstance(e, dict)]
            elif isinstance(source, dict):
                for task_id, value in source.items():
                    if isinstance(value, dict):
                        entries.append({**value, "task_id": value.get("task_id", task_id)})
            else:
                raise DataError(f"{path}: 'tasks' is neither an array nor a map")
        elif isinstance(data, list):
            entries = [e for e in data if isinstance(e, dict)]
        else:
            raise DataError(f"{path}: expected an object or array")
        for entry in entries:
            task_id = entry.get("task_id")
            if task_id:
                history[str(task_id)] = entry
    return history


# ----------------------------------------------------------------- time helpers


def as_ms(value: object) -> int | None:
    """Accept epoch ms (int/str) or ISO8601; return epoch ms or None."""
    if value in (None, "", "null"):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        ms = int(float(value))
        return ms if ms > 10**11 else ms * 1000 if ms > 10**8 else None
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return int(moment.timestamp() * 1000)
    return None


def fmt_duration(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    days, rem = divmod(int(round(minutes)), MINUTES_PER_DAY)
    hours, mins = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {mins}m" if hours else f"{mins}m"


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile — the convention SLEs are quoted with."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


# -------------------------------------------------- ClickUp -> normalized items


def started_minutes(entry: dict, started: tuple[str, ...]) -> float | None:
    """Measured minutes a task spent in started statuses, per its history."""
    total = 0.0
    seen = False
    for row in entry.get("status_history") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")).lower() in started:
            minutes = row.get("total_time_minutes")
            if isinstance(minutes, (int, float)):
                total += float(minutes)
                seen = True
    current = entry.get("current_status")
    if isinstance(current, dict) and str(current.get("status", "")).lower() in started:
        # current_status duplicates the open interval already counted in
        # status_history for the status the task sits in; only use it when
        # history did not report that status at all.
        if not seen:
            minutes = current.get("total_time_minutes")
            if isinstance(minutes, (int, float)):
                total += float(minutes)
                seen = True
    return total if seen else None


def clickup_priority(task: dict) -> str | None:
    value = task.get("priority")
    if isinstance(value, dict):
        value = value.get("priority")
    return str(value) if value not in (None, "") else None


def normalize_clickup(tasks: list[dict], history: dict[str, dict],
                      started: tuple[str, ...], done: str) -> list[dict]:
    """Raw ClickUp tasks -> the engine's item shape.

    `finished` is set only for the agreement's real done status — done-TYPED
    intermediates (--not-done) stay unfinished here and are flagged separately.
    """
    items = []
    for task in tasks:
        status = str(task.get("status", "")).lower()
        entry = history.get(str(task["id"]), {})
        items.append({
            "id": str(task["id"]),
            "title": str(task.get("name", "")).strip(),
            "state": status,
            "measured_minutes": started_minutes(entry, started) if entry else None,
            "finished": task.get("date_closed") if status == done else None,
            "created": task.get("date_created"),
            "priority": clickup_priority(task),
            "tags": [str(t.get("name", "")).lower() for t in task.get("tags") or []
                     if isinstance(t, dict)],
        })
    return items


# -------------------------------------------------------------------- analysis


def analyse(items: list[dict], args) -> dict:
    now_ms = args.now if args.now is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    started_states = tuple(s.lower() for s in args.started_states)
    done_state = args.done_state.lower()

    in_progress, completions = [], []
    proxy_used = False
    bad_timestamps = 0
    for item in items:
        state = str(item.get("state", "")).lower()
        for key in ("started", "finished", "created"):
            if item.get(key) not in (None, "", "null") and as_ms(item.get(key)) is None:
                bad_timestamps += 1
        measured = item.get("measured_minutes")
        started = as_ms(item.get("started"))
        finished = as_ms(item.get("finished"))
        created = as_ms(item.get("created"))
        title = str(item.get("title", "")).strip()

        if state in started_states and finished is None:
            if measured is not None:
                age, is_measured = float(measured), True
            elif started is not None:
                age, is_measured = (now_ms - started) / 60000, True
            elif created is not None:
                age, is_measured, proxy_used = (now_ms - created) / 60000, False, True
            else:
                age, is_measured = None, False
            in_progress.append({"id": str(item["id"]), "title": title,
                                "minutes": age, "measured": is_measured})
        elif state == done_state or finished is not None:
            if measured is not None:
                cycle, is_measured = float(measured), True
            elif finished is not None and started is not None:
                cycle, is_measured = (finished - started) / 60000, True
            elif finished is not None and created is not None:
                cycle, is_measured, proxy_used = (finished - created) / 60000, False, True
            else:
                cycle, is_measured = None, False
            completions.append({"id": str(item["id"]), "title": title,
                                "finished_ms": finished, "minutes": cycle,
                                "measured": is_measured})

    cycle_times = [c["minutes"] for c in completions if c["minutes"] is not None]
    unmeasurable = [c for c in completions if c["minutes"] is None]

    sle = None
    if len(cycle_times) >= args.min_samples:
        sle = {"percentile": args.percentile,
               "days": percentile(cycle_times, args.percentile) / MINUTES_PER_DAY,
               "samples": len(cycle_times),
               "includes_proxy": proxy_used}

    in_progress = sorted(in_progress, key=lambda i: i["minutes"] or -1, reverse=True)
    return {
        "wip": {"count": len(in_progress), "limit": args.wip_limit,
                "over_by": max(0, len(in_progress) - args.wip_limit)},
        "in_progress": in_progress,
        "throughput": throughput_by_week(completions),
        "cycle_time": {
            "samples": len(cycle_times),
            "median_days": (percentile(cycle_times, 50) / MINUTES_PER_DAY) if cycle_times else None,
            "p85_days": (percentile(cycle_times, 85) / MINUTES_PER_DAY) if cycle_times else None,
            "max_days": (max(cycle_times) / MINUTES_PER_DAY) if cycle_times else None,
            "lead_time_proxy": proxy_used,
            "finished": len(completions),
            "unmeasurable": len(unmeasurable),
        },
        "sle": sle,
        "findings": find_violations(items, in_progress, unmeasurable, bad_timestamps, args),
        "state_counts": Counter(str(i.get("state", "?")).lower() for i in items),
    }


def throughput_by_week(completions: list[dict]) -> list[tuple[str, int]]:
    weeks: Counter[str] = Counter()
    for item in completions:
        if item["finished_ms"] is None:
            continue
        moment = datetime.fromtimestamp(item["finished_ms"] / 1000, tz=timezone.utc)
        monday = moment - timedelta(days=moment.weekday())
        weeks[monday.strftime("%Y-%m-%d")] += 1
    return sorted(weeks.items())


def looks_like_a_product_name(title: str) -> bool:
    """A title with no separator and at most two words names an installation,
    not a result — the most common board defect."""
    if ":" in title or "—" in title or " - " in title:
        return False
    return 0 < len(title.split()) <= 2


def find_violations(items: list[dict], in_progress: list[dict],
                    unmeasurable: list[dict], bad_timestamps: int, args) -> list[dict]:
    findings: list[dict] = []
    if bad_timestamps:
        findings.append({"kind": "bad-timestamp", "count": bad_timestamps,
                         "message": "timestamp value(s) could not be parsed (not ISO8601 or "
                                    "epoch ms) — silently treated as absent; check the input",
                         "items": []})

    def add(kind: str, message: str, entries: list[str]) -> None:
        if entries:
            findings.append({"kind": kind, "message": message, "count": len(entries),
                             "items": entries[: args.max_items]})

    if len(in_progress) > args.wip_limit:
        add("wip-limit", f"{len(in_progress)} items started, limit is {args.wip_limit} — "
                         "finish before starting",
            [f"{i['title']} ({fmt_duration(i['minutes'])} old)" for i in in_progress])

    done_state = args.done_state.lower()
    open_items = [i for i in items
                  if str(i.get("state", "")).lower() not in (done_state, *DROPPED_STATES)]

    add("title", "titles that name a product instead of a change",
        [f"{i.get('title')} [{i.get('state')}]" for i in open_items
         if looks_like_a_product_name(str(i.get("title", "")))])

    if args.area_tags:
        area_tags = tuple(t.lower() for t in args.area_tags)
        untagged, multitagged = [], []
        for item in open_items:
            areas = [t for t in item.get("tags") or [] if t in area_tags]
            if not areas:
                untagged.append(f"{item.get('title')} [{item.get('state')}]")
            elif len(areas) > 1:
                multitagged.append(f"{item.get('title')} ({', '.join(areas)})")
        add("area-tag", f"open tickets without an area tag ({'/'.join(area_tags)})", untagged)
        add("area-tag", "more than one area tag — usually means more than one ticket", multitagged)

    if args.pullable:
        pullable = tuple(s.lower() for s in args.pullable)
        add("priority", f"no priority set at or past {pullable[0]!r}",
            [f"{i.get('title')} [{i.get('state')}]" for i in open_items
             if str(i.get("state", "")).lower() in pullable and not i.get("priority")])

    p0 = [str(i.get("title", "")) for i in open_items
          if str(i.get("priority", "")).upper() in ("P0", "URGENT", "5")]
    if len(p0) > args.max_p0:
        add("p0-inflation", f"{len(p0)} open P0s — if six things are urgent, nothing is", p0)

    add("no-measured-start",
        "finished without a recorded start — no start, so no Cycle Time and no SLE contribution",
        [c["title"] for c in unmeasurable])

    if args.not_done:
        stations = tuple(s.lower() for s in args.not_done)
        add("done-type", "in a done-typed status the agreement treats as intermediate — "
                         "not counted as finished",
            [f"{i.get('title')} [{i.get('state')}]" for i in items
             if str(i.get("state", "")).lower() in stations])

    return findings


# ----------------------------------------------------------------------- output


def render(report: dict, args, clickup_mode: bool) -> str:
    out: list[str] = []
    wip = report["wip"]
    out.append(f"WIP {wip['count']} / {wip['limit']}  [{'OVER LIMIT' if wip['over_by'] else 'ok'}]")

    if report["in_progress"]:
        out.append("\nWork Item Age (oldest first)")
        for item in report["in_progress"][: args.max_items]:
            if item["minutes"] is None:
                mark = ("  (no start recorded — supply --status-history)" if clickup_mode
                        else "  (no start recorded)")
            else:
                mark = "" if item["measured"] else "  ~proxy from created"
            out.append(f"  {fmt_duration(item['minutes']):>10}  {item['title'][:64]}{mark}")

    cycle = report["cycle_time"]
    out.append(f"\nCycle Time  ({cycle['samples']} of {cycle['finished']} finished measurable"
               + (", some from created — LEAD TIME PROXY" if cycle["lead_time_proxy"] else "") + ")")
    if cycle["samples"]:
        out.append(f"  median {cycle['median_days']:.1f}d · 85th {cycle['p85_days']:.1f}d "
                   f"· max {cycle['max_days']:.1f}d")
    elif cycle["finished"]:
        out.append(f"  none measurable — all {cycle['unmeasurable']} finished items lack a start")
    else:
        out.append("  no finished items in the supplied data")

    if report["throughput"]:
        out.append("\nThroughput (finished per week)")
        for week, count in report["throughput"][-args.max_weeks:]:
            out.append(f"  {week}  {'#' * min(count, 40)} {count}")

    out.append("")
    if report["sle"]:
        sle = report["sle"]
        proxy_note = " — includes lead-time-proxy samples" if sle.get("includes_proxy") else ""
        out.append(f"SLE: {sle['percentile']:.0f}% of items finish within "
                   f"{math.ceil(sle['days'])} days  (from {sle['samples']} finished items"
                   f"{proxy_note})")
        out.append("     A forecast with a sample size, not a promise — recompute every ~10.")
    else:
        out.append(f"SLE: not stated — {report['cycle_time']['samples']} usable samples, "
                   f"need {args.min_samples}. A percentile over a handful of tickets is theatre.")

    if report["findings"]:
        out.append("\nFindings")
        for finding in report["findings"]:
            out.append(f"  [{finding['kind']}] {finding['count']}× {finding['message']}")
            for entry in finding["items"]:
                out.append(f"      - {entry[:72]}")
            if finding["count"] > len(finding["items"]):
                out.append(f"      … and {finding['count'] - len(finding['items'])} more")
    else:
        out.append("\nFindings: none from item data (the judgement checks are still yours).")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Flow metrics and board invariants — raw ClickUp payloads or "
                    "normalized items from any tracker.",
        epilog="Feed it saved tool output; it never touches the network.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tasks", nargs="+", type=Path,
                        help="ClickUp mode: clickup_filter_tasks payload(s)")
    source.add_argument("--items", nargs="+", type=Path,
                        help="normalized mode: work-item JSON file(s) — see the module docstring")
    parser.add_argument("--status-history", nargs="*", default=[], type=Path,
                        help="ClickUp mode: clickup_get_bulk_tasks_time_in_status payload(s)")
    parser.add_argument("--wip-limit", type=int, default=3)
    parser.add_argument("--percentile", type=float, default=85.0)
    parser.add_argument("--min-samples", type=int, default=10,
                        help="refuse to state an SLE below this many finished items")
    parser.add_argument("--started-states", "--started-statuses", nargs="+",
                        default=list(STARTED_STATES), dest="started_states",
                        help="the contract's started statuses (default: doing/review/for review)")
    parser.add_argument("--done-state", "--done-status", default=DONE_STATE, dest="done_state",
                        help="the agreement's REAL finished status")
    parser.add_argument("--not-done", nargs="*", default=list(NOT_REALLY_DONE),
                        help="done-typed statuses the agreement treats as intermediate")
    parser.add_argument("--area-tags", nargs="*", default=None,
                        help="the board's area-tag set; enables the exactly-one-tag check")
    parser.add_argument("--pullable", nargs="*", default=None,
                        help="statuses at/past which priority is expected "
                             f"(ClickUp mode defaults to {'/'.join(PULLABLE)})")
    parser.add_argument("--max-p0", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=12, help="per-finding items to list")
    parser.add_argument("--max-weeks", type=int, default=12)
    parser.add_argument("--now", type=int, default=None,
                        help="epoch ms to treat as 'now' (for reproducible output)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not 0 < args.percentile < 100:
        parser.error("--percentile must be between 0 and 100 (exclusive)")
    if args.wip_limit < 1:
        parser.error("--wip-limit must be at least 1")
    if args.items and args.status_history:
        parser.error("--status-history belongs to ClickUp mode (--tasks)")

    clickup_mode = args.tasks is not None
    if clickup_mode and args.pullable is None:
        args.pullable = list(PULLABLE)

    try:
        if clickup_mode:
            started = tuple(s.lower() for s in args.started_states)
            items = normalize_clickup(read_tasks(args.tasks),
                                      read_history(list(args.status_history)),
                                      started, args.done_state.lower())
        else:
            items = read_normalized(args.items)
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = analyse(items, args)
    if args.json:
        report["state_counts"] = dict(report["state_counts"])
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render(report, args, clickup_mode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
