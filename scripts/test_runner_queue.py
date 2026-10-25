import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTER = Path(os.environ.get(
    "EXPORTER_SCRIPT",
    REPO_ROOT / "kubernetes/apps/forgejo/runner-queue/app/runner_queue.py"))
SCALER_TOKEN = "scaler-token-under-test"
WEBGRIP_ID = 7
OTHER_OWNER_ID = 9


class FakeForgejo(BaseHTTPRequestHandler):
    jobs = []
    status = 200
    calls = []

    def do_GET(self):
        url = urlsplit(self.path)
        FakeForgejo.calls.append((url.path, parse_qs(url.query), self.headers.get("Authorization")))
        if url.path == "/api/v1/orgs/webgrip":
            if self.headers.get("Authorization"):
                self.reply(403, {"message": "token does not have at least one of required scope(s): [read:organization]"})
            else:
                self.reply(200, {"id": WEBGRIP_ID, "username": "webgrip", "visibility": "public"})
        elif self.headers.get("Authorization") != f"token {SCALER_TOKEN}":
            self.reply(401, {"message": "token is required"})
        elif url.path == "/api/v1/admin/actions/runners/jobs":
            self.reply(FakeForgejo.status, FakeForgejo.jobs)
        else:
            self.reply(404, {"message": "not found"})

    def reply(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


def job(status, owner_id=WEBGRIP_ID):
    return {"id": 1, "status": status, "owner_id": owner_id, "runs_on": ["unfold-ci"]}


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def load_exporter(forgejo_url, token_file):
    os.environ.update({
        "FORGEJO_URL": forgejo_url,
        "FORGEJO_OWNER": "webgrip",
        "RUNNER_LABELS": "unfold-ci",
        "TOKEN_FILE": token_file,
    })
    spec = importlib.util.spec_from_file_location("runner_queue", EXPORTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerQueueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.forgejo = serve(FakeForgejo)
        cls.workdir = tempfile.TemporaryDirectory()
        cls.token_file = Path(cls.workdir.name) / "token"
        cls.token_file.write_text(SCALER_TOKEN + "\n")
        cls.exporter = load_exporter(f"http://127.0.0.1:{cls.forgejo.server_port}", str(cls.token_file))
        cls.queue = serve(cls.exporter.QueueHandler)
        cls.base = f"http://127.0.0.1:{cls.queue.server_port}"

    @classmethod
    def tearDownClass(cls):
        for server in (cls.queue, cls.forgejo):
            server.shutdown()
            server.server_close()
        cls.workdir.cleanup()

    def setUp(self):
        FakeForgejo.jobs = []
        FakeForgejo.status = 200
        FakeForgejo.calls = []

    def get(self, path, method="GET"):
        request = urllib.request.Request(self.base + path, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            body = error.read()
            return error.code, json.loads(body) if body.startswith(b"{") else None

    def test_counts_only_waiting_jobs_of_the_owner(self):
        FakeForgejo.jobs = [job("waiting"), job("waiting"), job("running"), job("blocked"),
                            job("waiting", OTHER_OWNER_ID)]
        self.assertEqual(self.get("/waiting-jobs/unfold-ci"), (200, {"label": "unfold-ci", "waiting": 2}))

    def test_asks_forgejo_for_the_label_with_the_scaler_token(self):
        self.get("/waiting-jobs/unfold-ci")
        queue_calls = [call for call in FakeForgejo.calls if call[0] == "/api/v1/admin/actions/runners/jobs"]
        self.assertEqual(queue_calls, [("/api/v1/admin/actions/runners/jobs", {"labels": ["unfold-ci"]},
                                        f"token {SCALER_TOKEN}")])

    def test_the_owner_is_looked_up_without_the_admin_token(self):
        self.exporter._owner_ids.clear()
        FakeForgejo.jobs = [job("waiting")]
        self.assertEqual(self.get("/waiting-jobs/unfold-ci"), (200, {"label": "unfold-ci", "waiting": 1}))
        self.assertIn(("/api/v1/orgs/webgrip", {}, None), FakeForgejo.calls)

    def test_an_empty_queue_is_zero(self):
        FakeForgejo.jobs = None
        self.assertEqual(self.get("/waiting-jobs/unfold-ci"), (200, {"label": "unfold-ci", "waiting": 0}))

    def test_a_label_that_is_not_published_is_not_found_and_never_reaches_forgejo(self):
        self.assertEqual(self.get("/waiting-jobs/docker")[0], 404)
        self.assertEqual(self.get("/waiting-jobs/")[0], 404)
        self.assertEqual(self.get("/api/v1/admin/actions/runners/jobs")[0], 404)
        self.assertEqual(FakeForgejo.calls, [])

    def test_an_unreadable_queue_is_an_error_not_zero(self):
        FakeForgejo.status = 500
        FakeForgejo.jobs = {"message": "boom"}
        status, body = self.get("/waiting-jobs/unfold-ci")
        self.assertEqual(status, 502)
        self.assertNotIn("waiting", body)

    def test_only_reads_are_served(self):
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertEqual(self.get("/waiting-jobs/unfold-ci", method)[0], 501, method)
        self.assertEqual(FakeForgejo.calls, [])

    def test_a_rotated_token_is_used_without_a_restart(self):
        try:
            self.token_file.write_text("rotated")
            self.assertEqual(self.get("/waiting-jobs/unfold-ci")[0], 502)
        finally:
            self.token_file.write_text(SCALER_TOKEN)
        self.assertEqual(self.get("/waiting-jobs/unfold-ci")[0], 200)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1] + sys.argv[1:], verbosity=1)
