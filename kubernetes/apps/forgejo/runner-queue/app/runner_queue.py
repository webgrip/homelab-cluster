#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORGEJO_URL = os.environ.get("FORGEJO_URL", "http://forgejo-http.forgejo.svc.cluster.local:3000").rstrip("/")
OWNER = os.environ.get("FORGEJO_OWNER", "webgrip")
PUBLISHED_LABELS = frozenset(label for label in os.environ.get("RUNNER_LABELS", "").split(",") if label)
TOKEN_FILE = os.environ.get("TOKEN_FILE", "/run/forgejo-runner-scaler/token")
PORT = int(os.environ.get("LISTEN_PORT", "8080"))
HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
WAITING_JOBS_ROUTE = "/waiting-jobs/"
FORGEJO_FAILURES = (urllib.error.URLError, OSError, ValueError, KeyError, TypeError)

_owner_ids = {}


def read_token():
    with open(TOKEN_FILE, encoding="utf-8") as handle:
        return handle.read().strip()


def forgejo_get(path, query=None, authenticated=True):
    url = f"{FORGEJO_URL}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    headers = {"Accept": "application/json"}
    if authenticated:
        headers["Authorization"] = f"token {read_token()}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read() or b"null")


def owner_id():
    if OWNER not in _owner_ids:
        _owner_ids[OWNER] = int(forgejo_get(f"/api/v1/orgs/{urllib.parse.quote(OWNER)}", authenticated=False)["id"])
    return _owner_ids[OWNER]


def waiting_jobs(label):
    jobs = forgejo_get("/api/v1/admin/actions/runners/jobs", {"labels": label}) or []
    owner = owner_id()
    return sum(1 for job in jobs if job["status"] == "waiting" and job["owner_id"] == owner)


class QueueHandler(BaseHTTPRequestHandler):
    server_version = "runner-queue"
    sys_version = ""

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            self.respond(200, {"status": "ok"})
            return
        label = path[len(WAITING_JOBS_ROUTE):] if path.startswith(WAITING_JOBS_ROUTE) else None
        if label not in PUBLISHED_LABELS:
            self.respond(404, {"error": "unknown runner label"})
            return
        try:
            count = waiting_jobs(label)
        except FORGEJO_FAILURES as error:
            print(f"forgejo job queue unreadable for {label}: {error!r}", file=sys.stderr, flush=True)
            self.respond(502, {"error": "forgejo job queue unreadable"})
            return
        self.respond(200, {"label": label, "waiting": count})

    def respond(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        print(f"{self.address_string()} {format % args}", file=sys.stderr, flush=True)


def main():
    if not PUBLISHED_LABELS:
        sys.exit("RUNNER_LABELS names no runner label to publish")
    ThreadingHTTPServer(("", PORT), QueueHandler).serve_forever()


if __name__ == "__main__":
    main()
