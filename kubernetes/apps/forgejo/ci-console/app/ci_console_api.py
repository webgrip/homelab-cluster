#!/usr/bin/env python3
import calendar
import gzip
import hashlib
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORGEJO_URL = os.environ.get("FORGEJO_URL", "http://forgejo-http.forgejo.svc.cluster.local:3000").rstrip("/")
PORT = int(os.environ.get("LISTEN_PORT", "8080"))
PREFIX = os.environ.get("PATH_PREFIX", "/-/ci/api")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "20"))
LANES = int(os.environ.get("LANES", "8"))

HOT_INTERVAL = 6.0
WARM_INTERVAL = 30.0
QUIET_INTERVAL = 600.0
REPOS_INTERVAL = 600.0
RUNNERS_INTERVAL = 15.0
USER_TTL = 300.0
SESSION_IDLE_STOP = 120.0
SESSION_FORGET = 1800.0
WINDOW = 24 * 3600
QUIET_AFTER = 14 * 24 * 3600
KEEP_SECONDS = 7 * 24 * 3600
KEEP_PER_REPO = 40
HOT_PAGE = 5
FULL_PAGE = 20
MAX_PAGES = 5
MAX_WATCHED = 10
TICK = 1.0

ACTIVE = {"running", "waiting", "blocked"}
FINISHED = {"success", "failure", "cancelled", "skipped"}


class AuthRejected(Exception):
    pass


class UpstreamError(Exception):
    def __init__(self, status, path):
        super().__init__(f"HTTP {status} for {path}")
        self.status = status


def log(message):
    print(f"[ci-console-api] {message}", file=sys.stderr, flush=True)


