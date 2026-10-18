import base64
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

FINGERPRINT_DOMAIN = b"github-secrets-bridge/v1"
GITHUB_API_VERSION = "2022-11-28"
USER_AGENT = "webgrip-github-secrets-bridge"


class AppCredentialsAbsent(Exception):
    pass


class BridgeFailure(Exception):
    pass


class RedactingStream:
    def __init__(self, stream):
        self.stream = stream
        self.sensitive_values = []

    def forbid(self, value):
        if value and len(value) >= 6 and value not in self.sensitive_values:
            self.sensitive_values.append(value)
            for line in value.splitlines():
                if len(line) >= 16 and line not in self.sensitive_values:
                    self.sensitive_values.append(line)

    def write(self, text):
        for value in self.sensitive_values:
            text = text.replace(value, "[redacted]")
        return self.stream.write(text)

    def flush(self):
        return self.stream.flush()


stdout = RedactingStream(sys.stdout)
stderr = RedactingStream(sys.stderr)


def forbid_in_output(value):
    stdout.forbid(value)
    stderr.forbid(value)


def log(message):
    stdout.write(message + "\n")
    stdout.flush()


def env(name, default=None):
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise BridgeFailure(f"environment variable {name} is required")
    return value


def http_request(method, url, headers=None, body=None, context=None, timeout=30):
    data = None
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        return error.code, parsed
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise BridgeFailure(f"{method} {url} failed: {type(error).__name__}") from None


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def der_read(data, offset):
    tag = data[offset]
    length = data[offset + 1]
    offset += 2
    if length & 0x80:
        size = length & 0x7F
        length = int.from_bytes(data[offset:offset + size], "big")
        offset += size
    return tag, data[offset:offset + length], offset + length


def der_sequence_items(data):
    items = []
    offset = 0
    while offset < len(data):
        tag, value, offset = der_read(data, offset)
        items.append((tag, value))
    return items


def rsa_private_key_from_pem(pem):
    lines = [line.strip() for line in pem.strip().splitlines()]
    body = "".join(line for line in lines if line and not line.startswith("-----"))
    der = base64.b64decode(body)
    tag, outer, _ = der_read(der, 0)
    if tag != 0x30:
        raise BridgeFailure("private key is not a DER sequence")
    items = der_sequence_items(outer)
    if len(items) == 3 and items[1][0] == 0x30 and items[2][0] == 0x04:
        _, inner, _ = der_read(items[2][1], 0)
        items = der_sequence_items(inner)
    integers = [int.from_bytes(value, "big") for tag, value in items if tag == 0x02]
    if len(integers) < 4:
        raise BridgeFailure("private key is not an RSA key")
    _, modulus, _, private_exponent = integers[:4]
    return modulus, private_exponent


SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def rs256_sign(message, modulus, private_exponent):
    size = (modulus.bit_length() + 7) // 8
    digest_info = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    padding = b"\xff" * (size - len(digest_info) - 3)
    encoded = b"\x00\x01" + padding + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), private_exponent, modulus)
    return signature.to_bytes(size, "big")


def github_app_jwt(app_id, private_key_pem, now):
    modulus, private_exponent = rsa_private_key_from_pem(private_key_pem)
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {"iat": int(now) - 60, "exp": int(now) + 540, "iss": str(app_id)}
    payload = b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    return f"{header}.{payload}.{b64url(rs256_sign(signing_input, modulus, private_exponent))}"


CURVE25519_PRIME = 2**255 - 19


def x25519(scalar, u_coordinate):
    clamped = bytearray(scalar)
    clamped[0] &= 248
    clamped[31] &= 127
    clamped[31] |= 64
    k = int.from_bytes(clamped, "little")
    x1 = int.from_bytes(u_coordinate, "little") & ((1 << 255) - 1)
    p = CURVE25519_PRIME
    x2, z2, x3, z3 = 1, 0, x1, 1
    swap = 0
    for bit_index in reversed(range(255)):
        bit = (k >> bit_index) & 1
        swap ^= bit
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a = (x2 + z2) % p
        aa = a * a % p
        b = (x2 - z2) % p
        bb = b * b % p
        e = (aa - bb) % p
        c = (x3 + z3) % p
        d = (x3 - z3) % p
        da = d * a % p
        cb = c * b % p
        x3 = (da + cb) ** 2 % p
        z3 = x1 * (da - cb) ** 2 % p
        x2 = aa * bb % p
        z2 = e * (aa + 121665 * e) % p
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * pow(z2, p - 2, p) % p).to_bytes(32, "little")


