#!/usr/bin/env python3
import copy
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PANEL_TYPES_WITHOUT_QUERIES = {"row", "text", "dashlist", "news", "annolist", "welcome", "gettingstarted"}
BUILTIN_DATASOURCES = {"-- Grafana --", "grafana", "-- Dashboard --", "__expr__"}
GENERIC_NO_VALUE = {"", "no data", "-", "0"}
ALL_VALUE = "$__all"
QUERY_INTERVAL_MS = 60000
QUERY_MAX_DATA_POINTS = 100
VARIABLE = re.compile(r"\$\{(\w+)(?::[^}]*)?\}|\[\[(\w+)(?::[^\]]*)?\]\]|\$(\w+)")


@dataclass(frozen=True)
class PanelResult:
    dashboard_uid: str
    dashboard: str
    panel_id: str
    panel: str
    status: str
    empty_expected: bool
    detail: str = ""


@dataclass
class Snapshot:
    results: list = field(default_factory=list)
    dashboards: int = 0
    last_success: float = 0.0
    check_duration: float = 0.0
    check_failures: int = 0
    token_configured: bool = False


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def walk_panels(panels: list):
    for panel in panels or []:
        yield panel
        yield from walk_panels(panel.get("panels"))


def variable_values(dashboard: dict) -> dict:
    values = {}
    for variable in (dashboard.get("templating") or {}).get("list") or []:
        name = variable.get("name")
        if not name:
            continue
        current = (variable.get("current") or {}).get("value")
        if variable.get("type") == "constant":
            current = variable.get("query", current)
        if isinstance(current, list):
            current = current if current else [ALL_VALUE]
            if ALL_VALUE in current:
                current = variable.get("allValue") or ".*"
            else:
                current = "|".join(str(item) for item in current)
        elif current == ALL_VALUE or current is None:
            current = variable.get("allValue") or ".*"
        values[name] = str(current)
    return values


def substitute(value, variables: dict):
    if isinstance(value, str):
        def replace(match):
            name = match.group(1) or match.group(2) or match.group(3)
            return variables.get(name, match.group(0))
        return VARIABLE.sub(replace, value)
    if isinstance(value, list):
        return [substitute(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, variables) for key, item in value.items()}
    return value


def as_datasource(reference) -> dict:
    if isinstance(reference, dict):
        return reference
    if isinstance(reference, str) and reference:
        return {"uid": reference}
    return {}


def is_builtin(datasource: dict) -> bool:
    return datasource.get("uid") in BUILTIN_DATASOURCES or datasource.get("type") in {"grafana", "datasource", "dashboard"}


def panel_queries(panel: dict, variables: dict) -> list:
    panel_datasource = as_datasource(panel.get("datasource"))
    queries = []
    for target in panel.get("targets") or []:
        if target.get("hide"):
            continue
        query = substitute(copy.deepcopy(target), variables)
        datasource = substitute(as_datasource(target.get("datasource")) or panel_datasource, variables)
        if not datasource or is_builtin(datasource) or datasource.get("uid") == "-- Mixed --":
            continue
        query["datasource"] = datasource
        query.setdefault("refId", "A")
        query["intervalMs"] = QUERY_INTERVAL_MS
        query["maxDataPoints"] = QUERY_MAX_DATA_POINTS
        queries.append(query)
    return queries


def empty_is_expected(panel: dict) -> bool:
    no_value = ((panel.get("fieldConfig") or {}).get("defaults") or {}).get("noValue")
    return isinstance(no_value, str) and no_value.strip().lower() not in GENERIC_NO_VALUE


def time_range(dashboard: dict, panel: dict) -> tuple:
    window = (dashboard.get("time") or {})
    start, end = window.get("from", "now-6h"), window.get("to", "now")
    if panel.get("timeFrom"):
        start = f"now-{panel['timeFrom']}"
    return start, end


def frame_has_values(frame: dict) -> bool:
    values = (frame.get("data") or {}).get("values") or []
    return any(column for column in values if column)


def classify(response: dict) -> tuple:
    results = (response or {}).get("results") or {}
    errors = [f"{ref}: {result['error']}" for ref, result in results.items() if result.get("error")]
    if errors:
        return "error", "; ".join(errors)[:300]
    if any(frame_has_values(frame) for result in results.values() for frame in result.get("frames") or []):
        return "data", ""
    return "empty", ""


class Unauthorized(Exception):
    pass


class GrafanaClient:
    def __init__(self, base_url: str, token: str, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, path: str, body=None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403) and path.startswith("/api/search"):
                raise Unauthorized(f"{path} returned {error.code}") from error
            try:
                return json.load(error)
            except Exception:
                return {"results": {"A": {"error": f"HTTP {error.code}"}}}

    def dashboard_uids(self) -> list:
        return [item["uid"] for item in self.request("/api/search?type=dash-db&limit=5000") if item.get("uid")]

    def dashboard(self, uid: str) -> dict:
        return self.request(f"/api/dashboards/uid/{urllib.parse.quote(uid)}").get("dashboard") or {}

    def query(self, start: str, end: str, queries: list) -> dict:
        return self.request("/api/ds/query", {"from": start, "to": end, "queries": queries})


