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
        self.files = {}
        self.tags = {}
        self.broken_repositories = set()
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

        def reply_text(self, text):
            raw = text.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def repository_file(self, parsed, query):
            match = re.match(r"^/api/v1/repos/webgrip/(?P<repo>[^/]+)/(?P<kind>raw|contents|tags)/?(?P<path>.*)$",
                             parsed.path)
            if not match:
                return self.reply(404, {"message": "not found"})
            repo, kind = match.group("repo"), match.group("kind")
            path = urllib.parse.unquote(match.group("path"))
            if repo in world.broken_repositories:
                return self.reply(500, {"message": "boom"})
            if kind == "tags":
                limit = int(query.get("limit", "30"))
                page = int(query.get("page", "1"))
                names = world.tags.get(repo, [])[(page - 1) * limit:page * limit]
                return self.reply(200, [{"name": name} for name in names])
            if kind == "raw":
                if (repo, path) not in world.files:
                    return self.reply(404, {"message": "not found"})
                return self.reply_text(world.files[(repo, path)])
            listing = [{"type": "file", "name": file.rsplit("/", 1)[-1], "path": file}
                       for owner, file in world.files if owner == repo and file.rsplit("/", 1)[0] == path]
            if not listing:
                return self.reply(404, {"message": "not found"})
            return self.reply(200, listing)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(parsed.query))
            world.requests.append((parsed.path, query, self.headers.get("Authorization")))
            if parsed.path.startswith("/api/v1/repos/"):
                return self.repository_file(parsed, query)
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
        pages = [int(query["page"]) for path, query, _ in self.world.requests
                 if path == "/api/v1/orgs/webgrip/repos"]
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

    def give_homelab_cluster_a_delivery_chain(self):
        self.world.tags["workflows"] = ["v4.0.0-rc.1", "v3.3.1", "v3.3.0", "v3.2.0", "release-notes"]
        self.world.tags["renovate-config"] = ["v1.19.2", "v1.18.0"]
        self.world.tags["agent-standards"] = ["v0.5.3"]
        self.world.files.update({
            ("homelab-cluster", "renovate.json"):
                '{"extends": ["local>webgrip/renovate-config:reviewed#v1.18.0"]}',
            ("homelab-cluster", ".forgejo/workflows/release.yml"):
                "jobs:\n  release:\n    uses: webgrip/workflows/.forgejo/workflows/semantic-release.yml@"
                "0123456789abcdef0123456789abcdef01234567 # v3.2.0\n"
                "  deploy:\n    uses: webgrip/workflows/.forgejo/workflows/cloudflare-deploy.yml@"
                "0123456789abcdef0123456789abcdef01234567 # v3.2.0\n",
            ("homelab-cluster", "apm.yml"):
                "dependencies:\n  - git: https://forgejo.webgrip.dev/webgrip/agent-standards.git\n"
                "    path: packages/baseline\n    ref: v0.5.3\n",
        })

    def repository_info(self, metrics, name):
        rows = [labels for metric, labels in metrics
                if metric == "repo_config_repository_info" and f'repository="{name}"' in labels]
        self.assertEqual(len(rows), 1, rows)
        return dict(re.findall(r'(\w+)="([^"]*)"', rows[0]))

    def test_repository_info_states_how_a_repository_ships(self):
        self.model_path.write_text(MODEL.replace("    core: true\n", "    core: true\n    staged: true\n", 1))
        self.give_homelab_cluster_a_delivery_chain()
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        info = self.repository_info(metrics, "homelab-cluster")
        self.assertEqual(info["kind"], "config")
        self.assertEqual(info["branching"], "staged")
        self.assertEqual(info["core"], "yes")
        self.assertEqual(info["github_mirror"], "yes")
        self.assertEqual(info["renovate_gate"], "reviewed")
        self.assertEqual(info["releases"], "shared semantic-release")
        self.assertEqual(info["ships"], "cloudflare")
        self.assertEqual(info["workflows"], "v3.2.0 · 2 behind")
        self.assertEqual(info["renovate_config"], "v1.18.0 · 1 behind")
        self.assertEqual(info["agent_standards"], "v0.5.3")
        self.assertEqual(info["semantic_release_config"], "-")
        self.assertEqual(info["workflow_calls"], "2")
        self.assertEqual(metrics[("repo_config_shared_latest", 'package="workflows",version="v3.3.1"')], 1)
        self.assertEqual(metrics[("repo_config_shared_pin_releases_behind",
                                  'package="workflows",repository="homelab-cluster"')], 2)
        self.assertEqual(metrics[("repo_config_shared_pin_releases_behind",
                                  'package="agent-standards",repository="homelab-cluster"')], 0)
        self.assertEqual(metrics[("repo_config_workflow_call",
                                  'repository="homelab-cluster",workflow="semantic-release"')], 1)
        self.assertEqual(metrics[("repo_config_scan_failed", 'repository="homelab-cluster"')], 0)
        self.assertEqual(metrics[("repo_config_inventory_scan_failed_repositories", "")], 0)

    def test_repository_without_delivery_files_reads_as_nothing(self):
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        info = self.repository_info(self.pushed(), ".profile")
        self.assertEqual(info["renovate_gate"], "none")
        self.assertEqual(info["releases"], "none")
        self.assertEqual(info["ships"], "nothing")
        self.assertEqual(info["workflows"], "-")
        self.assertEqual(info["branching"], "trunk")
        self.assertEqual(info["github_mirror"], "no")

    def test_unversioned_workflow_pin_is_reported(self):
        self.world.tags["workflows"] = ["v3.3.1"]
        self.world.files[("erfbeeld", ".github/workflows/ci.yml")] = (
            "jobs:\n  build:\n    uses: webgrip/workflows/.github/workflows/docker-build-and-push.yml@main\n")
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        info = self.repository_info(metrics, "erfbeeld")
        self.assertEqual(info["workflows"], "unversioned")
        self.assertEqual(info["ships"], "image")
        self.assertEqual(metrics[("repo_config_shared_pin_unversioned",
                                  'package="workflows",repository="erfbeeld"')], 1)

    def test_own_release_and_steps_are_read_but_reusable_definitions_are_not(self):
        self.world.files.update({
            ("erfbeeld", ".forgejo/workflows/release.yml"):
                "on: push\njobs:\n  release:\n    steps:\n      - run: npx semantic-release\n"
                "      - uses: docker/build-push-action@v6\n",
            (".profile", ".forgejo/workflows/library.yml"):
                "on:\n  workflow_call:\njobs:\n  ship:\n    steps:\n      - run: npx semantic-release && "
                "helm push chart.tgz oci://registry\n",
        })
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        erfbeeld = self.repository_info(metrics, "erfbeeld")
        self.assertEqual(erfbeeld["releases"], "own semantic-release")
        self.assertEqual(erfbeeld["ships"], "image")
        profile = self.repository_info(metrics, ".profile")
        self.assertEqual(profile["releases"], "none")
        self.assertEqual(profile["ships"], "nothing")

    def test_unmodelled_repository_reads_as_unmodelled(self):
        self.world.repositories.append(repository("new-thing"))
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.repository_info(self.pushed(), "new-thing")["kind"], "unmodelled")

    def test_unreadable_repository_is_reported_and_the_inventory_still_succeeds(self):
        self.world.broken_repositories.add("erfbeeld")
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(metrics[("repo_config_scan_failed", 'repository="erfbeeld"')], 1)
        self.assertEqual(metrics[("repo_config_scan_failed", 'repository="homelab-cluster"')], 0)
        self.assertEqual(metrics[("repo_config_inventory_scan_failed_repositories", "")], 1)
        self.assertEqual(self.repository_info(metrics, "erfbeeld")["workflows"], "unread")
        self.assertEqual(metrics[("repo_config_inventory_unmodelled_repositories", "")], 0)
        self.assertIn("could not read the delivery files of erfbeeld", output)

    def test_unreadable_releases_leave_pins_without_a_lag(self):
        self.give_homelab_cluster_a_delivery_chain()
        self.world.broken_repositories.add("workflows")
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(self.repository_info(metrics, "homelab-cluster")["workflows"], "v3.2.0")
        self.assertNotIn(("repo_config_shared_pin_releases_behind",
                          'package="workflows",repository="homelab-cluster"'), metrics)

    def test_model_facts_match_yaml_on_the_real_model(self):
        import yaml
        spec = importlib.util.spec_from_file_location("repo_config_inventory_facts", INVENTORY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = REAL_MODEL.read_text()
        repos = yaml.safe_load(text)["repos"]
        facts = module.model_facts(text)
        self.assertEqual(sorted(facts), sorted(repos))
        for key, repo in repos.items():
            self.assertEqual(facts[key].get("kind"), repo.get("kind"), key)
            self.assertEqual(facts[key].get("staged") == "true", bool(repo.get("staged")), key)
            self.assertEqual(facts[key].get("core") == "true", bool(repo.get("core")), key)
            self.assertEqual(facts[key].get("mirror_of"), repo.get("mirror_of"), key)
        expected_mirrors = sorted({repo["mirror_of"] for repo in repos.values()
                                   if repo.get("mirror_of") and not (repo.get("settings") or {}).get("archived")})
        self.assertEqual(module.github_mirrors(facts), expected_mirrors)
        self.assertTrue(expected_mirrors)

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
