#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import random
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/ai/omnigraph/distill/app"
DISTILLER = APP / "distill.py"
SNAPSHOT_QUERIES = APP / "snapshot.gq"
EXTRACTION_SCHEMA = APP / "extraction.schema.json"
PROMPT = APP / "extraction.prompt.txt"
MERGE_PROMPT = APP / "merge.prompt.txt"
BRAIN_SCHEMA = ROOT / "kubernetes/apps/ai/omnigraph/app/bundle/brain.pg"
NOW = "2026-09-28T12:00:00Z"
LATER = "2026-09-28T13:00:00Z"
MODEL = "fake-model"
CANDIDATE_SIMILARITY = 0.75
SAME_SIMILARITY = 0.97
ROWS_PER_COMMIT = 2000
STATEMENTS_PER_COMMIT = 500

spec = importlib.util.spec_from_file_location("distill", DISTILLER)
distill = importlib.util.module_from_spec(spec)
sys.modules["distill"] = distill
spec.loader.exec_module(distill)


def parse_schema():
    text = BRAIN_SCHEMA.read_text(encoding="utf-8")
    nodes = {}
    for name, body in re.findall(r"^node (\w+) \{(.*?)^\}", text, re.M | re.S):
        props = {}
        for prop, kind in re.findall(r"^\s+(\w+): ([^\n@]+)", body, re.M):
            props[prop] = kind.strip()
        nodes[name] = props
    edges = {name: (src, dst) for name, src, dst in re.findall(r"^edge (\w+): (\w+) -> (\w+)", text, re.M)}
    return nodes, edges


NODES, EDGES = parse_schema()


def topic(name, about=True, description="", aliases=()):
    return {"name": name, "about": about, "description": description, "aliases": list(aliases)}


def named(name, about=True, **extra):
    return dict({"name": name, "about": about}, **extra)


def extraction(topics=(), people=(), organizations=(), projects=(), places=(), areas=()):
    return {"topics": list(topics), "people": list(people), "organizations": list(organizations),
            "projects": list(projects), "places": list(places), "areas": list(areas)}


def basis(index, wobble=0.0):
    vector = [0.0] * distill.EMBEDDING_DIMENSION
    vector[index] = 1.0
    vector[(index + 1) % distill.EMBEDDING_DIMENSION] = wobble
    return vector


def scattered(text):
    generator = random.Random(hashlib.sha1(text.encode()).hexdigest())
    return [generator.gauss(0, 1) for _ in range(distill.EMBEDDING_DIMENSION)]


class FakeGraph:
    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.writes = 0

    def add(self, node_type, **data):
        data.setdefault("createdAt", "2026-09-01T00:00:00Z")
        data.setdefault("updatedAt", "2026-09-01T00:00:00Z")
        self.nodes[data["slug"]] = (node_type, data)

    def link(self, edge_type, source, target, identifier=None, data=None):
        assert source in self.nodes and target in self.nodes, (edge_type, source, target)
        identifier = identifier or hashlib.sha1(f"{edge_type}{source}{target}{len(self.edges)}".encode()).hexdigest()
        self.edges[identifier] = (edge_type, source, target, dict(data or {}))

    def snapshot(self, directory):
        queries = re.findall(r"^query (\w+)\(\) \{(.*?)^\}", SNAPSHOT_QUERIES.read_text(encoding="utf-8"), re.M | re.S)
        for name, body in queries:
            result = []
            node_match = re.search(r"\$n: (\w+)", body)
            if node_match:
                fields = re.findall(r"\$n\.(\w+)", body)
                for slug, (node_type, data) in sorted(self.nodes.items()):
                    if node_type == node_match.group(1):
                        result.append({f"n.{key}": data[key] for key in fields if data.get(key) is not None})
            else:
                source_type = re.search(r"\$s: (\w+)", body).group(1)
                edge_name = re.search(r"\$s \$e:(\w+) \$t", body).group(1)
                derived_side = re.search(r"\$(s|t)\.slug starts_with", body)
                for identifier, (edge_type, source, target, data) in sorted(self.edges.items()):
                    if edge_type.lower() != edge_name.lower() or self.nodes[source][0] != source_type:
                        continue
                    if derived_side and not (source if derived_side.group(1) == "s" else target).startswith("derived/"):
                        continue
                    row = {"e.@id": identifier, "s.@id": source, "t.@id": target}
                    if "$e.documents" in body and data.get("documents") is not None:
                        row["e.documents"] = data["documents"]
                    result.append(row)
            Path(directory, f"{name}.json").write_text(json.dumps({"rows": result}), encoding="utf-8")

    def apply(self, plan_dir):
        for path in sorted(Path(plan_dir).glob("prune-*.gq")):
            self.writes += 1
            statements = re.findall(r"^\s+delete (\w+) where (@id|slug) = (\".*\")$", path.read_text(encoding="utf-8"), re.M)
            assert statements, path.read_text(encoding="utf-8")
            assert len(statements) <= STATEMENTS_PER_COMMIT
            for type_name, field_name, literal in statements:
                value = json.loads(literal)
                if field_name == "@id":
                    assert type_name in EDGES
                    self.edges.pop(value, None)
                    continue
                if value in self.nodes and self.nodes[value][0] == type_name:
                    del self.nodes[value]
                    self.edges = {key: edge for key, edge in self.edges.items() if value not in (edge[1], edge[2])}
        for path in sorted(Path(plan_dir).glob("load-*.ndjson")):
            self.writes += 1
            lines = path.read_text(encoding="utf-8").splitlines()
            assert len(lines) <= ROWS_PER_COMMIT
            for line in lines:
                row = json.loads(line)
                if "type" in row:
                    self.check_node(row["type"], row["data"])
                    self.nodes[row["data"]["slug"]] = (row["type"], row["data"])
                else:
                    assert row["edge"] in EDGES, row
                    source_type, target_type = EDGES[row["edge"]]
                    assert row["from"] in self.nodes and self.nodes[row["from"]][0] == source_type, row
                    assert row["to"] in self.nodes and self.nodes[row["to"]][0] == target_type, row
                    assert row["id"] == distill.edge_id(row["edge"], row["from"], row["to"]), row
                    self.edges[row["id"]] = (row["edge"], row["from"], row["to"], row.get("data") or {})

    def check_node(self, node_type, data):
        props = NODES[node_type]
        for prop, kind in props.items():
            if not kind.endswith("?") and not kind.startswith("[") and prop not in data:
                raise AssertionError(f"{node_type} misses required {prop}: {data}")
            enum = re.match(r"enum\(([^)]*)\)", kind)
            if enum and prop in data:
                assert data[prop] in [value.strip() for value in enum.group(1).split(",")], (node_type, prop, data[prop])
        unknown = set(data) - set(props)
        assert not unknown, (node_type, unknown)
        if node_type == "Topic" and "embedding" in data:
            assert len(data["embedding"]) == distill.EMBEDDING_DIMENSION

    def owned(self, edge_type=None):
        return sorted((edge[0], edge[1], edge[2]) for key, edge in self.edges.items()
                      if key.startswith(distill.OWNED_EDGE_PREFIX) and (edge_type is None or edge[0] == edge_type))

    def of_type(self, node_type):
        return {slug: data for slug, (kind, data) in self.nodes.items() if kind == node_type}


