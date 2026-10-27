import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY = Path(os.environ.get(
    "INVENTORY_SCRIPT",
    REPO_ROOT / "kubernetes/apps/repo-config/repo-config/inventory/repo_config_inventory.py"))
REAL_MODEL = REPO_ROOT / "kubernetes/apps/repo-config/repo-config/model/repos.yaml"

TOKEN = "forgejo-read-only-token-cccccccccccccccccccccccccccccccc"

MODEL = """---
apiVersion: repo-config.webgrip.io/v1alpha1
kind: RepoSet
forgejo:
  owner: webgrip
repos:
  ".profile":
    forge: forgejo
    kind: none
  homelab-cluster:
    forge: forgejo
    kind: config
    core: true
  erfbeeld:
    forge: forgejo
    kind: service
    settings:
      private: true
  ledgerflow:
    forge: forgejo
    settings:
      archived: true
  webgrip/homelab-cluster:
    forge: github
    mirror_of: homelab-cluster
"""


def repository(name, private=False, archived=False, mirror=False):
    return {"name": name, "private": private, "archived": archived, "mirror": mirror}


class FakeWorld:
    def __init__(self):
        self.repositories = [
            repository(".profile"),
            repository("homelab-cluster"),
            repository("erfbeeld", private=True),
            repository("ledgerflow", archived=True),
            repository("babyagi", mirror=True),
        ]
        self.forgejo_status = 200
        self.metrics_status = 204
        self.requests = []
        self.pushes = []


def handler_for(world):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body=None):
            raw = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(parsed.query))
            world.requests.append((parsed.path, query, self.headers.get("Authorization")))
            if parsed.path != "/api/v1/orgs/webgrip/repos":
                return self.reply(404, {"message": "not found"})
            if world.forgejo_status != 200:
                return self.reply(world.forgejo_status, {"message": "boom"})
            authenticated = self.headers.get("Authorization") == f"token {TOKEN}"
            visible = [r for r in world.repositories if authenticated or not r["private"]]
            limit = int(query.get("limit", "30"))
            page = int(query.get("page", "1"))
            return self.reply(200, visible[(page - 1) * limit:page * limit])

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            world.pushes.append((self.path, self.rfile.read(length).decode()))
            self.reply(world.metrics_status)

    return Handler


