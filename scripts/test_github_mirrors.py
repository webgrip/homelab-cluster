import base64
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

import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

REPO_ROOT = Path(__file__).resolve().parent.parent
RECONCILER = Path(os.environ.get(
    "RECONCILER_SCRIPT",
    REPO_ROOT / "kubernetes/apps/github-config/github-mirrors/app/github_mirrors.py"))
REAL_MODEL = REPO_ROOT / "kubernetes/apps/repo-config/repo-config/model/repos.yaml"

APP_ID = "424242"
INSTALLATION_ID = "777"
VAULT_TOKEN = "s.fake-openbao-client-token-0001"
FORGEJO_TOKEN = "forgejo-token-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
MODEL_PATH = "kubernetes/apps/repo-config/repo-config/model/repos.yaml"

MODEL = """---
apiVersion: repo-config.webgrip.io/v1alpha1
kind: RepoSet
repos:
  renovate-config:
    forge: forgejo
    profile: protected
    kind: package
  telemetry-service:
    forge: forgejo
    profile: protected
    kind: package
  ledgerflow:
    forge: forgejo
    profile: baseline
    settings:
      archived: true
  webgrip/ledgerflow:
    forge: github
    profile: baseline
    mirror_of: ledgerflow
    settings:
      archived: true
  webgrip/renovate-config:
    forge: github
    profile: baseline
    mirror_of: renovate-config
  webgrip/telemetry-service:
    forge: github
    profile: baseline
    mirror_of: telemetry-service
"""


def installation_token(repository):
    return f"ghs_fakeInstallationTokenFor{repository.replace('.', '').replace('-', '')}0123456789"


def jwt_parts(token):
    header, payload, signature = token.split(".")
    pad = lambda part: part + "=" * (-len(part) % 4)
    return (f"{header}.{payload}".encode(), json.loads(base64.urlsafe_b64decode(pad(payload))),
            base64.urlsafe_b64decode(pad(signature)))


def release(release_id, tag, created_at, **extra):
    return {"id": release_id, "tag_name": tag, "name": f"Release {tag}", "body": f"notes for {tag}",
            "draft": False, "prerelease": False, "created_at": created_at, "assets": [], **extra}


class FakeWorld:
    def __init__(self):
        self.rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.app_secret = {"app_id": APP_ID, "installation_id": INSTALLATION_ID,
                           "private_key": self.rsa_key.private_bytes(
                               serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                               serialization.NoEncryption()).decode()}
        self.model = MODEL
        self.attachments = {"att-1": b"binary-asset-payload-0123456789"}
        self.forgejo = {
            "renovate-config": {"default_branch": "main", "head": "9163c948", "tags": ["v1.0.0", "v1.1.0"],
                                "releases": [release(11, "v1.0.0", "2026-01-01T00:00:00Z"),
                                             release(12, "v1.1.0", "2026-02-01T00:00:00Z")],
                                "push_mirrors": [{"remote_address": "https://github.com/webgrip/renovate-config.git",
                                                  "last_update": "2026-10-27T16:00:00Z", "last_error": "",
                                                  "interval": "8h0m0s"}]},
            "telemetry-service": {"default_branch": "main", "head": "15ed6273", "tags": ["v0.1.0"],
                                  "releases": [release(21, "v0.1.0", "2026-03-01T00:00:00Z")],
                                  "push_mirrors": [{"remote_address": "https://github.com/webgrip/telemetry-service",
                                                    "last_update": "2026-10-27T16:00:00Z", "last_error": "",
                                                    "interval": "8h0m0s"}]},
            "ledgerflow": {"default_branch": "main", "head": "35a599b6", "tags": [], "releases": [],
                           "push_mirrors": []},
            "discord-moon": {"default_branch": "main", "head": "3a0e8590", "tags": [], "releases": [],
                             "push_mirrors": [{"remote_address": "https://github.com/webgrip/discord-moon.git",
                                               "last_update": "", "last_error": "", "interval": "8h0m0s"}]},
            "babyagi": {"default_branch": "main", "head": "48f28181", "tags": [], "releases": [], "mirror": True,
                        "push_mirrors": []},
        }
        self.github = {
            "renovate-config": {"default_branch": "main", "head": "9163c948", "tags": ["v1.0.0", "v1.1.0"],
                                "releases": [release(5001, "v1.0.0", "2026-01-01T00:00:00Z")], "archived": False},
            "telemetry-service": {"default_branch": "main", "head": "15ed6273", "tags": ["v0.1.0"],
                                  "releases": [release(6001, "v0.1.0", "2026-03-01T00:00:00Z"),
                                               release(6002, "v0.0.9", "2025-12-01T00:00:00Z")],
                                  "archived": False},
            "ledgerflow": {"default_branch": "main", "head": "35a599b6", "tags": [], "releases": [], "archived": True},
            "discord-moon": {"default_branch": "main", "head": "3a0e8590", "tags": [], "releases": [], "archived": True},
            "babyagi": {"default_branch": "main", "head": "48f28181", "tags": [], "releases": [], "archived": True,
                        "fork": True},
        }
        self.installed = {"renovate-config", "telemetry-service"}
        self.vault_secret_present = True
        self.upload_status = 201
        self.next_release_id = 9000
        self.calls = []
        self.token_requests = []
        self.created = []
        self.patched = []
        self.deleted = []
        self.uploads = []
        self.metrics = []
        self.preexisting_ids = {r["id"] for repo in self.github.values() for r in repo["releases"]}