def epoch_ms(value):
    if not value:
        return 0
    try:
        seconds = calendar.timegm(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0
    return 0 if seconds < 86400 else seconds * 1000


def forgejo(token, path, params=None):
    url = FORGEJO_URL + "/api/v1" + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = json.load(response)
            total = response.headers.get("X-Total-Count")
            return body, int(total) if total and total.isdigit() else None
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise AuthRejected() from error
        raise UpstreamError(error.code, path) from error


def compact_run(raw, repo):
    status = raw.get("status") or "unknown"
    started = epoch_ms(raw.get("started"))
    stopped = epoch_ms(raw.get("stopped")) if status in FINISHED else 0
    duration = raw.get("duration")
    if duration:
        duration_ms = int(duration / 1e6)
    elif started and stopped:
        duration_ms = stopped - started
    else:
        duration_ms = 0
    html_url = raw.get("html_url") or ""
    path = urllib.parse.urlsplit(html_url).path if html_url else f"/{repo['name']}/actions/runs/{raw.get('index_in_repo')}"
    user = raw.get("trigger_user") or {}
    ref = raw.get("prettyref") or ""
    event = raw.get("trigger_event") or raw.get("event") or ""
    return {
        "key": f"{repo['name']}#{raw.get('index_in_repo')}",
        "id": raw.get("id"),
        "repo": repo["name"],
        "number": raw.get("index_in_repo"),
        "title": raw.get("title") or "(no title)",
        "workflow": raw.get("workflow_id") or "",
        "status": status,
        "event": event,
        "ref": ref,
        "sha": raw.get("commit_sha") or "",
        "actor": user.get("login") or "",
        "actorAvatar": user.get("avatar_url") or "",
        "created": epoch_ms(raw.get("created")),
        "started": started,
        "stopped": stopped,
        "duration": duration_ms,
        "updated": epoch_ms(raw.get("updated")),
        "path": path,
        "trunk": ref == (repo.get("default_branch") or "main") and raw.get("event") != "pull_request",
    }


def run_signature(run):
    return (run["status"], run["started"], run["stopped"], run["title"], run["updated"])


class RepoState:
    def __init__(self, info):
        self.info = info
        self.loaded = False
        self.error = None
        self.total = None
        self.last_activity = 0
        self.quiet = False
        self.hot = False
        self.next_at = 0.0
        self.watched = set()

    @property
    def name(self):
        return self.info["name"]


class Session:
    def __init__(self, key, token, user):
        self.key = key
        self.token = token
        self.lock = threading.Lock()
        self.user = user
        self.repos = {}
        self.runs = {}
        self.runners = None
        self.runners_note = ""
        self.queue = None
        self.repos_at = 0.0
        self.runners_at = 0.0
        self.synced_at = 0.0
        self.version = 1
        self.last_seen = time.time()
        self.worker = None
        self.auth_failed = False
        self.cached_body = None
        self.cached_version = 0
        self.dirty = False

    def touch(self, token):
        self.last_seen = time.time()
        self.token = token
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self.loop, name=f"session-{self.key[:8]}", daemon=True)
            self.worker.start()

    def bump(self):
        self.version += 1

    def loop(self):
        executor = ThreadPoolExecutor(max_workers=LANES, thread_name_prefix=f"lane-{self.key[:6]}")
        try:
            while time.time() - self.last_seen < SESSION_IDLE_STOP and not self.auth_failed:
                started = time.time()
                try:
                    self.cycle(executor)
                except AuthRejected:
                    self.auth_failed = True
                    self.bump()
                    break
                except Exception as error:
                    log(f"cycle error: {error!r}")
                time.sleep(max(0.0, TICK - (time.time() - started)))
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def cycle(self, executor):
        now = time.time()
        if now - self.repos_at > REPOS_INTERVAL:
            self.discover()
        if now - self.runners_at > RUNNERS_INTERVAL:
            self.sync_runners()
        due = [r for r in self.repos.values() if r.next_at <= now]
        due.sort(key=lambda r: (not r.hot, -r.last_activity))
        for repo in due:
            repo.next_at = now + WARM_INTERVAL
        before = {r.name: (r.loaded, r.error) for r in due}
        futures = [executor.submit(self.sync_repo, repo) for repo in due]
        for future in futures:
            future.result()
        if due:
            self.prune()
            self.synced_at = time.time()
            if any(before.get(r.name) != (r.loaded, r.error) for r in due if r.name in self.repos) or len(due) != sum(1 for r in due if r.name in self.repos):
                self.dirty = True
        if self.dirty:
            self.dirty = False
            self.bump()

    def discover(self):
        found, page = [], 1
        while True:
            body, _ = forgejo(self.token, "/repos/search", {"page": page, "limit": 50, "sort": "id", "order": "asc"})
            batch = (body or {}).get("data") or []
            found.extend(batch)
            if len(batch) < 50 or page >= 20:
                break
            page += 1
        seen = set()
        with self.lock:
            for raw in found:
                if not raw.get("has_actions") or raw.get("archived") or raw.get("mirror") or raw.get("empty"):
                    continue
                owner = raw.get("owner") or {}
                info = {
                    "name": raw.get("full_name"),
                    "id": raw.get("id"),
                    "owner_id": owner.get("id"),
                    "owner": owner.get("login"),
                    "default_branch": raw.get("default_branch") or "main",
                    "private": bool(raw.get("private")),
                }
                seen.add(info["name"])
                if info["name"] in self.repos:
                    self.repos[info["name"]].info = info
                else:
                    self.repos[info["name"]] = RepoState(info)
            for name in [n for n in self.repos if n not in seen]:
                self.drop_repo(name)
        self.repos_at = time.time()
        self.bump()

    def drop_repo(self, name):
        self.repos.pop(name, None)
        for key in [k for k, run in self.runs.items() if run["repo"] == name]:
            del self.runs[key]

    def runs_page(self, repo, page, limit):
        body, _ = forgejo(self.token, f"/repos/{repo.name}/actions/runs", {"page": page, "limit": limit})
        body = body or {}
        if isinstance(body.get("total_count"), int):
            repo.total = body["total_count"]
        return body.get("workflow_runs") or []

    def absorb(self, repo, items):
        added = 0
        with self.lock:
            for raw in items:
                run = compact_run(raw, repo.info)
                known = self.runs.get(run["key"])
                if known is None:
                    added += 1
                elif run_signature(known) == run_signature(run):
                    continue
                self.runs[run["key"]] = run
                self.dirty = True
                repo.last_activity = max(repo.last_activity, run["created"], run["updated"])
        return added

    def backfill(self, repo, page, stop_on_known):
        cutoff = (time.time() - WINDOW) * 1000
        while True:
            items = self.runs_page(repo, page, FULL_PAGE)
            added = self.absorb(repo, items)
            oldest = min((epoch_ms(i.get("created")) or float("inf") for i in items), default=float("inf"))
            if len(items) < FULL_PAGE or page >= MAX_PAGES or oldest < cutoff or (stop_on_known and added < len(items)):
                return
            page += 1

    def refresh_watched(self, repo, seen_ids):
        with self.lock:
            stale = [run["id"] for run in self.runs.values() if run["repo"] == repo.name and run["status"] in ACTIVE and run["id"] not in seen_ids]
        stale.extend(i for i in repo.watched if i not in seen_ids and i not in stale)
        repo.watched.clear()
        for run_id in stale[:MAX_WATCHED]:
            try:
                body, _ = forgejo(self.token, f"/repos/{repo.name}/actions/runs/{run_id}")
                if body:
                    self.absorb(repo, [body])
            except UpstreamError:
                continue

    def sync_repo(self, repo):
        first = not repo.loaded
        try:
            limit = FULL_PAGE if first else HOT_PAGE
            items = self.runs_page(repo, 1, limit)
            added = self.absorb(repo, items)
            if first:
                oldest = min((epoch_ms(i.get("created")) or float("inf") for i in items), default=float("inf"))
                if len(items) == FULL_PAGE and oldest > (time.time() - WINDOW) * 1000:
                    self.backfill(repo, 2, False)
            elif added == len(items) == limit:
                self.backfill(repo, 1, True)
            self.refresh_watched(repo, {i.get("id") for i in items})
            repo.loaded = True
            repo.error = None
            repo.quiet = not repo.total or (time.time() * 1000 - repo.last_activity > QUIET_AFTER * 1000)
            with self.lock:
                repo.hot = any(r["repo"] == repo.name and r["status"] in ACTIVE for r in self.runs.values())
            interval = HOT_INTERVAL if repo.hot else QUIET_INTERVAL if repo.quiet else WARM_INTERVAL
            repo.next_at = time.time() + interval * (1 if repo.hot else random.uniform(0.85, 1.15))
        except AuthRejected:
            raise
        except UpstreamError as error:
            if error.status == 404:
                with self.lock:
                    self.drop_repo(repo.name)
                return
            repo.error = str(error)
            repo.loaded = True
            repo.next_at = time.time() + WARM_INTERVAL
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            repo.error = str(error)
            repo.loaded = True
            repo.next_at = time.time() + WARM_INTERVAL

    def prune(self):
        cutoff = (time.time() - KEEP_SECONDS) * 1000
        with self.lock:
            by_repo = {}
            for run in self.runs.values():
                by_repo.setdefault(run["repo"], []).append(run)
            for runs in by_repo.values():
                runs.sort(key=lambda r: r["number"] or 0, reverse=True)
                for index, run in enumerate(runs):
                    if index >= KEEP_PER_REPO and run["created"] < cutoff and run["status"] not in ACTIVE:
                        del self.runs[run["key"]]
                        self.dirty = True

    def sync_runners(self):
        admin = bool(self.user and self.user.get("is_admin"))
        path = "/admin/actions/runners" if admin else "/user/actions/runners"
        runners, page = [], 1
        try:
            while True:
                body, _ = forgejo(self.token, path, {"page": page, "limit": 50, "visible": "true" if admin else None})
                batch = body if isinstance(body, list) else (body or {}).get("entries") or []
                runners.extend(batch)
                if len(batch) < 50 or page >= 10:
                    break
                page += 1
            listed = [{k: r.get(k) for k in ("id", "name", "status", "labels", "version", "ephemeral", "owner_id", "repo_id")} for r in runners]
            if listed != self.runners or self.runners_note:
                self.runners = listed
                self.runners_note = ""
                self.dirty = True
        except UpstreamError as error:
            note = f"Forgejo did not list runners for this account ({error})."
            if note != self.runners_note:
                self.runners_note = note
                self.dirty = True
        if admin:
            try:
                body, _ = forgejo(self.token, "/admin/actions/runners/jobs")
                queue = [{k: j.get(k) for k in ("id", "name", "status", "runs_on", "repo_id", "attempt")} for j in (body or [])]
            except UpstreamError:
                queue = None
            if queue != self.queue:
                self.queue = queue
                self.dirty = True
        self.runners_at = time.time()

    def wake(self, repo_name, run_id):
        repo = self.repos.get(repo_name)
        if not repo:
            return False
        if isinstance(run_id, int):
            repo.watched.add(run_id)
        repo.hot = True
        repo.next_at = time.time() + 1.0
        return True

    def snapshot(self):
        if self.cached_version == self.version and self.cached_body is not None:
            return self.cached_body
        with self.lock:
            repos = [
                {**r.info, "loaded": r.loaded, "error": r.error, "total": r.total, "lastActivity": r.last_activity, "quiet": r.quiet}
                for r in self.repos.values()
            ]
            runs = list(self.runs.values())
        body = {
            "version": self.version,
            "user": self.user,
            "authFailed": self.auth_failed,
            "reposDiscovered": self.repos_at > 0,
            "repos": repos,
            "runs": runs,
            "runners": self.runners,
            "runnersNote": self.runners_note,
            "queue": self.queue,
            "syncedAt": int(self.synced_at * 1000),
        }
        self.cached_body = json.dumps(body, separators=(",", ":")).encode()
        self.cached_version = self.version
        return self.cached_body


