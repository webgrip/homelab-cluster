import base64
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

GITHUB_API_VERSION = "2022-11-28"
USER_AGENT = "webgrip-github-mirrors"
METRIC_PREFIX = "github_mirror_"
PAGE_SIZE_FORGEJO = 50
PAGE_SIZE_GITHUB = 100
MAX_PAGES = 200


class CredentialsAbsent(Exception):
    pass


class ReconcilerFailure(Exception):
    pass


class NoAppAccess(Exception):
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
        raise ReconcilerFailure(f"environment variable {name} is required")
    return value


def http_raw(method, url, headers=None, data=None, timeout=60):
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ReconcilerFailure(f"{method} {url.split('?')[0]} failed: {type(error).__name__}") from None


def http_json(method, url, headers=None, body=None, timeout=60):
    request_headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
    status, raw = http_raw(method, url, headers=request_headers, data=data, timeout=timeout)
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


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
        raise ReconcilerFailure("private key is not a DER sequence")
    items = der_sequence_items(outer)
    if len(items) == 3 and items[1][0] == 0x30 and items[2][0] == 0x04:
        _, inner, _ = der_read(items[2][1], 0)
        items = der_sequence_items(inner)
    integers = [int.from_bytes(value, "big") for tag, value in items if tag == 0x02]
    if len(integers) < 4:
        raise ReconcilerFailure("private key is not an RSA key")
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


MODEL_ENTRY = re.compile(r'^  (?P<quote>"?)(?P<key>[^"\s#][^"]*?)(?P=quote):\s*$')
MODEL_FIELD = re.compile(r"^    (?P<field>[a-z_]+):\s*(?P<value>.*?)\s*$")
MODEL_SETTING = re.compile(r"^      (?P<field>[a-z_]+):\s*(?P<value>.*?)\s*$")


def model_github_entries(model_text):
    entries = {}
    in_repos = False
    key = None
    section = None
    for line in model_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            in_repos = line.rstrip() == "repos:"
            key = None
            continue
        if not in_repos:
            continue
        entry = MODEL_ENTRY.match(line)
        if entry:
            key = entry.group("key")
            section = None
            entries[key] = {"forge": None, "mirror_of": None, "archived": False}
            continue
        if key is None:
            continue
        field = MODEL_FIELD.match(line)
        if field:
            section = field.group("field")
            if section in ("forge", "mirror_of") and field.group("value"):
                entries[key][section] = field.group("value").strip('"')
            continue
        setting = MODEL_SETTING.match(line)
        if setting and section == "settings" and setting.group("field") == "archived":
            entries[key]["archived"] = setting.group("value") == "true"
    return {key: entry for key, entry in entries.items() if entry["forge"] == "github"}


def tracked_mirrors(github_entries, owner):
    return sorted(
        (key.split("/", 1)[1], entry["mirror_of"])
        for key, entry in github_entries.items()
        if key.split("/", 1)[0] == owner and entry["mirror_of"] and not entry["archived"])


GO_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(h|m|s|ms|us|µs|ns)")
GO_DURATION_SECONDS = {"h": 3600, "m": 60, "s": 1, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}


def go_duration_seconds(text):
    parts = GO_DURATION_PART.findall(text or "")
    return int(sum(float(number) * GO_DURATION_SECONDS[unit] for number, unit in parts))


def timestamp_seconds(text):
    if not text:
        return 0
    try:
        moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    seconds = int(moment.timestamp())
    return seconds if seconds > 0 else 0


