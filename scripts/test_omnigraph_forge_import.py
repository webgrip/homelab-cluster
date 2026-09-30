#!/usr/bin/env python3
import base64
import copy
import importlib.util
import json
import re
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/ai/omnigraph/forge-import/app"
IMPORTER = APP / "forge_import.py"
SNAPSHOT_QUERIES = APP / "snapshot.gq"
SNAPSHOT_SCRIPT = APP / "snapshot.sh"
BRAIN_SCHEMA = ROOT / "kubernetes/apps/ai/omnigraph/app/bundle/brain.pg"
NOW = "2026-09-28T12:00:00Z"
LATER = "2026-09-28T13:00:00Z"

spec = importlib.util.spec_from_file_location("forge_import", IMPORTER)
forge_import = importlib.util.module_from_spec(spec)
sys.modules["forge_import"] = forge_import
spec.loader.exec_module(forge_import)
EMBED_STEP = ROOT / "kubernetes/apps/ai/omnigraph/embed-step/app/embed_step.py"
CONTRACT = ROOT / "kubernetes/apps/ai/omnigraph/embed-step/app/contract.json"
embed_spec = importlib.util.spec_from_file_location("embed_step", EMBED_STEP)
embed_step = importlib.util.module_from_spec(embed_spec)
sys.modules["embed_step"] = embed_step
embed_spec.loader.exec_module(embed_step)

ADR_TEXT = "---\nstatus: accepted\ndate: 2026-07-01\n---\n# ADR-0001: Use Flux\n\nWe reconcile everything with Flux.\n"
LONG_DOC = "# Runbook\n\n" + "\n\n".join(f"Paragraph {index} " + "word " * 120 for index in range(12))


def user(login, full_name="", user_id=1):
    return {"id": user_id, "login": login, "full_name": full_name, "email": f"{login}@example.invalid"}


def repo(owner, name, **extra):
    base = {
        "full_name": f"{owner}/{name}", "name": name, "owner": {"login": owner}, "description": f"{name} repo",
        "html_url": f"https://forge.example/{owner}/{name}", "default_branch": "main", "language": "Go",
        "topics": [], "archived": False, "mirror": False, "fork": False, "private": True, "empty": False,
        "original_url": "", "has_issues": True, "has_pull_requests": True,
        "created_at": "2025-01-02T03:04:05+01:00", "updated_at": "2026-09-20T10:00:00+02:00",
    }
    base.update(extra)
    return base


def blob_entry(path, sha, size=100):
    return {"path": path, "type": "blob", "sha": sha, "size": size}