class FakeLiteLLM:
    def __init__(self, answers, vectors=None, cost=0.001, fail=(), unreachable=False, same=(), refuse=(), wrong_aliases=()):
        self.refuse = set(refuse)
        self.wrong_aliases = set(wrong_aliases)
        self.declared = {}
        for answer in answers.values():
            for item in answer["topics"]:
                self.declared.setdefault(item["name"], set()).update(item.get("aliases") or [])
        self.same = {frozenset(pair) for pair in same}
        self.questions = []
        self.answers = answers
        self.vectors = vectors or {}
        self.cost = cost
        self.fail = set(fail)
        self.unreachable = unreachable
        self.calls = []
        self.embedded = []

    def factory(self, base_url, key, counts):
        self.counts = counts
        return self

    def extract(self, model, system, schema, text):
        title = re.search(r"^Title: (.*)$", text, re.M).group(1)
        self.calls.append(title)
        if self.unreachable:
            raise distill.LLMUnreachable("down")
        if title in self.refuse:
            raise distill.ExtractionFailed("litellm answered HTTP 400", refused=True)
        if title in self.fail:
            return "not json", 10, 0, self.cost
        return json.dumps(self.answers.get(title, extraction())), 100, 20, self.cost

    def same_topic(self, model, system, pair):
        names = [side.split(" (")[0] for side in pair]
        self.questions.append(tuple(names))
        if names[0] in self.declared.get(names[1], set()) and names[0] not in self.wrong_aliases:
            return True
        return frozenset(names) in self.same

    def embed(self, model, texts):
        self.embedded.extend(texts)
        return [self.vectors.get(text) or scattered(text) for text in texts]


def documents_distilled(graph):
    return [slug for slug, data in graph.of_type("Distillation").items() if not data["source"].startswith("derived/")]


def seeded_graph():
    graph = FakeGraph()
    graph.add("Note", slug="obsidian/k8s-upgrade", name="K8s upgrade", kind="idea", content="Upgrading the Kubernetes cluster with Talos.")
    graph.add("Note", slug="obsidian/fiets", name="Fiets", kind="idea", content="Fietsketting vervangen voor de winter.")
    graph.add("Note", slug="obsidian/dinner-sam", name="Dinner with Sam", kind="journal", content="Dinner with Sam de Vries in Utrecht.")
    graph.add("Note", slug="forge/webgrip/homelab-cluster/adr/adr-0001", name="ADR-0001 Flux", kind="decision", content="We use Flux for GitOps.")
    graph.add("Project", slug="forge/webgrip/homelab-cluster", name="webgrip/homelab-cluster", kind="work", status="active", brief="GitOps homelab", tags=["forgejo"])
    graph.add("Project", slug="forge/webgrip/ploeg", name="webgrip/ploeg", kind="work", status="active", brief="Agent dispatch", tags=["forgejo"])
    graph.add("Project", slug="forge/actions/checkout", name="actions/checkout", kind="work", status="active", tags=["forgejo", "mirror"])
    graph.add("Artifact", slug="forge/webgrip/homelab-cluster/readme", name="webgrip/homelab-cluster README", kind="document", source="other",
              content="# Homelab\nFlux, Talos and Kubernetes. See also ploeg.", timestamp="2026-09-01T00:00:00Z")
    graph.add("Artifact", slug="forge/webgrip/homelab-cluster/issue/1", name="webgrip/homelab-cluster#1 Flux is slow", kind="post", source="other",
              content="Flux reconciles slowly. @alice", timestamp="2026-09-01T00:00:00Z")
    graph.add("Person", slug="forge/user/ryangr0", name="Ryan Grippeling", relation="self")
    graph.add("Person", slug="forge/user/alice", name="Alice Jansen", relation="professional")
    graph.add("Organization", slug="forge/org/webgrip", name="Webgrip", kind="company")
    graph.link("ArtifactForProject", "forge/webgrip/homelab-cluster/readme", "forge/webgrip/homelab-cluster")
    graph.link("NoteAboutProject", "forge/webgrip/homelab-cluster/adr/adr-0001", "forge/webgrip/homelab-cluster")
    graph.link("RelatedNote", "obsidian/k8s-upgrade", "obsidian/fiets")
    return graph


