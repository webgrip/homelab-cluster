import datetime
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
RENOVATE_GATES = ("reviewed", "unattended")
STABLE_TAG = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
RENOVATE_PRESET = re.compile(
    r"local>webgrip/renovate-config(?::(?P<preset>[\w-]+))?(?:#(?P<version>v\d+\.\d+\.\d+))?")
SHARED_CALL = re.compile(
    r"uses:[ \t]*[\"']?(?:https://[^/\s]+/)?webgrip/workflows/\.(?:forgejo|github)/"
    r"(?:workflows/(?P<workflow>[\w.-]+?)\.ya?ml|composite-actions/(?P<action>[\w.-]+?))"
    r"@(?P<ref>[^\s\"'#]+)[\"']?(?P<rest>[^\n]*)")
SEMVER_REF = re.compile(r"^v\d+\.\d+\.\d+$")
SHA_REF = re.compile(r"^[0-9a-f]{40}$")
PIN_COMMENT = re.compile(r"^[ \t]+#[ \t]*(?P<version>v\d+\.\d+\.\d+)(?:\s|$)")
LOCAL_ACTION = re.compile(r"uses:[ \t]*[\"']?\./(?P<path>[\w./-]+?)/?[\"']?[ \t]*$", re.M)
LOCAL_ACTION_FILES = ("action.yml", "action.yaml")
RELEASE_IMAGE_PIN = re.compile(
    r"(?:^|\s)(?:image|toolchain-image|container)[ \t]*:[ \t]*[\"']?"
    r"harbor\.webgrip\.dev/webgrip/semantic-release:v?(?P<version>\d+\.\d+\.\d+)(?![\w.-])", re.M)
FIRST_CONFIG_RELEASE = (1, 0, 0)
AGENT_STANDARDS_PIN = re.compile(
    r"git:\s*https://forgejo\.webgrip\.dev/webgrip/agent-standards(?:\.git)?\s*\n\s*path:\s*\S+\s*\n"
    r"\s*ref:\s*(?P<version>v\d+\.\d+\.\d+)"
    r"|agent-standards\.git@(?P<cli>v\d+\.\d+\.\d+)#subdirectory=cli")