class FakeForge:
    def __init__(self):
        self.me = user("ryangr0", "Ryan G")
        self.orgs = [{"username": "webgrip", "full_name": "Webgrip", "description": "the company", "website": "https://webgrip.example"},
                     {"username": "acme-client", "full_name": "", "description": "", "website": ""}]
        self.user_repos = [repo("ryangr0", "dotfiles", topics=["Shell"]),
                           repo("ryangr0", "babyagi", mirror=True, original_url="https://github.com/someone/babyagi.git"),
                           repo("ryangr0", "CV", mirror=True, original_url="https://github.com/Ryangr0/CV.git", archived=True),
                           repo("ryangr0", "brain-eval")]
        self.org_repos = {"webgrip": [repo("webgrip", "homelab-cluster", topics=["gitops", "Kubernetes"]), repo("webgrip", "obsidian-vault"),
                                      repo("webgrip", "renovate", mirror=True, original_url="https://github.com/webgrip/renovate.git")],
                          "acme-client": [repo("acme-client", "shop", language="")]}
        self.blobs = {"b-readme": "# Homelab\n\nFlux all the things.\n", "b-runbook": LONG_DOC, "b-adr": ADR_TEXT,
                      "b-guide": "# Guide\n\nHow to run it.\n", "b-dot": "dotfiles readme\n", "b-shop": "# Shop\n",
                      "b-cv": "# CV\n", "b-index": "# ADR index\n"}
        self.trees = {
            ("webgrip", "homelab-cluster"): [blob_entry("README.md", "b-readme"), blob_entry("docs/runbooks/flux.md", "b-runbook"),
                                             blob_entry("docs/adr/adr-0001-flux.md", "b-adr"), blob_entry("docs/adr/README.md", "b-index"),
                                             blob_entry("docs/guide.md", "b-guide"), blob_entry("docs/huge.md", "b-huge", size=forge_import.MAX_TEXT_BYTES + 1),
                                             blob_entry("src/main.go", "b-code"), {"path": "docs", "type": "tree", "sha": "t-docs"}],
            ("ryangr0", "dotfiles"): [blob_entry("readme", "b-dot")],
            ("ryangr0", "cv"): [blob_entry("README.md", "b-cv")],
            ("acme-client", "shop"): [blob_entry("Readme.md", "b-shop")],
        }
        self.issues = {("webgrip", "homelab-cluster"): [
            {"number": 1, "title": "Flux is slow", "state": "closed", "body": "It takes ages.", "user": user("ryangr0", "Ryan G"),
             "created_at": "2026-08-01T09:00:00Z", "closed_at": "2026-08-02T09:00:00Z", "html_url": "https://forge.example/webgrip/homelab-cluster/issues/1",
             "labels": [{"name": "bug"}]}]}
        self.pulls = {("webgrip", "homelab-cluster"): [
            {"number": 2, "title": "Speed up Flux", "state": "closed", "merged": True, "merged_at": "2026-08-03T09:00:00Z",
             "body": "Fixes #1", "user": user("renovate", "Renovate Bot", 7), "created_at": "2026-08-02T10:00:00Z",
             "html_url": "https://forge.example/webgrip/homelab-cluster/pulls/2", "head": {"ref": "fix"}, "base": {"ref": "main"}, "labels": []},
            {"number": 3, "title": "Ghost PR", "state": "open", "body": "", "user": {"id": -1, "login": "Ghost"},
             "created_at": "2026-08-04T10:00:00Z", "html_url": "https://forge.example/webgrip/homelab-cluster/pulls/3", "head": {"ref": "g"}, "base": {"ref": "main"}}]}
        self.comments = {("webgrip", "homelab-cluster"): [
            {"id": 11, "body": "Confirmed on worker-1", "user": user("alice", "Alice"), "created_at": "2026-08-01T10:00:00Z",
             "issue_url": "https://forge.example/api/v1/repos/webgrip/homelab-cluster/issues/1"}]}
        self.failing_paths = set()
        self.requests = []

    def all_repos(self):
        return self.user_repos + [item for repos in self.org_repos.values() for item in repos]

    def route(self, path, params):
        if path in self.failing_paths:
            return 500, {"message": "boom"}
        if path == "/api/v1/user":
            return 200, self.me
        if path == "/api/v1/user/orgs":
            return 200, self.orgs
        if path == "/api/v1/user/repos":
            return 200, self.user_repos
        match = re.fullmatch(r"/api/v1/orgs/([^/]+)/repos", path)
        if match:
            return 200, self.org_repos.get(match.group(1), [])
        match = re.fullmatch(r"/api/v1/repos/([^/]+)/([^/]+)/(.+)", path)
        if not match:
            return 404, {"message": "not found"}
        key = (match.group(1).lower(), match.group(2).lower())
        rest = match.group(3)
        if rest.startswith("git/trees/"):
            entries = self.trees.get(key, [])
            per_page, page = int(params["per_page"]), int(params["page"])
            window = entries[(page - 1) * per_page: page * per_page]
            return 200, {"tree": window, "truncated": page * per_page < len(entries), "page": page, "total_count": len(entries)}
        if rest.startswith("git/blobs/"):
            text = self.blobs[rest.rsplit("/", 1)[1]]
            return 200, {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"}
        if rest == "issues/comments":
            return 200, self.comments.get(key, [])
        if rest == "issues":
            return 200, self.issues.get(key, [])
        if rest == "pulls":
            return 200, self.pulls.get(key, [])
        return 404, {"message": "not found"}


class ForgeServer:
    def __init__(self, forge):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = dict(urllib.parse.parse_qsl(parsed.query))
                forge.requests.append(parsed.path)
                if self.headers.get("Authorization") != "token secret-token":
                    status, body = 401, {"message": "unauthorized"}
                else:
                    status, body = forge.route(parsed.path, params)
                if isinstance(body, list):
                    limit, page = int(params.get("limit", 50)), int(params.get("page", 1))
                    body = body[(page - 1) * limit: page * limit]
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        outer.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class SimulatedGraph:
    def __init__(self):
        self.nodes = {}
        self.passages = {}
        self.edges = {}

    def apply(self, out):
        for path in sorted(out.glob("prune-*.gq")):
            for statement in re.findall(r"^\s+(delete .+)$", path.read_text(encoding="utf-8"), re.M):
                self.delete(statement)
        for pattern in ("load-*.ndjson", "heal-*.ndjson"):
            for path in sorted(out.glob(pattern)):
                for line in path.read_text(encoding="utf-8").split("\n"):
                    if line.strip():
                        self.load(json.loads(line))

    def chunks(self, slug):
        return {pid: {"text": row["text"], "chunk_index": row["chunk_index"], "createdAt": row["createdAt"]}
                for pid, row in self.passages.items() if row.get("to") == slug}

    def vector_of(self, key):
        if key in self.passages:
            return self.passages[key].get("embedding")
        return self.nodes[key][1].get("embedding")

    def delete(self, statement):
        passage = re.fullmatch(r'delete Passage where @id = "(.+)"', statement)
        node = re.fullmatch(r'delete (Project|Organization|Person|Artifact|Note) where slug = "(.+)"', statement)
        edge = re.fullmatch(r'delete (\w+) where from = "(.+)"', statement)
        if passage:
            self.passages.pop(passage.group(1))
            self.edges = {key: value for key, value in self.edges.items() if not (key[0] == "PassageOf" and key[1] == passage.group(1))}
        elif node:
            slug = node.group(2)
            if any(row["to"] == slug for row in self.passages.values()):
                raise AssertionError(f"@card violation: {slug} still has passages")
            self.nodes.pop(slug)
            self.edges = {key: value for key, value in self.edges.items() if key[1] != slug and slug not in value}
        elif edge:
            self.edges.pop((edge.group(1), edge.group(2)), None)
        else:
            raise AssertionError(f"unexpected statement {statement}")

    def load(self, row):
        if row.get("type") == "Passage":
            existing = self.passages.get(row["id"], {})
            self.passages[row["id"]] = dict(row["data"], to=existing.get("to"))
        elif "type" in row:
            self.nodes[row["data"]["slug"]] = (row["type"], row["data"])
        elif row["edge"] == "PassageOf":
            if self.passages.get(row["from"], {}).get("to"):
                raise AssertionError(f"@unique violation on PassageOf for {row['from']}")
            self.passages[row["from"]]["to"] = row["to"]
        else:
            if row["from"] not in self.nodes or row["to"] not in self.nodes:
                raise AssertionError(f"dangling edge {row}")
            targets = self.edges.setdefault((row["edge"], row["from"]), [])
            if row["to"] in targets:
                raise AssertionError(f"duplicate edge {row}")
            targets.append(row["to"])

    def snapshot(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        fields = {
            "forge_projects": ("Project", ["slug", "name", "kind", "status", "brief", "description", "tags", "createdAt"]),
            "forge_orgs": ("Organization", ["slug", "name", "kind", "brief", "website", "createdAt"]),
            "forge_people": ("Person", ["slug", "name", "relation", "brief", "tags", "createdAt"]),
            "forge_artifacts": ("Artifact", ["slug", "name", "kind", "source", "source_ref", "thread_id", "url", "content_sha256", "timestamp", "createdAt"]),
            "forge_notes": ("Note", ["slug", "name", "kind", "content", "when", "tags", "createdAt", "updatedAt"]),
        }
        for query, (node_type, keys) in fields.items():
            rows = [{f"n.{key}": (data.get(key).rstrip("Z") if key in ("createdAt", "updatedAt", "timestamp") and data.get(key) else data.get(key)) for key in keys}
                    for slug, (kind, data) in sorted(self.nodes.items()) if kind == node_type and slug.startswith("forge/")]
            (directory / f"{query}.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
        passages = [{"p.@id": pid, "a.slug": row["to"], "p.createdAt": row["createdAt"].rstrip("Z")} for pid, row in sorted(self.passages.items()) if row.get("to")]
        (directory / "forge_passages.json").write_text(json.dumps({"rows": passages}), encoding="utf-8")
        with_vectors = [{"p.@id": pid} for pid, row in sorted(self.passages.items()) if row.get("to", "").startswith("forge/") and row.get("embedding")]
        (directory / "forge_passages_with_vectors.json").write_text(json.dumps({"rows": with_vectors}), encoding="utf-8")
        notes_with_vectors = [{"n.slug": slug} for slug, (kind, data) in sorted(self.nodes.items()) if kind == "Note" and slug.startswith("forge/") and data.get("embedding")]
        (directory / "forge_notes_with_vectors.json").write_text(json.dumps({"rows": notes_with_vectors}), encoding="utf-8")
        for query, edge in forge_import.SNAPSHOT_EDGES.items():
            rows = [{"n.slug": source, "t.slug": target} for (name, source), targets in sorted(self.edges.items()) if name == edge for target in targets]
            (directory / f"{query}.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")


class Harness:
    def __init__(self, forge=None, token="secret-token"):
        self.forge = forge or FakeForge()
        self.server = ForgeServer(self.forge)
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.token = self.root / "token"
        if token is not None:
            self.token.write_text(token + "\n", encoding="utf-8")
        self.scope = APP / "scope.json"
        self.graph = SimulatedGraph()
        self.runs = 0
        self.embedder = None
        self.reads = []

    def chunks(self, slug):
        self.reads.append(slug)
        return self.graph.chunks(slug)

    def plan(self, now=NOW):
        self.runs += 1
        snapshot = self.root / f"snapshot-{self.runs}"
        self.graph.snapshot(snapshot)
        self.out = self.root / f"plan-{self.runs}"
        args = forge_import.parse_args(["--forge-url", self.server.url, "--token-file", str(self.token), "--scope-file", str(self.scope),
                                        "--snapshot-dir", str(snapshot), "--omnigraph-url", "http://omnigraph.invalid",
                                        "--omnigraph-token-file", str(self.token), "--out", str(self.out)])
        return forge_import.run(args, now, reader=self)

    def embed(self, embedder, deadline=600):
        args = SimpleNamespace(plan=str(self.out), contract=str(CONTRACT), litellm_url="http://unused", key_file="/nonexistent",
                               tokens_per_second=1e9, deadline_seconds=deadline)
        return embed_step.embed(args, embedder=embedder)

    def plan_and_apply(self, now=NOW):
        plan = self.plan(now)
        if self.embedder is not None:
            self.embed_report = self.embed(self.embedder)
        self.graph.apply(self.out)
        return plan

    def load_rows(self):
        rows = []
        for path in sorted(self.out.glob("load-*.ndjson")):
            rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
        return rows

    def prune(self):
        return "".join(path.read_text(encoding="utf-8") for path in sorted(self.out.glob("prune-*.gq")))

    def close(self):
        self.server.close()
        self.dir.cleanup()


def nodes(rows, node_type):
    return {row["data"]["slug"]: row["data"] for row in rows if row.get("type") == node_type}


def edge_pairs(rows, edge):
    return sorted((row["from"], row["to"]) for row in rows if row.get("edge") == edge)


def schema_enum(block_name, field_name):
    schema = BRAIN_SCHEMA.read_text(encoding="utf-8")
    block = schema.split(f"node {block_name} {{", 1)[1].split("}", 1)[0]
    values = re.search(rf"{field_name}: enum\(([^)]*)\)", block).group(1)
    return {value.strip() for value in values.split(",")}


class SchemaParity(unittest.TestCase):
    def setUp(self):
        self.harness = Harness()
        self.harness.plan()
        self.rows = self.harness.load_rows()

    def tearDown(self):
        self.harness.close()

    def test_every_enum_value_written_exists_in_brain_schema(self):
        checks = {("Project", "kind"), ("Project", "status"), ("Organization", "kind"), ("Person", "relation"),
                  ("Artifact", "kind"), ("Artifact", "source"), ("Note", "kind")}
        for node_type, field_name in checks:
            allowed = schema_enum(node_type, field_name)
            for data in nodes(self.rows, node_type).values():
                self.assertIn(data[field_name], allowed, f"{node_type}.{field_name}")

    def test_every_written_property_exists_in_brain_schema(self):
        schema = BRAIN_SCHEMA.read_text(encoding="utf-8")
        for row in self.rows:
            if "type" not in row:
                continue
            block = schema.split(f"node {row['type']} {{", 1)[1].split("}", 1)[0]
            declared = set(re.findall(r"^\s+(\w+):", block, re.M))
            self.assertLessEqual(set(row["data"]), declared, row["type"])

    def test_every_edge_and_snapshot_traversal_exists_in_brain_schema(self):
        schema = BRAIN_SCHEMA.read_text(encoding="utf-8")
        for edge in forge_import.EDGE_TYPES + ("PassageOf",):
            self.assertRegex(schema, rf"edge {edge}:")
        queries = SNAPSHOT_QUERIES.read_text(encoding="utf-8")
        for edge in forge_import.EDGE_TYPES:
            self.assertIn(f" {edge[0].lower()}{edge[1:]} $t", queries)

    def test_snapshot_script_reads_every_query_the_planner_needs(self):
        script = SNAPSHOT_SCRIPT.read_text(encoding="utf-8")
        queries = SNAPSHOT_QUERIES.read_text(encoding="utf-8")
        for name in list(forge_import.SNAPSHOT_TYPES) + list(forge_import.SNAPSHOT_EDGES) + ["forge_passages"]:
            self.assertIn(name, script)
            self.assertIn(f"query {name}()", queries)


class Mapping(unittest.TestCase):
    def setUp(self):
        self.harness = Harness()
        self.plan = self.harness.plan()
        self.rows = self.harness.load_rows()

    def tearDown(self):
        self.harness.close()

    def test_one_project_per_visible_repo_with_stable_lowercase_slugs(self):
        self.assertEqual(sorted(nodes(self.rows, "Project")), [
            "forge/acme-client/shop", "forge/ryangr0/babyagi", "forge/ryangr0/cv", "forge/ryangr0/dotfiles",
            "forge/webgrip/homelab-cluster", "forge/webgrip/renovate"])

    def test_project_fields_carry_description_url_language_topics_and_activity(self):
        project = nodes(self.rows, "Project")["forge/webgrip/homelab-cluster"]
        self.assertEqual(project["name"], "webgrip/homelab-cluster")
        self.assertEqual(project["kind"], "work")
        self.assertEqual(project["status"], "active")
        self.assertEqual(project["brief"], "homelab-cluster repo")
        self.assertIn("URL: https://forge.example/webgrip/homelab-cluster", project["description"])
        self.assertIn("Language: Go", project["description"])
        self.assertIn("Last activity: 2026-09-20T08:00:00Z", project["description"])
        self.assertEqual(project["tags"], ["forgejo", "webgrip", "gitops", "kubernetes", "private"])
        self.assertEqual(project["createdAt"], "2025-01-02T02:04:05Z")

    def test_client_org_repos_are_tagged_with_the_org_and_linked_to_it(self):
        self.assertIn("acme-client", nodes(self.rows, "Project")["forge/acme-client/shop"]["tags"])
        self.assertIn(("forge/acme-client/shop", "forge/org/acme-client"), edge_pairs(self.rows, "ProjectForOrganization"))
        self.assertEqual(nodes(self.rows, "Organization")["forge/org/acme-client"]["name"], "acme-client")
        self.assertEqual(nodes(self.rows, "Organization")["forge/org/webgrip"]["website"], "https://webgrip.example")

    def test_user_repos_are_side_projects_without_an_org(self):
        project = nodes(self.rows, "Project")["forge/ryangr0/dotfiles"]
        self.assertEqual(project["kind"], "side-project")
        self.assertNotIn("forge/ryangr0/dotfiles", [source for source, _ in edge_pairs(self.rows, "ProjectForOrganization")])

    def test_archived_owned_mirror_is_imported_and_tagged(self):
        project = nodes(self.rows, "Project")["forge/ryangr0/cv"]
        self.assertEqual(project["status"], "completed")
        self.assertIn("archived", project["tags"])
        self.assertIn("mirror", project["tags"])
        self.assertIn("forge/ryangr0/cv/readme", nodes(self.rows, "Artifact"))

    def test_third_party_mirrors_keep_only_their_project_node(self):
        artifacts = nodes(self.rows, "Artifact")
        for project in ("forge/ryangr0/babyagi", "forge/webgrip/renovate"):
            self.assertIn("mirror", nodes(self.rows, "Project")[project]["tags"])
            self.assertFalse([slug for slug in artifacts if slug.startswith(project + "/")])
        self.assertEqual(self.plan.counts.project_only, 2)
        self.assertNotIn("/api/v1/repos/webgrip/renovate/issues", self.harness.forge.requests)

    def test_skip_listed_vault_repo_is_not_imported(self):
        self.assertNotIn("forge/webgrip/obsidian-vault", nodes(self.rows, "Project"))

    def test_the_private_brain_eval_repo_is_never_read_or_imported(self):
        self.assertFalse([slug for slug in nodes(self.rows, "Project") if slug.startswith("forge/ryangr0/brain-eval")])
        self.assertFalse([slug for slug in nodes(self.rows, "Artifact") if slug.startswith("forge/ryangr0/brain-eval")])
        self.assertFalse([path for path in self.harness.forge.requests if "/repos/ryangr0/brain-eval/" in path])

    def test_readme_docs_and_adrs_become_document_artifacts_for_the_project(self):
        artifacts = nodes(self.rows, "Artifact")
        expected = {"forge/webgrip/homelab-cluster/readme", "forge/webgrip/homelab-cluster/doc/docs/runbooks/flux",
                    "forge/webgrip/homelab-cluster/doc/docs/adr/adr-0001-flux", "forge/webgrip/homelab-cluster/doc/docs/adr/readme",
                    "forge/webgrip/homelab-cluster/doc/docs/guide"}
        self.assertEqual({slug for slug in artifacts if "/homelab-cluster/" in slug and "/doc/" in slug or slug.endswith("homelab-cluster/readme")}, expected)
        readme = artifacts["forge/webgrip/homelab-cluster/readme"]
        self.assertEqual((readme["kind"], readme["source"]), ("document", "other"))
        self.assertEqual(readme["content"], "# Homelab\n\nFlux all the things.\n")
        self.assertTrue(readme["source_ref"].endswith("README.md@b-readme"))
        self.assertEqual(readme["url"], "https://forge.example/webgrip/homelab-cluster/src/branch/main/README.md")
        self.assertIn(("forge/webgrip/homelab-cluster/doc/docs/guide", "forge/webgrip/homelab-cluster"), edge_pairs(self.rows, "ArtifactForProject"))
        self.assertIn("forge/ryangr0/dotfiles/readme", artifacts)
        self.assertIn("forge/acme-client/shop/readme", artifacts)

    def test_code_and_oversized_files_are_left_out(self):
        artifacts = nodes(self.rows, "Artifact")
        self.assertFalse([slug for slug in artifacts if "main-go" in slug or "huge" in slug])
        self.assertEqual(self.plan.counts.skipped_large, 1)

    def test_adr_is_a_decision_note_about_the_project_from_its_file(self):
        notes = nodes(self.rows, "Note")
        self.assertEqual(list(notes), ["forge/webgrip/homelab-cluster/adr/docs/adr/adr-0001-flux"])
        note = notes["forge/webgrip/homelab-cluster/adr/docs/adr/adr-0001-flux"]
        self.assertEqual(note["kind"], "decision")
        self.assertEqual(note["name"], "ADR-0001: Use Flux")
        self.assertEqual(note["when"], "2026-07-01")
        self.assertEqual(note["tags"], ["forgejo", "adr", "webgrip"])
        self.assertNotIn("status: accepted", note["content"])
        self.assertIn((note["slug"], "forge/webgrip/homelab-cluster"), edge_pairs(self.rows, "NoteAboutProject"))
        self.assertIn((note["slug"], "forge/webgrip/homelab-cluster/doc/docs/adr/adr-0001-flux"), edge_pairs(self.rows, "NoteFromArtifact"))

    def test_issue_artifact_has_state_timestamps_labels_body_and_comments(self):
        issue = nodes(self.rows, "Artifact")["forge/webgrip/homelab-cluster/issue/1"]
        self.assertEqual(issue["kind"], "post")
        self.assertEqual(issue["name"], "webgrip/homelab-cluster#1 Flux is slow")
        self.assertEqual(issue["timestamp"], "2026-08-01T09:00:00Z")
        self.assertEqual(issue["thread_id"], "forgejo:webgrip/homelab-cluster#1")
        self.assertEqual(issue["url"], "https://forge.example/webgrip/homelab-cluster/issues/1")
        for fragment in ("Issue #1 in webgrip/homelab-cluster: Flux is slow", "State: closed", "Closed on 2026-08-02T09:00:00Z",
                         "Labels: bug", "It takes ages.", "Comment by @alice on 2026-08-01T10:00:00Z:\nConfirmed on worker-1"):
            self.assertIn(fragment, issue["content"])

    def test_pull_request_reports_merged_and_branches(self):
        pull = nodes(self.rows, "Artifact")["forge/webgrip/homelab-cluster/pull/2"]
        self.assertIn("State: merged", pull["content"])
        self.assertIn("Merged on 2026-08-03T09:00:00Z", pull["content"])
        self.assertIn("Branch: fix into main", pull["content"])

    def test_authors_become_people_without_emails_and_ghosts_are_skipped(self):
        people = nodes(self.rows, "Person")
        self.assertEqual(sorted(people), ["forge/user/renovate", "forge/user/ryangr0"])
        self.assertEqual(people["forge/user/ryangr0"]["relation"], "self")
        self.assertEqual(people["forge/user/renovate"]["relation"], "professional")
        self.assertEqual(people["forge/user/renovate"]["name"], "Renovate Bot")
        self.assertEqual(people["forge/user/renovate"]["brief"], "Forgejo user @renovate")
        self.assertNotIn("email", json.dumps(self.rows))
        self.assertEqual(edge_pairs(self.rows, "ArtifactFromPerson"), [
            ("forge/webgrip/homelab-cluster/issue/1", "forge/user/ryangr0"), ("forge/webgrip/homelab-cluster/pull/2", "forge/user/renovate")])

    def test_passages_carry_the_text_with_explicit_ids_and_passage_of_in_the_same_file(self):
        slug = "forge/webgrip/homelab-cluster/doc/docs/runbooks/flux"
        passages = [row for row in self.rows if row.get("type") == "Passage" and row["id"].startswith(slug + "#")]
        self.assertGreater(len(passages), 3)
        self.assertEqual([row["data"]["chunk_index"] for row in passages], list(range(len(passages))))
        self.assertEqual([row["id"] for row in passages], [f"{slug}#{index}" for index in range(len(passages))])
        self.assertTrue(all(len(row["data"]["text"]) <= forge_import.PASSAGE_CHARS for row in passages))
        for path in self.harness.out.glob("load-*.ndjson"):
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            ids = {row["id"] for row in lines if row.get("type") == "Passage"}
            edges = {row["from"] for row in lines if row.get("edge") == "PassageOf"}
            self.assertEqual(ids, edges)

    def test_nodes_load_before_passages_and_edges(self):
        order = ["node" if "type" in row and row["type"] != "Passage" else "passage" if row.get("type") == "Passage" or row.get("edge") == "PassageOf" else "edge" for row in self.rows]
        self.assertEqual(order, sorted(order, key=["node", "passage", "edge"].index))


class Chunking(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(forge_import.chunk_text("# Title\n\nBody."), ["# Title\n\nBody."])

    def test_paragraphs_pack_up_to_the_limit_and_never_exceed_it(self):
        chunks = forge_import.chunk_text(LONG_DOC)
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(0 < len(chunk) <= forge_import.PASSAGE_CHARS for chunk in chunks))
        self.assertEqual(" ".join(" ".join(chunks).split()), " ".join(LONG_DOC.split()))

    def test_a_paragraph_without_spaces_is_cut_hard(self):
        chunks = forge_import.chunk_text("x" * (forge_import.PASSAGE_CHARS * 2 + 10))
        self.assertEqual([len(chunk) for chunk in chunks], [forge_import.PASSAGE_CHARS, forge_import.PASSAGE_CHARS, 10])

    def test_empty_text_has_no_chunks(self):
        self.assertEqual(forge_import.chunk_text(" \n\n "), [])


class DecisionDetection(unittest.TestCase):
    def test_decision_paths(self):
        decisions = ["docs/adr/adr-0001-flux.md", "docs/adrs/0002-x.md", "docs/adr-log/0003.md", "docs/decisions/use-go.md",
                     "docs/techdocs/docs/adr/adr-0048-dark-factory.md", "adr-0004-root.md", "services/api/ADR-0005-cache.md"]
        others = ["docs/adr/README.md", "docs/adr/index.md", "docs/adr/template.md", "docs/adr/adr-template.md", "docs/guide.md",
                  "src/decisions/x.md", "docs/adr/diagram.png", "README.md"]
        for path in decisions:
            self.assertTrue(forge_import.is_decision(path), path)
        for path in others:
            self.assertFalse(forge_import.is_decision(path), path)

    def test_readme_is_root_only(self):
        self.assertTrue(forge_import.is_readme("README.md"))
        self.assertTrue(forge_import.is_readme("readme"))
        self.assertFalse(forge_import.is_readme("docs/README.md"))


class Incremental(unittest.TestCase):
    def setUp(self):
        self.harness = Harness()
        self.harness.plan_and_apply()

    def tearDown(self):
        self.harness.close()

    def test_second_run_writes_nothing_and_fetches_no_blobs(self):
        self.harness.forge.requests.clear()
        plan = self.harness.plan_and_apply(LATER)
        self.assertEqual((plan.node_rows, plan.passage_units, plan.edge_rows, plan.prune_statements), ([], [], [], []))
        self.assertEqual(plan.counts.blobs_fetched, 0)
        self.assertFalse([path for path in self.harness.forge.requests if "/git/blobs/" in path])

    def test_changed_doc_rewrites_its_passages_and_drops_surplus_ids(self):
        slug = "forge/webgrip/homelab-cluster/doc/docs/runbooks/flux"
        before = {pid for pid in self.harness.graph.passages if pid.startswith(slug + "#")}
        self.harness.forge.blobs["b-runbook2"] = "# Runbook\n\nNow short.\n"
        tree = self.harness.forge.trees[("webgrip", "homelab-cluster")]
        tree[1] = blob_entry("docs/runbooks/flux.md", "b-runbook2")
        plan = self.harness.plan_and_apply(LATER)
        self.assertEqual([row["data"]["slug"] for row in plan.node_rows], [slug])
        self.assertEqual(plan.passage_units, [[{"type": "Passage", "id": f"{slug}#0", "data": {"text": "# Runbook\n\nNow short.", "chunk_index": 0, "createdAt": LATER}}]])
        self.assertEqual(sorted(plan.prune_statements), sorted(f'delete Passage where @id = "{pid}"' for pid in before - {f"{slug}#0"}))
        self.assertEqual(self.harness.graph.nodes[slug][1]["createdAt"], NOW)
        self.assertEqual(self.harness.graph.nodes[slug][1]["updatedAt"], LATER)
        self.assertEqual(self.harness.plan_and_apply(LATER).node_rows, [])

    def test_new_comment_updates_only_that_issue(self):
        self.harness.forge.comments[("webgrip", "homelab-cluster")].append(
            {"id": 12, "body": "Still slow", "user": user("ryangr0"), "created_at": "2026-08-05T10:00:00Z",
             "issue_url": "https://forge.example/api/v1/repos/webgrip/homelab-cluster/issues/1"})
        plan = self.harness.plan_and_apply(LATER)
        self.assertEqual([row["data"]["slug"] for row in plan.node_rows], ["forge/webgrip/homelab-cluster/issue/1"])
        self.assertEqual(plan.edge_rows, [])

    def test_removed_repo_deletes_passages_before_artifacts_and_its_project(self):
        self.harness.forge.org_repos["acme-client"] = []
        plan = self.harness.plan_and_apply(LATER)
        prune = plan.prune_statements
        self.assertIn('delete Project where slug = "forge/acme-client/shop"', prune)
        self.assertIn('delete Artifact where slug = "forge/acme-client/shop/readme"', prune)
        self.assertLess(prune.index('delete Passage where @id = "forge/acme-client/shop/readme#0"'),
                        prune.index('delete Artifact where slug = "forge/acme-client/shop/readme"'))
        self.assertNotIn("forge/acme-client/shop", self.harness.graph.nodes)

    def test_removed_adr_deletes_its_note_and_file(self):
        tree = self.harness.forge.trees[("webgrip", "homelab-cluster")]
        tree[:] = [entry for entry in tree if "adr-0001" not in entry["path"]]
        plan = self.harness.plan_and_apply(LATER)
        self.assertIn('delete Note where slug = "forge/webgrip/homelab-cluster/adr/docs/adr/adr-0001-flux"', plan.prune_statements)
        self.assertIn('delete Artifact where slug = "forge/webgrip/homelab-cluster/doc/docs/adr/adr-0001-flux"', plan.prune_statements)

    def test_author_without_remaining_threads_is_deleted(self):
        self.harness.forge.pulls[("webgrip", "homelab-cluster")].pop(0)
        plan = self.harness.plan_and_apply(LATER)
        self.assertIn('delete Person where slug = "forge/user/renovate"', plan.prune_statements)
        self.assertIn('delete Artifact where slug = "forge/webgrip/homelab-cluster/pull/2"', plan.prune_statements)

    def test_rewired_edge_is_deleted_then_reloaded_and_foreign_targets_survive(self):
        self.harness.graph.nodes["proj-manual"] = ("Project", {"slug": "proj-manual"})
        self.harness.graph.edges[("ArtifactForProject", "forge/ryangr0/dotfiles/readme")].append("proj-manual")
        self.harness.forge.user_repos[0]["owner"] = {"login": "ryangr0"}
        plan = self.harness.plan(LATER)
        self.assertEqual(plan.edge_rows, [])
        self.harness.forge.pulls[("webgrip", "homelab-cluster")][0]["user"] = user("ryangr0", "Ryan G")
        plan = self.harness.plan_and_apply(LATER)
        self.assertIn('delete ArtifactFromPerson where from = "forge/webgrip/homelab-cluster/pull/2"', plan.prune_statements)
        self.assertIn({"edge": "ArtifactFromPerson", "from": "forge/webgrip/homelab-cluster/pull/2", "to": "forge/user/ryangr0"}, plan.edge_rows)
        self.assertEqual(self.harness.graph.edges[("ArtifactForProject", "forge/ryangr0/dotfiles/readme")], ["forge/ryangr0/dotfiles", "proj-manual"])

    def test_rows_outside_forge_are_never_touched(self):
        self.harness.graph.nodes["nt-bike"] = ("Note", {"slug": "nt-bike"})
        plan = self.harness.plan(LATER)
        self.assertFalse([statement for statement in plan.prune_statements if "nt-bike" in statement])

    def test_partial_failure_self_heals(self):
        slug = "forge/ryangr0/dotfiles/readme"
        for pid in [pid for pid in self.harness.graph.passages if pid.startswith(slug + "#")]:
            del self.harness.graph.passages[pid]
        plan = self.harness.plan_and_apply(LATER)
        self.assertEqual(plan.passage_units, [[
            {"type": "Passage", "id": f"{slug}#0", "data": {"text": "dotfiles readme", "chunk_index": 0, "createdAt": LATER}},
            {"edge": "PassageOf", "from": f"{slug}#0", "to": slug}]])


class FakeEmbedder:
    def __init__(self, fail=False):
        self.texts = []
        self.fail = fail

    def __call__(self, texts):
        if self.fail:
            raise embed_step.EmbeddingUnavailable("litellm answered HTTP 503")
        self.texts.extend(texts)
        return [[1.0] + [0.0] * 383 for _ in texts], len(texts)


class RealisticEmbedder:
    def __call__(self, texts):
        vectors = []
        for text in texts:
            seed = len(text) + 1
            vectors.append([((index * 7919 + seed * 104729) % 2003 - 1001) / 7127.0 for index in range(384)])
        return vectors, len(texts)


RUNBOOK = "forge/webgrip/homelab-cluster/doc/docs/runbooks/flux"
ADR_NOTE = "forge/webgrip/homelab-cluster/adr/docs/adr/adr-0001-flux"


class WriteTimeVectors(unittest.TestCase):
    def setUp(self):
        self.harness = Harness()
        self.harness.embedder = FakeEmbedder()
        self.harness.plan_and_apply()

    def tearDown(self):
        self.harness.close()

    def vectorless(self):
        return sorted([pid for pid, row in self.harness.graph.passages.items() if not row.get("embedding")] +
                      [slug for slug, (kind, data) in self.harness.graph.nodes.items() if kind == "Note" and not data.get("embedding")])

    def test_first_import_writes_every_note_and_passage_with_a_384_float_vector(self):
        self.assertEqual(self.vectorless(), [])
        self.assertEqual(len(self.harness.graph.vector_of(ADR_NOTE)), 384)
        self.assertEqual(self.harness.embed_report["missing"], {"Note": 0, "Passage": 0})

    def test_an_updated_adr_note_row_carries_a_384_float_vector(self):
        self.harness.forge.blobs["b-adr2"] = ADR_TEXT + "\nAmended: also Helm.\n"
        tree = self.harness.forge.trees[("webgrip", "homelab-cluster")]
        tree[2] = blob_entry("docs/adr/adr-0001-flux.md", "b-adr2")
        plan = self.harness.plan_and_apply(LATER)
        rewritten = [row for row in plan.node_rows if row["type"] == "Note"]
        self.assertEqual([row["data"]["slug"] for row in rewritten], [ADR_NOTE])
        self.assertEqual(len(self.harness.graph.nodes[ADR_NOTE][1]["embedding"]), 384)
        self.assertEqual(self.vectorless(), [])

    def test_a_changed_doc_writes_only_its_changed_chunks_and_keeps_the_rest(self):
        before = {pid: dict(row) for pid, row in self.harness.graph.passages.items() if pid.startswith(RUNBOOK + "#")}
        self.assertGreater(len(before), 2)
        changed = LONG_DOC.replace("Paragraph 11 ", "Paragraph eleven ")
        self.harness.forge.blobs["b-runbook3"] = changed
        tree = self.harness.forge.trees[("webgrip", "homelab-cluster")]
        tree[1] = blob_entry("docs/runbooks/flux.md", "b-runbook3")
        self.harness.embedder.texts.clear()
        plan = self.harness.plan_and_apply(LATER)
        written = [unit[0]["id"] for unit in plan.passage_units]
        last = max(before, key=lambda pid: int(pid.rsplit("#", 1)[1]))
        self.assertEqual(written, [last])
        self.assertEqual(plan.counts.unchanged_chunks, len(before) - 1)
        self.assertEqual(len(self.harness.embedder.texts), 1)
        for pid in set(before) - {last}:
            self.assertEqual(self.harness.graph.passages[pid]["createdAt"], NOW)
        self.assertEqual(self.harness.graph.passages[last]["createdAt"], LATER)
        self.assertEqual(self.vectorless(), [])

    def test_a_second_run_writes_nothing_and_embeds_nothing(self):
        self.harness.embedder.texts.clear()
        self.harness.plan_and_apply(LATER)
        self.assertEqual(self.harness.embedder.texts, [])
        self.assertFalse(list(self.harness.out.glob("heal-*.ndjson")))

    def test_vectorless_rows_are_healed_oldest_first_up_to_the_cap(self):
        for pid, row in self.harness.graph.passages.items():
            row.pop("embedding", None)
        self.harness.graph.nodes[ADR_NOTE][1].pop("embedding")
        total = len(self.vectorless())
        saved = forge_import.HEAL_ROWS_PER_RUN
        forge_import.HEAL_ROWS_PER_RUN = 3
        try:
            plan = self.harness.plan_and_apply(LATER)
        finally:
            forge_import.HEAL_ROWS_PER_RUN = saved
        self.assertEqual((plan.node_rows, plan.passage_units), ([], []))
        self.assertEqual(plan.counts.heal_planned, 3)
        self.assertEqual(len(self.vectorless()), total - 3)
        self.assertEqual(self.harness.embed_report["missing"]["Note"] + self.harness.embed_report["missing"]["Passage"], total - 3)
        self.assertEqual(self.harness.graph.nodes[ADR_NOTE][1]["updatedAt"], NOW)
        for _ in range(total):
            if not self.vectorless():
                break
            self.harness.plan_and_apply(LATER)
        self.assertEqual(self.vectorless(), [])

    def test_a_failed_embedding_still_writes_the_change_and_the_next_run_heals_it(self):
        self.harness.forge.blobs["b-guide2"] = "# Guide\n\nHow to run it, now with Helm.\n"
        tree = self.harness.forge.trees[("webgrip", "homelab-cluster")]
        tree[4] = blob_entry("docs/guide.md", "b-guide2")
        self.harness.embedder = FakeEmbedder(fail=True)
        self.harness.plan_and_apply(LATER)
        guide = "forge/webgrip/homelab-cluster/doc/docs/guide#0"
        self.assertEqual(self.harness.graph.passages[guide]["text"], "# Guide\n\nHow to run it, now with Helm.")
        self.assertIsNone(self.harness.graph.passages[guide].get("embedding"))
        self.assertEqual(self.harness.embed_report["missing"]["Passage"], 1)
        self.harness.embedder = FakeEmbedder()
        plan = self.harness.plan_and_apply(LATER)
        self.assertEqual(plan.counts.heal_planned, 1)
        self.assertEqual(len(self.harness.graph.passages[guide]["embedding"]), 384)

    def test_heal_never_rewrites_rows_this_run_changes_or_deletes(self):
        for row in self.harness.graph.passages.values():
            row.pop("embedding", None)
        self.harness.forge.org_repos["acme-client"] = []
        plan = self.harness.plan(LATER)
        healed = {row.get("id") or row["data"]["slug"] for row in plan.heal_rows}
        deleted = {statement.split('"')[1] for statement in plan.prune_statements if statement.startswith("delete Passage")}
        self.assertTrue(deleted)
        self.assertFalse(healed & deleted)

    def test_embed_plan_lists_the_writer_and_heal_ages(self):
        for row in self.harness.graph.passages.values():
            row.pop("embedding", None)
        self.harness.plan(LATER)
        embed_plan = json.loads((self.harness.out / "embed-plan.json").read_text(encoding="utf-8"))
        self.assertEqual(embed_plan["writer"], "forge-import")
        self.assertTrue(all(since == NOW for since in embed_plan["heal_since"].values()))

    def test_unchanged_docs_are_never_read_back_from_the_graph(self):
        self.harness.reads.clear()
        self.harness.plan(LATER)
        self.assertEqual(self.harness.reads, [])


class Batching(unittest.TestCase):
    def setUp(self):
        self.saved = (forge_import.ROWS_PER_LOAD_FILE, forge_import.STATEMENTS_PER_PRUNE_FILE)
        forge_import.ROWS_PER_LOAD_FILE = 7
        forge_import.STATEMENTS_PER_PRUNE_FILE = 3
        forge = FakeForge()
        forge.issues[("webgrip", "homelab-cluster")] = [
            {"number": number, "title": f"Issue {number}", "state": "open", "body": "\n\n".join(["text " * 250] * 3),
             "user": user("ryangr0"), "created_at": "2026-08-01T09:00:00Z", "html_url": f"https://forge.example/i/{number}"}
            for number in range(10, 40)]
        self.harness = Harness(forge)

    def tearDown(self):
        forge_import.ROWS_PER_LOAD_FILE, forge_import.STATEMENTS_PER_PRUNE_FILE = self.saved
        self.harness.close()

    def test_load_files_respect_the_row_limit_and_keep_passage_pairs_together(self):
        self.harness.plan_and_apply()
        files = sorted(self.harness.out.glob("load-*.ndjson"))
        self.assertGreater(len(files), 10)
        for path in files:
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertLessEqual(len(lines), 7)
            self.assertEqual({row["id"] for row in lines if row.get("type") == "Passage" and len(lines) > 0 and any(edge.get("edge") == "PassageOf" for edge in lines)},
                             {row["from"] for row in lines if row.get("edge") == "PassageOf"})

    def test_load_files_stay_under_the_byte_limit_once_vectors_are_filled_in(self):
        saved = forge_import.BYTES_PER_LOAD_FILE
        forge_import.ROWS_PER_LOAD_FILE = 2000
        forge_import.BYTES_PER_LOAD_FILE = 40000
        try:
            self.harness.plan()
            self.harness.embed(RealisticEmbedder())
        finally:
            forge_import.BYTES_PER_LOAD_FILE = saved
        files = sorted(self.harness.out.glob("load-*.ndjson"))
        self.assertGreater(len(files), 3)
        for path in files:
            self.assertLessEqual(len(path.read_bytes()), 40000, path.name)

    def test_prune_files_respect_the_statement_limit(self):
        self.harness.plan_and_apply()
        self.harness.forge.issues[("webgrip", "homelab-cluster")] = []
        plan = self.harness.plan_and_apply(LATER)
        files = sorted(self.harness.out.glob("prune-*.gq"))
        self.assertEqual(len(files), -(-len(plan.prune_statements) // 3))
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("query forge_prune() {"))
            self.assertLessEqual(text.count("delete "), 3)
        self.assertFalse([slug for slug in self.harness.graph.nodes if "/issue/" in slug])


class FailClosed(unittest.TestCase):
    def test_missing_token_fails_with_a_clear_message_and_writes_nothing(self):
        harness = Harness(token=None)
        try:
            with self.assertRaises(forge_import.FailClosed) as raised:
                harness.plan()
            self.assertEqual(raised.exception.exit_code, forge_import.EXIT_NO_TOKEN)
            self.assertIn("no forge token", str(raised.exception))
            self.assertIn("secret/omnigraph/forge-import", str(raised.exception))
            self.assertFalse(harness.out.exists())
            self.assertEqual(harness.forge.requests, [])
        finally:
            harness.close()

    def test_rejected_token_fails_closed(self):
        harness = Harness(token="wrong")
        try:
            with self.assertRaises(forge_import.FailClosed) as raised:
                harness.plan()
            self.assertEqual(raised.exception.exit_code, forge_import.EXIT_FORGE_FAILED)
            self.assertIn("forge token rejected", str(raised.exception))
        finally:
            harness.close()

    def test_api_error_mid_run_writes_no_plan(self):
        harness = Harness()
        try:
            harness.plan_and_apply()
            harness.forge.failing_paths.add("/api/v1/repos/webgrip/homelab-cluster/pulls")
            with self.assertRaises(forge_import.FailClosed) as raised:
                harness.plan(LATER)
            self.assertEqual(raised.exception.exit_code, forge_import.EXIT_FORGE_FAILED)
            self.assertIn("HTTP 500", str(raised.exception))
            self.assertFalse(harness.out.exists())
        finally:
            harness.close()

    def test_token_that_sees_nothing_never_deletes_the_brain(self):
        harness = Harness()
        try:
            harness.plan_and_apply()
            harness.forge.user_repos, harness.forge.org_repos, harness.forge.orgs = [], {}, []
            with self.assertRaises(forge_import.FailClosed) as raised:
                harness.plan(LATER)
            self.assertEqual(raised.exception.exit_code, forge_import.EXIT_NOTHING_VISIBLE)
        finally:
            harness.close()

    def test_main_prints_the_refusal_and_returns_its_exit_code(self):
        harness = Harness(token=None)
        try:
            snapshot = harness.root / "empty"
            harness.graph.snapshot(snapshot)
            argv = ["--forge-url", harness.server.url, "--token-file", str(harness.token), "--scope-file", str(harness.scope),
                    "--snapshot-dir", str(snapshot), "--omnigraph-url", "http://omnigraph.invalid", "--omnigraph-token-file", str(harness.token),
                    "--out", str(harness.root / "plan")]
            self.assertEqual(forge_import.main(argv), forge_import.EXIT_NO_TOKEN)
        finally:
            harness.close()


class TreePagination(unittest.TestCase):
    def test_truncated_trees_are_read_page_by_page(self):
        saved = forge_import.TREE_PAGE_SIZE
        forge_import.TREE_PAGE_SIZE = 2
        harness = Harness()
        try:
            harness.plan()
            self.assertIn("forge/webgrip/homelab-cluster/doc/docs/guide", nodes(harness.load_rows(), "Artifact"))
        finally:
            forge_import.TREE_PAGE_SIZE = saved
            harness.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)
