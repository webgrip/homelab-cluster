#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

WRITER = "company-view"
INTERNAL = "internal"
PERSONAL = "personal"
EXCLUDED = "excluded"
CLIENT_PREFIX = "client:"
CLIENT_CODE = re.compile(r"^client:[a-z0-9][a-z0-9-]*$")
FORGE_PREFIX = "forge/"
REPOSITORY_PREFIX = "repo/"
RECORD_PREFIX = "record/"
ANY_REPOSITORY = "*"
HTTP_TIMEOUT_SECONDS = 120
ROWS_PER_LOAD_FILE = 2000
STATEMENTS_PER_PRUNE_FILE = 500
VECTOR_PROBE = [1.0] + [0.0] * 383
LAST_ACTIVITY = re.compile(r"^Last activity:\s*(\S+)\s*$", re.M)
URL_LINE = re.compile(r"^URL:\s*(\S+)\s*$", re.M)
REPOSITORY_STATUS = {"active": "active", "exploring": "active", "paused": "paused", "completed": "completed", "abandoned": "completed"}
NODE_ORDER = ("Repository", "Topic", "DecisionRecord")
EDGE_TYPES = ("RecordOf", "RecordAbout", "RepositoryAbout")
UNTIERED_REPORT = "untiered.json"

EXIT_OK = 0
EXIT_BAD_TIERS = 3
EXIT_GRAPH_UNREACHABLE = 4
EXIT_NOTHING_VISIBLE = 5
EXIT_UNTIERED = 7

BRAIN_QUERIES = {
    "projects": """query projects() {
    match { $p: Project  $p.slug starts_with "forge/" }
    return { $p.slug, $p.name, $p.status, $p.brief, $p.description }
}""",
    "artifact_projects": """query artifact_projects() {
    match { $a: Artifact  $a.slug starts_with "forge/"  $a artifactForProject $p }
    return { $a.slug, $p.slug }
}""",
    "records": """query records() {
    match { $n: Note  $n.slug starts_with "forge/"  $n noteAboutProject $p }
    return { $n.slug, $n.name, $n.content, $n.when, $p.slug }
}""",
    "record_urls": """query record_urls() {
    match { $n: Note  $n.slug starts_with "forge/"  $n noteFromArtifact $a }
    return { $n.slug, $a.url }
}""",
    "topics": """query topics() {
    match { $t: Topic }
    return { $t.slug, $t.name, $t.description, $t.aliases }
}""",
    "note_topics": """query note_topics() {
    match { $n: Note  $n noteAboutTopic $t }
    return { $n.slug, $t.slug }
}""",
    "artifact_topics": """query artifact_topics() {
    match { $a: Artifact  $a artifactAboutTopic $t }
    return { $a.slug, $t.slug }
}""",
    "project_topics": """query project_topics() {
    match { $p: Project  $p projectAboutTopic $t }
    return { $p.slug, $t.slug }
}""",
}

COMPANY_QUERIES = {
    "Repository": """query repositories() {
    match { $n: Repository }
    return { $n.slug, $n.name, $n.brief, $n.url, $n.status, $n.last_activity }
}""",
    "DecisionRecord": """query records() {
    match { $n: DecisionRecord }
    return { $n.slug, $n.repository, $n.title, $n.content, $n.decided_on, $n.url }
}""",
    "Topic": """query topics() {
    match { $n: Topic }
    return { $n.slug, $n.name, $n.description, $n.aliases }
}""",
}

COMPANY_VECTOR_QUERIES = {
    "DecisionRecord": """query record_vectors($v: Vector(384)) {
    match { $n: DecisionRecord }
    return { $n.slug }
    order { nearest($n.embedding, $v) }
    limit 1000000
}""",
    "Topic": """query topic_vectors($v: Vector(384)) {
    match { $n: Topic }
    return { $n.slug }
    order { nearest($n.embedding, $v) }
    limit 1000000
}""",
}

