import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

VIKUNJA_URL = os.environ["VIKUNJA_URL"].rstrip("/")
VIKUNJA_TOKEN_FILE = os.environ.get("VIKUNJA_TOKEN_FILE", "/run/secrets/vikunja/token")
LAYA_URL = os.environ["LAYA_URL"].rstrip("/")
LAYA_MODEL = os.environ.get("LAYA_MODEL", "typed-decisions")
PROJECTS = [int(p) for p in os.environ.get("PROJECTS", "3,5,6,9,10").split(",")]
MODE = os.environ.get("MODE", "shadow")
APPLY_THRESHOLD = float(os.environ.get("APPLY_THRESHOLD", "0.9"))
MIN_THEME_TICKETS = int(os.environ.get("MIN_THEME_TICKETS", "3"))
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "30"))
MARKER = "theme-suggester:v1"
SHADOW_THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
MAX_DESCRIPTION_CHARS = 6000
HEADER_BADGE = re.compile(r"^\s*<p>.*?<code>\[[^\]]*\]</code>.*?</p>", re.DOTALL)
SIZING_TOKEN = re.compile(
    r"\b(effort|time|unc|uncertainty|impact)\s*[/:]?\s*(S|M|L|H|hours|days|weeks|h|d|w|low|med|high)\b",
    re.IGNORECASE,
)
CONTROL_STATE = "My card was charged twice for the same invoice."
CONTROL_OPTIONS = {"billing": "Payments, invoices, refunds", "technical": "Bugs, outages, errors", "sales": "Pricing, upgrades, new accounts"}


