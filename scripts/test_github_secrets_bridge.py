import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from nacl.public import PrivateKey, SealedBox

REPO_ROOT = Path(__file__).resolve().parent.parent
BRIDGE = Path(os.environ.get(
    "BRIDGE_SCRIPT",
    REPO_ROOT / "kubernetes/apps/github-secrets-bridge/github-secrets-bridge/app/github_secrets_bridge.py"))
BRIDGE_APP_DIR = Path(os.environ.get(
    "BRIDGE_APP_DIR", REPO_ROOT / "kubernetes/apps/github-secrets-bridge/github-secrets-bridge/app"))
BRIDGE_POLICY = Path(os.environ.get(
    "BRIDGE_POLICY", REPO_ROOT / "kubernetes/apps/security/openbao/bootstrap/github-secrets-bridge.hcl"))

PLOEG_APP = {"path": "github/ploeg-hq-app", "app_id": "424242", "installation_id": "777",
             "token": "ghs_fakeInstallationToken0123456789abcd"}
UNFOLD_APP = {"path": "github/unfold-hq-app", "app_id": "535353", "installation_id": "888",
              "token": "ghs_fake-unfold-installation-token-0002"}
APPS = (PLOEG_APP, UNFOLD_APP)
OWNER = "ploeg-hq"
REPOSITORY = "ploeg"
SECRET_NAME = "RELEASE_CONSUMER_TOKEN_FORGEJO"
VAULT_TOKEN = "s.fake-openbao-client-token-0001"
CLOUDFLARE_TOKEN = "fake-cloudflare-deploy-value-0003"
CLOUDFLARE_ACCOUNT = "fake-cloudflare-account-0004"
BOT_APP_ID = "9191919"


def jwt_parts(token):
    header, payload, signature = token.split(".")
    pad = lambda part: part + "=" * (-len(part) % 4)
    return (f"{header}.{payload}".encode(), json.loads(base64.urlsafe_b64decode(pad(payload))),
            base64.urlsafe_b64decode(pad(signature)))


def rsa_pem(key, private_format=serialization.PrivateFormat.TraditionalOpenSSL):
    return key.private_bytes(serialization.Encoding.PEM, private_format, serialization.NoEncryption()).decode()


class FakeRepository:
    def __init__(self):
        self.key = PrivateKey.generate()
        self.secrets = {}
        self.versions = 0
        self.decrypted = {}
        self.put_status = 201

    def bump(self, name, value):
        self.versions += 1
        self.secrets[name] = {"name": name, "updated_at": f"2026-10-18T10:{self.versions:02d}:00Z"}
        self.decrypted.setdefault(name, []).append(value)


class FakeWorld:
    def __init__(self):
        self.rsa_keys = {app["app_id"]: rsa.generate_private_key(public_exponent=65537, key_size=2048) for app in APPS}
        self.kv = {app["path"]: {"app_id": app["app_id"], "installation_id": app["installation_id"],
                                 "private_key": rsa_pem(self.rsa_keys[app["app_id"]])} for app in APPS}
        self.bot_private_key = rsa_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))
        self.kv["github/unfold-hq-bot-app"] = {"app_id": BOT_APP_ID, "installation_id": "999",
                                               "private_key": self.bot_private_key}
        self.kv["cloudflare/deploy"] = {"CLOUDFLARE_API_TOKEN": CLOUDFLARE_TOKEN,
                                        "CLOUDFLARE_ACCOUNT_ID": CLOUDFLARE_ACCOUNT}
        self.every_private_key = [entry["private_key"] for entry in self.kv.values() if "private_key" in entry]
        self.kv_status = {}
        self.repositories = {"ploeg-hq/ploeg": FakeRepository(), "unfold-hq/unfold": FakeRepository()}
        self.configmaps = {}
        self.metrics = []
        self.calls = []
        self.token_requests = []
        self.revoked = 0
        self.jwt_errors = []

    @property
    def ploeg(self):
        return self.repositories["ploeg-hq/ploeg"]

    @property
    def decrypted_values(self):
        return self.ploeg.decrypted.get(SECRET_NAME, [])

    @property
    def github_secret(self):
        return self.ploeg.secrets.get(SECRET_NAME)

    def every_secret_value(self):
        return [value for repository in self.repositories.values()
                for values in repository.decrypted.values() for value in values]