def answers():
    return {
        "K8s upgrade": extraction(topics=[topic("Kubernetes", description="Container orchestration", aliases=["k8s"]), topic("Talos Linux")],
                                  projects=[named("homelab-cluster")], areas=["career"]),
        "Fiets": extraction(topics=[topic("Bicycle maintenance", description="Keeping bikes working", aliases=["fietsonderhoud"])], areas=["home"]),
        "Dinner with Sam": extraction(topics=[topic("Friendship")], people=[named("Sam de Vries", relation="friend")],
                                      places=[named("Utrecht", kind="city")], areas=["relationships"]),
        "ADR-0001 Flux": extraction(topics=[topic("GitOps"), topic("Flux CD")], projects=[named("webgrip/homelab-cluster"), named("ploeg")]),
        "webgrip/homelab-cluster": extraction(topics=[topic("Kubernetes"), topic("GitOps")], organizations=[named("Webgrip B.V.", kind="company")], areas=["career"]),
        "webgrip/ploeg": extraction(topics=[topic("AI agents")]),
        "actions/checkout": extraction(topics=[topic("CI/CD")]),
        "webgrip/homelab-cluster README": extraction(topics=[topic("Kubernetes"), topic("GitOps"), topic("Talos Linux")],
                                                     projects=[named("webgrip/homelab-cluster"), named("ploeg", about=False)]),
        "webgrip/homelab-cluster#1 Flux is slow": extraction(topics=[topic("Flux CD"), topic("Performance", about=False)],
                                                             people=[named("Alice Jansen", about=False, relation="colleague"), named("Bob Unknown", about=False, relation="colleague")]),
    }


class Harness:
    def __init__(self, graph, llm, **overrides):
        self.graph = graph
        self.llm = llm
        self.settings = dict(model=MODEL, embed_model="embed", candidate_similarity=CANDIDATE_SIMILARITY, same_similarity=SAME_SIMILARITY, related_min_documents=2,
                             max_documents=1000, max_spend_usd=10.0, workers=3)
        self.settings.update(overrides)

    def run(self, now=NOW):
        with tempfile.TemporaryDirectory() as work:
            snapshot, plan_dir = Path(work, "snapshot"), Path(work, "plan")
            snapshot.mkdir()
            self.graph.snapshot(snapshot)
            key = Path(work, "key")
            key.write_text("sk-test\n", encoding="utf-8")
            args = SimpleNamespace(snapshot_dir=str(snapshot), out=str(plan_dir), litellm_url="http://litellm.invalid", key_file=str(key),
                                   prompt_file=str(PROMPT), merge_prompt_file=str(MERGE_PROMPT), schema_file=str(EXTRACTION_SCHEMA), **self.settings)
            plan = distill.run(args, now, client_factory=self.llm.factory)
            self.files = sorted(path.name for path in plan_dir.glob("*")) if plan_dir.exists() else []
            self.failed_marker = Path(plan_dir, "failed").exists()
            if plan_dir.exists():
                self.graph.apply(plan_dir)
            return plan