def log(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def vikunja_token():
    try:
        with open(VIKUNJA_TOKEN_FILE) as handle:
            token = handle.read().strip()
    except FileNotFoundError:
        token = ""
    if not token:
        log("no_vikunja_token", path=VIKUNJA_TOKEN_FILE, action="mint a token for the theme-suggester Vikunja user into OpenBao at vikunja/theme-suggester (property token)")
        sys.exit(4)
    return token


def vikunja(method, path, body=None):
    request = urllib.request.Request(
        VIKUNJA_URL + path,
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Authorization": "Bearer " + vikunja_token(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def laya(state, question):
    body = json.dumps({"model": LAYA_MODEL, "state": state, "questions": {"q": question}}).encode()
    request = urllib.request.Request(LAYA_URL + "/v1/systemone", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.load(response)
    return payload["answers"]["q"], payload.get("model")


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "li", "h3", "h2", "br", "ul", "ol"):
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_data(self, data):
        self.parts.append(data)


def description_text(description_html):
    extractor = _TextExtractor()
    extractor.feed(HEADER_BADGE.sub("", description_html or "", count=1))
    text = html.unescape(re.sub(r"\n{3,}", "\n\n", "".join(extractor.parts)).strip())
    return SIZING_TOKEN.sub("", text)[:MAX_DESCRIPTION_CHARS]


def ticket_state(task, board_title):
    return {"title": task["title"], "board": board_title, "description": description_text(task.get("description"))}


def list_view_id(project_id):
    views = vikunja("GET", f"/projects/{project_id}/views")
    for view in views:
        if view.get("view_kind") in ("list", 0):
            return view["id"]
    return views[0]["id"]


def board_tasks(project_id):
    view_id = list_view_id(project_id)
    tasks, page = [], 1
    query = urllib.parse.urlencode({"filter": "done = false || done = true", "per_page": 250})
    while True:
        batch = vikunja("GET", f"/projects/{project_id}/views/{view_id}/tasks?{query}&page={page}")
        if not batch:
            return tasks
        tasks.extend(batch)
        if len(batch) < 250:
            return tasks
        page += 1


def themes_of(task):
    return [label for label in (task.get("labels") or []) if label["title"].startswith("theme/")]


def board_options(tasks):
    counts = Counter()
    labels = {}
    for task in tasks:
        themes = themes_of(task)
        if len(themes) == 1:
            counts[themes[0]["title"]] += 1
            labels[themes[0]["title"]] = themes[0]
    return {title: labels[title] for title, count in counts.items() if count >= MIN_THEME_TICKETS}


def theme_question(options):
    return {
        "type": "choice",
        "instructions": "Which theme does this ticket belong to?",
        "criteria": {title: "Work about " + title.split("/", 1)[1].replace("-", " ") for title in sorted(options)},
    }


def is_epic(task):
    return task["title"].lower().startswith("epic:")


def created_within(task, days):
    created = datetime.fromisoformat(task["created"].replace("Z", "+00:00"))
    return created >= datetime.now(timezone.utc) - timedelta(days=days)


def already_handled(task_id):
    comments = vikunja("GET", f"/tasks/{task_id}/comments")
    return any(MARKER in (comment.get("comment") or "") for comment in comments or [])


def control_check():
    answer, model = laya(CONTROL_STATE, {"type": "choice", "instructions": "Which team should handle this?", "criteria": CONTROL_OPTIONS})
    if answer.get("choice") != "billing":
        log("control_failed", answer=answer, model=model)
        sys.exit(2)
    log("control_passed", model=model)


def shadow(board_id, board_title, tasks, options, results):
    question = theme_question(options)
    for task in tasks:
        themes = themes_of(task)
        if task.get("done") or is_epic(task) or len(themes) != 1 or themes[0]["title"] not in options:
            continue
        if not created_within(task, LOOKBACK_DAYS):
            continue
        answer, model = laya(ticket_state(task, board_title), question)
        probability = answer["probabilities"][answer["choice"]]
        results.append((themes[0]["title"] == answer["choice"], probability))
        log("shadow", board=board_id, task=task["id"], truth=themes[0]["title"], choice=answer["choice"], p=round(probability, 4), model=model)


def apply(board_id, board_title, tasks, options, counters):
    question = theme_question(options)
    for task in tasks:
        if task.get("done") or themes_of(task) or already_handled(task["id"]):
            continue
        answer, model = laya(ticket_state(task, board_title), question)
        ranked = sorted(answer["probabilities"].items(), key=lambda item: item[1], reverse=True)[:3]
        choice, probability = ranked[0]
        alternatives = ", ".join(f"<code>{title}</code> ({p:.2f})" for title, p in ranked)
        if probability >= APPLY_THRESHOLD:
            vikunja("PUT", f"/tasks/{task['id']}/labels", {"label_id": options[choice]["id"]})
            text = f"<p>Theme <code>{choice}</code> applied by the theme suggester (p={probability:.2f} ≥ {APPLY_THRESHOLD}). Top three: {alternatives}. Remove the label if it is wrong.</p><p><code>{MARKER} model={model}</code></p>"
            counters["applied"] += 1
        else:
            text = f"<p>Suggested theme, not applied (p={probability:.2f} &lt; {APPLY_THRESHOLD}): {alternatives}.</p><p><code>{MARKER} model={model}</code></p>"
            counters["suggested"] += 1
        vikunja("PUT", f"/tasks/{task['id']}/comments", {"comment": text})
        log("apply", board=board_id, task=task["id"], choice=choice, p=round(probability, 4), applied=probability >= APPLY_THRESHOLD, model=model)


def shadow_summary(results):
    summary = {"evaluated": len(results), "agreement": round(sum(ok for ok, _ in results) / len(results), 4) if results else None}
    for threshold in SHADOW_THRESHOLDS:
        confident = [ok for ok, p in results if p >= threshold]
        summary[f"at_{threshold}"] = {
            "coverage": round(len(confident) / len(results), 4) if results else None,
            "precision": round(sum(confident) / len(confident), 4) if confident else None,
        }
    return summary


def main():
    if MODE not in ("shadow", "apply"):
        log("bad_mode", mode=MODE)
        sys.exit(2)
    control_check()
    projects = {project["id"]: project["title"] for project in vikunja("GET", "/projects?per_page=250")}
    scanned = 0
    results = []
    counters = Counter()
    for board_id in PROJECTS:
        tasks = board_tasks(board_id)
        scanned += len(tasks)
        options = board_options(tasks)
        if len(options) < 2:
            log("board_skipped", board=board_id, reason="fewer than two themes with enough tickets", options=len(options))
            continue
        board_title = projects.get(board_id, str(board_id))
        shadow(board_id, board_title, tasks, options, results)
        if MODE == "apply":
            apply(board_id, board_title, tasks, options, counters)
    log("summary", mode=MODE, scanned=scanned, shadow=shadow_summary(results), applied=counters["applied"], suggested=counters["suggested"], threshold=APPLY_THRESHOLD)
    if scanned == 0:
        log("empty_scan", reason="no tasks visible; the token may be revoked or the projects not shared with the bot user")
        sys.exit(3)


if __name__ == "__main__":
    main()
