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


def repository(name, private=False, archived=False, mirror=False, topics=None):
    return {"name": name, "private": private, "archived": archived, "mirror": mirror, "topics": topics or []}


def dashboard_issue(repo, *sections):
    body = ("This issue lists Renovate updates and detected dependencies. Read the [Dependency Dashboard]"
            "(https://docs.renovatebot.com/key-concepts/dashboard/) docs to learn more.\n\n" + "\n\n".join(sections))
    return {"number": 7, "title": "Renovate Dashboard", "body": body,
            "html_url": f"https://forgejo.example/webgrip/{repo}/issues/7"}


def pending_approval(*branches):
    lines = [f" - [ ] <!-- approve-branch=renovate/{branch} -->fix(deps): update {branch}" for branch in branches]
    if branches:
        lines.append(" - [ ] <!-- approve-all-pending-prs -->🔐 **Create all pending approval PRs at once** 🔐")
    return "## Pending Approval\n\nThe following branches are pending approval.\n\n" + "\n".join(lines)


def problems(*lines):
    return ("## Repository Problems\n\nRenovate tried to run on this repository, but found these problems.\n\n"
            + "\n".join(f" - {line}" for line in lines))


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
        self.pulls = {}
        self.issues = {}
        self.issues_status = 200
        self.check_states = {}
        self.broken_pulls = set()
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
            match = re.match(r"^/api/v1/repos/webgrip/(?P<repo>[^/]+)/(?P<kind>raw|contents|tags|pulls|issues|commits)"
                             r"/?(?P<path>.*)$", parsed.path)
            if not match:
                return self.reply(404, {"message": "not found"})
            repo, kind = match.group("repo"), match.group("kind")
            path = urllib.parse.unquote(match.group("path"))
            if repo in world.broken_repositories:
                return self.reply(500, {"message": "boom"})
            if kind == "pulls" and repo in world.broken_pulls:
                return self.reply(500, {"message": "boom"})
            if kind == "pulls":
                limit = int(query.get("limit", "30"))
                page = int(query.get("page", "1"))
                return self.reply(200, world.pulls.get(repo, [])[(page - 1) * limit:page * limit])
            if kind == "issues":
                if world.issues_status != 200:
                    return self.reply(world.issues_status, {"message": "token does not have the read:issue scope"})
                if query.get("state") != "open" or query.get("type") != "issues":
                    return self.reply(400, {"message": "only open issues are listed"})
                limit = int(query.get("limit", "30"))
                page = int(query.get("page", "1"))
                return self.reply(200, world.issues.get(repo, [])[(page - 1) * limit:page * limit])
            if kind == "commits":
                sha = path.removesuffix("/status")
                return self.reply(200, {"state": world.check_states.get(sha, ""), "statuses": []})
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
                                  'form="reusable",repository="homelab-cluster",workflow="semantic-release"')], 1)
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

    def test_composite_actions_are_calls_and_pins_in_both_forms(self):
        self.world.tags["workflows"] = ["v4.0.0", "v3.4.0", "v3.3.0"]
        sha = "0123456789abcdef0123456789abcdef01234567"
        self.world.files[("erfbeeld", ".forgejo/workflows/ci.yml")] = (
            "on: push\njobs:\n  build:\n    runs-on: docker\n    steps:\n"
            "      - uses: https://forgejo.webgrip.dev/webgrip/workflows/.forgejo/composite-actions/"
            "docker-build-push-registry-fast@v3.4.0\n"
            f"      - uses: webgrip/workflows/.forgejo/composite-actions/cosign-sign-attest@{sha} # v3.3.0\n")
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        info = self.repository_info(metrics, "erfbeeld")
        self.assertEqual(info["workflows"], "v3.3.0, v3.4.0 · 2 behind")
        self.assertEqual(info["workflow_calls"], "2")
        self.assertEqual(info["ships"], "image")
        self.assertEqual(metrics[("repo_config_workflow_call",
                                  'form="composite",repository="erfbeeld",workflow="docker-build-push-registry-fast"')], 1)
        self.assertEqual(metrics[("repo_config_workflow_call",
                                  'form="composite",repository="erfbeeld",workflow="cosign-sign-attest"')], 1)
        self.assertNotIn(("repo_config_shared_pin_unversioned", 'package="workflows",repository="erfbeeld"'), metrics)

    def test_a_pin_is_versioned_only_as_a_tag_or_a_sha_with_its_tag(self):
        self.world.tags["workflows"] = ["v3.4.0"]
        sha = "0123456789abcdef0123456789abcdef01234567"
        cases = {
            "erfbeeld": f"uses: webgrip/workflows/.forgejo/workflows/tests.yml@v3.4.0\n",
            "homelab-cluster": f"uses: webgrip/workflows/.forgejo/workflows/tests.yml@{sha} # v3.4.0\n",
            ".profile": f"uses: https://forgejo.webgrip.dev/webgrip/workflows/.forgejo/composite-actions/openbao-read@{sha}\n",
            "new-thing": "uses: https://forgejo.webgrip.dev/webgrip/workflows/.forgejo/composite-actions/edge-verify@main\n",
            "other-thing": f"uses: webgrip/workflows/.forgejo/composite-actions/openbao-read@{sha} # main\n",
        }
        self.world.repositories += [repository("new-thing"), repository("other-thing")]
        for name, line in cases.items():
            self.world.files[(name, ".forgejo/workflows/ci.yml")] = "jobs:\n  a:\n    steps:\n      - " + line
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        for name in ("erfbeeld", "homelab-cluster"):
            self.assertEqual(self.repository_info(metrics, name)["workflows"], "v3.4.0", name)
            self.assertNotIn(("repo_config_shared_pin_unversioned", f'package="workflows",repository="{name}"'),
                             metrics)
        for name in (".profile", "new-thing", "other-thing"):
            self.assertEqual(self.repository_info(metrics, name)["workflows"], "unversioned", name)
            self.assertEqual(metrics[("repo_config_shared_pin_unversioned",
                                      f'package="workflows",repository="{name}"')], 1, name)

    def test_a_tooling_repository_does_not_pin_itself(self):
        self.world.repositories.append(repository("workflows"))
        self.world.tags["workflows"] = ["v3.4.0"]
        self.world.files[("workflows", ".forgejo/workflows/ci.yml")] = (
            "jobs:\n  a:\n    uses: webgrip/workflows/.forgejo/workflows/tests.yml@main\n")
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(self.repository_info(metrics, "workflows")["workflows"], "-")
        self.assertNotIn(("repo_config_shared_pin_unversioned", 'package="workflows",repository="workflows"'), metrics)

    def test_the_release_image_is_a_semantic_release_config_pin(self):
        self.world.tags["semantic-release-config"] = ["v2.5.1", "v2.5.0", "v2.4.0", "v2.2.0", "v0.0.0"]
        image = "harbor.webgrip.dev/webgrip/semantic-release"
        digest = "@sha256:" + "a" * 64
        self.world.files.update({
            ("erfbeeld", ".forgejo/workflows/release.yml"):
                f"jobs:\n  release:\n    container:\n      image: {image}:2.4.0{digest}\n"
                f"  other:\n    uses: webgrip/workflows/.forgejo/workflows/semantic-release.yml@v3.4.0\n"
                f"    with:\n      toolchain-image: {image}:2.2.0{digest}\n"
                f"  retired:\n    container:\n      image: {image}:0.9.1\n",
            ("erfbeeld", "package.json"): '{"devDependencies": {"@webgrip/semantic-release-config": "2.5.0"}}',
            ("homelab-cluster", ".forgejo/workflows/release.yml"):
                f"jobs:\n  release:\n    container: '{image}:v2.5.1'\n",
        })
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(self.repository_info(metrics, "erfbeeld")["semantic_release_config"],
                         "v2.2.0, v2.4.0, v2.5.0 · 3 behind")
        self.assertEqual(self.repository_info(metrics, "homelab-cluster")["semantic_release_config"], "v2.5.1")

    def test_each_release_style_is_told_apart(self):
        self.world.repositories += [repository(name) for name in ("direct", "shared", "old-path", "own", "quiet")]
        composite = "uses: https://forgejo.webgrip.dev/webgrip/workflows/.forgejo/composite-actions"
        self.world.files.update({
            ("direct", ".forgejo/workflows/release.yml"):
                "on: push\njobs:\n  release:\n    steps:\n      - uses: ./.forgejo/actions/release\n",
            ("direct", ".forgejo/actions/release/action.yml"):
                "runs:\n  using: composite\n  steps:\n    - shell: sh\n"
                "      run: \"${GITHUB_WORKSPACE}/node_modules/.bin/webgrip-release\" --forge-url x\n",
            ("shared", ".forgejo/workflows/release.yml"):
                f"jobs:\n  release:\n    container:\n      image: harbor.webgrip.dev/webgrip/semantic-release:2.5.0\n"
                f"    steps:\n      - {composite}/semantic-release@v4.0.0\n"
                f"      - {composite}/renovate-trigger@v4.0.0\n",
            ("old-path", ".forgejo/workflows/release.yml"):
                f"jobs:\n  release:\n    steps:\n      - {composite}/semantic-release-monorepo@v3.4.0\n"
                f"      - run: node bin/webgrip-release.cjs\n",
            ("own", ".forgejo/workflows/release.yml"):
                "jobs:\n  release:\n    steps:\n      - run: npx semantic-release\n",
            ("quiet", ".forgejo/workflows/ci.yml"):
                "jobs:\n  test:\n    container:\n      image: harbor.webgrip.dev/webgrip/semantic-release:2.5.0\n"
                "    steps:\n      # semantic-release runs elsewhere; webgrip-release too\n      - run: make test\n",
            ("quiet", ".forgejo/workflows/library.yml"):
                f"on:\n  workflow_call:\njobs:\n  release:\n    steps:\n      - {composite}/semantic-release-monorepo@main\n",
            ("semantic-release-config", ".forgejo/workflows/release.yml"):
                "jobs:\n  release:\n    steps:\n      - run: |\n          node bin/webgrip-release.cjs --forge-url x\n",
        })
        self.world.repositories.append(repository("semantic-release-config"))
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        expected = {"direct": "webgrip-release", "semantic-release-config": "webgrip-release",
                    "shared": "shared semantic-release", "old-path": "monorepo (old path)",
                    "own": "own semantic-release", "quiet": "none"}
        for name, style in expected.items():
            self.assertEqual(self.repository_info(metrics, name)["releases"], style, name)

    def pull(self, number, title, branch="renovate/webgrip", body="", created="2026-10-31T10:00:00Z"):
        sha = f"{number:040x}"
        return {"number": number, "title": title, "body": body, "created_at": created,
                "head": {"ref": branch, "sha": sha}}

    def update(self, metrics, name, package):
        rows = [labels for metric, labels in metrics
                if metric == "repo_config_shared_pin_update" and f'repository="{name}"' in labels
                and f'package="{package}"' in labels]
        self.assertEqual(len(rows), 1, rows)
        return dict(re.findall(r'(\w+)="([^"]*)"', rows[0]))

    def test_each_behind_pin_states_whether_an_update_is_on_its_way(self):
        self.world.tags["workflows"] = ["v4.0.0", "v3.5.1", "v3.4.0"]
        self.world.tags["renovate-config"] = ["v1.19.3", "v1.19.2"]
        self.world.tags["agent-standards"] = ["v0.6.1", "v0.5.3"]
        self.world.tags["semantic-release-config"] = ["v2.5.1", "v2.4.0"]
        image = "harbor.webgrip.dev/webgrip/semantic-release"
        for name in ("homelab-cluster", "erfbeeld", ".profile"):
            self.world.files.update({
                (name, ".forgejo/workflows/ci.yml"):
                    f"jobs:\n  a:\n    container:\n      image: {image}:2.4.0\n"
                    "    steps:\n      - uses: https://forgejo.webgrip.dev/webgrip/workflows/.forgejo/"
                    "composite-actions/semantic-release@v3.4.0\n",
                (name, "renovate.json"): '{"extends": ["local>webgrip/renovate-config:reviewed#v1.19.2"]}',
                (name, "apm.yml"): "dependencies:\n  - git: https://forgejo.webgrip.dev/webgrip/agent-standards.git\n"
                                   "    path: packages/baseline\n    ref: v0.5.3\n",
            })
        table = ("| Package | Type | Update | Change |\n|---|---|---|---|\n"
                 "| [webgrip/workflows](https://forgejo.webgrip.dev/webgrip/workflows) | action | minor | "
                 "`v3.4.0` → `v3.5.1` |\n")
        self.world.pulls["homelab-cluster"] = [
            self.pull(16, "fix(deps): update webgrip dependencies", body=table),
            self.pull(17, "feat(actions): Update dependency webgrip/workflows to v4.0.0",
                      branch="renovate/webgrip-workflows-4.x", created="2026-11-01T09:00:00Z"),
            self.pull(18, "chore(renovate): update dependency webgrip/renovate-config ( v1.19.2 ➔ v1.19.3 )",
                      branch="renovate/webgrip-renovate-config-1.x"),
            self.pull(19, "chore(agents): update agent packages",
                      branch="renovate/agent-package-webgrip-agent-standards",
                      body="| Package | Update | Change |\n|---|---|---|\n| [webgrip/agent-standards]"
                           "(https://forgejo.webgrip.dev/webgrip/agent-standards) | minor | `v0.5.3` → `v0.6.1` |\n"),
            self.pull(20, "chore: update webgrip/workflows to v9.9.9", branch="feature/x"),
        ]
        self.world.check_states.update({f"{17:040x}": "success", f"{18:040x}": "failure", f"{19:040x}": "pending"})
        self.world.issues["homelab-cluster"] = [{"title": "Renovate Dependency Dashboard", "body":
            "## Pending Approval\n\n - [ ] <!-- approve-branch=renovate/webgrip -->ci(actions): Update "
            f"{image} Docker tag ( 2.4.0 ➔ 2.5.1 )\n"}]
        self.world.issues["erfbeeld"] = [{"title": "Renovate Dependency Dashboard", "body":
            "## Rate-Limited\n\n - [ ] <!-- unlimit-branch=renovate/webgrip-workflows-4.x -->feat(actions): Update "
            "dependency webgrip/workflows ( v3.4.0 ➔ v4.0.0 )\n\n## Open\n\n - [ ] <!-- rebase-branch=renovate/x -->"
            "[chore(renovate): update dependency webgrip/renovate-config ( v1.19.2 ➔ v1.19.3 )](pulls/3)\n"}]
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        green = self.update(metrics, "homelab-cluster", "workflows")
        self.assertEqual((green["state"], green["proposed"], green["pull"]), ("pr_green", "v4.0.0", "17"))
        red = self.update(metrics, "homelab-cluster", "renovate-config")
        self.assertEqual((red["state"], red["proposed"], red["pull"]), ("pr_red", "v1.19.3", "18"))
        pending = self.update(metrics, "homelab-cluster", "agent-standards")
        self.assertEqual((pending["state"], pending["proposed"]), ("pr_pending", "v0.6.1"))
        approval = self.update(metrics, "homelab-cluster", "semantic-release-config")
        self.assertEqual((approval["state"], approval["proposed"], approval["pull"]),
                         ("awaits_approval", "v2.5.1", ""))
        queued = self.update(metrics, "erfbeeld", "workflows")
        self.assertEqual((queued["state"], queued["proposed"]), ("queued", "v4.0.0"))
        self.assertEqual(self.update(metrics, "erfbeeld", "renovate-config")["state"], "no_pr")
        self.assertEqual(self.update(metrics, ".profile", "workflows")["state"], "no_pr")
        age = metrics[("repo_config_shared_pin_update_age_seconds",
                       'package="workflows",repository="homelab-cluster"')]
        self.assertGreater(age, 0)
        self.assertNotIn(("repo_config_shared_pin_update_age_seconds",
                          'package="semantic-release-config",repository="homelab-cluster"'), metrics)
        listings = [path for path, _, _ in self.world.requests if path.endswith("/pulls")]
        self.assertEqual(sorted(listings), ["/api/v1/repos/webgrip/.profile/pulls",
                                            "/api/v1/repos/webgrip/erfbeeld/pulls",
                                            "/api/v1/repos/webgrip/homelab-cluster/pulls"])

    def test_a_repository_on_the_newest_releases_reads_no_pull_requests(self):
        self.world.tags["workflows"] = ["v3.4.0"]
        self.world.files[("erfbeeld", ".forgejo/workflows/ci.yml")] = (
            "jobs:\n  a:\n    uses: webgrip/workflows/.forgejo/workflows/tests.yml@v3.4.0\n")
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertFalse([path for path, _, _ in self.world.requests if path.endswith("/pulls")])
        self.assertFalse([labels for metric, labels in metrics if metric == "repo_config_shared_pin_update"])
        dashboards = sorted(path for path, _, _ in self.world.requests if path.endswith("/issues"))
        self.assertEqual(dashboards, ["/api/v1/repos/webgrip/.profile/issues", "/api/v1/repos/webgrip/erfbeeld/issues",
                                      "/api/v1/repos/webgrip/homelab-cluster/issues"])

    def test_unreadable_pull_requests_leave_the_pins_and_skip_the_update_state(self):
        self.give_homelab_cluster_a_delivery_chain()
        self.world.broken_pulls.add("homelab-cluster")
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(self.repository_info(metrics, "homelab-cluster")["workflows"], "v3.2.0 · 2 behind")
        self.assertEqual(metrics[("repo_config_scan_failed", 'repository="homelab-cluster"')], 0)
        self.assertFalse([labels for metric, labels in metrics if metric == "repo_config_shared_pin_update"])
        self.assertIn("could not read the open updates of homelab-cluster", output)

    def control(self, metrics, name):
        rows = [labels for metric, labels in metrics
                if metric == "repo_config_control_state" and f'repository="{name}"' in labels]
        self.assertEqual(len(rows), 1, rows)
        return dict(re.findall(r'(\w+)="([^"]*)"', rows[0]))

    def schedule(self, name):
        for entry in self.world.repositories:
            if entry["name"] == name:
                entry["topics"] = ["renovate"]

    def test_repository_under_renovate_with_an_empty_queue_is_under_control(self):
        self.give_homelab_cluster_a_delivery_chain()
        self.schedule("homelab-cluster")
        self.world.issues["homelab-cluster"] = [
            {"number": 3, "title": "Docs drift report", "body": "## Pending Approval\n\n - [ ] <!-- approve-branch=x -->"},
            dashboard_issue("homelab-cluster", pending_approval(), problems("⚠️ WARN: Merging of PR failed")),
        ]
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        control = self.control(metrics, "homelab-cluster")
        self.assertEqual(control["state"], "under control")
        self.assertEqual(control["fix"], "")
        self.assertEqual(control["dashboard"], "https://forgejo.example/webgrip/homelab-cluster/issues/7")
        self.assertEqual(metrics[("repo_config_renovate_scheduled", 'repository="homelab-cluster"')], 1)
        self.assertEqual(metrics[("repo_config_renovate_dashboard_items",
                                  'repository="homelab-cluster",section="pending_approval"')], 0)
        self.assertEqual(metrics[("repo_config_renovate_dashboard_items",
                                  'repository="homelab-cluster",section="problems"')], 1)
        self.assertEqual(metrics[("repo_config_renovate_dashboard_errors", 'repository="homelab-cluster"')], 0)

    def test_repository_without_a_renovate_config_reads_as_no_renovate(self):
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(self.control(metrics, ".profile")["state"], "no renovate")
        self.assertEqual(metrics[("repo_config_renovate_scheduled", 'repository=".profile"')], 0)

    def test_model_opt_out_is_not_flagged(self):
        self.model_path.write_text(MODEL.replace('    kind: none\n', '    kind: none\n    renovate:\n      absent: true\n', 1))
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.control(self.pushed(), ".profile")["state"], "opted out")

    def test_config_without_the_renovate_topic_reads_as_not_scheduled(self):
        self.give_homelab_cluster_a_delivery_chain()
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        control = self.control(metrics, "homelab-cluster")
        self.assertEqual(control["state"], "not scheduled")
        self.assertIn("renovate topic", control["fix"])
        self.assertEqual(metrics[("repo_config_renovate_scheduled", 'repository="homelab-cluster"')], 0)

    def test_scheduled_repository_without_a_dashboard_reads_as_no_dashboard(self):
        self.give_homelab_cluster_a_delivery_chain()
        self.schedule("homelab-cluster")
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(self.control(metrics, "homelab-cluster")["state"], "no dashboard")
        self.assertNotIn(("repo_config_renovate_dashboard_errors", 'repository="homelab-cluster"'), metrics)

    def test_renovate_error_on_the_dashboard_reads_as_renovate_errors(self):
        self.give_homelab_cluster_a_delivery_chain()
        self.schedule("homelab-cluster")
        self.world.issues["homelab-cluster"] = [dashboard_issue(
            "homelab-cluster", problems("⚠️ WARN: Merging of PR failed", "❌ ERROR: config-validation"),
            pending_approval("lodash-4.x"))]
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(self.control(metrics, "homelab-cluster")["state"], "renovate errors")
        self.assertEqual(metrics[("repo_config_renovate_dashboard_errors", 'repository="homelab-cluster"')], 1)

    def test_pending_approvals_without_a_gate_say_the_gate_is_the_fix(self):
        self.world.tags["renovate-config"] = ["v1.19.2"]
        self.world.files[("erfbeeld", ".renovaterc.json5")] = (
            "{\n  // shared presets only\n  extends: [\"local>webgrip/renovate-config#v1.19.2\"],\n}\n")
        self.schedule("erfbeeld")
        self.world.issues["erfbeeld"] = [dashboard_issue("erfbeeld", pending_approval("a", "b", "c"))]
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(self.repository_info(metrics, "erfbeeld")["renovate_gate"], "presets")
        control = self.control(metrics, "erfbeeld")
        self.assertEqual(control["state"], "parked")
        self.assertIn("3 updates wait for a tick", control["fix"])
        self.assertIn("no gate preset", control["fix"])
        self.assertEqual(metrics[("repo_config_renovate_dashboard_items",
                                  'repository="erfbeeld",section="pending_approval"')], 3)

    def test_pending_approvals_under_a_gate_ask_for_a_tick(self):
        self.give_homelab_cluster_a_delivery_chain()
        self.schedule("homelab-cluster")
        self.world.issues["homelab-cluster"] = [dashboard_issue("homelab-cluster", pending_approval("a"))]
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        control = self.control(self.pushed(), "homelab-cluster")
        self.assertEqual(control["state"], "parked")
        self.assertNotIn("no gate preset", control["fix"])

    def test_pending_approvals_under_a_gate_alias_ask_for_a_tick(self):
        self.world.files[("erfbeeld", "renovate.json")] = '{"extends": ["local>webgrip/renovate-config:profile-site#v1.15.0"]}'
        self.schedule("erfbeeld")
        self.world.issues["erfbeeld"] = [dashboard_issue("erfbeeld", pending_approval("a", "b"))]
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        control = self.control(self.pushed(), "erfbeeld")
        self.assertEqual(control["state"], "parked")
        self.assertIn("2 updates wait for a tick on the Dependency Dashboard", control["fix"])

    def test_shared_pin_three_releases_behind_reads_as_drifting(self):
        self.give_homelab_cluster_a_delivery_chain()
        self.world.tags["workflows"] = ["v3.3.2", "v3.3.1", "v3.3.0", "v3.2.0"]
        self.schedule("homelab-cluster")
        self.world.issues["homelab-cluster"] = [dashboard_issue("homelab-cluster", pending_approval())]
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        control = self.control(self.pushed(), "homelab-cluster")
        self.assertEqual(control["state"], "drifting")
        self.assertIn("3 releases behind", control["fix"])

    def test_unversioned_shared_pin_reads_as_drifting(self):
        self.give_homelab_cluster_a_delivery_chain()
        self.world.files[("homelab-cluster", ".forgejo/workflows/ci.yml")] = (
            "jobs:\n  ci:\n    uses: webgrip/workflows/.forgejo/workflows/agents-check.yml@main\n")
        self.schedule("homelab-cluster")
        self.world.issues["homelab-cluster"] = [dashboard_issue("homelab-cluster", pending_approval())]
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.control(self.pushed(), "homelab-cluster")["state"], "drifting")

    def test_unreadable_issues_keep_the_pins_and_read_as_unread(self):
        self.give_homelab_cluster_a_delivery_chain()
        self.schedule("homelab-cluster")
        self.world.issues_status = 403
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        metrics = self.pushed()
        self.assertEqual(self.repository_info(metrics, "homelab-cluster")["workflows"], "v3.2.0 · 2 behind")
        self.assertEqual(metrics[("repo_config_scan_failed", 'repository="homelab-cluster"')], 0)
        control = self.control(metrics, "homelab-cluster")
        self.assertEqual(control["state"], "unread")
        self.assertIn("read:issue", control["fix"])
        self.assertIn("could not read the Dependency Dashboard of homelab-cluster", output)

    def test_unreadable_repository_reads_as_unread(self):
        self.world.broken_repositories.add("erfbeeld")
        code, output = self.run_inventory()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.control(self.pushed(), "erfbeeld")["state"], "unread")

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
