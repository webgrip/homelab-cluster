import base64
import json
import os
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
    REPO_ROOT / "kubernetes/apps/github-config/secrets-bridge/app/github_secrets_bridge.py"))

APP_ID = "424242"
INSTALLATION_ID = "777"
OWNER = "ploeg-hq"
REPOSITORY = "ploeg"
SECRET_NAME = "RELEASE_CONSUMER_TOKEN_FORGEJO"
VAULT_TOKEN = "s.fake-openbao-client-token-0001"
INSTALLATION_TOKEN = "ghs_fakeInstallationToken0123456789abcd"


def jwt_parts(token):
    header, payload, signature = token.split(".")
    pad = lambda part: part + "=" * (-len(part) % 4)
    return (f"{header}.{payload}".encode(), json.loads(base64.urlsafe_b64decode(pad(payload))),
            base64.urlsafe_b64decode(pad(signature)))


class FakeWorld:
    def __init__(self):
        self.rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_key_pem = self.rsa_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()).decode()
        self.repo_key = PrivateKey.generate()
        self.app_secret = {"app_id": APP_ID, "installation_id": INSTALLATION_ID,
                           "private_key": self.private_key_pem}
        self.vault_read_status = 200
        self.github_put_status = 201
        self.github_secret = None
        self.github_secret_version = 0
        self.decrypted_values = []
        self.configmaps = {}
        self.metrics = []
        self.calls = []
        self.token_requests = []
        self.revoked = 0
        self.jwt_errors = []

    def bump_secret(self, value):
        self.github_secret_version += 1
        self.github_secret = {"name": SECRET_NAME,
                              "updated_at": f"2026-10-18T10:00:{self.github_secret_version:02d}Z"}
        self.decrypted_values.append(value)


