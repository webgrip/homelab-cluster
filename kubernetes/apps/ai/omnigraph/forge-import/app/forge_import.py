#!/usr/bin/env python3
import argparse
import base64
import datetime
import hashlib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SLUG_PREFIX = "forge/"
PERSON_PREFIX = "forge/user/"
ORG_PREFIX = "forge/org/"
SAFE_SLUG = re.compile(r"^forge/[a-z0-9._/#-]+$")
PAGE_SIZE = 50
TREE_PAGE_SIZE = 1000
MAX_TEXT_BYTES = 1024 * 1024
PASSAGE_CHARS = 1500
ROWS_PER_LOAD_FILE = 2000
BYTES_PER_LOAD_FILE = 16 * 1024 * 1024
STATEMENTS_PER_PRUNE_FILE = 500
ACTIVE_WITHIN_DAYS = 180
HTTP_TIMEOUT_SECONDS = 60
README_NAMES = ("readme.md", "readme.markdown", "readme", "readme.txt", "readme.rst")
DOC_SUFFIXES = (".md", ".markdown", ".mdx")
ADR_DIRECTORY = re.compile(r"^(adr.*|decisions|decision-records)$")
ADR_FILE = re.compile(r"^adr[-_].*\.(md|markdown|mdx)$")
NOT_A_DECISION = re.compile(r"^(readme|index|template|adr[-_]template)\.(md|markdown|mdx)$")
ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.M)
FRONTMATTER_DATE = re.compile(r"^\s*-?\s*\**date\**\s*:\s*\**\s*(\d{4}-\d{2}-\d{2})", re.I | re.M)

EXIT_OK = 0
EXIT_NO_TOKEN = 3
EXIT_FORGE_FAILED = 4
EXIT_NOTHING_VISIBLE = 5

EDGE_TYPES = ("ProjectForOrganization", "ArtifactForProject", "ArtifactFromPerson", "NoteAboutProject", "NoteFromArtifact")
SINGLE_TARGET_EDGES = frozenset({"ArtifactFromPerson", "NoteFromArtifact"})
NODE_ORDER = ("Organization", "Person", "Project", "Artifact", "Note")
DELETE_ORDER = ("Note", "Artifact", "Project", "Person", "Organization")


class FailClosed(Exception):
    def __init__(self, exit_code, message):
        super().__init__(message)
        self.exit_code = exit_code


class ForgeError(Exception):
    pass


@dataclass
class Counts:
    repos: int = 0
    project_only: int = 0
    orgs: int = 0
    people: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    relinked: int = 0
    passages_written: int = 0
    passages_deleted: int = 0
    blobs_fetched: int = 0
    skipped_large: int = 0
    api_calls: int = 0

    def line(self):
        return " ".join(f"{key}={value}" for key, value in self.__dict__.items())


@dataclass
class Record:
    type: str
    data: dict
    content: str | None = None
    fetch_marker: str | None = None
    keep: bool = False


@dataclass
class Desired:
    records: dict = field(default_factory=dict)
    edges: dict = field(default_factory=dict)
    fetches: dict = field(default_factory=dict)

    def add(self, record):
        self.records[record.data["slug"]] = record

    def link(self, edge, source, target):
        self.edges.setdefault((edge, source), [])
        if target not in self.edges[(edge, source)]:
            self.edges[(edge, source)].append(target)


@dataclass
class Plan:
    counts: Counts
    prune_statements: list
    node_rows: list
    passage_units: list
    edge_rows: list


@dataclass
class Scope:
    owned_upstream_owners: frozenset
    third_party_repos: frozenset
    skip_repos: frozenset