COMPANY_EDGE_QUERIES = {
    "RecordOf": """query record_of() {
    match { $s: DecisionRecord  $s recordOf $t }
    return { $s.slug, $t.slug }
}""",
    "RecordAbout": """query record_about() {
    match { $s: DecisionRecord  $s recordAbout $t }
    return { $s.slug, $t.slug }
}""",
    "RepositoryAbout": """query repository_about() {
    match { $s: Repository  $s repositoryAbout $t }
    return { $s.slug, $t.slug }
}""",
}


class Refused(Exception):
    def __init__(self, exit_code, message):
        super().__init__(message)
        self.exit_code = exit_code


class GraphClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def rows(self, graph, query, params=None):
        body = json.dumps({"query": query, "params": params or {}, "branch": "main"}).encode()
        headers = {"content-type": "application/json", "Authorization": f"Bearer {self.token}"}
        contract = os.environ.get("OMNIGRAPH_HTTP_API", "").strip()
        if contract:
            headers["Omnigraph-Http-Api"] = contract
        request = urllib.request.Request(f"{self.base_url}/graphs/{graph}/query", data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return json.loads(response.read()).get("rows") or []
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", errors="replace")[:300]
            error.close()
            raise Refused(EXIT_GRAPH_UNREACHABLE, f"omnigraph answered HTTP {error.code} reading {graph}/main: {text}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise Refused(EXIT_GRAPH_UNREACHABLE, f"omnigraph not reachable reading {graph}/main ({type(error).__name__})") from None


@dataclass
class Tiers:
    owners: dict
    repositories: dict

    def of(self, full_name):
        owner, _, _ = full_name.lower().partition("/")
        return self.repositories.get(full_name.lower()) or self.repositories.get(f"{owner}/{ANY_REPOSITORY}") or self.owners.get(owner)


def valid_tier(value):
    return value in (INTERNAL, PERSONAL, EXCLUDED) or bool(CLIENT_CODE.match(value or ""))


def read_tiers(defaults_path, overrides_path):
    defaults = json.loads(Path(defaults_path).read_text(encoding="utf-8"))
    try:
        overrides_text = Path(overrides_path).read_text(encoding="utf-8").strip()
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        overrides_text = ""
    if not overrides_text:
        raise Refused(EXIT_BAD_TIERS, "no repository tiers: the omnigraph-repo-tiers Secret is empty; store them at secret/omnigraph/repo-tiers (field tiers)")
    try:
        overrides = json.loads(overrides_text)
    except ValueError:
        raise Refused(EXIT_BAD_TIERS, "repository tiers are not a JSON object of owner/name to tier") from None
    if not isinstance(overrides, dict):
        raise Refused(EXIT_BAD_TIERS, "repository tiers are not a JSON object of owner/name to tier")
    owners = {owner.lower(): tier for owner, tier in (defaults.get("owners") or {}).items()}
    repositories = {name.lower(): tier for name, tier in overrides.items()}
    invalid = sorted(name for name, tier in list(owners.items()) + list(repositories.items()) if not isinstance(tier, str) or not valid_tier(tier))
    malformed = sorted(name for name in repositories if name.count("/") != 1)
    if invalid or malformed:
        raise Refused(EXIT_BAD_TIERS, f"repository tiers refused: {len(invalid)} entries name no known tier and {len(malformed)} keys are not owner/name; nothing was planned")
    return Tiers(owners, repositories)


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
        return datetime.date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def blank_to_none(value):
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, list) and not value:
        return None
    return value


def gq_string(value):
    return json.dumps(value, ensure_ascii=False)


@dataclass
class Brain:
    projects: list
    artifact_projects: dict
    records: list
    record_urls: dict
    topics: dict
    topic_sources: dict


def read_brain(client):
    fetched = {name: client.rows("brain", query) for name, query in BRAIN_QUERIES.items()}
    topic_sources = {}
    for name, variable in (("note_topics", "n"), ("artifact_topics", "a"), ("project_topics", "p")):
        for row in fetched[name]:
            topic_sources.setdefault(row["t.slug"], set()).add(row[f"{variable}.slug"])
    return Brain(
        projects=fetched["projects"],
        artifact_projects={row["a.slug"]: row["p.slug"] for row in fetched["artifact_projects"]},
        records=fetched["records"],
        record_urls={row["n.slug"]: row.get("a.url") for row in fetched["record_urls"]},
        topics={row["t.slug"]: row for row in fetched["topics"]},
        topic_sources=topic_sources,
    )


def repository_slug(project_slug):
    return REPOSITORY_PREFIX + project_slug[len(FORGE_PREFIX):]


def record_slug(note_slug):
    return RECORD_PREFIX + note_slug[len(FORGE_PREFIX):]


def matched(pattern, text):
    found = pattern.search(text or "")
    return found.group(1) if found else None


def repository_row(project):
    return {
        "slug": repository_slug(project["p.slug"]),
        "name": project["p.name"],
        "brief": blank_to_none(project.get("p.brief")),
        "url": matched(URL_LINE, project.get("p.description")),
        "status": REPOSITORY_STATUS.get(project.get("p.status"), "paused"),
        "last_activity": utc_timestamp(matched(LAST_ACTIVITY, project.get("p.description"))),
    }


@dataclass
class View:
    nodes: dict = field(default_factory=dict)
    edges: dict = field(default_factory=dict)
    untiered: list = field(default_factory=list)
    mixed_topics: int = 0
    tier_counts: dict = field(default_factory=dict)

    def add(self, type_name, data):
        self.nodes[(type_name, data["slug"])] = data

    def link(self, edge, source, target):
        self.edges.setdefault((edge, source), set()).add(target)


def project_tiers(brain, tiers):
    by_slug = {}
    for project in brain.projects:
        by_slug[project["p.slug"]] = tiers.of(project["p.name"])
    return by_slug


def source_tier(slug, project_tier, artifact_projects, record_projects):
    if slug in project_tier:
        return project_tier[slug]
    if slug in artifact_projects:
        return project_tier.get(artifact_projects[slug])
    if slug in record_projects:
        return project_tier.get(record_projects[slug])
    return PERSONAL


def build_view(brain, tiers):
    view = View()
    project_tier = project_tiers(brain, tiers)
    for project in brain.projects:
        tier = project_tier[project["p.slug"]]
        view.tier_counts[tier or "untiered"] = view.tier_counts.get(tier or "untiered", 0) + 1
        if tier is None:
            view.untiered.append(project["p.name"])
    documented = set(brain.artifact_projects.values())
    internal_projects = {project["p.slug"]: project for project in brain.projects
                         if project_tier[project["p.slug"]] == INTERNAL and project["p.slug"] in documented}
    record_projects = {row["n.slug"]: row["p.slug"] for row in brain.records}
    qualifying = set()
    for topic_slug, sources in brain.topic_sources.items():
        source_tiers = {source_tier(source, project_tier, brain.artifact_projects, record_projects) for source in sources}
        if topic_slug not in brain.topics:
            continue
        if source_tiers == {INTERNAL}:
            qualifying.add(topic_slug)
        elif INTERNAL in source_tiers:
            view.mixed_topics += 1
    for project_slug, project in internal_projects.items():
        view.add("Repository", repository_row(project))
    for row in brain.records:
        if row["p.slug"] not in internal_projects:
            continue
        slug = record_slug(row["n.slug"])
        view.add("DecisionRecord", {
            "slug": slug,
            "repository": repository_slug(row["p.slug"]),
            "title": row.get("n.name") or slug.rsplit("/", 1)[-1],
            "content": blank_to_none(row.get("n.content")),
            "decided_on": valid_date(row.get("n.when")),
            "url": blank_to_none(brain.record_urls.get(row["n.slug"])),
        })
        view.link("RecordOf", slug, repository_slug(row["p.slug"]))
    used_topics = set()
    for topic_slug in sorted(qualifying):
        for source in brain.topic_sources[topic_slug]:
            if source in record_projects and record_projects[source] in internal_projects:
                view.link("RecordAbout", record_slug(source), topic_slug)
                used_topics.add(topic_slug)
                continue
            project_slug = source if source in internal_projects else brain.artifact_projects.get(source)
            if project_slug in internal_projects:
                view.link("RepositoryAbout", repository_slug(project_slug), topic_slug)
                used_topics.add(topic_slug)
    for topic_slug in sorted(used_topics):
        topic = brain.topics[topic_slug]
        view.add("Topic", {
            "slug": topic_slug,
            "name": topic["t.name"],
            "description": blank_to_none(topic.get("t.description")),
            "aliases": blank_to_none(topic.get("t.aliases")),
        })
    view.untiered.sort()
    return view


@dataclass
class Current:
    nodes: dict
    vectors: set
    edges: dict


def read_company(client):
    nodes, vectors, edges = {}, set(), {}
    for type_name, query in COMPANY_QUERIES.items():
        for row in client.rows("company", query):
            nodes[(type_name, row["n.slug"])] = {key.split(".", 1)[1]: row[key] for key in row}
    for type_name, query in COMPANY_VECTOR_QUERIES.items():
        for row in client.rows("company", query, {"v": VECTOR_PROBE}):
            vectors.add((type_name, row["n.slug"]))
    for edge, query in COMPANY_EDGE_QUERIES.items():
        for row in client.rows("company", query):
            edges.setdefault((edge, row["s.slug"]), set()).add(row["t.slug"])
    return Current(nodes, vectors, edges)


def normalised(key, value):
    if key == "last_activity":
        return utc_timestamp(value)
    if key == "decided_on":
        return valid_date(value)
    return blank_to_none(value)


def differs(wanted, existing):
    return any(normalised(key, value) != normalised(key, existing.get(key)) for key, value in wanted.items())


EMBEDDED = frozenset({"DecisionRecord", "Topic"})


@dataclass
class Plan:
    prune: list
    rows: list
    counts: dict


def plan_writes(view, current):
    counts = {"new": 0, "updated": 0, "unvectored": 0, "unchanged": 0, "deleted": 0, "relinked": 0}
    rows = {type_name: [] for type_name in NODE_ORDER}
    for (type_name, slug), data in sorted(view.nodes.items()):
        existing = current.nodes.get((type_name, slug))
        if existing is None:
            counts["new"] += 1
        elif differs(data, existing):
            counts["updated"] += 1
        elif type_name in EMBEDDED and (type_name, slug) not in current.vectors and data.get("content" if type_name == "DecisionRecord" else "name"):
            counts["unvectored"] += 1
        else:
            counts["unchanged"] += 1
            continue
        rows[type_name].append({"type": type_name, "data": {key: value for key, value in data.items() if value is not None}})
    edge_prune, edge_rows = [], []
    sources = {key for key in view.edges} | {key for key in current.edges}
    for edge, source in sorted(sources):
        wanted = view.edges.get((edge, source), set())
        have = current.edges.get((edge, source), set())
        if wanted == have:
            continue
        counts["relinked"] += 1
        if have:
            edge_prune.append(f"delete {edge} where from = {gq_string(source)}")
        edge_rows.extend({"edge": edge, "from": source, "to": target} for target in sorted(wanted))
    node_prune = []
    for type_name in ("DecisionRecord", "Repository", "Topic"):
        for kind, slug in sorted(current.nodes):
            if kind == type_name and (kind, slug) not in view.nodes:
                node_prune.append(f"delete {kind} where slug = {gq_string(slug)}")
                counts["deleted"] += 1
    ordered = [row for type_name in NODE_ORDER for row in rows[type_name]] + edge_rows
    return Plan(prune=edge_prune + node_prune, rows=ordered, counts=counts)


def write_plan(plan, view, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for index in range(0, len(plan.prune), STATEMENTS_PER_PRUNE_FILE):
        body = "\n".join(f"    {statement}" for statement in plan.prune[index:index + STATEMENTS_PER_PRUNE_FILE])
        (out / f"prune-{index // STATEMENTS_PER_PRUNE_FILE:04d}.gq").write_text(f"query company_prune() {{\n{body}\n}}\n", encoding="utf-8")
    for index in range(0, len(plan.rows), ROWS_PER_LOAD_FILE):
        batch = plan.rows[index:index + ROWS_PER_LOAD_FILE]
        (out / f"load-{index // ROWS_PER_LOAD_FILE:04d}.ndjson").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in batch), encoding="utf-8")
    (out / "embed-plan.json").write_text(json.dumps({"writer": WRITER, "missing": [], "heal_since": {}}), encoding="utf-8")
    (out / UNTIERED_REPORT).write_text(json.dumps(view.untiered), encoding="utf-8")