def handler_for(world):
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

        def github_authorised(self):
            return self.headers.get("Authorization") == f"Bearer {INSTALLATION_TOKEN}"

        def handle_any(self, method):
            path = self.path
            body = self.body()
            world.calls.append(f"{method} {path}")
            repo = f"/repos/{OWNER}/{REPOSITORY}"
            if method == "POST" and path == "/v1/auth/kubernetes/login":
                request = json.loads(body)
                if request.get("role") != "github-secrets-bridge" or request.get("jwt") != "fake-sa-jwt":
                    return self.reply(403, {"errors": ["permission denied"]})
                return self.reply(200, {"auth": {"client_token": VAULT_TOKEN}})
            if method == "GET" and path == "/v1/secret/data/github/ploeg-hq-app":
                if self.headers.get("X-Vault-Token") != VAULT_TOKEN:
                    return self.reply(403, {"errors": ["permission denied"]})
                if world.vault_read_status != 200:
                    return self.reply(world.vault_read_status, {"errors": []})
                if world.app_secret is None:
                    return self.reply(404, {"errors": []})
                return self.reply(200, {"data": {"data": world.app_secret}})
            if method == "POST" and path == f"/app/installations/{INSTALLATION_ID}/access_tokens":
                signing_input, claims, signature = jwt_parts(self.headers["Authorization"].removeprefix("Bearer "))
                try:
                    world.rsa_key.public_key().verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
                except Exception:
                    world.jwt_errors.append("bad signature")
                    return self.reply(401, {"message": "bad jwt"})
                if claims.get("iss") != APP_ID or claims["exp"] - claims["iat"] > 600:
                    world.jwt_errors.append("bad claims")
                    return self.reply(401, {"message": "bad claims"})
                world.token_requests.append(json.loads(body))
                return self.reply(201, {"token": INSTALLATION_TOKEN})
            if method == "DELETE" and path == "/installation/token":
                world.revoked += 1
                return self.reply(204)
            if path.startswith(repo) and not self.github_authorised():
                return self.reply(401, {"message": "Bad credentials"})
            if method == "GET" and path == f"{repo}/actions/secrets/public-key":
                return self.reply(200, {"key_id": "kid-1", "key": base64.b64encode(bytes(world.repo_key.public_key)).decode()})
            if method == "GET" and path == f"{repo}/actions/secrets/{SECRET_NAME}":
                return self.reply(200, world.github_secret) if world.github_secret else self.reply(404, {"message": "Not Found"})
            if method == "PUT" and path == f"{repo}/actions/secrets/{SECRET_NAME}":
                if world.github_put_status >= 300:
                    return self.reply(world.github_put_status, {"message": "boom"})
                request = json.loads(body)
                if request.get("key_id") != "kid-1":
                    return self.reply(422, {"message": "key_id"})
                plaintext = SealedBox(world.repo_key).decrypt(base64.b64decode(request["encrypted_value"])).decode()
                created = world.github_secret is None
                world.bump_secret(plaintext)
                return self.reply(201 if created else 204)
            if path.startswith("/api/v1/namespaces/github-config/configmaps"):
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
                if method == "POST":
                    world.configmaps[manifest["metadata"]["name"]] = manifest
                    return self.reply(201, manifest)
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
        self.outputs = []
        self.set_source("forgejo-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def set_source(self, value):
        self.source_value = value
        self.source.write_text(value + "\n")

    def run_bridge(self):
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "GITHUB_OWNER": OWNER, "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_SECRET_NAME": SECRET_NAME,
            "GITHUB_API": self.url, "VAULT_ADDR": self.url, "VAULT_ROLE": "github-secrets-bridge",
            "APP_SECRET_PATH": "github/ploeg-hq-app", "SOURCE_PATH": str(self.source),
            "SERVICE_ACCOUNT_TOKEN_PATH": str(self.sa_token), "KUBERNETES_API": self.url,
            "KUBERNETES_CA_PATH": "", "NAMESPACE": "github-config",
            "STATE_CONFIGMAP": "github-secrets-bridge-state",
            "METRICS_URL": f"{self.url}/api/v1/import/prometheus?extra_label=job=github-secrets-bridge",
        }
        result = subprocess.run([sys.executable, "-I", str(BRIDGE)], env=environment, capture_output=True,
                                text=True, timeout=120)
        self.outputs.append(result.stdout + result.stderr)
        return result

    def puts(self):
        return [call for call in self.world.calls if call.startswith("PUT /repos/")]

    def assert_nothing_sensitive_escaped(self):
        sensitive = [self.source_value, INSTALLATION_TOKEN, VAULT_TOKEN] + [
            line for line in self.world.private_key_pem.splitlines() if not line.startswith("-----")]
        sensitive += self.world.decrypted_values
        surfaces = list(self.outputs) + [json.dumps(self.world.configmaps)] + list(self.world.metrics)
        for surface in surfaces:
            for value in sensitive:
                self.assertNotIn(value, surface, "a secret value reached a log, the state ConfigMap or a metric")

    def test_absent_app_credentials_exit_zero_and_touch_nothing_on_github(self):
        self.world.app_secret = None
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("app credentials absent", result.stdout)
        self.assertFalse([c for c in self.world.calls if "/repos/" in c or "/app/" in c])
        self.assertIn("github_secrets_bridge_app_credentials_present", self.world.metrics[-1])
        self.assertIn("} 0\n", self.world.metrics[-1].split("run_success")[0])
        self.assert_nothing_sensitive_escaped()

    def test_incomplete_app_credentials_count_as_absent(self):
        self.world.app_secret = {"app_id": APP_ID, "installation_id": "", "private_key": ""}
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0)
        self.assertIn("app credentials absent", result.stdout)

    def test_openbao_denial_fails_instead_of_reading_as_absent(self):
        self.world.vault_read_status = 403
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
                         [{"repositories": [REPOSITORY], "permissions": {"secrets": "write"}}])
        self.assertEqual(self.world.revoked, 1)
        self.assertEqual(self.world.jwt_errors, [])
        self.assertIn("app_credentials_present", self.world.metrics[-1])
        self.assertIn("last_write_timestamp_seconds", self.world.metrics[-1])
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
        self.world.github_secret = None
        result = self.run_bridge()
        self.assertEqual(len(self.puts()), 2)
        self.assertIn("absent on GitHub", result.stdout)

    def test_secret_overwritten_outside_the_bridge_is_restored(self):
        self.run_bridge()
        self.world.bump_secret("someone-else")
        result = self.run_bridge()
        self.assertEqual(len(self.puts()), 2)
        self.assertEqual(self.world.decrypted_values[-1], self.source_value)
        self.assertIn("outside the bridge", result.stdout)

    def test_failed_github_write_fails_the_run_and_keeps_the_old_state(self):
        self.world.github_put_status = 500
        result = self.run_bridge()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("github-secrets-bridge-state", self.world.configmaps)
        self.assertEqual(self.world.revoked, 1)
        self.assert_nothing_sensitive_escaped()

    def test_pkcs8_private_key_signs_a_valid_app_jwt(self):
        self.world.app_secret["private_key"] = self.world.rsa_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.world.jwt_errors, [])
        self.assertEqual(len(self.puts()), 1)

    def test_empty_source_fails(self):
        self.set_source("")
        result = self.run_bridge()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.puts())


if __name__ == "__main__":
    unittest.main(verbosity=2)
