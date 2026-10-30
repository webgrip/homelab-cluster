import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "webgrip-repo-config-inventory"
METRIC_PREFIX = "repo_config_"
PAGE_SIZE = 50
MAX_PAGES = 100

MODEL_ENTRY = re.compile(r'^  (?P<quote>"?)(?P<key>[^"\s#][^"]*?)(?P=quote):\s*$')
MODEL_FIELD = re.compile(r"^    (?P<field>[a-z_]+):\s*(?P<value>.*?)\s*$")
MODEL_SETTING = re.compile(r"^      (?P<field>[a-z_]+):\s*(?P<value>.*?)\s*$")
MODEL_FACTS = ("forge", "kind", "staged", "core", "mirror_of")

SHARED_PACKAGES = ("workflows", "renovate-config", "agent-standards", "semantic-release-config")
UNVERSIONED = "unversioned"
TAG_PAGES = 10
WORKFLOW_DIRECTORIES = (".forgejo/workflows", ".github/workflows")
RENOVATE_FILES = ("renovate.json", "renovate.json5", ".renovaterc.json", ".forgejo/renovate.json",
                  ".github/renovate.json")
RENOVATE_GATES = ("profile-app", "profile-site", "profile-library", "profile-image-set")
STABLE_TAG = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
RENOVATE_PRESET = re.compile(
    r"local>webgrip/renovate-config(?::(?P<preset>[\w-]+))?(?:#(?P<version>v\d+\.\d+\.\d+))?")
WORKFLOW_CALL = re.compile(
    r"uses:\s*[\"']?(?:https://[^/\s]+/)?webgrip/workflows/\.(?:forgejo|github)/workflows/"
    r"(?P<workflow>[\w.-]+?)\.ya?ml@[^\s\"']+[\"']?(?:[ \t]*#[ \t]*(?P<version>v\d+\.\d+\.\d+))?")
AGENT_STANDARDS_PIN = re.compile(
    r"git:\s*https://forgejo\.webgrip\.dev/webgrip/agent-standards(?:\.git)?\s*\n\s*path:\s*\S+\s*\n"
    r"\s*ref:\s*(?P<version>v\d+\.\d+\.\d+)"
    r"|agent-standards\.git@(?P<cli>v\d+\.\d+\.\d+)#subdirectory=cli")
RELEASE_CONFIG_PIN = re.compile(r'"@webgrip/semantic-release-config"\s*:\s*"[\^~=]?(?P<version>\d+\.\d+\.\d+)"')
SHIPS_BY_WORKFLOW = {
    "cloudflare-deploy": "cloudflare",
    "docker-build-and-push": "image",
    "docker-build-and-push-registry": "image",
    "docker-build-and-push-registry-fast": "image",
    "helm-chart-push": "chart",
    "helm-chart-deploy": "chart",
    "helm-charts-deploy": "chart",
    "techdocs-deploy-docs-site": "docs",
    "techdocs-deploy-backstage-s3": "docs",
}
SHIPS_BY_STEP = {
    "cloudflare": re.compile(r"wrangler(?:@[\w.-]+)?\s+(?:pages\s+)?deploy|cloudflare/wrangler-action"),
    "image": re.compile(r"docker/build-push-action|buildah\s+(?:bud|push)|kaniko|docker\s+push|crane\s+push"),
    "chart": re.compile(r"helm\s+push|helm-push"),
    "npm": re.compile(r"(?:npm|pnpm|yarn)\s+publish"),
}
OWN_RELEASE = re.compile(r"semantic-release|knope\s+release")
REUSABLE_DEFINITION = re.compile(r"^\s*workflow_call\s*:", re.M)


class InventoryFailure(Exception):
    pass