def check_dashboard(client: GrafanaClient, dashboard: dict) -> list:
    variables = variable_values(dashboard)
    results = []
    for panel in walk_panels(dashboard.get("panels")):
        if panel.get("type") in PANEL_TYPES_WITHOUT_QUERIES or panel.get("libraryPanel"):
            continue
        queries = panel_queries(panel, variables)
        if not queries:
            continue
        start, end = time_range(dashboard, panel)
        try:
            status, detail = classify(client.query(start, end, queries))
        except Exception as error:
            status, detail = "error", f"{type(error).__name__}: {error}"[:300]
        results.append(PanelResult(dashboard_uid=dashboard.get("uid", ""), dashboard=dashboard.get("title", ""),
                                   panel_id=str(panel.get("id", "")), panel=panel.get("title") or "(untitled)",
                                   status=status, empty_expected=empty_is_expected(panel), detail=detail))
    return results


def escape(value) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_labels(pairs: dict) -> str:
    return "{" + ",".join(f'{key}="{escape(value)}"' for key, value in pairs.items()) + "}"


def render(snapshot: Snapshot) -> str:
    lines = [
        "# HELP grafana_panel_check_token_configured 1 when a Grafana service-account token is mounted.",
        "# TYPE grafana_panel_check_token_configured gauge",
        f"grafana_panel_check_token_configured {int(snapshot.token_configured)}",
        "# HELP grafana_panel_check_last_success_timestamp_seconds Time the last full check finished.",
        "# TYPE grafana_panel_check_last_success_timestamp_seconds gauge",
        f"grafana_panel_check_last_success_timestamp_seconds {snapshot.last_success}",
        "# HELP grafana_panel_check_duration_seconds Duration of the last check.",
        "# TYPE grafana_panel_check_duration_seconds gauge",
        f"grafana_panel_check_duration_seconds {snapshot.check_duration}",
        "# HELP grafana_panel_check_failures_total Checks that could not list dashboards.",
        "# TYPE grafana_panel_check_failures_total counter",
        f"grafana_panel_check_failures_total {snapshot.check_failures}",
        "# HELP grafana_panel_check_dashboards Dashboards in the last check.",
        "# TYPE grafana_panel_check_dashboards gauge",
        f"grafana_panel_check_dashboards {snapshot.dashboards}",
    ]
    series = (
        ("grafana_panel_has_data", "1 when the panel's queries returned at least one value.",
         lambda result: int(result.status == "data")),
        ("grafana_panel_query_error", "1 when a query of the panel returned an error.",
         lambda result: int(result.status == "error")),
        ("grafana_panel_empty_expected", "1 when the panel declares a no-value text, so empty is a healthy state.",
         lambda result: int(result.empty_expected)),
    )
    for metric, help_text, value in series:
        lines.append(f"# HELP {metric} {help_text}")
        lines.append(f"# TYPE {metric} gauge")
        for result in snapshot.results:
            labels = {"dashboard_uid": result.dashboard_uid, "dashboard": result.dashboard,
                      "panel_id": result.panel_id, "panel": result.panel}
            lines.append(f"{metric}{render_labels(labels)} {value(result)}")
    return "\n".join(lines) + "\n"


class Exporter:
    def __init__(self, client_factory, token_path: str):
        self.client_factory = client_factory
        self.token_path = token_path
        self.snapshot = Snapshot()
        self.lock = threading.Lock()

    def read_token(self) -> str:
        try:
            with open(self.token_path, encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""

    def refresh(self) -> None:
        started = time.time()
        token = self.read_token()
        with self.lock:
            previous = self.snapshot
        snapshot = Snapshot(results=previous.results, dashboards=previous.dashboards,
                            last_success=previous.last_success, check_failures=previous.check_failures,
                            token_configured=bool(token))
        if not token:
            snapshot.check_failures += 1
            log("no Grafana token mounted; waiting for the service-account secret")
        else:
            client = self.client_factory(token)
            try:
                uids = client.dashboard_uids()
                results = []
                for uid in uids:
                    try:
                        results.extend(check_dashboard(client, client.dashboard(uid)))
                    except Exception as error:
                        log(f"dashboard {uid} skipped: {type(error).__name__}: {error}")
                snapshot.results = results
                snapshot.dashboards = len(uids)
                snapshot.last_success = time.time()
                broken = [r for r in results if r.status != "data" and not r.empty_expected]
                log(f"checked {len(results)} panels on {len(uids)} dashboards; {len(broken)} without data")
            except Exception as error:
                snapshot.check_failures += 1
                log(f"check failed: {type(error).__name__}: {error}")
        snapshot.check_duration = time.time() - started
        with self.lock:
            self.snapshot = snapshot

    def metrics(self) -> str:
        with self.lock:
            return render(self.snapshot)


def make_handler(exporter: Exporter):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                body, status, kind = exporter.metrics().encode(), 200, "text/plain; version=0.0.4"
            elif self.path == "/healthz":
                body, status, kind = b"ok\n", 200, "text/plain"
            else:
                body, status, kind = b"not found\n", 404, "text/plain"
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    return Handler


def main() -> None:
    base_url = os.environ.get("GRAFANA_URL", "http://grafana-service.observability.svc.cluster.local:3000")
    timeout = int(os.environ.get("QUERY_TIMEOUT_SECONDS", "60"))
    interval = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "3600"))
    exporter = Exporter(lambda token: GrafanaClient(base_url, token, timeout),
                        os.environ.get("GRAFANA_TOKEN_FILE", "/var/run/grafana/token"))

    def loop():
        while True:
            exporter.refresh()
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()
    port = int(os.environ.get("LISTEN_PORT", "9802"))
    ThreadingHTTPServer(("", port), make_handler(exporter)).serve_forever()


if __name__ == "__main__":
    main()