def forgejo_release_view(entry):
    view = dict(entry)
    view["assets"] = [dict(asset) for asset in entry.get("assets", [])]
    return view


def handler_for(world):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def body(self):
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        def reply(self, status, payload=None, raw=None):
            data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else b"")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def paged(self, items, query, size_key, default_size):
            size = int(query.get(size_key, [default_size])[0])
            page = int(query.get("page", ["1"])[0])
            return self.reply(200, items[(page - 1) * size: page * size])

        def handle_any(self, method):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            body = self.body()
            world.calls.append(f"{method} {path}")

            if method == "POST" and path == "/v1/auth/kubernetes/login":
                request = json.loads(body)
                if request.get("role") != "github-mirrors" or request.get("jwt") != "fake-sa-jwt":
                    return self.reply(403, {"errors": ["permission denied"]})
                return self.reply(200, {"auth": {"client_token": VAULT_TOKEN}})
            if method == "GET" and path == "/v1/secret/data/github/webgrip-app":
                if self.headers.get("X-Vault-Token") != VAULT_TOKEN:
                    return self.reply(403, {"errors": ["permission denied"]})
                if not world.vault_secret_present:
                    return self.reply(404, {"errors": []})
                return self.reply(200, {"data": {"data": world.app_secret}})

            if path.startswith("/forgejo/"):
                return self.forgejo(method, path.removeprefix("/forgejo"), query)
            if path.startswith("/github/") or path.startswith("/uploads/"):
                return self.github(method, path, query, body)
            if method == "POST" and path.startswith("/api/v1/import/prometheus"):
                world.metrics.append(body.decode())
                return self.reply(204)
            return self.reply(500, {"message": f"unexpected {method} {path}"})

        def forgejo(self, method, path, query):
            authorised = self.headers.get("Authorization") == f"token {FORGEJO_TOKEN}"
            if path.startswith("/attachments/"):
                return self.reply(200, raw=world.attachments[path.rsplit("/", 1)[-1]])
            if path == f"/api/v1/repos/webgrip/homelab-cluster/raw/{MODEL_PATH}":
                return self.reply(200, raw=world.model.encode())
            if path == "/api/v1/orgs/webgrip/repos":
                repos = [{"name": name, "mirror": repo.get("mirror", False)} for name, repo in sorted(world.forgejo.items())]
                return self.paged(repos, query, "limit", "30")
            match = re.fullmatch(r"/api/v1/repos/webgrip/([^/]+)(/.*)?", path)
            if not match or match.group(1) not in world.forgejo:
                return self.reply(404, {})
            repo = world.forgejo[match.group(1)]
            rest = match.group(2) or ""
            if rest == "":
                return self.reply(200, {"name": match.group(1), "default_branch": repo["default_branch"]})
            if rest == f"/branches/{repo['default_branch']}":
                return self.reply(200, {"commit": {"id": repo["head"]}})
            if rest == "/tags":
                return self.paged([{"name": tag} for tag in repo["tags"]], query, "limit", "30")
            if rest == "/releases":
                return self.paged([forgejo_release_view(r) for r in repo["releases"]], query, "limit", "30")
            if rest == "/push_mirrors":
                if not authorised:
                    return self.reply(403, {"message": "token required"})
                return self.reply(200, repo["push_mirrors"])
            return self.reply(404, {})

        def github(self, method, path, query, body):
            if method == "POST" and path == f"/github/app/installations/{INSTALLATION_ID}/access_tokens":
                signing_input, claims, signature = jwt_parts(self.headers["Authorization"].removeprefix("Bearer "))
                world.rsa_key.public_key().verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
                if claims.get("iss") != APP_ID:
                    return self.reply(401, {"message": "bad claims"})
                request = json.loads(body)
                world.token_requests.append(request)
                repositories = request.get("repositories") or []
                if len(repositories) != 1 or repositories[0] not in world.installed:
                    return self.reply(422, {"message": "not installed"})
                return self.reply(201, {"token": installation_token(repositories[0])})
            if method == "DELETE" and path == "/github/installation/token":
                return self.reply(204)
            if method == "GET" and path == "/github/orgs/webgrip/repos":
                if self.headers.get("Authorization"):
                    return self.reply(400, {"message": "the public listing is read without a token"})
                repos = [{"name": name, "fork": repo.get("fork", False), "archived": repo["archived"]}
                         for name, repo in sorted(world.github.items())]
                return self.paged(repos, query, "per_page", "30")
            upload = re.fullmatch(r"/uploads/repos/webgrip/([^/]+)/releases/(\d+)/assets", path)
            if upload:
                if self.headers.get("Authorization") != f"Bearer {installation_token(upload.group(1))}":
                    return self.reply(401, {})
                world.uploads.append({"repo": upload.group(1), "release": int(upload.group(2)),
                                      "name": query["name"][0], "data": body})
                return self.reply(world.upload_status, {"id": 1})
            match = re.fullmatch(r"/github/repos/webgrip/([^/]+)(/.*)?", path)
            if not match or match.group(1) not in world.github:
                return self.reply(404, {})
            name = match.group(1)
            if self.headers.get("Authorization") != f"Bearer {installation_token(name)}":
                return self.reply(401, {"message": "Bad credentials"})
            repo = world.github[name]
            rest = match.group(2) or ""
            if method == "GET" and rest == "":
                return self.reply(200, {"name": name, "default_branch": repo["default_branch"], "archived": repo["archived"]})
            if method == "GET" and rest == f"/branches/{repo['default_branch']}":
                return self.reply(200, {"commit": {"sha": repo["head"]}})
            if method == "GET" and rest == "/tags":
                return self.paged([{"name": tag} for tag in repo["tags"]], query, "per_page", "30")
            if method == "GET" and rest == "/releases":
                return self.paged(repo["releases"], query, "per_page", "30")
            if method == "POST" and rest == "/releases":
                request = json.loads(body)
                world.created.append({"repo": name, **request})
                if any(r["tag_name"] == request["tag_name"] for r in repo["releases"]):
                    return self.reply(422, {"message": "already_exists"})
                if request["tag_name"] not in repo["tags"]:
                    repo["tags"].append(request["tag_name"])
                world.next_release_id += 1
                created = {"id": world.next_release_id, "tag_name": request["tag_name"], "name": request["name"],
                           "body": request["body"], "draft": request["draft"], "prerelease": request["prerelease"],
                           "upload_url": f"http://{self.headers['Host']}/uploads/repos/webgrip/{name}/releases/{world.next_release_id}/assets{{?name,label}}"}
                repo["releases"].append(created)
                return self.reply(201, created)
            release_match = re.fullmatch(r"/releases/(\d+)", rest)
            if release_match:
                release_id = int(release_match.group(1))
                if method == "PATCH":
                    world.patched.append({"repo": name, "id": release_id, **json.loads(body)})
                    for r in repo["releases"]:
                        if r["id"] == release_id:
                            r.update({key: value for key, value in json.loads(body).items() if key == "draft"})
                    return self.reply(200, {"id": release_id})
                if method == "DELETE":
                    world.deleted.append({"repo": name, "id": release_id})
                    repo["releases"] = [r for r in repo["releases"] if r["id"] != release_id]
                    return self.reply(204)
            return self.reply(404, {})

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")

        def do_PATCH(self):
            self.handle_any("PATCH")

        def do_DELETE(self):
            self.handle_any("DELETE")

    return Handler