def log(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def env(name, default=None):
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise InventoryFailure(f"environment variable {name} is required")
    return value


def read_file(path):
    try:
        with open(path) as handle:
            return handle.read()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return ""


def model_forgejo_entries(model_text):
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
            entries[key] = {"forge": None, "archived": False, "private": False}
            continue
        if key is None:
            continue
        field = MODEL_FIELD.match(line)
        if field:
            section = field.group("field")
            if section == "forge":
                entries[key]["forge"] = field.group("value").strip('"')
            continue
        setting = MODEL_SETTING.match(line)
        if setting and section == "settings" and setting.group("field") in ("archived", "private"):
            entries[key][setting.group("field")] = setting.group("value") == "true"
    return {key: entry for key, entry in entries.items() if entry["forge"] == "forgejo"}


def model_facts(model_text):
    facts = {}
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
            facts[key] = {"archived": False, "renovate_absent": False}
            continue
        if key is None:
            continue
        field = MODEL_FIELD.match(line)
        if field:
            section = field.group("field")
            if section in MODEL_FACTS:
                facts[key][section] = field.group("value").strip('"')
            continue
        setting = MODEL_SETTING.match(line)
        if not setting:
            continue
        if section == "settings" and setting.group("field") == "archived":
            facts[key]["archived"] = setting.group("value") == "true"
        if section == "renovate" and setting.group("field") == "absent":
            facts[key]["renovate_absent"] = setting.group("value") == "true"
    return facts


def github_mirrors(facts):
    return sorted({fact["mirror_of"] for fact in facts.values()
                   if fact.get("forge") == "github" and fact.get("mirror_of") and not fact["archived"]})


def active_sources(repositories):
    return sorted(repository["name"] for repository in repositories
                  if not repository.get("archived") and not repository.get("mirror"))


def unmodelled(active, modelled):
    return sorted(set(active) - set(modelled))


def private_repositories_expected(entries):
    return sorted(name for name, entry in entries.items() if entry["private"] and not entry["archived"])


def list_org_repositories(forgejo_url, owner, token):
    repositories = []
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Authorization": f"token {token}"}
    path = f"/api/v1/orgs/{owner}/repos"
    for page in range(1, MAX_PAGES + 1):
        request = urllib.request.Request(f"{forgejo_url.rstrip('/')}{path}?limit={PAGE_SIZE}&page={page}",
                                         headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.loads(response.read() or b"[]")
        except urllib.error.HTTPError as error:
            raise InventoryFailure(f"Forgejo GET {path} page {page} returned {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise InventoryFailure(f"Forgejo GET {path} page {page} failed: {type(error).__name__}") from None
        if not isinstance(batch, list):
            raise InventoryFailure(f"Forgejo GET {path} page {page} did not return a list")
        if not batch:
            return repositories
        repositories.extend(batch)
    raise InventoryFailure(f"Forgejo GET {path} has more than {MAX_PAGES} pages")


class Forgejo:
    def __init__(self, url, owner, token):
        self.base = f"{url.rstrip('/')}/api/v1"
        self.owner = owner
        self.headers = {"User-Agent": USER_AGENT, "Authorization": f"token {token}"}

    def get(self, path):
        request = urllib.request.Request(f"{self.base}{path}", headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise InventoryFailure(f"Forgejo GET {path} returned {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise InventoryFailure(f"Forgejo GET {path} failed: {type(error).__name__}") from None

    def raw(self, repository, path):
        body = self.get(f"/repos/{self.owner}/{repository}/raw/{urllib.parse.quote(path)}")
        return None if body is None else body.decode(errors="replace")

    def listing(self, repository, directory):
        body = self.get(f"/repos/{self.owner}/{repository}/contents/{urllib.parse.quote(directory)}")
        if body is None:
            return []
        entries = json.loads(body)
        if not isinstance(entries, list):
            return []
        return [entry["path"] for entry in entries
                if entry.get("type") == "file" and entry.get("name", "").endswith((".yml", ".yaml"))]

    def stable_tags(self, repository):
        tags = []
        for page in range(1, TAG_PAGES + 1):
            body = self.get(f"/repos/{self.owner}/{repository}/tags?limit={PAGE_SIZE}&page={page}")
            batch = json.loads(body) if body else []
            if not batch:
                break
            tags.extend(tag["name"] for tag in batch if STABLE_TAG.match(tag.get("name", "")))
        return sorted({version_key(tag): normalise(tag) for tag in tags}.values(), key=version_key)


def latest_releases(forgejo, package):
    try:
        return forgejo.stable_tags(package)
    except (InventoryFailure, ValueError) as failure:
        log(f"could not read the releases of {package}: {failure}")
        return []


def version_key(version):
    match = STABLE_TAG.match(version)
    return int(match.group("major")), int(match.group("minor")), int(match.group("patch"))


def normalise(version):
    return version if version.startswith("v") else f"v{version}"


def renovate_reading(text):
    if text is None:
        return {"gate": "none", "pins": set()}
    presets = [match.group("preset") or "default" for match in RENOVATE_PRESET.finditer(text)]
    pins = {match.group("version") or UNVERSIONED for match in RENOVATE_PRESET.finditer(text)}
    gates = [preset for preset in presets if preset in RENOVATE_GATES]
    if gates:
        gate = gates[0].removeprefix("profile-")
    elif presets:
        gate = "presets"
    else:
        gate = "own"
    return {"gate": gate, "pins": pins}


def workflow_reading(texts):
    calls, pins, ships, own_release = set(), set(), set(), False
    for text in texts:
        for match in WORKFLOW_CALL.finditer(text):
            calls.add(match.group("workflow"))
            pins.add(match.group("version") or UNVERSIONED)
        if REUSABLE_DEFINITION.search(text):
            continue
        for ship, pattern in SHIPS_BY_STEP.items():
            if pattern.search(text):
                ships.add(ship)
        own_release = own_release or bool(OWN_RELEASE.search(WORKFLOW_CALL.sub("", text)))
    ships.update(SHIPS_BY_WORKFLOW[call] for call in calls if call in SHIPS_BY_WORKFLOW)
    if calls & {"semantic-release", "semantic-release-monorepo"}:
        releases = "shared semantic-release"
    elif own_release:
        releases = "own semantic-release"
    else:
        releases = "none"
    return {"calls": calls, "pins": pins, "ships": ships, "releases": releases}


def scan_repository(forgejo, name):
    renovate_text = None
    for path in RENOVATE_FILES:
        renovate_text = forgejo.raw(name, path)
        if renovate_text is not None:
            break
    workflow_texts = [forgejo.raw(name, path) or "" for directory in WORKFLOW_DIRECTORIES
                      for path in forgejo.listing(name, directory)]
    agent_texts = [forgejo.raw(name, "apm.yml") or "", forgejo.raw(name, "mise.toml") or ""]
    package_text = forgejo.raw(name, "package.json") or ""
    renovate = renovate_reading(renovate_text)
    workflows = workflow_reading(workflow_texts)
    agent_pins = {match.group("version") or match.group("cli")
                  for text in agent_texts for match in AGENT_STANDARDS_PIN.finditer(text)}
    release_config_pins = {normalise(match.group("version")) for match in RELEASE_CONFIG_PIN.finditer(package_text)}
    return {
        "gate": renovate["gate"],
        "calls": workflows["calls"],
        "ships": workflows["ships"],
        "releases": workflows["releases"],
        "pins": {
            "workflows": workflows["pins"],
            "renovate-config": renovate["pins"],
            "agent-standards": agent_pins,
            "semantic-release-config": release_config_pins,
        },
    }


def releases_behind(pins, stable):
    versioned = [pin for pin in pins if pin != UNVERSIONED and STABLE_TAG.match(pin)]
    if not versioned or not stable:
        return None
    oldest = min(versioned, key=version_key)
    return sum(1 for tag in stable if version_key(tag) > version_key(oldest))


def pin_cell(pins, behind):
    if not pins:
        return "-"
    text = ", ".join(sorted(pins, key=lambda pin: version_key(pin) if STABLE_TAG.match(pin) else (-1, 0, 0)))
    if behind:
        return f"{text} · {behind} behind"
    return text


def label_name(package):
    return package.replace("-", "_")


def record_scans(metrics, active, facts, mirrors, scans, latest):
    for package, stable in latest.items():
        if stable:
            metrics.set("shared_latest", {"package": package, "version": stable[-1]}, 1)
    for name in active:
        fact = facts.get(name, {})
        scan = scans.get(name)
        labels = {
            "repository": name,
            "kind": fact.get("kind") or ("unset" if name in facts else "unmodelled"),
            "branching": "staged" if fact.get("staged") == "true" else "trunk",
            "core": "yes" if fact.get("core") == "true" else "no",
            "github_mirror": "yes" if name in mirrors else "no",
        }
        if scan is None:
            labels.update({"renovate_gate": "unread", "releases": "unread", "ships": "unread", "workflow_calls": "0"})
            labels.update({label_name(package): "unread" for package in SHARED_PACKAGES})
            metrics.set("repository_info", labels, 1)
            metrics.set("scan_failed", {"repository": name}, 1)
            continue
        metrics.set("scan_failed", {"repository": name}, 0)
        labels.update({"renovate_gate": scan["gate"], "releases": scan["releases"],
                       "ships": ", ".join(sorted(scan["ships"])) or "nothing",
                       "workflow_calls": str(len(scan["calls"]))})
        for package in SHARED_PACKAGES:
            pins = scan["pins"][package]
            behind = releases_behind(pins, latest.get(package, []))
            labels[label_name(package)] = pin_cell(pins, behind)
            if behind is not None:
                metrics.set("shared_pin_releases_behind", {"repository": name, "package": package}, behind)
            if UNVERSIONED in pins:
                metrics.set("shared_pin_unversioned", {"repository": name, "package": package}, 1)
        for call in sorted(scan["calls"]):
            metrics.set("workflow_call", {"repository": name, "workflow": call}, 1)
        metrics.set("repository_info", labels, 1)


def escape_label(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


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
        request = urllib.request.Request(url, data=self.render().encode(), method="POST",
                                         headers={"Content-Type": "text/plain", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise InventoryFailure(f"metrics push failed: {type(error).__name__}") from None
        if status >= 300:
            raise InventoryFailure(f"metrics push returned {status}")


def run():
    forgejo_url = env("FORGEJO_URL")
    owner = env("FORGEJO_OWNER", "webgrip")
    metrics_url = env("METRICS_URL")
    token = read_file(env("FORGEJO_TOKEN_PATH")).strip()
    if not token:
        raise InventoryFailure("the read-only Forgejo token is absent; an anonymous read would miss private repositories")

    entries = model_forgejo_entries(read_file(env("MODEL_PATH")))
    if not entries:
        raise InventoryFailure("the model lists no Forgejo repository; the model ConfigMap is missing or unreadable")

    repositories = list_org_repositories(forgejo_url, owner, token)
    visible_private = sorted(repository["name"] for repository in repositories if repository.get("private"))
    expected_private = private_repositories_expected(entries)
    if expected_private and not visible_private:
        raise InventoryFailure(
            f"the token sees no private repository although the model has {len(expected_private)};"
            " it lacks read:repository or team membership")

    active = active_sources(repositories)
    missing = unmodelled(active, entries)
    metrics = Metrics()
    for name in active:
        metrics.set("unmodelled_repository", {"repository": name}, 1 if name in missing else 0)
    forgejo = Forgejo(forgejo_url, owner, token)
    facts = model_facts(read_file(env("MODEL_PATH")))
    latest = {package: latest_releases(forgejo, package) for package in SHARED_PACKAGES}
    scans = {}
    for name in active:
        try:
            scans[name] = scan_repository(forgejo, name)
        except (InventoryFailure, ValueError) as failure:
            log(f"could not read the delivery files of {name}: {failure}")
    record_scans(metrics, active, facts, github_mirrors(facts), scans, latest)
    metrics.set("inventory_scan_failed_repositories", {}, len(active) - len(scans))
    metrics.set("inventory_active_repositories", {}, len(active))
    metrics.set("inventory_private_repositories_visible", {}, len(visible_private))
    metrics.set("inventory_unmodelled_repositories", {}, len(missing))
    metrics.set("inventory_last_success_timestamp_seconds", {}, int(time.time()))
    metrics.push(metrics_url)

    log(f"read {len(repositories)} repositories in {owner}: {len(active)} active, {len(visible_private)} private")
    if missing:
        log(f"outside the repo-config model: {', '.join(missing)}")
    else:
        log("every active repository is in the repo-config model")
    return 0


def main():
    try:
        return run()
    except InventoryFailure as failure:
        log(f"inventory failed: {failure}")
        return 1
    except Exception as unexpected:
        log(f"inventory failed with an unexpected {type(unexpected).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