def samples(text):
    parsed = {}
    for line in text.splitlines():
        match = re.match(r'^(?P<name>[a-z_]+)\{(?P<labels>[^}]*)\} (?P<value>\S+)$', line)
        if match:
            parsed[(match.group("name"), match.group("labels"))] = float(match.group("value"))
    return parsed


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.world))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.work = tempfile.TemporaryDirectory()
        self.token_path = Path(self.work.name) / "FORGEJO_TOKEN"
        self.token_path.write_text(TOKEN + "\n")
        self.model_path = Path(self.work.name) / "repos.yaml"
        self.model_path.write_text(MODEL)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.work.cleanup()

    def run_inventory(self):
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "FORGEJO_URL": self.url,
            "FORGEJO_OWNER": "webgrip",
            "FORGEJO_TOKEN_PATH": str(self.token_path),
            "MODEL_PATH": str(self.model_path),
            "METRICS_URL": f"{self.url}/api/v1/import/prometheus?extra_label=job=repo-config-inventory",
        }
        result = subprocess.run([sys.executable, "-I", str(INVENTORY)], env=environment,
                                capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout + result.stderr

    def pushed(self):
        self.assertEqual(len(self.world.pushes), 1, "exactly one metrics push per successful run")
        return samples(self.world.pushes[0][1])

    def test_fully_modelled_org_passes_and_reports_zero(self):
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(metrics[("repo_config_unmodelled_repository", 'repository="homelab-cluster"')], 0)
        self.assertEqual(metrics[("repo_config_unmodelled_repository", 'repository="erfbeeld"')], 0)
        self.assertEqual(metrics[("repo_config_unmodelled_repository", 'repository=".profile"')], 0)
        self.assertEqual(metrics[("repo_config_inventory_unmodelled_repositories", "")], 0)
        self.assertEqual(metrics[("repo_config_inventory_active_repositories", "")], 3)
        self.assertGreater(metrics[("repo_config_inventory_last_success_timestamp_seconds", "")], 1.7e9)
        self.assertIn("every active repository is in the repo-config model", output)

    def test_unmodelled_private_repository_is_reported(self):
        self.world.repositories.append(repository("secret-project", private=True))
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(metrics[("repo_config_unmodelled_repository", 'repository="secret-project"')], 1)
        self.assertEqual(metrics[("repo_config_inventory_unmodelled_repositories", "")], 1)
        self.assertIn("secret-project", output)

    def test_unmodelled_public_repository_is_reported(self):
        self.world.repositories.append(repository("new-thing"))
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.pushed()[("repo_config_unmodelled_repository", 'repository="new-thing"')], 1)

    def test_archived_and_mirrored_repositories_are_not_counted(self):
        self.world.repositories += [repository("old-thing", archived=True), repository("upstream-fork", mirror=True)]
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        names = {labels for name, labels in metrics if name == "repo_config_unmodelled_repository"}
        self.assertNotIn('repository="old-thing"', names)
        self.assertNotIn('repository="upstream-fork"', names)
        self.assertNotIn('repository="babyagi"', names)
        self.assertEqual(metrics[("repo_config_inventory_unmodelled_repositories", "")], 0)

    def test_pages_are_read_until_an_empty_page(self):
        self.world.repositories += [repository(f"filler-{index:03d}") for index in range(110)]
        self.world.repositories.append(repository("last-page-repo", private=True))
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(metrics[("repo_config_unmodelled_repository", 'repository="last-page-repo"')], 1)
        pages = [int(query["page"]) for path, query, _ in self.world.requests]
        self.assertEqual(pages, [1, 2, 3, 4])

    def test_every_request_carries_the_token(self):
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        self.assertTrue(self.world.requests)
        self.assertTrue(all(auth == f"token {TOKEN}" for _, _, auth in self.world.requests))
        self.assertNotIn(TOKEN, output)
        self.assertNotIn(TOKEN, self.world.pushes[0][1])

    def test_absent_token_fails_without_reading_anonymously(self):
        self.token_path.write_text("")
        code, output = self.run_inventory()
        self.assertEqual(code, 1, output)
        self.assertEqual(self.world.requests, [])
        self.assertEqual(self.world.pushes, [])

    def test_token_blind_to_private_repositories_fails(self):
        self.token_path.write_text("some-other-token-that-reads-only-public-repos")
        code, output = self.run_inventory()
        self.assertEqual(code, 1, output)
        self.assertIn("sees no private repository", output)
        self.assertEqual(self.world.pushes, [])

    def test_forgejo_error_fails_without_a_success_timestamp(self):
        self.model_path.write_text(MODEL.replace("      private: true\n", "      private: false\n"))
        self.world.forgejo_status = 500
        code, output = self.run_inventory()
        self.assertEqual(code, 1, output)
        self.assertEqual(self.world.pushes, [])

    def test_empty_model_fails(self):
        self.model_path.write_text("")
        code, output = self.run_inventory()
        self.assertEqual(code, 1, output)
        self.assertEqual(self.world.pushes, [])

    def test_rejected_metrics_push_fails_the_run(self):
        self.world.metrics_status = 400
        code, output = self.run_inventory()
        self.assertEqual(code, 1, output)
        self.assertIn("metrics push returned 400", output)

    def test_model_parser_matches_yaml_on_the_real_model(self):
        import yaml
        spec = importlib.util.spec_from_file_location("repo_config_inventory_under_test", INVENTORY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = REAL_MODEL.read_text()
        repos = yaml.safe_load(text)["repos"]
        expected = sorted(key for key, repo in repos.items() if repo["forge"] == "forgejo")
        entries = module.model_forgejo_entries(text)
        self.assertEqual(sorted(entries), expected)
        self.assertGreaterEqual(len(expected), 20)
        settings = {key: repos[key].get("settings") or {} for key in expected}
        expected_private = sorted(key for key in expected
                                  if settings[key].get("private") and not settings[key].get("archived"))
        self.assertEqual(module.private_repositories_expected(entries), expected_private)
        self.assertTrue(expected_private)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *sys.argv[1:]], verbosity=1)