SESSIONS = {}
TOKENS = {}
SESSIONS_LOCK = threading.Lock()


def user_for(token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    cached = TOKENS.get(digest)
    if cached and time.time() - cached[1] < USER_TTL:
        return cached[0]
    body, _ = forgejo(token, "/user")
    user = {"login": body.get("login"), "avatar_url": body.get("avatar_url"), "is_admin": bool(body.get("is_admin"))}
    TOKENS[digest] = (user, time.time())
    return user


def session_for(token):
    user = user_for(token)
    key = hashlib.sha256(str(user["login"]).encode()).hexdigest()
    with SESSIONS_LOCK:
        session = SESSIONS.get(key)
        if session is None:
            session = Session(key, token, user)
            SESSIONS[key] = session
    session.user = user
    return session


def reaper():
    while True:
        time.sleep(60)
        now = time.time()
        with SESSIONS_LOCK:
            for key in [k for k, s in SESSIONS.items() if s.last_seen < now - SESSION_FORGET]:
                del SESSIONS[key]
            for digest in [d for d, (_, at) in TOKENS.items() if at < now - USER_TTL]:
                del TOKENS[digest]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ci-console-api"

    def log_message(self, fmt, *args):
        return

    def reply(self, status, body=b"", content_type="application/json", headers=None):
        payload = body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode()
        encoded = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(payload) > 1024
        if encoded:
            payload = gzip.compress(payload, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Authorization, Accept-Encoding")
        if encoded:
            self.send_header("Content-Encoding", "gzip")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def bearer(self):
        header = self.headers.get("Authorization") or ""
        return header[7:].strip() if header.lower().startswith("bearer ") else ""

    def authorised_session(self):
        token = self.bearer()
        if not token:
            self.reply(401, {"message": "missing bearer token"})
            return None
        try:
            session = session_for(token)
        except AuthRejected:
            self.reply(401, {"message": "Forgejo rejected the token"})
            return None
        except (UpstreamError, urllib.error.URLError, TimeoutError) as error:
            self.reply(502, {"message": f"Forgejo unreachable: {error}"})
            return None
        session.auth_failed = False
        session.touch(token)
        return session

    def route(self):
        return urllib.parse.urlsplit(self.path).path.removeprefix(PREFIX) or "/"

    def do_GET(self):
        route = self.route()
        if route == "/healthz":
            self.reply(200, {"ok": True, "sessions": len(SESSIONS)})
            return
        if route != "/state":
            self.reply(404, {"message": "not found"})
            return
        session = self.authorised_session()
        if not session:
            return
        have = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("have", [""])[0]
        headers = {"X-State-Version": str(session.version), "X-Synced-At": str(int(session.synced_at * 1000))}
        if have == str(session.version):
            self.reply(304, headers=headers)
            return
        self.reply(200, session.snapshot(), headers=headers)

    def do_POST(self):
        if self.route() != "/wake":
            self.reply(404, {"message": "not found"})
            return
        session = self.authorised_session()
        if not session:
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except ValueError:
            self.reply(400, {"message": "body is not JSON"})
            return
        self.reply(200, {"woken": session.wake(str(body.get("repo") or ""), body.get("runId"))})


def main():
    threading.Thread(target=reaper, name="reaper", daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    log(f"listening on :{PORT}, prefix {PREFIX}, upstream {FORGEJO_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