def summary_line(view, plan):
    kinds = {type_name: sum(1 for kind, _ in view.nodes if kind == type_name) for type_name in NODE_ORDER}
    tiers = " ".join(f"tier_{name.replace(':', '_')}={count}" for name, count in sorted(view.tier_counts.items()) if not name.startswith(CLIENT_PREFIX))
    clients = sum(count for name, count in view.tier_counts.items() if name.startswith(CLIENT_PREFIX))
    parts = [f"repositories={kinds['Repository']}", f"records={kinds['DecisionRecord']}", f"topics={kinds['Topic']}",
             f"topics_left_out_mixed={view.mixed_topics}", tiers, f"tier_client={clients}", f"untiered={len(view.untiered)}"]
    parts += [f"{key}={value}" for key, value in plan.counts.items()]
    return "company view plan: " + " ".join(part for part in parts if part)


def plan_command(args):
    tiers = read_tiers(args.default_tiers_file, args.tiers_file)
    token = Path(args.omnigraph_token_file).read_text(encoding="utf-8").strip()
    client = GraphClient(args.omnigraph_url, token)
    brain = read_brain(client)
    if not brain.projects:
        raise Refused(EXIT_NOTHING_VISIBLE, "the brain shows no Forgejo projects; refusing to empty the company view")
    view = build_view(brain, tiers)
    current = read_company(client)
    plan = plan_writes(view, current)
    write_plan(plan, view, args.out)
    print(summary_line(view, plan))
    return EXIT_OK


def verdict_command(args):
    report = Path(args.plan) / UNTIERED_REPORT
    if not report.exists():
        print("company view refused: no plan was written, so no repository was checked for a tier", file=sys.stderr)
        return EXIT_UNTIERED
    untiered = json.loads(report.read_text(encoding="utf-8"))
    if untiered:
        print(f"company view untiered: {len(untiered)} repositories have no tier and stay out of the company view: {', '.join(untiered)}", file=sys.stderr)
        return EXIT_UNTIERED
    print("company view tiers: every repository the brain knows has a tier")
    return EXIT_OK


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Copy the Webgrip-internal repositories, decision records and topics of the brain into the company graph.")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--default-tiers-file", required=True)
    plan.add_argument("--tiers-file", required=True)
    plan.add_argument("--omnigraph-url", required=True)
    plan.add_argument("--omnigraph-token-file", required=True)
    plan.add_argument("--out", required=True)
    verdict = commands.add_parser("verdict")
    verdict.add_argument("--plan", required=True)
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    try:
        return plan_command(args) if args.command == "plan" else verdict_command(args)
    except Refused as error:
        print(f"company view refused: {error}", file=sys.stderr)
        return error.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