def x25519_public_key(private_key):
    return x25519(private_key, (9).to_bytes(32, "little"))


def rotl32(value, shift):
    return ((value << shift) & 0xFFFFFFFF) | (value >> (32 - shift))


def salsa20_rounds(state):
    x = list(state)
    for _ in range(10):
        for a, b, c, d in ((0, 4, 8, 12), (5, 9, 13, 1), (10, 14, 2, 6), (15, 3, 7, 11),
                           (0, 1, 2, 3), (5, 6, 7, 4), (10, 11, 8, 9), (15, 12, 13, 14)):
            x[b] ^= rotl32((x[a] + x[d]) & 0xFFFFFFFF, 7)
            x[c] ^= rotl32((x[b] + x[a]) & 0xFFFFFFFF, 9)
            x[d] ^= rotl32((x[c] + x[b]) & 0xFFFFFFFF, 13)
            x[a] ^= rotl32((x[d] + x[c]) & 0xFFFFFFFF, 18)
    return x


SALSA_CONSTANTS = [int.from_bytes(b"expa", "little"), int.from_bytes(b"nd 3", "little"),
                   int.from_bytes(b"2-by", "little"), int.from_bytes(b"te k", "little")]


def words(data):
    return [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]


def salsa_state(key, sixteen_bytes):
    k = words(key)
    n = words(sixteen_bytes)
    return [SALSA_CONSTANTS[0], k[0], k[1], k[2], k[3], SALSA_CONSTANTS[1], n[0], n[1],
            n[2], n[3], SALSA_CONSTANTS[2], k[4], k[5], k[6], k[7], SALSA_CONSTANTS[3]]


def hsalsa20(key, sixteen_bytes):
    x = salsa20_rounds(salsa_state(key, sixteen_bytes))
    return b"".join(x[i].to_bytes(4, "little") for i in (0, 5, 10, 15, 6, 7, 8, 9))