def parse_metrics(text):
    samples = {}
    for line in text.splitlines():
        match = re.fullmatch(r"(\w+)\{(.*)\} (\S+)", line)
        if match:
            labels = tuple(sorted(re.findall(r'(\w+)="([^"]*)"', match.group(2))))
            samples[(match.group(1), labels)] = float(match.group(3))
    return samples


class ReconcilerTest(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.world))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.tmp = tempfile.TemporaryDirectory()
        self.sa_token = Path(self.tmp.name, "sa-token")
        self.sa_token.write_text("fake-sa-jwt")
        self.forgejo_token = Path(self.tmp.name, "FORGEJO_TOKEN")
        self.forgejo_token.write_text(FORGEJO_TOKEN + "\n")
        self.budget = "25"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def run_reconciler(self):
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "FORGEJO_URL": f"{self.url}/forgejo", "FORGEJO_TOKEN_PATH": str(self.forgejo_token),
            "GITHUB_API": f"{self.url}/github", "VAULT_ADDR": self.url, "VAULT_ROLE": "github-mirrors",
            "APP_SECRET_PATH": "github/webgrip-app", "SERVICE_ACCOUNT_TOKEN_PATH": str(self.sa_token),
            "SCRATCH_DIR": self.tmp.name, "MAX_RELEASE_COPIES_PER_RUN": self.budget,
            "METRICS_URL": f"{self.url}/api/v1/import/prometheus?extra_label=job=github-mirrors",
        }
        result = subprocess.run([sys.executable, "-I", str(RECONCILER)], env=environment, capture_output=True,
                                text=True, timeout=120)
        self.output = result.stdout + result.stderr
        self.metrics = parse_metrics("".join(self.world.metrics))
        return result.returncode

    def metric(self, name, **labels):
        return self.metrics.get((f"github_mirror_{name}", tuple(sorted(labels.items()))))

    def assert_no_preexisting_release_touched(self):
        touched = {entry["id"] for entry in self.world.patched + self.world.deleted}
        self.assertFalse(touched & self.world.preexisting_ids, f"pre-existing GitHub releases changed: {touched}")
        recreated = [entry for entry in self.world.created
                     if entry["tag_name"] in {"v1.0.0", "v0.1.0", "v0.0.9"}]
        self.assertEqual(recreated, [], "a release already on GitHub was created again")

    def test_missing_release_is_copied_with_assets_and_flags(self):
        self.world.forgejo["renovate-config"]["releases"][1]["assets"] = [
            {"name": "bundle.tar.gz", "size": 31,
             "browser_download_url": "https://forgejo.webgrip.dev/attachments/att-1"}]
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual([(c["repo"], c["tag_name"], c["draft"]) for c in self.world.created],
                         [("renovate-config", "v1.1.0", True)])
        self.assertEqual(self.world.created[0]["body"], "notes for v1.1.0")
        self.assertEqual(self.world.created[0]["name"], "Release v1.1.0")
        self.assertNotIn("target_commitish", self.world.created[0])
        self.assertEqual([(u["name"], u["data"]) for u in self.world.uploads],
                         [("bundle.tar.gz", b"binary-asset-payload-0123456789")])
        self.assertEqual([(p["draft"], p["make_latest"]) for p in self.world.patched], [(False, "true")])
        self.assertEqual(self.metric("releases_missing_before", repository="renovate-config"), 1)
        self.assertEqual(self.metric("releases_missing", repository="renovate-config"), 0)
        self.assertEqual(self.metric("releases_copied", repository="renovate-config"), 1)
        self.assertEqual(self.metric("head_match", repository="renovate-config"), 1)
        self.assertEqual(self.metric("tags_missing", repository="renovate-config"), 0)
        self.assertIsNotNone(self.metric("reconciler_last_success_timestamp_seconds"))
        self.assert_no_preexisting_release_touched()

    def test_extra_github_releases_are_counted_and_never_changed(self):
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual(self.metric("releases_extra", repository="telemetry-service"), 1)
        self.assertEqual(self.metric("releases_missing", repository="telemetry-service"), 0)
        self.assertEqual([c for c in self.world.created if c["repo"] == "telemetry-service"], [])
        self.assert_no_preexisting_release_touched()

    def test_release_waits_until_its_tag_reached_github(self):
        self.world.forgejo["renovate-config"]["tags"].append("v1.2.0")
        self.world.forgejo["renovate-config"]["releases"].append(release(13, "v1.2.0", "2026-03-01T00:00:00Z"))
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual([c["tag_name"] for c in self.world.created], ["v1.1.0"])
        self.assertEqual(self.metric("tags_missing", repository="renovate-config"), 1)
        self.assertEqual(self.metric("releases_missing", repository="renovate-config"), 1)
        self.assertNotIn("v1.2.0", self.world.github["renovate-config"]["tags"])

    def test_older_copy_is_not_marked_latest(self):
        self.world.forgejo["renovate-config"]["tags"].append("v1.2.0")
        self.world.github["renovate-config"]["tags"].append("v1.2.0")
        self.world.forgejo["renovate-config"]["releases"].append(release(13, "v1.2.0", "2026-03-01T00:00:00Z"))
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual([c["tag_name"] for c in self.world.created], ["v1.1.0", "v1.2.0"])
        self.assertEqual([p["make_latest"] for p in self.world.patched], ["false", "true"])

    def test_copy_budget_copies_the_oldest_first(self):
        self.budget = "1"
        self.world.forgejo["renovate-config"]["tags"].append("v1.2.0")
        self.world.github["renovate-config"]["tags"].append("v1.2.0")
        self.world.forgejo["renovate-config"]["releases"].insert(0, release(13, "v1.2.0", "2026-03-01T00:00:00Z"))
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual([c["tag_name"] for c in self.world.created], ["v1.1.0"])
        self.assertEqual(self.metric("releases_missing", repository="renovate-config"), 1)

    def test_draft_release_stays_a_draft(self):
        self.world.forgejo["renovate-config"]["releases"][1]["draft"] = True
        self.world.forgejo["renovate-config"]["releases"][1]["prerelease"] = True
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual([(c["draft"], c["prerelease"]) for c in self.world.created], [(True, True)])
        self.assertEqual(self.world.patched, [])

    def test_failed_asset_upload_discards_only_the_new_draft(self):
        self.world.upload_status = 500
        self.world.forgejo["renovate-config"]["releases"][1]["assets"] = [
            {"name": "bundle.tar.gz", "size": 31,
             "browser_download_url": "https://forgejo.webgrip.dev/attachments/att-1"}]
        self.assertEqual(self.run_reconciler(), 0, self.output)
        created_ids = {r["id"] for r in self.world.github["renovate-config"]["releases"]}
        self.assertEqual(created_ids, {5001})
        self.assertEqual(len(self.world.deleted), 1)
        self.assertEqual(self.metric("releases_copy_failed", repository="renovate-config"), 1)
        self.assertEqual(self.metric("releases_missing", repository="renovate-config"), 1)
        self.assert_no_preexisting_release_touched()

    def test_installation_tokens_are_scoped_to_one_repository_and_contents(self):
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertTrue(self.world.token_requests)
        for request in self.world.token_requests:
            self.assertEqual(len(request["repositories"]), 1)
            self.assertEqual(request["permissions"], {"contents": "write"})
        self.assertNotIn(installation_token("renovate-config"), self.output)
        self.assertNotIn(FORGEJO_TOKEN, self.output)

    def test_archived_and_untracked_repositories_are_left_alone(self):
        self.assertEqual(self.run_reconciler(), 0, self.output)
        requested = {request["repositories"][0] for request in self.world.token_requests}
        self.assertEqual(requested, {"renovate-config", "telemetry-service"})
        self.assertIsNone(self.metric("tracked", repository="ledgerflow"))

    def test_absent_app_credentials_exit_zero_and_touch_nothing_on_github(self):
        self.world.vault_secret_present = False
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual(self.metric("credentials_present", credential="github_app"), 0)
        self.assertEqual(self.metric("model_tracked_mirrors"), 2)
        self.assertFalse([call for call in self.world.calls if call.split(" ")[1].startswith("/github/")])

    def test_push_mirror_status_is_exported(self):
        self.world.forgejo["renovate-config"]["push_mirrors"][0]["last_error"] = "authentication required"
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual(self.metric("error", repository="renovate-config"), 1)
        self.assertEqual(self.metric("error", repository="telemetry-service"), 0)
        self.assertEqual(self.metric("interval_seconds", repository="renovate-config"), 28800)
        self.assertEqual(self.metric("last_update_timestamp_seconds", repository="renovate-config"), 1793116800)
        self.assertEqual(self.metric("push_status_known", repository="renovate-config"), 1)

    def test_push_mirror_status_is_unknown_without_a_forgejo_token(self):
        self.forgejo_token.write_text("")
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual(self.metric("credentials_present", credential="forgejo_token"), 0)
        self.assertEqual(self.metric("push_status_known", repository="renovate-config"), 0)
        self.assertIsNone(self.metric("error", repository="renovate-config"))
        self.assertEqual(self.metric("model_drift_known", forge="forgejo"), 0)
        self.assertEqual(self.metric("head_match", repository="renovate-config"), 1)

    def test_head_mismatch_is_reported(self):
        self.world.github["renovate-config"]["head"] = "01114137"
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual(self.metric("head_match", repository="renovate-config"), 0)
        self.assertEqual(self.metric("head_match", repository="telemetry-service"), 1)

    def test_a_repository_outside_the_installation_is_reported_and_the_rest_checked(self):
        self.world.installed.discard("telemetry-service")
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual(self.metric("app_access", repository="telemetry-service"), 0)
        self.assertEqual(self.metric("app_access", repository="renovate-config"), 1)
        self.assertEqual(self.metric("releases_copied", repository="renovate-config"), 1)

    def test_model_drift_on_both_forges(self):
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual(self.metric("model_drift", forge="github", repository="discord-moon"), 1)
        self.assertEqual(self.metric("model_drift", forge="github", repository="renovate-config"), 0)
        self.assertIsNone(self.metric("model_drift", forge="github", repository="babyagi"))
        self.assertEqual(self.metric("model_drift", forge="forgejo", repository="discord-moon"), 1)
        self.assertEqual(self.metric("model_drift", forge="forgejo", repository="renovate-config"), 0)
        self.assertEqual(self.metric("model_drift_known", forge="github"), 1)
        self.assertEqual(self.metric("model_drift_known", forge="forgejo"), 1)

    def test_archived_entries_close_drift_without_being_tracked(self):
        self.world.forgejo["webgrip.nl"] = {"default_branch": "main", "head": "03f807e2", "tags": [], "releases": [],
                                            "push_mirrors": []}
        self.world.github["webgrip.nl"] = {"default_branch": "main", "head": "45e315e0", "tags": [], "releases": [],
                                           "archived": True}
        self.world.model += ("  webgrip/discord-moon:\n    forge: github\n    profile: baseline\n    managed: false\n"
                             "    mirror_of: discord-moon\n    settings:\n      archived: true\n"
                             "  webgrip/webgrip.nl:\n    forge: github\n    profile: baseline\n    managed: false\n"
                             "    settings:\n      archived: true\n")
        self.assertEqual(self.run_reconciler(), 0, self.output)
        self.assertEqual(self.metric("model_drift", forge="github", repository="discord-moon"), 0)
        self.assertEqual(self.metric("model_drift", forge="forgejo", repository="discord-moon"), 0)
        self.assertEqual(self.metric("model_drift", forge="github", repository="webgrip.nl"), 0)
        self.assertIsNone(self.metric("tracked", repository="discord-moon"))
        self.assertIsNone(self.metric("tracked", repository="webgrip.nl"))
        self.assertIsNone(self.metric("head_match", repository="webgrip.nl"))
        requested = {request["repositories"][0] for request in self.world.token_requests}
        self.assertEqual(requested, {"renovate-config", "telemetry-service"})

    def test_a_broken_read_fails_the_run_but_still_reports(self):
        del self.world.github["telemetry-service"]
        self.assertEqual(self.run_reconciler(), 1, self.output)
        self.assertEqual(self.metric("check_ok", repository="telemetry-service"), 0)
        self.assertEqual(self.metric("check_ok", repository="renovate-config"), 1)
        self.assertIsNone(self.metric("reconciler_last_success_timestamp_seconds"))

    def test_model_parser_matches_yaml_on_the_real_model(self):
        sys.path.insert(0, str(RECONCILER.parent))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("github_mirrors_under_test", RECONCILER)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        text = REAL_MODEL.read_text()
        repos = yaml.safe_load(text)["repos"]
        expected = sorted((key.split("/", 1)[1], repo["mirror_of"]) for key, repo in repos.items()
                          if repo["forge"] == "github" and key.startswith("webgrip/") and "mirror_of" in repo
                          and not (repo.get("settings") or {}).get("archived", False))
        self.assertEqual(module.tracked_mirrors(module.model_github_entries(text), "webgrip"), expected)
        self.assertGreaterEqual(len(expected), 10)
        expected_keys = sorted(key for key, repo in repos.items() if repo["forge"] == "github")
        self.assertEqual(sorted(module.model_github_entries(text)), expected_keys)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *sys.argv[1:]], verbosity=1)