RELEASE_CONFIG_PIN = re.compile(r'"@webgrip/semantic-release-config"\s*:\s*"[\^~=]?(?P<version>\d+\.\d+\.\d+)"')
SHIPS_BY_CALL = {
    "cloudflare-deploy": "cloudflare",
    "docker-build-and-push": "image",
    "docker-build-and-push-ghcr": "image",
    "docker-build-and-push-harbor": "image",
    "docker-build-and-push-harbor-fast": "image",
    "docker-build-and-push-registry": "image",
    "docker-build-and-push-registry-fast": "image",
    "docker-build-push": "image",
    "docker-build-push-registry": "image",
    "docker-build-push-registry-fast": "image",
    "helm-chart-push": "chart",
    "helm-charts-push": "chart",
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
OWN_RELEASE = re.compile(r"(?:^|[\s;&|(\"'`]|\.bin/)semantic-release(?=[\s;&|)\"'`]|$)|knope\s+release", re.M)
WEBGRIP_RELEASE = re.compile(r"bin/webgrip-release\b|^[ \t]*(?:-[ \t]*)?(?:run:[ \t]*)?(?:npx[ \t]+)?webgrip-release(?=[\s\"']|$)",
                             re.M)
COMMENT_LINE = re.compile(r"^[ \t]*#.*$", re.M)
OLD_RELEASE_CALLS = {"semantic-release-monorepo"}
SHARED_RELEASE_CALLS = {"semantic-release"}
RELEASE_WEBGRIP = "webgrip-release"
RELEASE_SHARED = "shared semantic-release"
RELEASE_OLD_MONOREPO = "monorepo (old path)"
RELEASE_OWN = "own semantic-release"
RELEASE_NONE = "none"

PULL_PAGES = 10
RENOVATE_BRANCH = "renovate/"
DEPENDENCY_PACKAGES = {
    "webgrip/workflows": "workflows",
    "webgrip/renovate-config": "renovate-config",
    "webgrip/agent-standards": "agent-standards",
    "@webgrip/semantic-release-config": "semantic-release-config",
    "harbor.webgrip.dev/webgrip/semantic-release": "semantic-release-config",
}
FORGE_PREFIX = re.compile(r"^(?:https?://)?forgejo\.webgrip\.dev/")
ARROW = r"(?:→|➔|->)"
UPDATE_ROW = re.compile(
    r"^\|[ \t]*\[?(?P<dependency>[^\]|\n]+?)\]?(?:\([^)\n]*\))?[ \t]*\|(?:[^|`\n]*\|){1,2}[ \t]*"
    r"`[^`\n]*`[ \t]*" + ARROW + r"[ \t]*`(?P<version>[^`\n]+)`", re.M)
UPDATE_TITLE = re.compile(
    r"[Uu]pdate\s+(?:dependency\s+)?(?P<dependency>\S+)(?:\s+(?:Docker\s+tag|action))?\s+"
    r"(?:\(\s*\S+\s*" + ARROW + r"\s*(?P<version>[^\s)]+)\s*\)|to\s+(?P<to>\S+))")
DASHBOARD_TITLE = "Dependency Dashboard"
DASHBOARD_LINE = re.compile(r"<!--\s*(?P<action>[a-z]+)-branch=\S+\s*-->(?P<title>[^\n]*)")
DASHBOARD_HAS_A_PULL = ("rebase", "retry", "recreate")
CHECK_STATES = {"success": "pr_green", "failure": "pr_red", "error": "pr_red"}
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

    def open_pulls(self, repository):
        pulls = []
        for page in range(1, PULL_PAGES + 1):
            body = self.get(f"/repos/{self.owner}/{repository}/pulls?state=open&limit={PAGE_SIZE}&page={page}")
            batch = json.loads(body) if body else []
            if not isinstance(batch, list) or not batch:
                break
            pulls.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        return pulls

    def check_state(self, repository, sha):
        body = self.get(f"/repos/{self.owner}/{repository}/commits/{sha}/status")
        return (json.loads(body) or {}).get("state", "") if body else ""

    def dependency_dashboard(self, repository):
        query = urllib.parse.quote(DASHBOARD_TITLE)
        body = self.get(f"/repos/{self.owner}/{repository}/issues?state=open&type=issues&q={query}&limit=10")
        issues = json.loads(body) if body else []
        for issue in issues if isinstance(issues, list) else []:
            if DASHBOARD_TITLE in (issue.get("title") or ""):
                return issue.get("body") or ""
        return ""


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
        gate = gates[0]
    elif presets:
        gate = "presets"
    else:
        gate = "own"
    return {"gate": gate, "pins": pins}


def call_pin(ref, rest):
    if SEMVER_REF.match(ref):
        return ref
    comment = PIN_COMMENT.match(rest)
    if SHA_REF.match(ref) and comment:
        return comment.group("version")
    return UNVERSIONED


def release_image_pins(text):
    return {normalise(match.group("version")) for match in RELEASE_IMAGE_PIN.finditer(text)
            if version_key(match.group("version")) >= FIRST_CONFIG_RELEASE}


def release_style(called, runs_webgrip_release, runs_own_release):
    if called & OLD_RELEASE_CALLS:
        return RELEASE_OLD_MONOREPO
    if called & SHARED_RELEASE_CALLS:
        return RELEASE_SHARED
    if runs_webgrip_release:
        return RELEASE_WEBGRIP
    if runs_own_release:
        return RELEASE_OWN
    return RELEASE_NONE


def workflow_reading(texts):
    calls, pins, ships, image_pins, run_calls = set(), set(), set(), set(), set()
    webgrip_release, own_release = False, False
    for text in texts:
        called = set()
        for match in SHARED_CALL.finditer(text):
            if match.group("workflow"):
                called.add(("reusable", match.group("workflow")))
            else:
                called.add(("composite", match.group("action")))
            pins.add(call_pin(match.group("ref"), match.group("rest")))
        calls |= called
        image_pins |= release_image_pins(text)
        if REUSABLE_DEFINITION.search(text):
            continue
        run_calls |= {name for _, name in called}
        for ship, pattern in SHIPS_BY_STEP.items():
            if pattern.search(text):
                ships.add(ship)
        steps = SHARED_CALL.sub("", COMMENT_LINE.sub("", text))
        webgrip_release = webgrip_release or bool(WEBGRIP_RELEASE.search(steps))
        own_release = own_release or bool(OWN_RELEASE.search(steps))
    ships.update(SHIPS_BY_CALL[name] for name in run_calls if name in SHIPS_BY_CALL)
    return {"calls": calls, "pins": pins, "ships": ships, "image_pins": image_pins,
            "releases": release_style(run_calls, webgrip_release, own_release)}


def local_action_texts(forgejo, name, workflow_texts):
    paths = sorted({match.group("path").rstrip("/") for text in workflow_texts
                    for match in LOCAL_ACTION.finditer(text)})
    texts = []
    for path in paths:
        for file in LOCAL_ACTION_FILES:
            text = forgejo.raw(name, f"{path}/{file}")
            if text is not None:
                texts.append(text)
                break
    return texts


def scan_repository(forgejo, name):
    renovate_text = None
    for path in RENOVATE_FILES:
        renovate_text = forgejo.raw(name, path)
        if renovate_text is not None:
            break
    workflow_texts = [forgejo.raw(name, path) or "" for directory in WORKFLOW_DIRECTORIES
                      for path in forgejo.listing(name, directory)]
    workflow_texts += local_action_texts(forgejo, name, workflow_texts)
    agent_texts = [forgejo.raw(name, "apm.yml") or "", forgejo.raw(name, "mise.toml") or ""]
    package_text = forgejo.raw(name, "package.json") or ""
    renovate = renovate_reading(renovate_text)
    workflows = workflow_reading(workflow_texts)
    agent_pins = {match.group("version") or match.group("cli")
                  for text in agent_texts for match in AGENT_STANDARDS_PIN.finditer(text)}
    release_config_pins = {normalise(match.group("version")) for match in RELEASE_CONFIG_PIN.finditer(package_text)}
    release_config_pins |= workflows["image_pins"]
    pins = {
        "workflows": workflows["pins"],
        "renovate-config": renovate["pins"],
        "agent-standards": agent_pins,
        "semantic-release-config": release_config_pins,
    }
    return {
        "gate": renovate["gate"],
        "calls": workflows["calls"],
        "ships": workflows["ships"],
        "releases": workflows["releases"],
        "pins": {package: set() if package == name else found for package, found in pins.items()},
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


def dependency_package(dependency):
    return DEPENDENCY_PACKAGES.get(FORGE_PREFIX.sub("", dependency.strip()))


def proposed_version(text):
    version = text.strip().strip("`")
    return normalise(version) if STABLE_TAG.match(version) else None


def proposed_updates(title, body):
    found = {}
    for dependency, version in ([(m.group("dependency"), m.group("version")) for m in UPDATE_ROW.finditer(body)]
                                or [(m.group("dependency"), m.group("version") or m.group("to"))
                                    for m in UPDATE_TITLE.finditer(title)]):
        package = dependency_package(dependency)
        if package is None:
            continue
        candidate = proposed_version(version)
        if package not in found or (candidate and (found[package] is None or
                                                    version_key(candidate) > version_key(found[package]))):
            found[package] = candidate
    return found


def newest_first(proposal):
    version = proposal["proposed"]
    return (version_key(version) if version else (-1, 0, 0), -proposal["created"])


def epoch(stamp):
    try:
        return int(datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
    except (AttributeError, ValueError):
        return 0


def renovate_proposals(pulls):
    proposals = {}
    for pull in pulls:
        if not ((pull.get("head") or {}).get("ref") or "").startswith(RENOVATE_BRANCH):
            continue
        for package, version in proposed_updates(pull.get("title") or "", pull.get("body") or "").items():
            proposal = {"proposed": version, "pull": pull.get("number"), "created": epoch(pull.get("created_at")),
                        "sha": (pull.get("head") or {}).get("sha")}
            if package not in proposals or newest_first(proposal) > newest_first(proposals[package]):
                proposals[package] = proposal
    return proposals


def dashboard_waits(body):
    waits = {}
    for line in DASHBOARD_LINE.finditer(body):
        if line.group("action") in DASHBOARD_HAS_A_PULL:
            continue
        state = "awaits_approval" if line.group("action") == "approve" else "queued"
        for package, version in proposed_updates(line.group("title"), "").items():
            if package not in waits or state == "awaits_approval":
                waits[package] = {"state": state, "proposed": version}
    return waits


def update_status(forgejo, name, behind_packages, now):
    proposals = renovate_proposals(forgejo.open_pulls(name))
    statuses = {}
    waiting = None
    for package in sorted(behind_packages):
        proposal = proposals.get(package)
        if proposal:
            state = CHECK_STATES.get(forgejo.check_state(name, proposal["sha"]), "pr_pending")
            statuses[package] = {"state": state, "proposed": proposal["proposed"], "pull": proposal["pull"],
                                 "age": max(0, now - proposal["created"]) if proposal["created"] else None}
            continue
        if waiting is None:
            waiting = dashboard_waits(forgejo.dependency_dashboard(name))
        wait = waiting.get(package, {"state": "no_pr", "proposed": None})
        statuses[package] = {"state": wait["state"], "proposed": wait["proposed"], "pull": None, "age": None}
    return statuses


def label_name(package):
    return package.replace("-", "_")


def record_scans(metrics, active, facts, mirrors, scans, latest, updates):
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
        for package, status in sorted(updates.get(name, {}).items()):
            metrics.set("shared_pin_update", {"repository": name, "package": package, "state": status["state"],
                                              "proposed": status["proposed"] or "",
                                              "pull": str(status["pull"] or "")}, 1)
            if status["age"] is not None:
                metrics.set("shared_pin_update_age_seconds", {"repository": name, "package": package}, status["age"])
        for form, call in sorted(scan["calls"]):
            metrics.set("workflow_call", {"repository": name, "workflow": call, "form": form}, 1)
        metrics.set("repository_info", labels, 1)


def behind_packages(scan, latest):
    return {package for package in SHARED_PACKAGES
            if (releases_behind(scan["pins"][package], latest.get(package, [])) or 0) > 0}


def read_update_statuses(forgejo, scans, latest, now):
    updates = {}
    for name, scan in sorted(scans.items()):
        behind = behind_packages(scan, latest)
        if not behind:
            continue
        try:
            updates[name] = update_status(forgejo, name, behind, now)
        except (InventoryFailure, ValueError) as failure:
            log(f"could not read the open updates of {name}: {failure}")
    return updates


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
    updates = read_update_statuses(forgejo, scans, latest, int(time.time()))
    record_scans(metrics, active, facts, github_mirrors(facts), scans, latest, updates)
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