class Metrics:
    def __init__(self):
        self.samples = []

    def set(self, name, labels, value):
        self.samples.append((name, dict(labels), value))

    def render(self):
        lines = []
        for name, labels, value in self.samples:
            label_text = ",".join(f'{key}="{escape_label(str(val))}"' for key, val in sorted(labels.items()))
            lines.append(f"{METRIC_PREFIX}{name}{{{label_text}}} {value}\n")
        return "".join(lines)

    def push(self, url):
        if not url:
            return
        request = urllib.request.Request(url, data=self.render().encode(), method="POST",
                                         headers={"Content-Type": "text/plain", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=10):
                pass
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            log(f"metrics push failed ({type(error).__name__}); the CronJob status still carries the result")


def escape_label(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class OpenBao:
    def __init__(self, address, role, jwt_path):
        self.address = address.rstrip("/")
        self.role = role
        self.jwt_path = jwt_path

    def login(self):
        with open(self.jwt_path) as handle:
            jwt = handle.read().strip()
        status, body = http_json("POST", f"{self.address}/v1/auth/kubernetes/login",
                                 body={"role": self.role, "jwt": jwt})
        if status != 200 or not body or "auth" not in body:
            raise ReconcilerFailure(f"OpenBao kubernetes login for role {self.role} returned {status}")
        token = body["auth"]["client_token"]
        forbid_in_output(token)
        return token

    def read_kv(self, token, path):
        status, body = http_json("GET", f"{self.address}/v1/secret/data/{path}", headers={"X-Vault-Token": token})
        if status == 404:
            raise CredentialsAbsent(f"secret/{path} does not exist")
        if status == 403:
            raise ReconcilerFailure(f"OpenBao denied reading secret/{path} (403)")
        if status != 200 or not body:
            raise ReconcilerFailure(f"OpenBao read of secret/{path} returned {status}")
        data = (body.get("data") or {}).get("data")
        if data is None:
            raise CredentialsAbsent(f"secret/{path} has no live version")
        return data


class Forgejo:
    def __init__(self, url, owner, token):
        self.url = url.rstrip("/")
        self.api = f"{self.url}/api/v1"
        self.owner = owner
        self.token = token

    def headers(self):
        return {"Authorization": f"token {self.token}"} if self.token else {}

    def get(self, path):
        status, body = http_json("GET", f"{self.api}{path}", headers=self.headers())
        if status != 200:
            raise ReconcilerFailure(f"Forgejo GET {path} returned {status}")
        return body

    def pages(self, path):
        items = []
        separator = "&" if "?" in path else "?"
        for page in range(1, MAX_PAGES + 1):
            batch = self.get(f"{path}{separator}limit={PAGE_SIZE_FORGEJO}&page={page}") or []
            items.extend(batch)
            if len(batch) < PAGE_SIZE_FORGEJO:
                return items
        raise ReconcilerFailure(f"Forgejo GET {path} has more than {MAX_PAGES} pages")

    def raw_file(self, repository, path, ref):
        status, raw = http_raw("GET", f"{self.api}/repos/{self.owner}/{repository}/raw/{path}?ref={ref}",
                               headers=self.headers())
        if status != 200:
            raise ReconcilerFailure(f"Forgejo raw {repository}/{path}@{ref} returned {status}")
        return raw.decode()

    def push_mirrors(self, repository):
        if not self.token:
            return None
        status, body = http_json("GET", f"{self.api}/repos/{self.owner}/{repository}/push_mirrors",
                                 headers=self.headers())
        if status in (401, 403, 404):
            return None
        if status != 200:
            raise ReconcilerFailure(f"Forgejo push_mirrors of {repository} returned {status}")
        return body or []

    def download(self, asset, directory, max_bytes):
        source = urllib.parse.urlsplit(asset["browser_download_url"])
        url = f"{self.url}{source.path}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **self.headers()})
        target = os.path.join(directory, "asset")
        written = 0
        try:
            with urllib.request.urlopen(request, timeout=300) as response, open(target, "wb") as handle:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise ReconcilerFailure(f"asset {asset['name']} is larger than {max_bytes} bytes")
                    handle.write(chunk)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ReconcilerFailure(f"downloading asset {asset['name']} failed: {type(error).__name__}") from None
        return target, written


def github_mirror_of(push_mirrors, github_owner, repository):
    wanted = f"github.com/{github_owner}/{repository}".lower()
    matches = [mirror for mirror in push_mirrors
               if (mirror.get("remote_address") or "").lower().removesuffix(".git").endswith(wanted)]
    return matches[0] if matches else None


class GitHubApp:
    def __init__(self, api, owner, app_id, installation_id, private_key):
        self.api = api.rstrip("/")
        self.owner = owner
        self.app_id = app_id
        self.installation_id = installation_id
        self.private_key = private_key

    def repository(self, name):
        app_jwt = github_app_jwt(self.app_id, self.private_key, time.time())
        status, body = http_json(
            "POST", f"{self.api}/app/installations/{self.installation_id}/access_tokens",
            headers=github_headers(app_jwt),
            body={"repositories": [name], "permissions": {"contents": "write"}})
        if status in (404, 422):
            raise NoAppAccess(f"the App installation does not cover {self.owner}/{name} with contents write ({status})")
        if status != 201 or not body or "token" not in body:
            raise ReconcilerFailure(f"GitHub refused an installation token for {self.owner}/{name} ({status})")
        forbid_in_output(body["token"])
        return GitHubRepository(self.api, self.owner, name, body["token"])


def github_headers(bearer):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


class GitHubRepository:
    def __init__(self, api, owner, name, token):
        self.api = api
        self.owner = owner
        self.name = name
        self.token = token
        self.created_release_ids = set()

    def call(self, method, path, body=None):
        return http_json(method, f"{self.api}/repos/{self.owner}/{self.name}{path}",
                         headers=github_headers(self.token), body=body)

    def get(self, path):
        status, body = self.call("GET", path)
        if status != 200:
            raise ReconcilerFailure(f"GitHub GET {self.owner}/{self.name}{path} returned {status}")
        return body

    def pages(self, path):
        items = []
        for page in range(1, MAX_PAGES + 1):
            batch = self.get(f"{path}?per_page={PAGE_SIZE_GITHUB}&page={page}") or []
            items.extend(batch)
            if len(batch) < PAGE_SIZE_GITHUB:
                return items
        raise ReconcilerFailure(f"GitHub GET {path} has more than {MAX_PAGES} pages")

    def create_draft_release(self, release):
        status, body = self.call("POST", "/releases", body={
            "tag_name": release["tag_name"],
            "name": release.get("name") or release["tag_name"],
            "body": release.get("body") or "",
            "draft": True,
            "prerelease": bool(release.get("prerelease")),
        })
        if status != 201 or not body or "id" not in body:
            raise ReconcilerFailure(f"GitHub refused release {release['tag_name']} on {self.owner}/{self.name} ({status})")
        self.created_release_ids.add(body["id"])
        return body

    def upload_asset(self, created, name, path, size):
        upload_url = created["upload_url"].split("{", 1)[0]
        url = f"{upload_url}?name={urllib.parse.quote(name)}"
        headers = {**github_headers(self.token), "Content-Type": "application/octet-stream",
                   "Content-Length": str(size)}
        with open(path, "rb") as handle:
            status, _ = http_raw("POST", url, headers=headers, data=handle, timeout=600)
        if status != 201:
            raise ReconcilerFailure(f"GitHub refused asset {name} on {self.owner}/{self.name} ({status})")

    def own_release(self, release_id):
        if release_id not in self.created_release_ids:
            raise ReconcilerFailure(f"refusing to change GitHub release {release_id}: this run did not create it")

    def publish(self, release_id, make_latest):
        self.own_release(release_id)
        status, _ = self.call("PATCH", f"/releases/{release_id}",
                              body={"draft": False, "make_latest": "true" if make_latest else "false"})
        if status != 200:
            raise ReconcilerFailure(f"GitHub refused to publish release {release_id} on {self.owner}/{self.name} ({status})")

    def discard(self, release_id):
        self.own_release(release_id)
        self.call("DELETE", f"/releases/{release_id}")
        self.created_release_ids.discard(release_id)

    def revoke(self):
        http_json("DELETE", f"{self.api}/installation/token", headers=github_headers(self.token))


def newest_stable_tag(releases):
    stable = [release for release in releases if not release.get("draft") and not release.get("prerelease")]
    if not stable:
        return None
    return max(stable, key=lambda release: release.get("created_at") or "")["tag_name"]


def copy_release(github, forgejo, release, make_latest, scratch, max_asset_bytes):
    created = github.create_draft_release(release)
    try:
        for asset in release.get("assets") or []:
            with tempfile.TemporaryDirectory(dir=scratch) as directory:
                path, size = forgejo.download(asset, directory, max_asset_bytes)
                github.upload_asset(created, asset["name"], path, size)
        if not release.get("draft"):
            github.publish(created["id"], make_latest)
    except Exception:
        github.discard(created["id"])
        raise


def reconcile_mirror(config, forgejo, app, github_repository, forgejo_repository, metrics, copy_budget):
    labels = {"repository": forgejo_repository}
    metrics.set("tracked", labels, 1)

    source = forgejo.get(f"/repos/{forgejo.owner}/{forgejo_repository}")
    source_branch = source["default_branch"]
    source_head = forgejo.get(f"/repos/{forgejo.owner}/{forgejo_repository}/branches/{urllib.parse.quote(source_branch, safe='')}")["commit"]["id"]

    push_mirrors = forgejo.push_mirrors(forgejo_repository)
    if push_mirrors is None:
        metrics.set("push_status_known", labels, 0)
    else:
        metrics.set("push_status_known", labels, 1)
        mirror = github_mirror_of(push_mirrors, config["github_owner"], github_repository)
        metrics.set("push_mirror_configured", labels, 1 if mirror else 0)
        if mirror:
            metrics.set("error", labels, 1 if (mirror.get("last_error") or "").strip() else 0)
            metrics.set("last_update_timestamp_seconds", labels, timestamp_seconds(mirror.get("last_update")))
            metrics.set("interval_seconds", labels, go_duration_seconds(mirror.get("interval")))

    try:
        github = app.repository(github_repository)
    except NoAppAccess as missing:
        log(f"{forgejo_repository}: {missing}")
        metrics.set("app_access", labels, 0)
        return 0
    metrics.set("app_access", labels, 1)

    try:
        target = github.get("")
        target_head = github.get(f"/branches/{urllib.parse.quote(source_branch, safe='')}")["commit"]["sha"]
        metrics.set("head_match", labels, 1 if target_head == source_head and target.get("default_branch") == source_branch else 0)

        source_tags = {tag["name"] for tag in forgejo.pages(f"/repos/{forgejo.owner}/{forgejo_repository}/tags")}
        target_tags = {tag["name"] for tag in github.pages("/tags")}
        metrics.set("tags_missing", labels, len(source_tags - target_tags))

        source_releases = forgejo.pages(f"/repos/{forgejo.owner}/{forgejo_repository}/releases")
        target_release_tags = {release["tag_name"] for release in github.pages("/releases")}
        source_release_tags = {release["tag_name"] for release in source_releases}
        missing = sorted((release for release in source_releases if release["tag_name"] not in target_release_tags),
                         key=lambda release: release.get("created_at") or "")
        metrics.set("releases_missing_before", labels, len(missing))
        metrics.set("releases_extra", labels, len(target_release_tags - source_release_tags))

        latest_tag = newest_stable_tag(source_releases)
        copied = 0
        failed = 0
        writable = not target.get("archived")
        for release in missing:
            if copied >= copy_budget or not writable:
                break
            if release["tag_name"] not in target_tags:
                continue
            try:
                copy_release(github, forgejo, release, release["tag_name"] == latest_tag, config["scratch"],
                             config["max_asset_bytes"])
                copied += 1
                log(f"{forgejo_repository}: copied release {release['tag_name']} to {config['github_owner']}/{github_repository}")
            except ReconcilerFailure as failure:
                failed += 1
                log(f"{forgejo_repository}: release {release['tag_name']} not copied: {failure}")
        metrics.set("releases_copied", labels, copied)
        metrics.set("releases_copy_failed", labels, failed)
        metrics.set("releases_missing", labels, len(missing) - copied)
        return copied
    finally:
        github.revoke()


def public_github_repositories(api, owner):
    repositories = []
    for page in range(1, MAX_PAGES + 1):
        status, batch = http_json("GET", f"{api.rstrip('/')}/orgs/{owner}/repos?type=public&per_page={PAGE_SIZE_GITHUB}&page={page}",
                                  headers=github_headers(None))
        if status != 200 or batch is None:
            return None
        repositories.extend(batch)
        if len(batch) < PAGE_SIZE_GITHUB:
            return repositories
    return None


def report_model_drift(config, forgejo, github_entries, metrics):
    owner = config["github_owner"]
    modelled_github = {key.split("/", 1)[1] for key in github_entries if key.split("/", 1)[0] == owner}
    modelled_sources = {entry["mirror_of"] for key, entry in github_entries.items()
                        if key.split("/", 1)[0] == owner and entry["mirror_of"]}
    forgejo_repositories = forgejo.pages(f"/orgs/{forgejo.owner}/repos")
    forgejo_sources = {repository["name"] for repository in forgejo_repositories if not repository.get("mirror")}

    github_repositories = public_github_repositories(config["github_public_api"], owner)
    if github_repositories is None:
        metrics.set("model_drift_known", {"forge": "github"}, 0)
    else:
        metrics.set("model_drift_known", {"forge": "github"}, 1)
        for repository in github_repositories:
            if repository.get("fork") or repository["name"] not in forgejo_sources:
                continue
            drifted = repository["name"] not in modelled_github
            metrics.set("model_drift", {"forge": "github", "repository": repository["name"]}, 1 if drifted else 0)

    if not forgejo.token:
        metrics.set("model_drift_known", {"forge": "forgejo"}, 0)
        return
    known = True
    for name in sorted(forgejo_sources):
        push_mirrors = forgejo.push_mirrors(name)
        if push_mirrors is None:
            known = False
            continue
        if github_mirror_of(push_mirrors, owner, name) is None:
            continue
        metrics.set("model_drift", {"forge": "forgejo", "repository": name}, 0 if name in modelled_sources else 1)
    metrics.set("model_drift_known", {"forge": "forgejo"}, 1 if known else 0)


def read_optional(path):
    try:
        with open(path) as handle:
            value = handle.read().strip()
    except (FileNotFoundError, IsADirectoryError):
        value = ""
    forbid_in_output(value)
    return value


def load_app(config):
    vault = OpenBao(config["vault_addr"], config["vault_role"], config["service_account_token"])
    app = vault.read_kv(vault.login(), config["app_secret_path"])
    app_id = str(app.get("app_id") or "").strip()
    installation_id = str(app.get("installation_id") or "").strip()
    private_key = str(app.get("private_key") or "")
    forbid_in_output(private_key)
    if not (app_id and installation_id and private_key.strip()):
        raise CredentialsAbsent(f"secret/{config['app_secret_path']} lacks app_id, installation_id or private_key")
    return GitHubApp(config["github_api"], config["github_owner"], app_id, installation_id, private_key)


def read_config():
    return {
        "forgejo_url": env("FORGEJO_URL"),
        "forgejo_owner": env("FORGEJO_OWNER", "webgrip"),
        "forgejo_token_path": env("FORGEJO_TOKEN_PATH"),
        "model_repository": env("MODEL_REPOSITORY", "homelab-cluster"),
        "model_path": env("MODEL_PATH", "kubernetes/apps/repo-config/repo-config/model/repos.yaml"),
        "model_ref": env("MODEL_REF", "main"),
        "github_owner": env("GITHUB_OWNER", "webgrip"),
        "github_api": env("GITHUB_API", "https://api.github.com"),
        "github_public_api": env("GITHUB_PUBLIC_API", os.environ.get("GITHUB_API") or "https://api.github.com"),
        "vault_addr": env("VAULT_ADDR"),
        "vault_role": env("VAULT_ROLE"),
        "app_secret_path": env("APP_SECRET_PATH"),
        "service_account_token": env("SERVICE_ACCOUNT_TOKEN_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/token"),
        "metrics_url": os.environ.get("METRICS_URL", ""),
        "copy_budget": int(env("MAX_RELEASE_COPIES_PER_RUN", "25")),
        "max_asset_bytes": int(env("MAX_ASSET_BYTES", str(1 << 30))),
        "scratch": env("SCRATCH_DIR", tempfile.gettempdir()),
    }


def run():
    config = read_config()
    metrics = Metrics()
    metrics.set("reconciler_run_timestamp_seconds", {}, int(time.time()))
    forgejo_token = read_optional(config["forgejo_token_path"])
    metrics.set("credentials_present", {"credential": "forgejo_token"}, 1 if forgejo_token else 0)
    forgejo = Forgejo(config["forgejo_url"], config["forgejo_owner"], forgejo_token)

    try:
        github_entries = model_github_entries(
            forgejo.raw_file(config["model_repository"], config["model_path"], config["model_ref"]))
        mirrors = tracked_mirrors(github_entries, config["github_owner"])
        metrics.set("model_tracked_mirrors", {}, len(mirrors))

        try:
            app = load_app(config)
        except CredentialsAbsent as absent:
            log(f"GitHub App credentials absent: {absent}; nothing read from or written to GitHub."
                " Owner step: docs/techdocs/docs/runbooks/github-mirrors.md")
            metrics.set("credentials_present", {"credential": "github_app"}, 0)
            metrics.set("reconciler_last_success_timestamp_seconds", {}, int(time.time()))
            return 0
        metrics.set("credentials_present", {"credential": "github_app"}, 1)

        failures = 0
        budget = config["copy_budget"]
        for github_repository, forgejo_repository in mirrors:
            try:
                budget -= reconcile_mirror(config, forgejo, app, github_repository, forgejo_repository, metrics, budget)
                metrics.set("check_ok", {"repository": forgejo_repository}, 1)
            except ReconcilerFailure as failure:
                failures += 1
                metrics.set("check_ok", {"repository": forgejo_repository}, 0)
                log(f"{forgejo_repository}: check failed: {failure}")

        try:
            report_model_drift(config, forgejo, github_entries, metrics)
        except ReconcilerFailure as failure:
            failures += 1
            log(f"model drift check failed: {failure}")

        if failures:
            log(f"{failures} check(s) failed")
            return 1
        metrics.set("reconciler_last_success_timestamp_seconds", {}, int(time.time()))
        log(f"checked {len(mirrors)} tracked mirror(s)")
        return 0
    finally:
        metrics.push(config["metrics_url"])


def main():
    sys.stdout = stdout
    sys.stderr = stderr
    try:
        return run()
    except ReconcilerFailure as failure:
        log(f"reconciler failed: {failure}")
        return 1
    except Exception as unexpected:
        log(f"reconciler failed with an unexpected {type(unexpected).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