def salsa20_stream(key, eight_byte_nonce, length):
    blocks = []
    for counter in range((length + 63) // 64):
        state = salsa_state(key, eight_byte_nonce + counter.to_bytes(8, "little"))
        mixed = salsa20_rounds(state)
        blocks.append(b"".join(((mixed[i] + state[i]) & 0xFFFFFFFF).to_bytes(4, "little") for i in range(16)))
    return b"".join(blocks)[:length]


def poly1305(one_time_key, message):
    r = int.from_bytes(one_time_key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(one_time_key[16:32], "little")
    p = (1 << 130) - 5
    accumulator = 0
    for i in range(0, len(message), 16):
        block = message[i:i + 16] + b"\x01"
        accumulator = (accumulator + int.from_bytes(block, "little")) * r % p
    return ((accumulator + s) % (1 << 128)).to_bytes(16, "little")


def crypto_box(message, nonce, recipient_public_key, sender_private_key):
    shared = x25519(sender_private_key, recipient_public_key)
    box_key = hsalsa20(shared, bytes(16))
    subkey = hsalsa20(box_key, nonce[:16])
    stream = salsa20_stream(subkey, nonce[16:24], 32 + len(message))
    ciphertext = bytes(m ^ k for m, k in zip(message, stream[32:]))
    return poly1305(stream[:32], ciphertext) + ciphertext


def sealed_box(message, recipient_public_key, ephemeral_private_key=None):
    if len(recipient_public_key) != 32:
        raise BridgeFailure("repository public key is not a 32-byte X25519 key")
    ephemeral_private_key = ephemeral_private_key or os.urandom(32)
    ephemeral_public_key = x25519_public_key(ephemeral_private_key)
    nonce = hashlib.blake2b(ephemeral_public_key + recipient_public_key, digest_size=24).digest()
    return ephemeral_public_key + crypto_box(message, nonce, recipient_public_key, ephemeral_private_key)


def source_fingerprint(target, value):
    return hashlib.sha256(FINGERPRINT_DOMAIN + b"\0" + target.encode() + b"\0" + value.encode()).hexdigest()


class OpenBao:
    def __init__(self, address, role, jwt_path):
        self.address = address.rstrip("/")
        self.role = role
        self.jwt_path = jwt_path

    def login(self):
        with open(self.jwt_path) as handle:
            jwt = handle.read().strip()
        status, body = http_request("POST", f"{self.address}/v1/auth/kubernetes/login",
                                    body={"role": self.role, "jwt": jwt})
        if status != 200 or not body or "auth" not in body:
            raise BridgeFailure(f"OpenBao kubernetes login for role {self.role} returned {status}")
        token = body["auth"]["client_token"]
        forbid_in_output(token)
        return token

    def read_kv(self, token, path):
        status, body = http_request("GET", f"{self.address}/v1/secret/data/{path}",
                                    headers={"X-Vault-Token": token})
        if status == 404:
            raise AppCredentialsAbsent(f"secret/{path} does not exist")
        if status == 403:
            raise BridgeFailure(f"OpenBao denied reading secret/{path} (403)")
        if status != 200 or not body:
            raise BridgeFailure(f"OpenBao read of secret/{path} returned {status}")
        data = (body.get("data") or {}).get("data")
        if data is None:
            raise AppCredentialsAbsent(f"secret/{path} has no live version")
        return data


class GitHub:
    def __init__(self, api, owner, repository):
        self.api = api.rstrip("/")
        self.owner = owner
        self.repository = repository
        self.token = None

    def headers(self, bearer):
        return {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "Authorization": f"Bearer {bearer}"}

    def mint_installation_token(self, app_jwt, installation_id):
        status, body = http_request(
            "POST", f"{self.api}/app/installations/{installation_id}/access_tokens",
            headers=self.headers(app_jwt),
            body={"repositories": [self.repository], "permissions": {"secrets": "write"}})
        if status != 201 or not body or "token" not in body:
            raise BridgeFailure(f"GitHub refused an installation token for installation {installation_id} ({status})")
        self.token = body["token"]
        forbid_in_output(self.token)

    def call(self, method, path, body=None):
        return http_request(method, f"{self.api}/repos/{self.owner}/{self.repository}{path}",
                            headers=self.headers(self.token), body=body)

    def secret_metadata(self, name):
        status, body = self.call("GET", f"/actions/secrets/{name}")
        if status == 404:
            return None
        if status != 200 or not body:
            raise BridgeFailure(f"GitHub secret metadata read for {name} returned {status}")
        return body

    def public_key(self):
        status, body = self.call("GET", "/actions/secrets/public-key")
        if status != 200 or not body:
            raise BridgeFailure(f"GitHub repository public key read returned {status}")
        return body["key_id"], base64.b64decode(body["key"])

    def put_secret(self, name, value):
        key_id, public_key = self.public_key()
        encrypted = base64.b64encode(sealed_box(value.encode(), public_key)).decode()
        status, _ = self.call("PUT", f"/actions/secrets/{name}", body={"encrypted_value": encrypted, "key_id": key_id})
        if status not in (201, 204):
            raise BridgeFailure(f"GitHub secret write for {name} returned {status}")

    def revoke(self):
        if self.token:
            http_request("DELETE", f"{self.api}/installation/token", headers=self.headers(self.token))


class StateConfigMap:
    def __init__(self, api, namespace, name, token_path, ca_path):
        self.url = f"{api.rstrip('/')}/api/v1/namespaces/{namespace}/configmaps"
        self.name = name
        self.namespace = namespace
        self.token_path = token_path
        self.context = ssl.create_default_context(cafile=ca_path) if ca_path and os.path.exists(ca_path) else None

    def headers(self):
        with open(self.token_path) as handle:
            return {"Authorization": f"Bearer {handle.read().strip()}"}

    def read(self):
        status, body = http_request("GET", f"{self.url}/{self.name}", headers=self.headers(), context=self.context)
        if status == 404:
            return {}
        if status != 200 or not body:
            raise BridgeFailure(f"reading ConfigMap {self.namespace}/{self.name} returned {status}")
        return body.get("data") or {}

    def write(self, data):
        manifest = {"apiVersion": "v1", "kind": "ConfigMap",
                    "metadata": {"name": self.name, "namespace": self.namespace,
                                 "labels": {"app.kubernetes.io/name": "github-secrets-bridge"}},
                    "data": data}
        status, _ = http_request("PUT", f"{self.url}/{self.name}", headers=self.headers(), body=manifest,
                                 context=self.context)
        if status == 404:
            status, _ = http_request("POST", self.url, headers=self.headers(), body=manifest, context=self.context)
        if status not in (200, 201):
            raise BridgeFailure(f"writing ConfigMap {self.namespace}/{self.name} returned {status}")


def push_metrics(url, labels, samples):
    if not url:
        return
    label_text = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    lines = "".join(f"github_secrets_bridge_{name}{{{label_text}}} {value}\n" for name, value in samples.items())
    request = urllib.request.Request(url, data=lines.encode(), method="POST",
                                     headers={"Content-Type": "text/plain", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10):
            pass
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log(f"metrics push failed ({type(error).__name__}); the CronJob status still carries the result")


def read_source(path):
    try:
        with open(path) as handle:
            value = handle.read().strip()
    except FileNotFoundError:
        value = ""
    forbid_in_output(value)
    if not value:
        raise BridgeFailure(f"source value at {path} is empty or missing")
    return value


def sync_is_current(state, fingerprint, metadata):
    return (metadata is not None
            and state.get("source_fingerprint") == fingerprint
            and state.get("github_updated_at") == metadata.get("updated_at"))


def run():
    owner = env("GITHUB_OWNER")
    repository = env("GITHUB_REPOSITORY")
    secret_name = env("GITHUB_SECRET_NAME")
    target = f"{owner}/{repository}/{secret_name}"
    labels = {"owner": owner, "repository": repository, "secret": secret_name}
    metrics_url = os.environ.get("METRICS_URL", "")
    service_account_token = env("SERVICE_ACCOUNT_TOKEN_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/token")

    source = read_source(env("SOURCE_PATH"))

    vault = OpenBao(env("VAULT_ADDR"), env("VAULT_ROLE"), service_account_token)
    try:
        app = vault.read_kv(vault.login(), env("APP_SECRET_PATH"))
        app_id = str(app.get("app_id") or "").strip()
        installation_id = str(app.get("installation_id") or "").strip()
        private_key = str(app.get("private_key") or "")
        forbid_in_output(private_key)
        if not (app_id and installation_id and private_key.strip()):
            raise AppCredentialsAbsent(f"secret/{env('APP_SECRET_PATH')} lacks app_id, installation_id or private_key")
    except AppCredentialsAbsent as absent:
        log(f"app credentials absent: {absent}; nothing written to {target}. Owner step: docs/techdocs/docs/runbooks/github-app-ploeg-hq.md")
        push_metrics(metrics_url, labels, {"app_credentials_present": 0, "run_success_timestamp_seconds": int(time.time())})
        return 0

    state_store = StateConfigMap(env("KUBERNETES_API", "https://kubernetes.default.svc"), env("NAMESPACE"),
                                 env("STATE_CONFIGMAP"), service_account_token,
                                 os.environ.get("KUBERNETES_CA_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"))
    github = GitHub(env("GITHUB_API", "https://api.github.com"), owner, repository)
    fingerprint = source_fingerprint(target, source)
    samples = {"app_credentials_present": 1}
    try:
        github.mint_installation_token(github_app_jwt(app_id, private_key, time.time()), installation_id)
        state = state_store.read()
        metadata = github.secret_metadata(secret_name)
        if sync_is_current(state, fingerprint, metadata):
            log(f"{target} already matches the source; no write")
        else:
            reason = ("absent on GitHub" if metadata is None
                      else "source changed" if state.get("source_fingerprint") != fingerprint
                      else "changed on GitHub outside the bridge")
            github.put_secret(secret_name, source)
            metadata = github.secret_metadata(secret_name)
            if metadata is None:
                raise BridgeFailure(f"{target} is still absent after the write")
            state_store.write({"source_fingerprint": fingerprint, "github_updated_at": metadata.get("updated_at", ""),
                               "target": target})
            samples["last_write_timestamp_seconds"] = int(time.time())
            log(f"{target} written ({reason})")
    finally:
        github.revoke()
    samples["run_success_timestamp_seconds"] = int(time.time())
    push_metrics(metrics_url, labels, samples)
    return 0


def main():
    sys.stdout = stdout
    sys.stderr = stderr
    try:
        return run()
    except BridgeFailure as failure:
        log(f"bridge failed: {failure}")
        return 1
    except Exception as unexpected:
        log(f"bridge failed with an unexpected {type(unexpected).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