def read_scope(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    lowered = lambda key: frozenset(item.lower() for item in raw.get(key, []))
    return Scope(lowered("owned_upstream_owners"), lowered("third_party_repos"), lowered("skip_repos"))


def read_token(path):
    try:
        token = Path(path).read_text(encoding="utf-8").strip()
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        token = ""
    if not token:
        raise FailClosed(EXIT_NO_TOKEN, "no forge token: the omnigraph-forge-import-forgejo Secret has no token yet; store a read-only Forgejo token at secret/omnigraph/forge-import (field token)")
    return token


class ForgeClient:
    def __init__(self, base_url, token, counts):
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.token = token
        self.counts = counts

    def get(self, path, params=None):
        query = "?" + urllib.parse.urlencode(params) if params else ""
        request = urllib.request.Request(self.base_url + path + query, headers={"Authorization": f"token {self.token}", "Accept": "application/json"})
        self.counts.api_calls += 1
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            error.close()
            if error.code == 401:
                raise ForgeError("forge token rejected (HTTP 401): recreate the read-only token at secret/omnigraph/forge-import") from error
            raise ForgeError(f"forgejo API {path} answered HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ForgeError(f"forgejo API {path} not reachable: {error}") from error

    def pages(self, path, params=None):
        page = 1
        while True:
            batch = self.get(path, dict(params or {}, limit=PAGE_SIZE, page=page))
            if not batch:
                return
            yield from batch
            if len(batch) < PAGE_SIZE:
                return
            page += 1

    def tree(self, owner, repo, ref):
        entries = []
        page = 1
        while True:
            body = self.get(f"/repos/{owner}/{repo}/git/trees/{urllib.parse.quote(ref, safe='')}", {"recursive": "true", "per_page": TREE_PAGE_SIZE, "page": page})
            entries.extend(body.get("tree") or [])
            if not body.get("truncated") or not body.get("tree"):
                return entries
            page += 1

    def blob(self, owner, repo, sha):
        body = self.get(f"/repos/{owner}/{repo}/git/blobs/{sha}")
        raw = base64.b64decode(body.get("content") or "")
        return raw.decode("utf-8")


def ascii_fold(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def slug_segment(text):
    return re.sub(r"[^a-z0-9]+", "-", ascii_fold(text)).strip("-") or "untitled"


def name_segment(text):
    return re.sub(r"[^a-z0-9._-]+", "-", ascii_fold(text)).strip("-") or "untitled"


def repo_slug(owner, name):
    return f"{SLUG_PREFIX}{name_segment(owner)}/{name_segment(name)}"


def path_slug(path):
    stem = PurePosixPath(path)
    stem = stem.with_suffix("") if stem.suffix.lower() in DOC_SUFFIXES else stem
    return "/".join(slug_segment(part) for part in stem.parts)


def unique_path_slugs(paths):
    by_slug = {}
    for path in paths:
        by_slug.setdefault(path_slug(path), []).append(path)
    slugs = {}
    for slug, owners in by_slug.items():
        for path in owners:
            slugs[path] = slug if len(owners) == 1 else f"{slug}-{hashlib.sha1(path.encode()).hexdigest()[:8]}"
    return slugs


def utc_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def valid_date(value):
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


def sha256(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def cap(text):
    encoded = (text or "").encode("utf-8")
    return text if len(encoded) <= MAX_TEXT_BYTES else encoded[:MAX_TEXT_BYTES].decode("utf-8", "ignore")


def split_frontmatter(text):
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return "", text
    for index in range(1, len(lines)):
        if lines[index].rstrip() in ("---", "..."):
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:])
    return "", text


def document_title(text):
    frontmatter, body = split_frontmatter(text)
    title = re.search(r"^title\s*:\s*[\"']?(.+?)[\"']?\s*$", frontmatter, re.M | re.I)
    if title:
        return title.group(1).strip()
    heading = HEADING.search(body)
    return heading.group(1).strip() if heading else None


def decision_date(text):
    match = FRONTMATTER_DATE.search(text)
    return valid_date(match.group(1)) if match else None


def is_readme(path):
    return "/" not in path and path.lower() in README_NAMES


def is_doc(path):
    lower = path.lower()
    return lower.startswith("docs/") and lower.endswith(DOC_SUFFIXES)


def is_decision(path):
    parts = PurePosixPath(path.lower()).parts
    base = parts[-1]
    if not base.endswith(DOC_SUFFIXES) or NOT_A_DECISION.match(base):
        return False
    if ADR_FILE.match(base):
        return True
    return parts[0] == "docs" and any(ADR_DIRECTORY.match(part) for part in parts[1:-1])


def chunk_text(text):
    chunks = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text or ""):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for piece in split_long(paragraph):
            if current and len(current) + 2 + len(piece) > PASSAGE_CHARS:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def split_long(paragraph):
    pieces = []
    while len(paragraph) > PASSAGE_CHARS:
        cut = paragraph.rfind(" ", 0, PASSAGE_CHARS)
        cut = cut if cut > PASSAGE_CHARS // 2 else PASSAGE_CHARS
        pieces.append(paragraph[:cut].strip())
        paragraph = paragraph[cut:].strip()
    if paragraph:
        pieces.append(paragraph)
    return pieces


def upstream_owner(repo):
    if repo.get("fork") and repo.get("parent"):
        return ((repo["parent"].get("owner") or {}).get("login") or "").lower()
    match = re.match(r"^[a-z]+://[^/]+/([^/]+)/", (repo.get("original_url") or "").lower())
    return match.group(1) if match else ""


def imports_content(repo, scope):
    full_name = repo["full_name"].lower()
    if full_name in scope.third_party_repos or repo.get("empty"):
        return False
    if repo.get("mirror") or repo.get("fork"):
        return upstream_owner(repo) in scope.owned_upstream_owners
    return True


def project_record(repo, org_logins, now):
    owner = repo["owner"]["login"]
    is_org = owner.lower() in org_logins
    updated = utc_timestamp(repo.get("updated_at")) or now
    if repo.get("archived"):
        status = "completed"
    else:
        age = datetime.datetime.fromisoformat(now.rstrip("Z")) - datetime.datetime.fromisoformat(updated.rstrip("Z"))
        status = "active" if age.days <= ACTIVE_WITHIN_DAYS else "paused"
    tags = ["forgejo"]
    tags += [owner.lower()] if is_org else []
    tags += [topic.lower() for topic in repo.get("topics") or []]
    tags += [flag for flag in ("archived", "mirror", "fork", "private") if repo.get(flag)]
    lines = [f"Forgejo repository {repo['full_name']}", f"URL: {repo.get('html_url')}"]
    if repo.get("language"):
        lines.append(f"Language: {repo['language']}")
    if repo.get("mirror") and repo.get("original_url"):
        lines.append(f"Mirror of: {repo['original_url']}")
    if repo.get("website"):
        lines.append(f"Website: {repo['website']}")
    lines.append(f"Last activity: {updated}")
    return Record("Project", {
        "slug": repo_slug(owner, repo["name"]),
        "name": repo["full_name"],
        "kind": "work" if is_org else "side-project",
        "status": status,
        "brief": (repo.get("description") or "").strip() or None,
        "description": "\n".join(lines),
        "tags": list(dict.fromkeys(tags)),
        "createdAt": utc_timestamp(repo.get("created_at")) or now,
    })


def org_record(org):
    return Record("Organization", {
        "slug": ORG_PREFIX + name_segment(org["username"]),
        "name": (org.get("full_name") or "").strip() or org["username"],
        "kind": "company",
        "brief": (org.get("description") or "").strip() or None,
        "website": (org.get("website") or "").strip() or None,
    })


def person_record(user, self_login):
    login = user["login"]
    return Record("Person", {
        "slug": PERSON_PREFIX + name_segment(login),
        "name": (user.get("full_name") or "").strip() or login,
        "relation": "self" if login.lower() == self_login.lower() else "professional",
        "brief": f"Forgejo user @{login}",
        "tags": ["forgejo"],
    })


def real_user(user):
    return bool(user) and user.get("id", 0) > 0 and bool(user.get("login"))


def thread_header(kind, number, repo, item):
    state = item.get("state") or "open"
    if kind == "pull" and item.get("merged"):
        state = "merged"
    author = (item.get("user") or {}).get("login") or "unknown"
    lines = [f"{'Pull request' if kind == 'pull' else 'Issue'} #{number} in {repo['full_name']}: {item.get('title') or ''}".rstrip(),
             f"State: {state}", f"Opened by @{author} on {utc_timestamp(item.get('created_at'))}"]
    closed = utc_timestamp(item.get("merged_at") if state == "merged" else item.get("closed_at"))
    if closed and state != "open":
        lines.append(f"{state.capitalize()} on {closed}")
    if kind == "pull":
        lines.append(f"Branch: {(item.get('head') or {}).get('ref')} into {(item.get('base') or {}).get('ref')}")
    labels = [label.get("name") for label in item.get("labels") or [] if label.get("name")]
    if labels:
        lines.append("Labels: " + ", ".join(labels))
    return "\n".join(lines)


def thread_content(kind, number, repo, item, comments):
    parts = [thread_header(kind, number, repo, item)]
    body = (item.get("body") or "").strip()
    if body:
        parts.append(body)
    for comment in comments:
        text = (comment.get("body") or "").strip()
        if text:
            author = (comment.get("user") or {}).get("login") or "unknown"
            parts.append(f"Comment by @{author} on {utc_timestamp(comment.get('created_at'))}:\n{text}")
    return cap("\n\n".join(parts))


def comment_number(comment):
    for key in ("issue_url", "pull_request_url", "html_url"):
        match = re.search(r"/(?:issues|pulls)/(\d+)", comment.get(key) or "")
        if match:
            return int(match.group(1))
    return None


def collect_threads(client, repo, project_slug, desired, self_login, now):
    owner, name = repo["owner"]["login"], repo["name"]
    comments = {}
    for comment in client.pages(f"/repos/{owner}/{name}/issues/comments"):
        number = comment_number(comment)
        if number is not None:
            comments.setdefault(number, []).append(comment)
    for number_comments in comments.values():
        number_comments.sort(key=lambda comment: (comment.get("created_at") or "", comment.get("id") or 0))
    sources = []
    if repo.get("has_issues", True):
        sources.append(("issue", client.pages(f"/repos/{owner}/{name}/issues", {"state": "all", "type": "issues"})))
    if repo.get("has_pull_requests", True):
        sources.append(("pull", client.pages(f"/repos/{owner}/{name}/pulls", {"state": "all"})))
    for kind, items in sources:
        for item in items:
            number = item["number"]
            content = thread_content(kind, number, repo, item, comments.get(number, []))
            slug = f"{project_slug}/{kind}/{number}"
            desired.add(Record("Artifact", {
                "slug": slug,
                "name": f"{repo['full_name']}#{number} {item.get('title') or ''}".strip(),
                "kind": "post",
                "source": "other",
                "source_ref": f"forgejo:{repo['full_name']}#{number}",
                "thread_id": f"forgejo:{repo['full_name']}#{number}",
                "url": item.get("html_url"),
                "content_sha256": sha256(content),
                "timestamp": utc_timestamp(item.get("created_at")) or now,
            }, content=content))
            desired.link("ArtifactForProject", slug, project_slug)
            author = item.get("user")
            if real_user(author):
                person = person_record(author, self_login)
                desired.records.setdefault(person.data["slug"], person)
                desired.link("ArtifactFromPerson", slug, person.data["slug"])


def collect_files(client, repo, project_slug, desired, counts, now):
    owner, name = repo["owner"]["login"], repo["name"]
    entries = [entry for entry in client.tree(owner, name, repo.get("default_branch") or "main") if entry.get("type") == "blob"]
    wanted = [entry for entry in entries if is_readme(entry["path"]) or is_doc(entry["path"]) or is_decision(entry["path"])]
    readmes = sorted((entry for entry in wanted if is_readme(entry["path"])), key=lambda entry: README_NAMES.index(entry["path"].lower()))
    others = [entry for entry in wanted if not is_readme(entry["path"])]
    slugs = unique_path_slugs([entry["path"] for entry in others])
    chosen = [(readmes[0], f"{project_slug}/readme")] if readmes else []
    chosen += [(entry, f"{project_slug}/doc/{slugs[entry['path']]}") for entry in others]
    timestamp = utc_timestamp(repo.get("updated_at")) or now
    for entry, slug in chosen:
        if (entry.get("size") or 0) > MAX_TEXT_BYTES:
            counts.skipped_large += 1
            continue
        path = entry["path"]
        decision_slug = f"{project_slug}/adr/{slugs[path]}" if path in slugs and is_decision(path) else None
        record = Record("Artifact", {
            "slug": slug,
            "name": f"{repo['full_name']} {'README' if slug.endswith('/readme') else path}",
            "kind": "document",
            "source": "other",
            "source_ref": f"forgejo:{repo['full_name']}:{path}@{entry['sha']}",
            "thread_id": None,
            "url": f"{repo.get('html_url')}/src/branch/{repo.get('default_branch') or 'main'}/{urllib.parse.quote(path)}",
            "content_sha256": None,
            "timestamp": timestamp,
        }, fetch_marker=entry["sha"])
        desired.add(record)
        desired.link("ArtifactForProject", slug, project_slug)
        desired.fetches[slug] = (owner, name, entry["sha"], path, decision_slug, repo)
        if decision_slug:
            desired.add(Record("Note", {"slug": decision_slug}, keep=True))
            desired.link("NoteAboutProject", decision_slug, project_slug)
            desired.link("NoteFromArtifact", decision_slug, slug)


def decision_record(slug, path, text, repo, org_logins):
    _, body = split_frontmatter(text)
    owner = repo["owner"]["login"].lower()
    tags = ["forgejo", "adr"] + ([owner] if owner in org_logins else [])
    return Record("Note", {
        "slug": slug,
        "name": document_title(text) or PurePosixPath(path).stem,
        "kind": "decision",
        "content": body.strip("\n") or None,
        "when": decision_date(text),
        "tags": tags,
    })


def visible_repos(client, org_logins):
    repos = {}
    for repo in client.pages("/user/repos"):
        repos[repo["full_name"].lower()] = repo
    for org in sorted(org_logins):
        for repo in client.pages(f"/orgs/{org}/repos"):
            repos[repo["full_name"].lower()] = repo
    return [repos[key] for key in sorted(repos)]


def collect(client, scope, graph, now):
    counts = client.counts
    self_login = client.get("/user")["login"]
    orgs = list(client.pages("/user/orgs"))
    org_logins = {org["username"].lower() for org in orgs}
    desired = Desired()
    for org in orgs:
        desired.add(org_record(org))
    counts.orgs = len(orgs)
    for repo in visible_repos(client, org_logins):
        if repo["full_name"].lower() in scope.skip_repos:
            continue
        counts.repos += 1
        project = project_record(repo, org_logins, now)
        desired.add(project)
        slug = project.data["slug"]
        owner_slug = ORG_PREFIX + name_segment(repo["owner"]["login"])
        if repo["owner"]["login"].lower() in org_logins:
            desired.link("ProjectForOrganization", slug, owner_slug)
        if not imports_content(repo, scope):
            counts.project_only += 1
            continue
        collect_files(client, repo, slug, desired, counts, now)
        collect_threads(client, repo, slug, desired, self_login, now)
    fetch_changed_files(client, desired, graph, org_logins)
    counts.people = sum(1 for record in desired.records.values() if record.type == "Person")
    return desired


def fetch_changed_files(client, desired, graph, org_logins):
    for slug, (owner, name, sha, path, decision_slug, repo) in sorted(desired.fetches.items()):
        record = desired.records[slug]
        existing = graph.records.get(slug)
        unchanged = existing is not None and existing.get("source_ref") == record.data["source_ref"]
        has_passages = slug in graph.passages
        note_present = decision_slug is None or decision_slug in graph.records
        if unchanged and has_passages and note_present:
            record.keep = True
            continue
        text = client.blob(owner, name, sha)
        client.counts.blobs_fetched += 1
        text = cap(text)
        record.content = text
        record.data["content_sha256"] = sha256(text)
        title = document_title(text)
        if title and not slug.endswith("/readme"):
            record.data["name"] = f"{repo['full_name']} {path}: {title}"
        if decision_slug:
            desired.records[decision_slug] = decision_record(decision_slug, path, text, repo, org_logins)


@dataclass
class Graph:
    records: dict
    types: dict
    passages: dict
    edges: dict


SNAPSHOT_TYPES = {
    "forge_projects": "Project",
    "forge_orgs": "Organization",
    "forge_people": "Person",
    "forge_artifacts": "Artifact",
    "forge_notes": "Note",
}
SNAPSHOT_EDGES = {
    "forge_project_orgs": "ProjectForOrganization",
    "forge_artifact_projects": "ArtifactForProject",
    "forge_artifact_people": "ArtifactFromPerson",
    "forge_note_projects": "NoteAboutProject",
    "forge_note_artifacts": "NoteFromArtifact",
}
TIMESTAMP_FIELDS = frozenset({"createdAt", "updatedAt", "timestamp"})


def graph_rows(path):
    return json.loads(Path(path).read_text(encoding="utf-8")).get("rows", [])


def normalise(key, value):
    if key in TIMESTAMP_FIELDS:
        return utc_timestamp(value)
    if isinstance(value, list) and not value:
        return None
    return value


def read_graph(snapshot_dir):
    snapshot = Path(snapshot_dir)
    records, types = {}, {}
    for query, node_type in SNAPSHOT_TYPES.items():
        for row in graph_rows(snapshot / f"{query}.json"):
            slug = row.get("n.slug")
            if not slug or not SAFE_SLUG.fullmatch(slug):
                continue
            records[slug] = {key.split(".", 1)[1]: normalise(key.split(".", 1)[1], value) for key, value in row.items()}
            types[slug] = node_type
    passages = {}
    for row in graph_rows(snapshot / "forge_passages.json"):
        passages.setdefault(row["a.slug"], set()).add(row["p.@id"])
    edges = {}
    for query, edge in SNAPSHOT_EDGES.items():
        for row in graph_rows(snapshot / f"{query}.json"):
            if SAFE_SLUG.fullmatch(row["n.slug"]):
                edges.setdefault((edge, row["n.slug"]), set()).add(row["t.slug"])
    return Graph(records=records, types=types, passages=passages, edges=edges)


def differs(record, existing):
    wanted = {key: normalise(key, value) for key, value in record.data.items() if key not in ("createdAt", "updatedAt")}
    return any(existing.get(key) != value for key, value in wanted.items())


def passage_id(slug, index):
    return f"{slug}#{index}"


def build_plan(desired, graph, counts, now):
    prune = {kind: [] for kind in ("Passage",) + DELETE_ORDER}
    edge_prune = []
    node_rows = {kind: [] for kind in NODE_ORDER}
    passage_units = []
    edge_rows = []
    written = set()
    for slug in sorted(set(graph.records) - set(desired.records)):
        node_type = graph.types[slug]
        for pid in sorted(graph.passages.get(slug, ())):
            prune["Passage"].append(f'delete Passage where @id = "{pid}"')
            counts.passages_deleted += 1
        prune[node_type].append(f'delete {node_type} where slug = "{slug}"')
        counts.deleted += 1
    for slug, record in sorted(desired.records.items()):
        existing = graph.records.get(slug)
        if record.keep and existing is not None:
            counts.unchanged += 1
            continue
        if existing is not None and not differs(record, existing) and (record.type != "Artifact" or slug in graph.passages or not chunk_text(record.content)):
            counts.unchanged += 1
            continue
        if existing is None:
            counts.new += 1
        else:
            counts.updated += 1
        data = dict(record.data)
        data["createdAt"] = (existing or {}).get("createdAt") or data.get("createdAt") or now
        data["updatedAt"] = now
        if record.type == "Artifact":
            data["content"] = record.content
        node_rows[record.type].append({"type": record.type, "data": data})
        written.add(slug)
        if record.type == "Artifact":
            existing_ids = graph.passages.get(slug, set())
            chunks = chunk_text(record.content)
            wanted_ids = set()
            for index, text in enumerate(chunks):
                pid = passage_id(slug, index)
                wanted_ids.add(pid)
                row = {"type": "Passage", "id": pid, "data": {"text": text, "chunk_index": index, "createdAt": now}}
                unit = [row] if pid in existing_ids else [row, {"edge": "PassageOf", "from": pid, "to": slug}]
                passage_units.append(unit)
                counts.passages_written += 1
            for pid in sorted(existing_ids - wanted_ids):
                prune["Passage"].append(f'delete Passage where @id = "{pid}"')
                counts.passages_deleted += 1
    for (edge, source), targets in sorted(desired.edges.items()):
        if source not in desired.records:
            continue
        current = graph.edges.get((edge, source), set())
        managed = {target for target in current if target.startswith(SLUG_PREFIX)}
        if managed == set(targets):
            continue
        counts.relinked += 1
        if current:
            edge_prune.append(f'delete {edge} where from = "{source}"')
        kept = [] if edge in SINGLE_TARGET_EDGES else sorted(target for target in current if not target.startswith(SLUG_PREFIX))
        for target in list(targets) + kept:
            edge_rows.append({"edge": edge, "from": source, "to": target})
    statements = prune["Passage"] + [statement for kind in DELETE_ORDER for statement in prune[kind]] + edge_prune
    ordered_nodes = [row for kind in NODE_ORDER for row in node_rows[kind]]
    return Plan(counts=counts, prune_statements=statements, node_rows=ordered_nodes, passage_units=passage_units, edge_rows=edge_rows)


def batched_units(units):
    batch, rows, size = [], 0, 0
    for unit in units:
        lines = [json.dumps(row, ensure_ascii=False) + "\n" for row in unit]
        unit_size = sum(len(line.encode("utf-8")) for line in lines)
        if batch and (rows + len(lines) > ROWS_PER_LOAD_FILE or size + unit_size > BYTES_PER_LOAD_FILE):
            yield batch
            batch, rows, size = [], 0, 0
        batch.extend(lines)
        rows += len(lines)
        size += unit_size
    if batch:
        yield batch


def write_plan(plan, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for index in range(0, len(plan.prune_statements), STATEMENTS_PER_PRUNE_FILE):
        body = "\n".join(f"    {statement}" for statement in plan.prune_statements[index:index + STATEMENTS_PER_PRUNE_FILE])
        (out / f"prune-{index // STATEMENTS_PER_PRUNE_FILE:04d}.gq").write_text(f"query forge_prune() {{\n{body}\n}}\n", encoding="utf-8")
    number = 0
    for units in ([[row] for row in plan.node_rows], plan.passage_units, [[row] for row in plan.edge_rows]):
        for batch in batched_units(units):
            (out / f"load-{number:04d}.ndjson").write_text("".join(batch), encoding="utf-8")
            number += 1


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Plan a Forgejo import into the Omnigraph brain graph.")
    parser.add_argument("--forge-url", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--scope-file", required=True)
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def run(args, now):
    token = read_token(args.token_file)
    scope = read_scope(args.scope_file)
    graph = read_graph(args.snapshot_dir)
    counts = Counts()
    client = ForgeClient(args.forge_url, token, counts)
    try:
        desired = collect(client, scope, graph, now)
    except ForgeError as error:
        raise FailClosed(EXIT_FORGE_FAILED, str(error)) from error
    has_projects = any(record.type == "Project" for record in desired.records.values())
    if not has_projects and any(kind == "Project" for kind in graph.types.values()):
        raise FailClosed(EXIT_NOTHING_VISIBLE, "the forge token sees no repositories; refusing to delete what the brain already has")
    plan = build_plan(desired, graph, counts, now)
    write_plan(plan, args.out)
    return plan


def main(argv):
    args = parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        plan = run(args, now)
    except FailClosed as error:
        print(f"forge import refused: {error}", file=sys.stderr)
        return error.exit_code
    print(f"forge import plan: {plan.counts.line()}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
