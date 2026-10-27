import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

USER_AGENT = "webgrip-repo-config-inventory"
METRIC_PREFIX = "repo_config_"
PAGE_SIZE = 50
MAX_PAGES = 100

MODEL_ENTRY = re.compile(r'^  (?P<quote>"?)(?P<key>[^"\s#][^"]*?)(?P=quote):\s*$')
MODEL_FIELD = re.compile(r"^    (?P<field>[a-z_]+):\s*(?P<value>.*?)\s*$")
MODEL_SETTING = re.compile(r"^      (?P<field>[a-z_]+):\s*(?P<value>.*?)\s*$")


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