class ExtractionParsing(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(EXTRACTION_SCHEMA.read_text(encoding="utf-8"))

    def test_fenced_json_is_accepted_and_cleaned(self):
        raw = "```json\n" + json.dumps({
            "topics": [topic(" Kubernetes  cluster ", aliases=["k8s", "", 3]), topic("Mentioned only", about=False)] + [topic(f"T{i}") for i in range(10)],
            "people": [{"name": "Sam", "about": True, "relation": "not-a-relation"}, {"name": "", "about": True, "relation": "friend"}],
            "organizations": [], "projects": [], "places": [{"name": "Utrecht", "about": "yes", "kind": "city"}],
            "areas": ["career", "made-up"]}) + "\n```"
        parsed = distill.parse_extraction(raw, self.schema)
        self.assertEqual(parsed["topics"][0], {"name": "Kubernetes cluster", "about": True, "description": "", "aliases": ["k8s"]})
        self.assertEqual(len(parsed["topics"]), distill.MAX_TOPICS)
        self.assertNotIn("Mentioned only", [item["name"] for item in parsed["topics"]])
        self.assertEqual(parsed["people"], [{"name": "Sam", "about": True, "relation": None}])
        self.assertFalse(parsed["places"][0]["about"])
        self.assertEqual(parsed["areas"], ["career"])

    def test_garbage_is_refused(self):
        for raw in ("", "no json here", "[1, 2]", json.dumps({"topics": "Kubernetes"})):
            with self.assertRaises(distill.ExtractionFailed):
                distill.parse_extraction(raw, self.schema)

    def test_schema_enums_match_brain(self):
        people = self.schema["properties"]["people"]["items"]["properties"]["relation"]["enum"]
        self.assertNotIn("self", people)
        for prop, node, field in (("people", "Person", "relation"), ("organizations", "Organization", "kind"), ("places", "Place", "kind")):
            wanted = self.schema["properties"][prop]["items"]["properties"]["relation" if prop == "people" else "kind"]["enum"]
            allowed = [value.strip() for value in re.match(r"enum\(([^)]*)\)", NODES[node][field]).group(1).split(",")]
            self.assertTrue(set(wanted) <= set(allowed), prop)
        areas = [value.strip() for value in re.match(r"enum\(([^)]*)\)", NODES["Area"]["kind"]).group(1).split(",")]
        self.assertEqual(self.schema["properties"]["areas"]["items"]["enum"], areas)


class Resolution(unittest.TestCase):
    def test_name_keys_fold_case_accents_articles_and_legal_suffixes(self):
        self.assertEqual(distill.name_key("Kubernetes"), distill.name_key("kubernetes"))
        self.assertEqual(distill.name_key("Webgrip B.V."), distill.name_key("webgrip"))
        self.assertEqual(distill.name_key("Café Olé"), distill.name_key("cafe ole"))
        self.assertEqual(distill.name_key("The Network Policies"), distill.name_key("network policy"))
        self.assertNotEqual(distill.name_key("PostgreSQL"), distill.name_key("MySQL"))

    def test_first_run_links_documents_to_resolved_entities(self):
        graph = seeded_graph()
        llm = FakeLiteLLM(answers())
        plan = Harness(graph, llm).run()
        topics = graph.of_type("Topic")
        names = sorted(data["name"] for data in topics.values())
        self.assertEqual(names, ["AI agents", "Bicycle maintenance", "CI/CD", "Flux CD", "Friendship", "GitOps", "Kubernetes", "Talos Linux"])
        self.assertTrue(all(slug.startswith("derived/topic/") for slug in topics))
        self.assertIn(("NoteAboutTopic", "obsidian/k8s-upgrade", "derived/topic/kubernetes"), graph.owned())
        self.assertIn(("NoteAboutProject", "obsidian/k8s-upgrade", "forge/webgrip/homelab-cluster"), graph.owned())
        self.assertIn(("ProjectAboutTopic", "forge/webgrip/homelab-cluster", "derived/topic/gitops"), graph.owned())
        self.assertIn(("ProjectInArea", "forge/webgrip/homelab-cluster", "derived/area/career"), graph.owned())
        self.assertIn(("NoteAboutPerson", "obsidian/dinner-sam", "derived/person/sam-de-vries"), graph.owned())
        self.assertIn(("NoteAboutPlace", "obsidian/dinner-sam", "derived/place/utrecht"), graph.owned())
        self.assertIn(("MentionsPerson", "forge/webgrip/homelab-cluster/issue/1", "forge/user/alice"), graph.owned())
        self.assertNotIn(("ArtifactAboutProject", "forge/webgrip/homelab-cluster/readme", "forge/webgrip/ploeg"), graph.owned())
        self.assertNotIn("derived/person/bob-unknown", graph.nodes)
        self.assertNotIn("Organization", {graph.nodes[slug][0] for slug in graph.nodes if slug.startswith("derived/")})
        self.assertEqual(plan.counts.processed, 9)
        self.assertEqual(plan.counts.failed, 0)
        self.assertEqual(len(documents_distilled(graph)), 9)

    def test_importer_managed_edges_and_own_project_are_left_alone(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        owned = graph.owned()
        self.assertFalse([edge for edge in owned if edge[1].startswith("forge/") and edge[0] in distill.IMPORTER_MANAGED["forge/"]])
        self.assertNotIn(("ArtifactAboutProject", "forge/webgrip/homelab-cluster/readme", "forge/webgrip/homelab-cluster"), owned)
        self.assertFalse([edge for edge in owned if edge[0] == "RelatedNote"])
        self.assertEqual(len([edge for edge in graph.edges.values() if edge[0] == "NoteAboutProject" and edge[1].startswith("forge/")]), 1)

    def test_embedding_candidates_merge_only_when_confirmed_or_near_identical(self):
        graph = seeded_graph()
        extra = answers()
        extra["webgrip/ploeg"] = extraction(topics=[topic("Kubernetes platform")])
        extra["actions/checkout"] = extraction(topics=[topic("Cycling"), topic("Kubernetes distribution"), topic("Kubernetes spelling")])
        platform = basis(1)
        platform[5] = 0.3
        vectors = {"Kubernetes": basis(1), "Kubernetes platform": platform, "Cycling": basis(1, 1.2),
                   "Kubernetes distribution": basis(1, 0.4), "Kubernetes spelling": basis(1, 0.1)}
        llm = FakeLiteLLM(extra, vectors, same=[("Kubernetes platform", "Kubernetes")])
        plan = Harness(graph, llm).run()
        topics = graph.of_type("Topic")
        self.assertEqual(plan.counts.topics_merged, 2)
        self.assertNotIn("derived/topic/kubernetes-platform", topics)
        self.assertNotIn("derived/topic/kubernetes-spelling", topics)
        self.assertIn("derived/topic/kubernetes-distribution", topics)
        self.assertIn("derived/topic/cycling", topics)
        self.assertIn(("Kubernetes distribution", "Kubernetes"), llm.questions)
        self.assertNotIn(("Cycling", "Kubernetes"), llm.questions)
        self.assertIn("Kubernetes platform", topics["derived/topic/kubernetes"]["aliases"])
        self.assertIn(("ProjectAboutTopic", "forge/webgrip/ploeg", "derived/topic/kubernetes"), graph.owned())

    def test_alias_hits_are_confirmed_and_wrong_aliases_are_dropped(self):
        graph = seeded_graph()
        first = answers()
        first["Fiets"] = extraction(topics=[topic("containerd", description="Container runtime", aliases=["Docker", "cri"])])
        Harness(graph, FakeLiteLLM(first)).run()
        self.assertEqual(sorted(graph.nodes["derived/topic/kubernetes"][1]["aliases"]), ["k8s"])
        self.assertEqual(sorted(graph.nodes["derived/topic/containerd"][1]["aliases"]), ["Docker", "cri"])
        graph.nodes["obsidian/dinner-sam"][1]["content"] = "Now about clusters and images."
        second = answers()
        second["Dinner with Sam"] = extraction(topics=[topic("K8S"), topic("Docker")])
        llm = FakeLiteLLM(second, same=[("K8S", "Kubernetes")])
        llm.declared["containerd"] = {"cri"}
        plan = Harness(graph, llm).run(LATER)
        self.assertIn(("NoteAboutTopic", "obsidian/dinner-sam", "derived/topic/kubernetes"), graph.owned())
        self.assertIn(("NoteAboutTopic", "obsidian/dinner-sam", "derived/topic/docker"), graph.owned())
        self.assertEqual(graph.nodes["derived/topic/containerd"][1]["aliases"], ["cri"])
        self.assertEqual(plan.counts.aliases_dropped, 1)
        self.assertIn(("K8S", "Kubernetes"), llm.questions)
        self.assertIn(("Docker", "containerd"), llm.questions)

    def test_an_alias_of_a_topic_created_in_the_same_run_is_not_trusted(self):
        graph = seeded_graph()
        extra = answers()
        extra["Dinner with Sam"] = extraction(topics=[topic("containerd", aliases=["Docker"])])
        extra["Fiets"] = extraction(topics=[topic("Docker")])
        llm = FakeLiteLLM(extra, wrong_aliases={"Docker"})
        Harness(graph, llm).run()
        self.assertIn(("NoteAboutTopic", "obsidian/fiets", "derived/topic/docker"), graph.owned())
        self.assertIn(("Docker", "containerd"), llm.questions)

    def test_every_alias_is_audited_once_and_wrong_ones_are_removed(self):
        graph = seeded_graph()
        extra = answers()
        extra["Fiets"] = extraction(topics=[topic("containerd", aliases=["Docker Engine", "container runtime"])])
        llm = FakeLiteLLM(extra, wrong_aliases={"Docker Engine"})
        plan = Harness(graph, llm).run()
        self.assertEqual(graph.nodes["derived/topic/containerd"][1]["aliases"], ["container runtime"])
        self.assertEqual(plan.counts.aliases_dropped, 1)
        self.assertIn("derived/distill/derived/topic/containerd", graph.nodes)
        graph.nodes["obsidian/dinner-sam"][1]["content"] = "changed"
        llm = FakeLiteLLM(answers())
        plan = Harness(graph, llm).run(LATER)
        self.assertEqual(plan.counts.alias_questions, 0)
        graph.nodes["obsidian/fiets"][1]["content"] = "changed"
        Harness(graph, FakeLiteLLM(answers())).run(LATER)
        self.assertNotIn("derived/topic/containerd", graph.nodes)
        self.assertNotIn("derived/distill/derived/topic/containerd", graph.nodes)

    def test_an_unanswered_audit_keeps_the_aliases_and_asks_again(self):
        graph = seeded_graph()
        extra = answers()
        extra["Fiets"] = extraction(topics=[topic("containerd", aliases=["Docker Engine"])])
        llm = FakeLiteLLM(extra)
        llm.same_topic = lambda model, system, pair: None
        Harness(graph, llm).run()
        self.assertEqual(graph.nodes["derived/topic/containerd"][1]["aliases"], ["Docker Engine"])
        self.assertNotIn("derived/distill/derived/topic/containerd", graph.nodes)

    def test_new_topic_aliases_never_shadow_existing_topic_names(self):
        graph = seeded_graph()
        extra = answers()
        extra["Fiets"] = extraction(topics=[topic("Container orchestration", aliases=["Kubernetes", "orchestration"])])
        Harness(graph, FakeLiteLLM(extra)).run()
        self.assertEqual(graph.nodes["derived/topic/container-orchestration"][1]["aliases"], ["orchestration"])

    def test_similar_siblings_stay_apart_when_the_adjudicator_says_no(self):
        graph = seeded_graph()
        extra = answers()
        extra["Fiets"] = extraction(topics=[topic("MySQL")])
        extra["webgrip/ploeg"] = extraction(topics=[topic("PostgreSQL")])
        llm = FakeLiteLLM(extra, {"MySQL": basis(7), "PostgreSQL": basis(7, 0.45)})
        Harness(graph, llm).run()
        self.assertIn("derived/topic/mysql", graph.nodes)
        self.assertIn("derived/topic/postgresql", graph.nodes)
        self.assertIn(("PostgreSQL", "MySQL"), llm.questions)

    def test_the_owner_is_recognised_by_first_name_and_login(self):
        graph = seeded_graph()
        extra = answers()
        extra["Fiets"] = extraction(topics=[topic("Bicycle maintenance")], people=[named("Ryan", relation="colleague"), named("ryangr0", relation="colleague")])
        Harness(graph, FakeLiteLLM(extra)).run()
        self.assertIn(("NoteAboutPerson", "obsidian/fiets", "forge/user/ryangr0"), graph.owned())
        self.assertFalse([slug for slug in graph.nodes if slug.startswith("derived/person/ryan")])

    def test_ambiguous_project_names_prefer_the_non_mirror_and_never_create_projects(self):
        graph = seeded_graph()
        graph.add("Project", slug="forge/ryangr0/checkout", name="ryangr0/checkout", kind="side-project", status="active", tags=["forgejo"])
        extra = answers()
        extra["Fiets"] = extraction(topics=[topic("Bicycle maintenance")], projects=[named("checkout"), named("Unknown Thing")])
        Harness(graph, FakeLiteLLM(extra)).run()
        self.assertIn(("NoteAboutProject", "obsidian/fiets", "forge/ryangr0/checkout"), graph.owned())
        self.assertEqual(len(graph.of_type("Project")), 4)


class Incremental(unittest.TestCase):
    def test_second_run_is_a_no_op(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        before = (dict(graph.nodes), dict(graph.edges))
        llm = FakeLiteLLM(answers())
        harness = Harness(graph, llm)
        plan = harness.run(LATER)
        self.assertEqual(llm.calls, [])
        self.assertEqual(harness.files, [])
        self.assertEqual((dict(graph.nodes), dict(graph.edges)), before)
        self.assertEqual(plan.counts.pending, 0)

    def test_changed_document_is_relinked_and_orphans_are_removed(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        graph.nodes["obsidian/fiets"][1]["content"] = "Nu over hardlopen."
        changed = answers()
        changed["Fiets"] = extraction(topics=[topic("Running")], areas=["health"])
        llm = FakeLiteLLM(changed)
        plan = Harness(graph, llm).run(LATER)
        self.assertEqual(llm.calls, ["Fiets"])
        self.assertNotIn("derived/topic/bicycle-maintenance", graph.nodes)
        self.assertNotIn("derived/area/home", graph.nodes)
        self.assertIn(("NoteAboutTopic", "obsidian/fiets", "derived/topic/running"), graph.owned())
        self.assertIn(("NoteAboutArea", "obsidian/fiets", "derived/area/health"), graph.owned())
        self.assertEqual(plan.counts.edges_removed, 2)
        self.assertEqual(plan.counts.entities_deleted, 2)

    def test_shared_entities_survive_while_another_document_links_them(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        graph.nodes["obsidian/k8s-upgrade"][1]["content"] = "Only about Talos now."
        changed = answers()
        changed["K8s upgrade"] = extraction(topics=[topic("Talos Linux")])
        Harness(graph, FakeLiteLLM(changed)).run(LATER)
        self.assertIn("derived/topic/kubernetes", graph.nodes)
        self.assertNotIn(("NoteAboutTopic", "obsidian/k8s-upgrade", "derived/topic/kubernetes"), graph.owned())

    def test_deleted_source_drops_its_state_and_orphaned_entities(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        del graph.nodes["obsidian/dinner-sam"]
        graph.edges = {key: edge for key, edge in graph.edges.items() if "obsidian/dinner-sam" not in (edge[1], edge[2])}
        llm = FakeLiteLLM(answers())
        plan = Harness(graph, llm).run(LATER)
        self.assertEqual(llm.calls, [])
        for slug in ("derived/distill/obsidian/dinner-sam", "derived/person/sam-de-vries", "derived/place/utrecht", "derived/topic/friendship", "derived/area/relationships"):
            self.assertNotIn(slug, graph.nodes)
        self.assertEqual(plan.counts.sources_gone, 1)

    def test_a_foreign_link_keeps_a_derived_entity_alive_and_is_never_duplicated(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        graph.add("Note", slug="nt-sam-birthday", name="Sam birthday", kind="idea", content="Sam turns 40.")
        graph.link("NoteAboutPerson", "nt-sam-birthday", "derived/person/sam-de-vries")
        graph.link("NoteAboutTopic", "obsidian/fiets", "derived/topic/bicycle-maintenance", identifier="hand-made")
        graph.nodes["obsidian/dinner-sam"][1]["content"] = "Dinner alone."
        graph.nodes["obsidian/fiets"][1]["content"] = "Fietsketting, opnieuw."
        changed = answers()
        changed["Dinner with Sam"] = extraction(topics=[topic("Cooking")])
        Harness(graph, FakeLiteLLM(changed)).run(LATER)
        self.assertIn("derived/person/sam-de-vries", graph.nodes)
        self.assertNotIn(("NoteAboutPerson", "obsidian/dinner-sam", "derived/person/sam-de-vries"), graph.owned())
        self.assertIn("hand-made", graph.edges)
        self.assertNotIn(("NoteAboutTopic", "obsidian/fiets", "derived/topic/bicycle-maintenance"), graph.owned())

    def test_a_topic_merge_never_folds_an_existing_topic_so_remember_edges_keep_their_target(self):
        graph = seeded_graph()
        first = answers()
        first["Fiets"] = extraction(topics=[topic("Kubernetes cluster")])
        Harness(graph, FakeLiteLLM(first, {"Kubernetes": basis(1), "Kubernetes cluster": basis(1, 0.6)})).run()
        self.assertIn("derived/topic/kubernetes-cluster", graph.nodes)
        capture = "nt-20260928-a1b2c3d4e5"
        remembered = f"remember:NoteAboutTopic:{capture}>derived/topic/kubernetes-cluster"
        graph.add("Note", slug=capture, name="Capture", kind="idea", content="A cluster idea.")
        graph.link("NoteAboutTopic", capture, "derived/topic/kubernetes-cluster", identifier=remembered)
        graph.nodes["obsidian/dinner-sam"][1]["content"] = "Now about the kubernetes platform."
        second = answers()
        second["Fiets"] = extraction(topics=[topic("Kubernetes cluster")])
        second["Dinner with Sam"] = extraction(topics=[topic("Kubernetes platform")])
        second["Capture"] = extraction()
        platform = basis(1)
        platform[5] = 0.3
        vectors = {"Kubernetes": basis(1), "Kubernetes cluster": basis(1, 0.6), "Kubernetes platform": platform}
        confirmed = [("Kubernetes platform", "Kubernetes"), ("Kubernetes cluster", "Kubernetes")]
        plan = Harness(graph, FakeLiteLLM(second, vectors, same=confirmed)).run(LATER)
        self.assertEqual(plan.counts.topics_merged, 1)
        self.assertNotIn("derived/topic/kubernetes-platform", graph.nodes)
        self.assertIn("derived/topic/kubernetes", graph.nodes)
        self.assertIn("derived/topic/kubernetes-cluster", graph.nodes)
        self.assertEqual(graph.edges[remembered][:3], ("NoteAboutTopic", capture, "derived/topic/kubernetes-cluster"))

    def test_rows_outside_the_derived_namespace_are_never_written_or_deleted(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        graph.nodes["obsidian/fiets"][1]["content"] = "changed"
        foreign_before = {slug: (kind, dict(data)) for slug, (kind, data) in graph.nodes.items() if not slug.startswith("derived/")}
        foreign_edges = {key: edge for key, edge in graph.edges.items() if not key.startswith(distill.OWNED_EDGE_PREFIX)}
        Harness(graph, FakeLiteLLM({})).run(LATER)
        self.assertEqual({key: edge for key, edge in graph.edges.items() if not key.startswith(distill.OWNED_EDGE_PREFIX)}, foreign_edges)
        for slug, row in foreign_before.items():
            self.assertEqual(graph.nodes[slug], row)
        with tempfile.TemporaryDirectory() as work:
            graph.snapshot(work)

    def test_related_topics_follow_co_occurrence(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        related = graph.owned("TopicRelatedTopic")
        self.assertIn(("TopicRelatedTopic", "derived/topic/gitops", "derived/topic/kubernetes"), related)
        self.assertNotIn(("TopicRelatedTopic", "derived/topic/ai-agents", "derived/topic/kubernetes"), related)
        documents = [edge[3]["documents"] for edge in graph.edges.values() if edge[0] == "TopicRelatedTopic" and edge[1] == "derived/topic/gitops" and edge[2] == "derived/topic/kubernetes"]
        self.assertEqual(documents, [2])
        graph.nodes["forge/webgrip/homelab-cluster"][1]["brief"] = "changed"
        changed = answers()
        changed["webgrip/homelab-cluster"] = extraction(topics=[topic("Homelab")])
        Harness(graph, FakeLiteLLM(changed)).run(LATER)
        self.assertNotIn(("TopicRelatedTopic", "derived/topic/gitops", "derived/topic/kubernetes"), graph.owned("TopicRelatedTopic"))

    def test_new_extractor_version_reprocesses_everything(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        llm = FakeLiteLLM(answers())
        Harness(graph, llm, model="other-model").run(LATER)
        self.assertEqual(len(llm.calls), 9)


class LimitsAndFailures(unittest.TestCase):
    def test_document_cap_and_spend_cap_defer_the_rest(self):
        graph = seeded_graph()
        llm = FakeLiteLLM(answers())
        plan = Harness(graph, llm, max_documents=3).run()
        self.assertEqual(sorted(llm.calls), ["Dinner with Sam", "Fiets", "K8s upgrade"])
        self.assertEqual(plan.counts.skipped_budget, 6)
        llm = FakeLiteLLM(answers(), cost=0.5)
        plan = Harness(graph, llm, max_spend_usd=0.9, workers=1).run(LATER)
        self.assertEqual(plan.counts.processed, 2)
        self.assertEqual(plan.counts.skipped_budget, 4)
        self.assertEqual(len(documents_distilled(graph)), 5)

    def test_failed_extractions_are_retried_and_mark_the_run(self):
        graph = seeded_graph()
        llm = FakeLiteLLM(answers(), fail={"Fiets", "Dinner with Sam"})
        harness = Harness(graph, llm)
        plan = harness.run()
        self.assertEqual(plan.counts.failed, 2)
        self.assertTrue(harness.failed_marker)
        self.assertNotIn("derived/distill/obsidian/fiets", graph.nodes)
        llm = FakeLiteLLM(answers())
        Harness(graph, llm).run(LATER)
        self.assertEqual(sorted(llm.calls), ["Dinner with Sam", "Fiets"])

    def test_a_refused_document_is_not_retried_until_it_changes(self):
        graph = seeded_graph()
        llm = FakeLiteLLM(answers(), refuse={"Fiets"})
        harness = Harness(graph, llm)
        plan = harness.run()
        self.assertEqual((plan.counts.refused, plan.counts.failed), (1, 0))
        self.assertFalse(harness.failed_marker)
        self.assertIn("derived/distill/obsidian/fiets", graph.nodes)
        self.assertFalse([edge for edge in graph.owned() if edge[1] == "obsidian/fiets"])
        llm = FakeLiteLLM(answers())
        Harness(graph, llm).run(LATER)
        self.assertEqual(llm.calls, [])
        graph.nodes["obsidian/fiets"][1]["content"] = "changed"
        Harness(graph, llm).run(LATER)
        self.assertEqual(llm.calls, ["Fiets"])

    def test_rate_limits_are_retried_and_other_errors_classified(self):
        replies = [(429, b"{}"), (503, b"{}"), (200, json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {}}).encode()), (400, b"{}"), (401, b"{}")]

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                status, body = replies.pop(0)
                self.send_response(status)
                self.send_header("Retry-After", "0")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            counts = distill.Counts()
            client = distill.LiteLLM(f"http://127.0.0.1:{server.server_port}", "sk-test", counts)
            body, _ = client.post("/v1/chat/completions", {})
            self.assertEqual(counts.retries, 2)
            with self.assertRaises(distill.ExtractionFailed) as refused:
                client.post("/v1/chat/completions", {})
            self.assertTrue(refused.exception.refused)
            with self.assertRaises(distill.ExtractionFailed) as denied:
                client.post("/v1/chat/completions", {})
            self.assertFalse(denied.exception.refused)
        finally:
            server.shutdown()

    def test_unreachable_litellm_fails_closed_without_writing(self):
        graph = seeded_graph()
        with self.assertRaises(distill.FailClosed):
            Harness(graph, FakeLiteLLM(answers(), unreachable=True)).run()
        self.assertFalse([slug for slug in graph.nodes if slug.startswith("derived/")])

    def test_empty_snapshot_with_state_refuses(self):
        graph = seeded_graph()
        Harness(graph, FakeLiteLLM(answers())).run()
        for slug in [slug for slug, (kind, _) in graph.nodes.items() if kind in ("Note", "Artifact", "Project")]:
            del graph.nodes[slug]
        graph.edges = {key: edge for key, edge in graph.edges.items() if edge[1] in graph.nodes and edge[2] in graph.nodes}
        with self.assertRaises(distill.FailClosed):
            Harness(graph, FakeLiteLLM(answers())).run(LATER)

    def test_large_plans_are_split_under_the_write_limits(self):
        graph = FakeGraph()
        many = {}
        for index in range(700):
            name = f"Note {index}"
            graph.add("Note", slug=f"obsidian/n{index}", name=name, kind="idea", content=f"text {index}")
            many[name] = extraction(topics=[topic(f"Topic {index} {part}") for part in "abc"])
        harness = Harness(graph, FakeLiteLLM(many), related_min_documents=1)
        harness.run()
        loads = [name for name in harness.files if name.startswith("load-")]
        self.assertGreater(len(loads), 3)
        self.assertEqual(len(graph.of_type("Topic")), 2100)
        for index in range(700):
            graph.nodes[f"obsidian/n{index}"][1]["content"] = "changed"
        harness = Harness(graph, FakeLiteLLM({}))
        harness.run(LATER)
        self.assertGreater(len([name for name in harness.files if name.startswith("prune-")]), 1)
        self.assertEqual(graph.of_type("Topic"), {})

    def test_statements_quote_awkward_slugs(self):
        graph = seeded_graph()
        graph.add("Note", slug='nt-quote"and\\slash', name="Awkward", kind="idea", content="odd")
        extra = answers()
        extra["Awkward"] = extraction(topics=[topic("Kubernetes")])
        Harness(graph, FakeLiteLLM(extra)).run()
        graph.nodes['nt-quote"and\\slash'][1]["content"] = "odd again"
        extra["Awkward"] = extraction()
        Harness(graph, FakeLiteLLM(extra)).run(LATER)
        self.assertFalse([edge for edge in graph.owned() if edge[1] == 'nt-quote"and\\slash'])


class SnapshotCoverage(unittest.TestCase):
    def test_every_edge_that_can_touch_a_derived_entity_is_read(self):
        text = SNAPSHOT_QUERIES.read_text(encoding="utf-8")
        derivable = set(distill.ENTITY_TYPES)
        written = set(distill.EDGE_FOR.values()) | {distill.RELATED}
        for name, (source, target) in EDGES.items():
            if name in written:
                self.assertIn(f"query edge_{name}()", text, name)
                continue
            if target in derivable:
                self.assertIn(f"query edge_{name}_to()", text, name)
            if source in derivable:
                self.assertIn(f"query edge_{name}_from()", text, name)

    def test_written_edges_exist_in_the_schema_with_the_right_endpoints(self):
        for (source, target), edge in distill.EDGE_FOR.items():
            self.assertEqual(EDGES[edge], (source, target), edge)
        self.assertEqual(EDGES[distill.RELATED], ("Topic", "Topic"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