def handler_for(world):
    installations = {app["installation_id"]: app for app in APPS}
    owners_by_token = {PLOEG_APP["token"]: "ploeg-hq", UNFOLD_APP["token"]: "unfold-hq"}
    apps_by_token = {app["token"]: app for app in APPS}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def body(self):
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        def reply(self, status, payload=None):
            raw = json.dumps(payload).encode() if payload is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def bearer(self):
            return (self.headers.get("Authorization") or "").removeprefix("Bearer ")

        def openbao(self, method, path, body):
            if method == "POST" and path == "/v1/auth/kubernetes/login":
                request = json.loads(body)
                if request.get("role") != "github-secrets-bridge" or request.get("jwt") != "fake-sa-jwt":
                    return self.reply(403, {"errors": ["permission denied"]})
                return self.reply(200, {"auth": {"client_token": VAULT_TOKEN}})
            kv_path = path.removeprefix("/v1/secret/data/")
            if self.headers.get("X-Vault-Token") != VAULT_TOKEN:
                return self.reply(403, {"errors": ["permission denied"]})
            if world.kv_status.get(kv_path, 200) != 200:
                return self.reply(world.kv_status[kv_path], {"errors": []})
            if kv_path not in world.kv:
                return self.reply(404, {"errors": []})
            return self.reply(200, {"data": {"data": world.kv[kv_path]}})

        def installation_token(self, installation_id, body):
            app = installations.get(installation_id)
            if app is None:
                return self.reply(404, {"message": "no installation"})
            signing_input, claims, signature = jwt_parts(self.bearer())
            try:
                world.rsa_keys[app["app_id"]].public_key().verify(
                    signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
            except Exception:
                world.jwt_errors.append("bad signature")
                return self.reply(401, {"message": "bad jwt"})
            if claims.get("iss") != app["app_id"] or claims["exp"] - claims["iat"] > 600:
                world.jwt_errors.append("bad claims")
                return self.reply(401, {"message": "bad claims"})
            world.token_requests.append({"installation": installation_id, **json.loads(body)})
            return self.reply(201, {"token": app["token"]})

        def repository_call(self, method, owner, name, rest, body):
            repository = world.repositories.get(f"{owner}/{name}")
            if repository is None or owners_by_token.get(self.bearer()) != owner:
                return self.reply(401, {"message": "Bad credentials"})
            app = apps_by_token[self.bearer()]
            granted = [request for request in world.token_requests if request["installation"] == app["installation_id"]]
            if not granted or granted[-1].get("repositories") != [name]:
                return self.reply(403, {"message": "token not scoped to this repository"})
            if method == "GET" and rest == "/actions/secrets/public-key":
                return self.reply(200, {"key_id": "kid-1", "key": base64.b64encode(bytes(repository.key.public_key)).decode()})
            secret = re.fullmatch(r"/actions/secrets/([A-Z0-9_]+)", rest)
            if secret and method == "GET":
                found = repository.secrets.get(secret.group(1))
                return self.reply(200, found) if found else self.reply(404, {"message": "Not Found"})
            if secret and method == "PUT":
                if repository.put_status >= 300:
                    return self.reply(repository.put_status, {"message": "boom"})
                request = json.loads(body)
                if request.get("key_id") != "kid-1":
                    return self.reply(422, {"message": "key_id"})
                plaintext = SealedBox(repository.key).decrypt(base64.b64decode(request["encrypted_value"])).decode()
                created = secret.group(1) not in repository.secrets
                repository.bump(secret.group(1), plaintext)
                return self.reply(201 if created else 204)
            return self.reply(500, {"message": f"unexpected {method} {rest}"})

        def configmap_call(self, method, path, body):
            if self.headers.get("Authorization") != "Bearer fake-sa-jwt":
                return self.reply(401, {})
            name = path.rsplit("/", 1)[-1]
            if method == "GET":
                return self.reply(200, world.configmaps[name]) if name in world.configmaps else self.reply(404, {})
            manifest = json.loads(body)
            if method == "PUT":
                if manifest["metadata"]["name"] not in world.configmaps:
                    return self.reply(404, {})
                world.configmaps[manifest["metadata"]["name"]] = manifest
                return self.reply(200, manifest)
            world.configmaps[manifest["metadata"]["name"]] = manifest
            return self.reply(201, manifest)

        def handle_any(self, method):
            path = self.path
            body = self.body()
            world.calls.append(f"{method} {path}")
            if path == "/v1/auth/kubernetes/login" or (method == "GET" and path.startswith("/v1/secret/data/")):
                return self.openbao(method, path, body)
            token_request = re.fullmatch(r"/app/installations/(\d+)/access_tokens", path)
            if method == "POST" and token_request:
                return self.installation_token(token_request.group(1), body)
            if method == "DELETE" and path == "/installation/token":
                world.revoked += 1
                return self.reply(204)
            repo_call = re.fullmatch(r"/repos/([^/]+)/([^/]+)(/.*)", path)
            if repo_call:
                return self.repository_call(method, *repo_call.groups(), body)
            if path.startswith("/api/v1/namespaces/github-secrets-bridge/configmaps"):
                return self.configmap_call(method, path, body)
            if method == "POST" and path.startswith("/api/v1/import/prometheus"):
                world.metrics.append(body.decode())
                return self.reply(204)
            return self.reply(500, {"message": f"unexpected {method} {path}"})

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")

        def do_PUT(self):
            self.handle_any("PUT")

        def do_DELETE(self):
            self.handle_any("DELETE")

    return Handler


def target(owner, repository, secret, app, source, state):
    return {"owner": owner, "repository": repository, "secret": secret, "app_secret_path": app["path"],
            "source": source, "state_configmap": state}


def ploeg_bot_target(field, secret):
    return target("ploeg-hq", "ploeg", secret, PLOEG_APP, {"openbao": "github/unfold-hq-bot-app", "property": field},
                  f"state-ploeg-{field.replace('_', '-')}")


def unfold_cloudflare_target(field):
    return target("unfold-hq", "unfold", field, UNFOLD_APP, {"openbao": "cloudflare/deploy", "property": field},
                  f"state-unfold-{field.lower().replace('_', '-')}")


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.world))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.tmp = tempfile.TemporaryDirectory()
        self.sa_token = Path(self.tmp.name, "sa-token")
        self.sa_token.write_text("fake-sa-jwt")
        self.source = Path(self.tmp.name, "source")
        self.targets_file = Path(self.tmp.name, "targets.json")
        self.outputs = []
        self.set_source("forgejo-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.targets = [self.release_target()]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def release_target(self):
        return target(OWNER, REPOSITORY, SECRET_NAME, PLOEG_APP, {"file": str(self.source)},
                      "github-secrets-bridge-state")

    def set_source(self, value):
        self.source_value = value
        self.source.write_text(value + "\n")

    def run_bridge(self):
        self.targets_file.write_text(json.dumps(self.targets))
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "TARGETS_PATH": str(self.targets_file),
            "GITHUB_API": self.url, "VAULT_ADDR": self.url, "VAULT_ROLE": "github-secrets-bridge",
            "SERVICE_ACCOUNT_TOKEN_PATH": str(self.sa_token), "KUBERNETES_API": self.url,
            "KUBERNETES_CA_PATH": "", "NAMESPACE": "github-secrets-bridge",
            "METRICS_URL": f"{self.url}/api/v1/import/prometheus?extra_label=job=github-secrets-bridge",
        }
        result = subprocess.run([sys.executable, "-I", str(BRIDGE)], env=environment, capture_output=True,
                                text=True, timeout=120)
        self.outputs.append(result.stdout + result.stderr)
        return result

    def puts(self, owner=OWNER):
        return [call for call in self.world.calls if call.startswith(f"PUT /repos/{owner}/")]

    def metric(self, name, secret):
        lines = [line for push in self.world.metrics for line in push.splitlines()
                 if line.startswith(f"github_secrets_bridge_{name}{{") and f'secret="{secret}"' in line]
        return lines[-1].rsplit(" ", 1)[1] if lines else None

    def assert_nothing_sensitive_escaped(self):
        sensitive = [self.source_value, VAULT_TOKEN, CLOUDFLARE_TOKEN, CLOUDFLARE_ACCOUNT]
        sensitive += [app["token"] for app in APPS]
        for pem in self.world.every_private_key:
            sensitive += [line for line in pem.splitlines() if not line.startswith("-----")]
        sensitive += self.world.every_secret_value()
        surfaces = list(self.outputs) + [json.dumps(self.world.configmaps)] + list(self.world.metrics)
        for surface in surfaces:
            for value in sensitive:
                self.assertNotIn(value, surface, "a secret value reached a log, the state ConfigMap or a metric")

    def test_absent_app_credentials_exit_zero_and_touch_nothing_on_github(self):
        del self.world.kv[PLOEG_APP["path"]]
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("app credentials absent", result.stdout)
        self.assertIn("docs/techdocs/docs/runbooks/github-app-ploeg-hq.md", result.stdout)
        self.assertFalse([c for c in self.world.calls if "/repos/" in c or "/app/" in c])
        self.assertEqual(self.metric("app_credentials_present", SECRET_NAME), "0")
        self.assertIsNotNone(self.metric("run_success_timestamp_seconds", SECRET_NAME))
        self.assert_nothing_sensitive_escaped()

    def test_incomplete_app_credentials_count_as_absent(self):
        self.world.kv[PLOEG_APP["path"]] = {"app_id": PLOEG_APP["app_id"], "installation_id": "", "private_key": ""}
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0)
        self.assertIn("app credentials absent", result.stdout)

    def test_openbao_denial_fails_instead_of_reading_as_absent(self):
        self.world.kv_status[PLOEG_APP["path"]] = 403
        result = self.run_bridge()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("app credentials absent", result.stdout)

    def test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint(self):
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(self.puts()), 1)
        self.assertEqual(self.world.decrypted_values, [self.source_value])
        state = self.world.configmaps["github-secrets-bridge-state"]["data"]
        self.assertEqual(len(state["source_fingerprint"]), 64)
        self.assertEqual(state["github_updated_at"], self.world.github_secret["updated_at"])
        self.assertEqual(self.world.token_requests,
                         [{"installation": PLOEG_APP["installation_id"], "repositories": [REPOSITORY],
                           "permissions": {"secrets": "write"}}])
        self.assertEqual(self.world.revoked, 1)
        self.assertEqual(self.world.jwt_errors, [])
        self.assertEqual(self.metric("app_credentials_present", SECRET_NAME), "1")
        self.assertIsNotNone(self.metric("last_write_timestamp_seconds", SECRET_NAME))
        self.assert_nothing_sensitive_escaped()

    def test_unchanged_source_is_not_rewritten(self):
        self.run_bridge()
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(self.puts()), 1, "an unchanged source was written again")
        self.assertIn("no write", result.stdout)
        self.assertNotIn("last_write_timestamp_seconds", self.world.metrics[-1])
        self.assertEqual(self.world.revoked, 2)
        self.assert_nothing_sensitive_escaped()

    def test_changed_source_is_rewritten(self):
        self.run_bridge()
        self.set_source("forgejo-token-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(self.puts()), 2)
        self.assertEqual(self.world.decrypted_values[-1], self.source_value)
        self.assertIn("source changed", result.stdout)
        self.assert_nothing_sensitive_escaped()

    def test_secret_deleted_on_github_is_restored(self):
        self.run_bridge()
        del self.world.ploeg.secrets[SECRET_NAME]
        result = self.run_bridge()
        self.assertEqual(len(self.puts()), 2)
        self.assertIn("absent on GitHub", result.stdout)

    def test_secret_overwritten_outside_the_bridge_is_restored(self):
        self.run_bridge()
        self.world.ploeg.bump(SECRET_NAME, "someone-else")
        result = self.run_bridge()
        self.assertEqual(len(self.puts()), 2)
        self.assertEqual(self.world.decrypted_values[-1], self.source_value)
        self.assertIn("outside the bridge", result.stdout)

    def test_failed_github_write_fails_the_run_and_keeps_the_old_state(self):
        self.world.ploeg.put_status = 500
        result = self.run_bridge()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("github-secrets-bridge-state", self.world.configmaps)
        self.assertEqual(self.world.revoked, 1)
        self.assert_nothing_sensitive_escaped()

    def test_pkcs8_private_key_signs_a_valid_app_jwt(self):
        self.world.kv[PLOEG_APP["path"]]["private_key"] = rsa_pem(self.world.rsa_keys[PLOEG_APP["app_id"]],
                                                                  serialization.PrivateFormat.PKCS8)
        self.world.every_private_key.append(self.world.kv[PLOEG_APP["path"]]["private_key"])
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.world.jwt_errors, [])
        self.assertEqual(len(self.puts()), 1)

    def test_empty_source_fails(self):
        self.set_source("")
        result = self.run_bridge()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.puts())

    def test_every_target_is_written_through_its_own_owner_app_token_and_state(self):
        self.targets = [self.release_target(), ploeg_bot_target("app_id", "RELEASE_CONSUMER_GITHUB_APP_ID"),
                        ploeg_bot_target("private_key", "RELEASE_CONSUMER_GITHUB_APP_PRIVATE_KEY"),
                        unfold_cloudflare_target("CLOUDFLARE_API_TOKEN"),
                        unfold_cloudflare_target("CLOUDFLARE_ACCOUNT_ID")]
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.world.repositories["ploeg-hq/ploeg"].decrypted,
                         {SECRET_NAME: [self.source_value], "RELEASE_CONSUMER_GITHUB_APP_ID": [BOT_APP_ID],
                          "RELEASE_CONSUMER_GITHUB_APP_PRIVATE_KEY": [self.world.bot_private_key.strip()]})
        self.assertEqual(self.world.repositories["unfold-hq/unfold"].decrypted,
                         {"CLOUDFLARE_API_TOKEN": [CLOUDFLARE_TOKEN], "CLOUDFLARE_ACCOUNT_ID": [CLOUDFLARE_ACCOUNT]})
        for request in self.world.token_requests:
            expected = REPOSITORY if request["installation"] == PLOEG_APP["installation_id"] else "unfold"
            self.assertEqual(request["repositories"], [expected])
            self.assertEqual(request["permissions"], {"secrets": "write"})
        self.assertEqual(self.world.revoked, len(self.targets))
        self.assertEqual(set(self.world.configmaps), {spec["state_configmap"] for spec in self.targets})
        second = self.run_bridge()
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertEqual(second.stdout.count("already matches the source; no write"), len(self.targets))
        self.assert_nothing_sensitive_escaped()

    def test_an_owner_without_its_app_leaves_the_other_owner_synced(self):
        del self.world.kv[UNFOLD_APP["path"]]
        self.targets = [unfold_cloudflare_target("CLOUDFLARE_API_TOKEN"), self.release_target()]
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("docs/techdocs/docs/runbooks/github-app-unfold-hq.md", result.stdout)
        self.assertFalse([call for call in self.world.calls if "/repos/unfold-hq/" in call
                          or f"/installations/{UNFOLD_APP['installation_id']}/" in call])
        self.assertNotIn("GET /v1/secret/data/cloudflare/deploy", self.world.calls)
        self.assertEqual(self.world.decrypted_values, [self.source_value])
        self.assertEqual(self.metric("app_credentials_present", "CLOUDFLARE_API_TOKEN"), "0")
        self.assertEqual(self.metric("app_credentials_present", SECRET_NAME), "1")
        self.assert_nothing_sensitive_escaped()

    def test_absent_openbao_source_exits_zero_and_writes_nothing(self):
        del self.world.kv["github/unfold-hq-bot-app"]
        self.targets = [ploeg_bot_target("app_id", "RELEASE_CONSUMER_GITHUB_APP_ID")]
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("source absent", result.stdout)
        self.assertFalse(self.puts())
        self.assertFalse(self.world.token_requests)
        self.assertEqual(self.metric("source_present", "RELEASE_CONSUMER_GITHUB_APP_ID"), "0")
        self.assertEqual(self.metric("app_credentials_present", "RELEASE_CONSUMER_GITHUB_APP_ID"), "1")

    def test_openbao_source_without_its_property_fails(self):
        self.world.kv["cloudflare/deploy"] = {"CLOUDFLARE_API_TOKEN": CLOUDFLARE_TOKEN}
        self.targets = [unfold_cloudflare_target("CLOUDFLARE_ACCOUNT_ID")]
        result = self.run_bridge()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.puts("unfold-hq"))
        self.assert_nothing_sensitive_escaped()

    def test_openbao_denial_on_a_source_fails_instead_of_reading_as_absent(self):
        self.world.kv_status["cloudflare/deploy"] = 403
        self.targets = [unfold_cloudflare_target("CLOUDFLARE_API_TOKEN")]
        result = self.run_bridge()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("source absent", result.stdout)

    def test_one_failing_target_does_not_stop_the_others(self):
        self.world.repositories["unfold-hq/unfold"].put_status = 500
        self.targets = [unfold_cloudflare_target("CLOUDFLARE_API_TOKEN"), self.release_target()]
        result = self.run_bridge()
        self.assertEqual(result.returncode, 1)
        self.assertIn("unfold-hq/unfold/CLOUDFLARE_API_TOKEN", result.stdout)
        self.assertEqual(self.world.decrypted_values, [self.source_value])
        self.assertIn("github-secrets-bridge-state", self.world.configmaps)
        self.assertEqual(self.world.revoked, 2)
        self.assert_nothing_sensitive_escaped()


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.targets = json.loads((BRIDGE_APP_DIR / "targets.json").read_text())

    def test_targets_are_unique_and_keep_the_ploeg_state(self):
        keys = [(spec["owner"], spec["repository"], spec["secret"]) for spec in self.targets]
        self.assertEqual(len(keys), len(set(keys)))
        states = [spec["state_configmap"] for spec in self.targets]
        self.assertEqual(len(states), len(set(states)))
        release = [spec for spec in self.targets if spec["secret"] == SECRET_NAME]
        self.assertEqual([spec["state_configmap"] for spec in release], ["github-secrets-bridge-state"])

    def test_every_state_configmap_is_writable_by_the_bridge(self):
        rbac = (BRIDGE_APP_DIR / "rbac.yaml").read_text()
        for spec in self.targets:
            self.assertIn(f'- "{spec["state_configmap"]}"\n', rbac, spec["state_configmap"])

    def test_every_openbao_path_the_targets_read_is_granted(self):
        policy = BRIDGE_POLICY.read_text()
        for spec in self.targets:
            paths = [spec["app_secret_path"]] + ([spec["source"]["openbao"]] if "openbao" in spec["source"] else [])
            for path in paths:
                self.assertIn(f'path "secret/data/{path}" {{\n  capabilities = ["read"]', policy, path)

    def test_the_cronjob_reads_the_targets_file_the_kustomization_ships(self):
        self.assertIn("targets.json=./targets.json", (BRIDGE_APP_DIR / "kustomization.yaml").read_text())
        self.assertIn("{name: TARGETS_PATH, value: /scripts/targets.json}", (BRIDGE_APP_DIR / "cronjob.yaml").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
