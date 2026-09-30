#!/usr/bin/env python3
import datetime
import faulthandler
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = Path(os.environ.get("BRAIN_EVAL_APP", ROOT / "kubernetes/apps/ai/omnigraph/brain-eval/app"))
LITELLM_CONFIG = ROOT / "kubernetes/apps/ai/litellm/app/litellm-config.configmap.yaml"
EVAL_KEY_JOB = ROOT / "kubernetes/apps/ai/litellm/keys/app/omnigraph-eval-key-register.job.yaml"
HARNESS = APP / "brain_eval.py"
sys.path.insert(0, str(APP))
spec = importlib.util.spec_from_file_location("brain_eval", HARNESS)
be = importlib.util.module_from_spec(spec)
sys.modules["brain_eval"] = be
spec.loader.exec_module(be)
cand = importlib.import_module("candidates")

SENTINEL = be.SENTINEL_PHRASE
SNAPSHOT = "01SNAPSHOT0000000000000000"
SNAPSHOT_TIME = datetime.datetime(2026, 9, 28, 12, 0, tzinfo=datetime.timezone.utc)
RUNBOOK = "forge/webgrip/homelab-cluster/doc/docs/runbook"
ADR_ARTIFACT = "forge/webgrip/homelab-cluster/doc/docs/adr/adr-0001"
ADR_NOTE = "forge/webgrip/homelab-cluster/adr/docs/adr/adr-0001"
TOPIC = "derived/topic/flux"
Q1 = "How do I reconcile the cluster?"
Q2 = f"Hoe zat het met de {SENTINEL} tuin?"
Q3 = "What do I know about Flux?"
Q4 = "Wat schreef ik deze week?"
Q5 = "What did I decide about the solar inverter?"
Q6 = "Why did we choose Flux?"


def iso(days_before):
    return (SNAPSHOT_TIME - datetime.timedelta(days=days_before)).strftime("%Y-%m-%dT%H:%M:%S")


NOTES = [
    {"slug": "obsidian/alpha", "name": "Alpha", "updatedAt": iso(2), "content": "alpha note"},
    {"slug": "obsidian/beta", "name": "Beta", "updatedAt": iso(30), "content": "beta note"},
    {"slug": "obsidian/gamma", "name": "Gamma", "updatedAt": iso(40), "content": f"gamma {SENTINEL}"},
    {"slug": ADR_NOTE, "name": "ADR 1", "updatedAt": iso(50), "content": "adr"},
    {"slug": "derived/summary/topic/flux", "name": "Summary", "updatedAt": iso(1), "content": "summary"},
]
ARTIFACTS = [
    {"slug": RUNBOOK, "name": "Runbook", "kind": "document", "timestamp": iso(3), "content": "runbook"},
    {"slug": ADR_ARTIFACT, "name": "ADR 1", "kind": "document", "timestamp": iso(60), "content": "adr"},
    {"slug": "obsidian-file/gamma", "name": "Gamma", "kind": "document", "timestamp": iso(1), "content": None},
    {"slug": "forge/webgrip/homelab-cluster/issue/1", "name": "Flux is slow", "kind": "post", "timestamp": iso(5), "content": "Issue #1\nState: open\nbody"},
    {"slug": "forge/webgrip/homelab-cluster/issue/2", "name": "Old bug", "kind": "post", "timestamp": iso(5), "content": "Issue #2\nState: closed\nbody"},
    {"slug": "forge/webgrip/homelab-cluster/pull/3", "name": "chore(deps): update flux", "kind": "post", "timestamp": iso(4), "content": "PR #3\nState: open\nbody"},
    {"slug": "forge/webgrip/other/issue/9", "name": "Other", "kind": "post", "timestamp": iso(4), "content": "Issue #9\nState: open\nbody"},
]
NOTE_ARTIFACT = [(ADR_NOTE, ADR_ARTIFACT), ("obsidian/gamma", "obsidian-file/gamma")]
ARTIFACT_PROJECT = [("forge/webgrip/homelab-cluster/issue/1", "forge/webgrip/homelab-cluster"), ("forge/webgrip/homelab-cluster/pull/3", "forge/webgrip/homelab-cluster"),
                    ("forge/webgrip/other/issue/9", "forge/webgrip/other")]
ARTIFACT_AUTHOR = [("forge/webgrip/homelab-cluster/pull/3", "forge/user/renovate"), ("forge/webgrip/homelab-cluster/issue/1", "forge/user/ryangr0")]
RECALL = {
    Q1: ([ADR_NOTE], [RUNBOOK, ADR_ARTIFACT], [TOPIC]),
    Q2: (["obsidian/beta"], ["obsidian-file/gamma"], []),
    Q3: ([], [], [TOPIC]),
    Q4: (["obsidian/beta", "obsidian/alpha"], [], []),
    Q5: (["obsidian/beta"], [], []),
    Q6: ([], [ADR_ARTIFACT], []),
}
CASES = [
    {"id": "c01", "split": "dev", "category": "docs-en", "language": "en", "answerable": True, "question": Q1,
     "expected": [{"slug": RUNBOOK, "grade": 2}, {"slug": ADR_ARTIFACT, "grade": 1}], "key_facts": ["run flux reconcile"]},
    {"id": "c02", "split": "dev", "category": "notes-nl", "language": "nl", "answerable": True, "question": Q2,
     "expected": [{"slug": "obsidian/gamma", "grade": 2}], "key_facts": [f"de {SENTINEL} bloeit"]},
    {"id": "c03", "split": "holdout", "category": "about", "language": "en", "answerable": True, "question": Q3,
     "expected": [{"slug": TOPIC, "grade": 2}], "key_facts": ["Flux reconciles git"]},
    {"id": "c04", "split": "dev", "category": "temporal", "language": "nl", "answerable": True, "question": Q4,
     "expected": [], "key_facts": [], "temporal": {"kind": "recent_notes", "days": 7}},
    {"id": "c05", "split": "holdout", "category": "unanswerable", "language": "en", "answerable": False, "question": Q5, "expected": [], "key_facts": []},
    {"id": "c06", "split": "holdout", "category": "docs-en", "language": "en", "answerable": True, "question": Q6,
     "expected": [{"slug": ADR_NOTE, "grade": 2}], "key_facts": ["Flux was chosen for GitOps"]},
]
EXPECTED_NDCG = {"c01": (1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3)), "c02": 1 / math.log2(3), "c03": 1.0, "c04": 1 / math.log2(3), "c06": 1.0}


class FakeOmnigraph:
    def __init__(self):
        self.stored_calls = []
        self.inline_calls = []
        self.snapshots = []
        self.export_calls = 0

    def rows_for_inline(self, source, params):
        if "$p: Project" in source:
            return []
        if "query e1_" in source:
            vectors = {RUNBOOK: [0.0, 1.0], ADR_ARTIFACT: [1.0, 0.0], "obsidian-file/gamma": [0.6, 0.8]}
            return [{"p.@id": f"{slug}#0", "a.slug": slug, "p.text": f"text of {slug}", "p.embedding": vector + [0.0] * 382} for slug, vector in vectors.items()]
        if "count($x)" in source:
            return [{"n": 8}]
        if "nearest($x.embedding, $v)" in source:
            type_name = re.search(r"\$x: (\w+)", source).group(1)
            if type_name == "Passage":
                return [{"x.@id": f"p{index}"} for index in range(8) if index % 4]
            return [{"x.@id": row["slug"]} for row in NOTES if row["slug"] != "obsidian/beta"]
        if "noteFromArtifact" in source:
            return [{"n.slug": note, "a.slug": artifact} for note, artifact in NOTE_ARTIFACT]
        if "artifactForProject" in source:
            return [{"a.slug": artifact, "p.slug": project} for artifact, project in ARTIFACT_PROJECT]
        if "artifactFromPerson" in source:
            return [{"a.slug": artifact, "u.slug": person} for artifact, person in ARTIFACT_AUTHOR]
        match = re.search(r"\$x: (\w+)", source)
        if match:
            columns = re.findall(r"\$x\.(\w+)", source)
            table = {"Note": NOTES, "Artifact": ARTIFACTS, "Topic": [{"slug": TOPIC, "name": "Flux"}]}.get(match.group(1), [])
            return [{f"x.{column}": row.get(column) for column in columns} for row in table]
        return []

    def handle(self, method, path, body):
        if method == "GET" and path == "/graphs/brain/queries":
            return 200, {"queries": [{"name": name, "params": [{"name": "q"}]} for name in ("recall_notes", "recall_passages", "recall_topics", "notes_recent")]}
        if method == "GET" and path.startswith("/graphs/brain/commits/"):
            return 200, {"graph_commit_id": SNAPSHOT, "created_at": int(SNAPSHOT_TIME.timestamp() * 1_000_000)}
        if method == "POST" and path == "/graphs/brain/query":
            self.inline_calls.append(body["query"])
            self.snapshots.append(body.get("snapshot"))
            return 200, {"rows": self.rows_for_inline(body["query"], body.get("params") or {}), "graph_commit_id": SNAPSHOT}
        if method == "POST" and path.startswith("/graphs/brain/queries/"):
            name = path.rsplit("/", 1)[1]
            self.stored_calls.append(name)
            self.snapshots.append(body.get("snapshot"))
            if name == "notes_recent":
                return 200, {"rows": [{"n.slug": "obsidian/beta"}]}
            notes, passages, topics = RECALL.get(body["params"]["q"], ([], [], []))
            if name == "recall_notes":
                return 200, {"rows": [{"n.slug": slug, "n.content": f"text {SENTINEL}"} for slug in notes]}
            if name == "recall_passages":
                return 200, {"rows": [{"a.slug": slug, "p.text": f"passage {SENTINEL}"} for slug in passages]}
            return 200, {"rows": [{"t.slug": slug} for slug in topics]}
        if method == "POST" and path == "/graphs/brain/export":
            self.export_calls += 1
            rows = []
            for type_name in body["type_names"]:
                if type_name == "Passage":
                    rows += [{"type": "Passage", "id": f"p{index}", "data": {"text": "t", "embedding": [0.1] if index % 4 else None}} for index in range(8)]
                if type_name == "Note":
                    rows += [{"type": "Note", "id": note["slug"], "data": {"content": note["content"], "embedding": [0.1]}} for note in NOTES]
            return 200, "\n".join(json.dumps(row) for row in rows) + "\n"
        return 404, {"code": "not_found"}


CUT_OFF_VERDICT = '{"key_facts": [{"index": 0, "pres'


class FakeLiteLLM:
    def __init__(self, judge_mode="good"):
        self.judge_mode = judge_mode
        self.case_verdicts = 0
        self.chat_calls = 0
        self.mcp_calls = []
        self.bodies = []

    def verdict(self, payload):
        user = json.loads(payload["messages"][-1]["content"])
        if self.judge_mode == "garbled":
            return "The answer looks fine to me."
        if user["question"] != be.CONTROL_CASE["question"] and self.judge_mode.startswith("cut-off-"):
            self.case_verdicts += 1
            if (self.judge_mode == "cut-off-always" or (self.judge_mode == "cut-off-first-attempt" and self.case_verdicts % 2 == 1)
                    or (self.judge_mode == "cut-off-first-answer" and self.case_verdicts <= be.JUDGE_ATTEMPTS)):
                return CUT_OFF_VERDICT
        answer = user["answer"]
        if self.judge_mode == "broken":
            supported = True
        else:
            supported = "9000" not in answer and "unsupported" not in answer
        return {"key_facts": [{"index": item["index"], "present": supported} for item in user["key_facts"]],
                "claims": [{"grounded": supported}], "citations": [{"supported": supported}], "abstained": False}

    def chat(self, payload):
        self.chat_calls += 1
        self.bodies.append(json.dumps(payload))
        response_format = (payload.get("response_format") or {}).get("json_schema", {}).get("name")
        if response_format == "brain_eval_judgement":
            verdict = self.verdict(payload)
            content = verdict if isinstance(verdict, str) else json.dumps(verdict)
            finish = "length" if content == CUT_OFF_VERDICT else "stop"
            return {"choices": [{"message": {"content": content}, "finish_reason": finish}], "usage": {"prompt_tokens": 10, "completion_tokens": payload["max_tokens"] if finish == "length" else 5}}
        messages = payload["messages"]
        if payload.get("tools") and not any(message["role"] == "tool" for message in messages):
            return {"choices": [{"message": {"content": "", "tool_calls": [{"id": "call1", "type": "function", "function": {
                "name": payload["tools"][0]["function"]["name"], "arguments": json.dumps({"query": messages[-1]["content"]})}}]}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5}}
        return {"choices": [{"message": {"content": f"The answer mentions {SENTINEL} [doc:x]."}}], "usage": {"prompt_tokens": 30, "completion_tokens": 9}}

    def mcp(self, body):
        method = body.get("method")
        self.mcp_calls.append(method)
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {}}}, "json"
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{"name": "omnigraph_brain_eval-query", "description": "run GQ",
                                                                             "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}}]}}, "sse"
        if method == "tools/call":
            return {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": f"rows about {SENTINEL}"}], "isError": False}}, "sse"
        return None, "json"


class FakeVmagent:
    def __init__(self):
        self.bodies = []


def interleaved(*lists):
    merged = []
    for position in range(max((len(items) for items in lists), default=0)):
        for items in lists:
            if position < len(items):
                merged.append(items[position])
    return merged


class FakeBrainTools:
    def __init__(self):
        self.requests = []
        self.p1_order = {}
        self.p0_swap = False
        self.p0_truncated_questions = set()
        self.tool_chars = 1200
        self.answer_commit = None

    def search(self, query):
        self.requests.append(query)
        question, profile, snapshot = query["q"][0], query["profile"][0], (query.get("snapshot") or [None])[0]
        documents = interleaved(*RECALL.get(question, ([], [], [])))
        if profile == "p0" and self.p0_swap and len(documents) > 2:
            documents = [documents[0], documents[2], documents[1], *documents[3:]]
        if profile == "p0" and question in self.p0_truncated_questions:
            documents = documents[:-1]
        if profile == "p1":
            documents = self.p1_order.get(question, list(reversed(documents)))
        return {"results": [{"document": document, "ref": f"doc:{document}#0"} for document in documents], "tool_chars": self.tool_chars,
                "graph_commit": self.answer_commit or snapshot, "profile": profile}


def brain_tools_handler(fake):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(self.path)
            if parsed.path != "/api/search":
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(fake.search(parse_qs(parsed.query))).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


def serve(handler_factory):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def omnigraph_handler(fake):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, payload):
            data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/x-ndjson" if isinstance(payload, str) else "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply(*fake.handle("GET", self.path, None))

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            self.reply(*fake.handle("POST", self.path, body))
    return Handler


def litellm_handler(fake):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            if self.path == "/v1/chat/completions":
                data = json.dumps(fake.chat(body)).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("x-litellm-response-cost", "0.01")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path == "/v1/embeddings":
                vectors = []
                for index, text in enumerate(body["input"]):
                    axes = {"runbook": (1.0, 0.0, 0.0), "adr-0001": (0.0, 1.0, 0.0), "gamma": (0.0, 0.0, 1.0)}
                    head = next((axis for word, axis in axes.items() if word in text), (0.8, 0.0, 0.6))
                    vectors.append({"index": index, "embedding": list(head) + [0.0] * 381})
                data = json.dumps({"data": vectors, "model": body["model"]}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("x-litellm-response-cost", "0.0")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path.endswith("/mcp"):
                message, kind = fake.mcp(body)
                if message is None:
                    self.send_response(202)
                    self.send_header("content-length", "0")
                    self.end_headers()
                    return
                data = (f"event: message\ndata: {json.dumps(message)}\n\n" if kind == "sse" else json.dumps(message)).encode()
                self.send_response(200)
                self.send_header("content-type", "text/event-stream" if kind == "sse" else "application/json")
                self.send_header("mcp-session-id", "session-1")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(404)
            self.end_headers()
    return Handler


def vmagent_handler(fake):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            fake.bodies.append(self.rfile.read(int(self.headers.get("content-length") or 0)).decode())
            self.send_response(204)
            self.end_headers()
    return Handler


class Harness:
    def __init__(self, judge_mode="good"):
        self.tmp = tempfile.TemporaryDirectory(prefix="brain-eval-test-")
        self.root = Path(self.tmp.name)
        self.repo = self.root / "work" / "repo"
        self.out = self.root / "work" / "out"
        (self.repo / "cases").mkdir(parents=True)
        (self.root / "work" / "store-kind").write_text("provisional\n")
        for case in CASES:
            (self.repo / "cases" / f"{case['id']}.yaml").write_text(be.dump_case(case))
        (self.root / "token").write_text("omnigraph-token\n")
        (self.root / "key").write_text("sk-test\n")
        self.omnigraph = FakeOmnigraph()
        self.litellm = FakeLiteLLM(judge_mode)
        self.vmagent = FakeVmagent()
        self.brain_tools = FakeBrainTools()
        self.servers = []
        for fake, factory, attr in ((self.omnigraph, omnigraph_handler, "omnigraph_url"), (self.litellm, litellm_handler, "litellm_url"), (self.vmagent, vmagent_handler, "vmagent_base"),
                                    (self.brain_tools, brain_tools_handler, "brain_tools_url")):
            server, url = serve(factory(fake))
            self.servers.append(server)
            setattr(self, attr, url)

    def run(self, *command, env=None, global_args=()):
        argv = [sys.executable, str(HARNESS), f"--repo-dir={self.repo}", f"--out-dir={self.out}", f"--omnigraph-url={self.omnigraph_url}",
                f"--omnigraph-token-file={self.root / 'token'}", f"--litellm-url={self.litellm_url}", f"--litellm-key-file={self.root / 'key'}",
                f"--vmagent-url={self.vmagent_base}/api/v1/import/prometheus", f"--prompts-dir={APP}", f"--brain-tools-url={self.brain_tools_url}", *global_args, *command]
        return subprocess.run(argv, capture_output=True, text=True, timeout=120, env={**os.environ, **(env or {})})

    def results(self, prefix):
        return sorted((self.repo / "results").rglob(f"{prefix}*.json"))

    def close(self):
        for server in self.servers:
            server.shutdown()
        self.tmp.cleanup()


class CaseFormat(unittest.TestCase):
    def test_dump_and_load_round_trip_every_field(self):
        case = dict(CASES[3], provisional=True, origin="drafted", entities=["a", "b"], beyond_first_1024_tokens=True, notes="line one: \"quoted\" # not a comment")
        self.assertEqual(be.load_case(be.dump_case(case)), case)

    def test_hand_written_yaml_with_plain_scalars_comments_and_block_text(self):
        text = """# a case Ryan wrote
id: r01
split: dev
category: notes-nl
language: nl
origin: ryan
answerable: true
question: >-
  Wat heb ik besloten
  over de verbouwing?
expected:
  - slug: obsidian/verbouwing   # the main note
    grade: 2
key_facts: [ "we kiezen hout", 'geen "beton"' ]
"""
        case = be.validate_case(be.load_case(text), "r01")
        self.assertEqual(case["question"], "Wat heb ik besloten over de verbouwing?")
        self.assertEqual(case["expected"], [{"slug": "obsidian/verbouwing", "grade": 2}])
        self.assertEqual(case["key_facts"], ["we kiezen hout", 'geen "beton"'])

    def test_unsupported_yaml_is_refused_with_its_line(self):
        with self.assertRaisesRegex(be.CaseFormatError, "line 2"):
            be.load_case("id: x\n  nested: wrong\n")
        with self.assertRaises(be.CaseFormatError):
            be.load_case("id: &anchor x\n")

    def test_validation_names_every_problem(self):
        with self.assertRaisesRegex(be.CaseFormatError, "split must be one of.*category must be one of"):
            be.validate_case({"id": "x", "split": "train", "category": "misc", "language": "en", "answerable": True, "question": "q", "expected": [{"slug": "a", "grade": 1}], "key_facts": ["f"]}, "x")
        with self.assertRaisesRegex(be.CaseFormatError, "expects no documents"):
            be.validate_case({"id": "x", "split": "dev", "category": "unanswerable", "language": "en", "answerable": False, "question": "q", "expected": [{"slug": "a", "grade": 1}]}, "x")


class Metrics(unittest.TestCase):
    def test_graded_ndcg_recall_hit_and_mrr_match_hand_computed_values(self):
        grades = {"a": 2, "b": 1, "c": 2}
        ranked = ["x", "b", "a", "y", "c"]
        dcg = 1 / math.log2(3) + 3 / math.log2(4) + 3 / math.log2(6)
        idcg = 3 / math.log2(2) + 3 / math.log2(3) + 1 / math.log2(4)
        scores = be.retrieval_scores(ranked, grades)
        self.assertAlmostEqual(scores["ndcg_at_8"], dcg / idcg, places=9)
        self.assertAlmostEqual(scores["recall_at_5"], 1.0)
        self.assertEqual(scores["hit_at_1"], 0.0)
        self.assertAlmostEqual(scores["mrr_at_8"], 0.5)
        self.assertAlmostEqual(be.retrieval_scores(["x", "y", "z", "w", "v", "a"], grades)["recall_at_5"], 0.0)
        self.assertAlmostEqual(be.retrieval_scores(["x", "y", "z", "w", "v", "a"], grades)["recall_at_8"], 1 / 3)

    def test_sign_test_and_decision_rule(self):
        self.assertAlmostEqual(be.sign_test_p(6, 1), 2 * (1 + 7) / 128)
        baseline = {f"c{index}": 0.5 for index in range(10)}
        candidate = dict(baseline, c0=0.9, c1=0.9, c2=0.9, c3=0.9, c4=0.4)
        categories = {case: "docs-en" if case in ("c0", "c1") else "about" for case in baseline}
        decision = be.decide(baseline, candidate, categories)
        self.assertTrue(decision["adopt"], decision)
        self.assertEqual((decision["wins"], decision["losses"]), (4, 1))
        losing = dict(candidate, c5=0.1)
        categories["c5"] = "about"
        decision = be.decide(baseline, losing, categories)
        self.assertFalse(decision["adopt"])
        self.assertTrue(any("categories losing" in reason for reason in decision["reasons"]))
        self.assertFalse(be.decide(baseline, dict(baseline, c0=0.6), categories)["adopt"])

    def test_equivalence_rolls_passages_shadow_artifacts_and_adr_notes_up_to_one_document(self):
        equivalence = be.Equivalence(dict(NOTE_ARTIFACT))
        self.assertEqual(equivalence.canonical("obsidian-file/gamma"), "obsidian/gamma")
        self.assertEqual(equivalence.canonical("obsidian-file/unlinked"), "obsidian/unlinked")
        self.assertEqual(equivalence.canonical("obsidian/gamma"), "obsidian/gamma")
        self.assertEqual(equivalence.canonical(ADR_NOTE), ADR_ARTIFACT)
        self.assertEqual(equivalence.canonical_ranking([ADR_NOTE, RUNBOOK, ADR_ARTIFACT, "obsidian-file/gamma", "obsidian/gamma"]), [ADR_ARTIFACT, RUNBOOK, "obsidian/gamma"])
        self.assertEqual(equivalence.canonical_expectation([{"slug": ADR_NOTE, "grade": 1}, {"slug": ADR_ARTIFACT, "grade": 2}]), {ADR_ARTIFACT: 2})

    def test_metric_labels_come_from_the_allowlist_only(self):
        sink = be.MetricSink()
        sink.add("brain_eval_score", {"metric": "ndcg_at_8", "profile": "p0", "category": "all", "split": "dev", "mode": "retrieval"}, 0.5)
        with self.assertRaisesRegex(be.EvalError, "not allowed"):
            sink.add("brain_eval_score", {"metric": "ndcg_at_8", "profile": "p0", "category": "all", "split": "dev", "mode": "retrieval", "case": "c01"}, 0.5)
        with self.assertRaisesRegex(be.EvalError, "not allowed"):
            sink.add("brain_eval_score", {"metric": "ndcg_at_8", "profile": "p0", "category": "obsidian/gamma", "split": "dev", "mode": "retrieval"}, 0.5)
        with self.assertRaisesRegex(be.EvalError, "allowlist"):
            sink.add("brain_eval_question_text", {}, 1)

    def test_values_keep_every_significant_digit_a_timestamp_needs(self):
        sink = be.MetricSink()
        sink.add("brain_eval_last_success_timestamp_seconds", {"mode": "retrieval"}, 1790648123.25)
        sink.add("brain_eval_score", {"metric": "ndcg_at_8", "profile": "p0", "category": "all", "split": "all", "mode": "retrieval"}, 0.437283123)
        self.assertEqual(sink.text(), 'brain_eval_last_success_timestamp_seconds{mode="retrieval"} 1790648123.25\n'
                                      'brain_eval_score{category="all",metric="ndcg_at_8",mode="retrieval",profile="p0",split="all"} 0.437283123\n')


class TemporalTruth(unittest.TestCase):
    def test_expectations_come_from_the_scan_and_a_python_filter_never_from_stored_queries(self):
        fake = FakeOmnigraph()
        server, url = serve(omnigraph_handler(fake))
        try:
            omnigraph = be.Omnigraph(url, "brain", "t")
            scans = be.temporal_scans(omnigraph, SNAPSHOT, {"recent_notes", "recent_docs", "open_threads"})
            self.assertEqual(fake.stored_calls, [])
            self.assertEqual(set(fake.snapshots), {SNAPSHOT})
            notes = be.temporal_expectation({"temporal": {"kind": "recent_notes", "days": 7}}, scans, SNAPSHOT_TIME)
            self.assertEqual(notes, {"obsidian/alpha": 1})
            stored_answer = {row["n.slug"] for row in be.Omnigraph(url, "brain", "t").stored("notes_recent", {}, SNAPSHOT)[0]}
            self.assertNotEqual(set(notes), stored_answer)
            docs = be.temporal_expectation({"temporal": {"kind": "recent_docs", "days": 7}}, scans, SNAPSHOT_TIME)
            self.assertEqual(docs, {RUNBOOK: 1})
            threads = be.temporal_expectation({"temporal": {"kind": "open_threads", "days": 365, "project": "forge/webgrip/homelab-cluster"}}, scans, SNAPSHOT_TIME)
            self.assertEqual(threads, {"forge/webgrip/homelab-cluster/issue/1": 1})
            with_deps = be.temporal_expectation({"temporal": {"kind": "open_threads", "days": 365, "include_dependency_updates": True}}, scans, SNAPSHOT_TIME)
            self.assertEqual(set(with_deps), {"forge/webgrip/homelab-cluster/issue/1", "forge/webgrip/homelab-cluster/pull/3", "forge/webgrip/other/issue/9"})
        finally:
            server.shutdown()


class RetrievalRun(unittest.TestCase):
    def setUp(self):
        self.harness = Harness()

    def tearDown(self):
        self.harness.close()

    def test_p0_scores_every_case_pinned_to_one_snapshot_with_hand_computed_aggregates(self):
        result = self.harness.run("retrieval", "--missing-vectors", global_args=(f"--snapshot={SNAPSHOT}", "--day=2026-09-28"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        document = json.loads(self.harness.results("retrieval-p0")[0].read_text())
        per_case = {case["id"]: case["metrics"]["ndcg_at_8"] for case in document["cases"]}
        self.assertEqual(set(per_case), set(EXPECTED_NDCG))
        for case_id, value in EXPECTED_NDCG.items():
            self.assertAlmostEqual(per_case[case_id], value, places=6, msg=case_id)
        dev = document["aggregates"]["all|dev"]["ndcg_at_8"]
        self.assertAlmostEqual(dev, sum(EXPECTED_NDCG[c] for c in ("c01", "c02", "c04")) / 3, places=5)
        self.assertEqual(document["run"]["excluded_cases"], [["c05", "unanswerable"]])
        self.assertEqual(document["run"]["sentinel_runs"], 1)
        self.assertEqual(set(self.harness.omnigraph.snapshots), {SNAPSHOT})
        self.assertNotIn("notes_recent", self.harness.omnigraph.stored_calls)
        metrics = (self.harness.out / "metrics.prom").read_text()
        self.assertIn('brain_eval_missing_vectors_ratio{type="Passage"} 0.25\n', metrics)
        self.assertIn('brain_eval_missing_vectors_ratio{type="Note"} 0.2\n', metrics)
        self.assertEqual(self.harness.omnigraph.export_calls, 0)
        self.assertIn('brain_eval_stale_cases 0', metrics)
        self.assertIn('brain_eval_set_provisional 1', metrics)
        self.assertRegex(metrics, r'brain_eval_score\{category="all",metric="ndcg_at_8",mode="retrieval",profile="p0",split="dev"\} 0\.6861')

    def test_two_runs_on_one_snapshot_give_identical_scores(self):
        documents = []
        for _ in range(2):
            result = self.harness.run("retrieval", global_args=(f"--snapshot={SNAPSHOT}", "--day=2026-09-28"))
            self.assertEqual(result.returncode, 0, result.stderr)
        for path in self.harness.results("retrieval-p0"):
            document = json.loads(path.read_text())
            documents.append(({case["id"]: case["metrics"] for case in document["cases"]}, document["aggregates"]))
        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0], documents[1])

    def test_a_renamed_expected_slug_excludes_the_case_as_stale(self):
        result = self.harness.run("retrieval", "--scratch-stale", global_args=(f"--snapshot={SNAPSHOT}",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("brain_eval_stale_cases 1", (self.harness.out / "metrics.prom").read_text())
        document = json.loads(self.harness.results("retrieval-p0")[0].read_text())
        self.assertEqual(document["run"]["stale_cases"], ["scratch-stale"])
        self.assertNotIn("scratch-stale", {case["id"] for case in document["cases"]})

    def test_push_metrics_adds_the_success_timestamp_for_the_run_mode(self):
        self.assertEqual(self.harness.run("retrieval", global_args=(f"--snapshot={SNAPSHOT}",)).returncode, 0)
        result = self.harness.run("push-metrics")
        self.assertEqual(result.returncode, 0, result.stderr)
        pushed = "".join(self.harness.vmagent.bodies)
        stamp = float(re.search(r'brain_eval_last_success_timestamp_seconds\{mode="retrieval"\} (\S+)', pushed).group(1))
        self.assertLess(abs(stamp - time.time()), 120)
        self.assertIn('brain_eval_run_valid{mode="retrieval"} 1', pushed)
        for line in pushed.strip().split("\n"):
            name = line.split("{")[0].split(" ")[0]
            self.assertIn(name, be.METRIC_LABELS)
            for label, value in re.findall(r'(\w+)="([^"]*)"', line):
                self.assertIn(value, be.METRIC_LABELS[name][label], line)


class BrainToolsProfiles(unittest.TestCase):
    def setUp(self):
        self.harness = Harness()

    def tearDown(self):
        self.harness.close()

    def test_rest_profiles_run_pinned_and_the_p0_replica_matches_the_direct_p0(self):
        result = self.harness.run("retrieval", "--profile=p0", "--profile=p0-rest", "--profile=p1", global_args=(f"--snapshot={SNAPSHOT}", "--day=2026-09-28"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.harness.brain_tools.requests)
        for query in self.harness.brain_tools.requests:
            self.assertEqual(query["snapshot"], [SNAPSHOT])
            self.assertEqual(query["limit"], [str(be.CANDIDATE_POOL_DEPTH)])
        metrics = (self.harness.out / "metrics.prom").read_text()
        self.assertIn('brain_eval_replica_identical_ratio{profile="p0-rest"} 1', metrics)
        direct = json.loads(next(path for path in self.harness.results("retrieval-p0") if path.name == "retrieval-p0.json").read_text())
        replica = json.loads(self.harness.results("retrieval-p0-rest")[0].read_text())
        self.assertEqual({case["id"]: case["ranked"] for case in direct["cases"]}, {case["id"]: case["ranked"] for case in replica["cases"]})
        self.assertEqual(replica["run"]["replicas"]["p0:p0-rest"]["differing"], [])
        self.assertEqual(replica["run"]["replicas"]["p0:p0-rest"]["cases"], len(CASES))
        rest = json.loads(self.harness.results("retrieval-p1")[0].read_text())
        self.assertEqual({case["payload_chars"] for case in rest["cases"]}, {1200})
        self.assertRegex(metrics, r'brain_eval_score\{category="all",metric="ndcg_at_8",mode="retrieval",profile="p1",split="dev"\}')

    def test_a_replica_that_ranks_differently_is_reported_by_case(self):
        self.harness.brain_tools.p0_swap = True
        result = self.harness.run("retrieval", "--profile=p0", "--profile=p0-rest", global_args=(f"--snapshot={SNAPSHOT}",))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        replica = json.loads(self.harness.results("retrieval-p0-rest")[0].read_text())
        self.assertIn("c01", replica["run"]["replicas"]["p0:p0-rest"]["differing"])
        self.assertNotIn('brain_eval_replica_identical_ratio{profile="p0-rest"} 1\n', (self.harness.out / "metrics.prom").read_text())

    def test_the_replica_check_covers_the_cases_no_metric_scores(self):
        self.harness.brain_tools.p0_truncated_questions = {Q5}
        result = self.harness.run("retrieval", "--profile=p0", "--profile=p0-rest", global_args=(f"--snapshot={SNAPSHOT}",))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        replica = json.loads(self.harness.results("retrieval-p0-rest")[0].read_text())
        self.assertEqual(replica["run"]["excluded_cases"], [["c05", "unanswerable"]])
        self.assertNotIn("c05", {case["id"] for case in replica["cases"]})
        self.assertEqual(replica["run"]["replicas"]["p0:p0-rest"]["differing"], ["c05"])

    def test_brain_tools_answering_from_another_commit_invalidates_the_run(self):
        self.harness.brain_tools.answer_commit = "01OTHERCOMMIT0000000000000"
        result = self.harness.run("retrieval", "--profile=p1", global_args=(f"--snapshot={SNAPSHOT}",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instead of the pinned snapshot", result.stdout + result.stderr)

    def test_the_gate_refuses_a_candidate_whose_answers_pass_the_response_budget(self):
        self.harness.brain_tools.p1_order = {Q1: [RUNBOOK, ADR_ARTIFACT], Q2: ["obsidian/gamma"], Q4: ["obsidian/alpha"]}
        self.harness.brain_tools.tool_chars = 6001
        result = self.harness.run("gate", "--profile=p0", "--profile=p1", "--compare=p0:p1", global_args=(f"--snapshot={SNAPSHOT}",))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        decision = json.loads(self.harness.results("gate")[0].read_text())["decisions"]["p0:p1"]
        self.assertFalse(decision["adopt"])
        self.assertIn("guardrail failed: response <= 6000 characters", decision["reasons"])
        self.harness.brain_tools.tool_chars = 900
        again = self.harness.run("gate", "--profile=p0", "--profile=p1", "--compare=p0:p1", global_args=(f"--snapshot={SNAPSHOT}",))
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        passed = json.loads(next(path for path in self.harness.results("gate") if path.name == "gate-2.json").read_text())["decisions"]["p0:p1"]
        self.assertFalse(any(reason.startswith("guardrail failed") for reason in passed["reasons"]), passed["reasons"])


class PublicRepoLeakCheck(unittest.TestCase):
    def test_case_text_in_the_public_repo_is_counted_and_a_clean_repo_passes(self):
        harness = Harness()
        try:
            public = harness.root / "public"
            (public / "docs").mkdir(parents=True)
            (public / "docs" / "clean.md").write_text("How do I reconcile everything? Flux reconciles git every hour.\n")
            (public / ".git").mkdir()
            (public / ".git" / "leak").write_text(Q1)
            result = harness.run("retrieval", f"--public-repo-dir={public}", global_args=(f"--snapshot={SNAPSHOT}",))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("brain_eval_public_repo_leaks 0", (harness.out / "metrics.prom").read_text())
            (public / "docs" / "leak.md").write_text(f"Notes: {Q2.upper()} and more\n")
            (public / "runbook.md").write_text("Flux was chosen for GitOps across the whole homelab, as the ADR says\n")
            result = harness.run("retrieval", f"--public-repo-dir={public}", global_args=(f"--snapshot={SNAPSHOT}",))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("brain_eval_public_repo_leaks 1", (harness.out / "metrics.prom").read_text())
            self.assertIn('"cases_found": 1', result.stdout)
            self.assertNotIn(SENTINEL, result.stdout + result.stderr)
        finally:
            harness.close()


class ExperimentRun(unittest.TestCase):
    def test_e1_ranks_the_pool_both_ways_writes_a_decision_and_metrics(self):
        harness = Harness()
        try:
            contract = ROOT / "kubernetes/apps/ai/omnigraph/embed-step/app/contract.json"
            result = harness.run("experiment", global_args=(f"--snapshot={SNAPSHOT}", f"--contract-file={contract}"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads(harness.results("experiment-e1")[0].read_text())
            self.assertEqual({row["id"] for row in document["arms"]["e1-raw"]}, {"c01", "c02"})
            self.assertIn("adopt", document["decision"])
            by_arm = {arm: {row["id"]: row["metrics"]["ndcg_at_8"] for row in rows} for arm, rows in document["arms"].items()}
            self.assertAlmostEqual(by_arm["e1-raw"]["c01"], 3.5 / (3 + 1 / math.log2(3)), places=6)
            self.assertAlmostEqual(by_arm["e1-prefixed"]["c01"], 2.5 / (3 + 1 / math.log2(3)), places=6)
            metrics = (harness.out / "metrics.prom").read_text()
            self.assertIn('profile="e1-raw"', metrics)
            self.assertIn('profile="e1-prefixed"', metrics)
            self.assertIn('"event": "experiment e1"', result.stdout)
        finally:
            harness.close()


class GateRun(unittest.TestCase):
    def test_a_gate_scores_retrieval_and_answers_and_applies_the_decision_rule(self):
        harness = Harness()
        try:
            result = harness.run("gate", "--profile=p0", "--compare=p0:p0", "--arm=b0", "--repeats=2", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"},
                                 global_args=(f"--snapshot={SNAPSHOT}",))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads(harness.results("gate")[0].read_text())
            decision = document["decisions"]["p0:p0"]
            self.assertFalse(decision["adopt"])
            self.assertEqual((decision["wins"], decision["losses"]), (0, 0))
            self.assertEqual(len(document["answers"]["b0"]["cases"]), 2 * len(CASES))
            self.assertEqual(document["run"]["judge_model"], be.JUDGE_MODEL)
            self.assertEqual(document["run"]["calibration_templates_written"], len(CASES))
            self.assertEqual(len(list((harness.repo / "calibration" / "pending").glob("*.json"))), len(CASES))
            metrics = (harness.out / "metrics.prom").read_text()
            self.assertIn('brain_eval_cost_usd{mode="gate"}', metrics)
            self.assertIn("brain_eval_judge_control_ok 1", metrics)
        finally:
            harness.close()

    def test_an_answer_the_judge_cannot_read_is_left_unscored_while_the_share_stays_small(self):
        harness = Harness(judge_mode="cut-off-first-answer")
        try:
            result = harness.run("gate", "--profile=p0", "--arm=b0", "--repeats=2", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"},
                                 global_args=(f"--snapshot={SNAPSHOT}",))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            answers = json.loads(harness.results("gate")[0].read_text())["answers"]["b0"]
            self.assertEqual(answers["judge_unreadable"], 1)
            first = next(case for case in answers["cases"] if case["id"] == CASES[0]["id"] and case["repeat"] == 0)
            self.assertIsNone(first["metrics"]["key_fact_recall"])
            self.assertIsNone(first["metrics"]["faithfulness"])
            self.assertEqual(first["metrics"]["tool_calls"], 1.0)
            again = next(case for case in answers["cases"] if case["id"] == CASES[0]["id"] and case["repeat"] == 1)
            self.assertEqual(again["metrics"]["key_fact_recall"], 1.0)
        finally:
            harness.close()

    def test_a_gate_whose_judge_fails_the_control_pair_publishes_control_ok_0_and_scores_nothing(self):
        harness = Harness(judge_mode="broken")
        try:
            result = harness.run("gate", "--profile=p0", "--arm=b0", "--repeats=1", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"},
                                 global_args=(f"--snapshot={SNAPSHOT}",))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            pushed = "".join(harness.vmagent.bodies)
            self.assertIn("brain_eval_judge_control_ok 0", pushed)
            self.assertIn('brain_eval_run_valid{mode="gate"} 0', pushed)
            self.assertNotIn("brain_eval_score", pushed)
            self.assertEqual(harness.results("gate"), [])
            self.assertEqual(harness.litellm.mcp_calls, [])
        finally:
            harness.close()


class AnswerRun(unittest.TestCase):
    def tearDown(self):
        self.harness.close()

    def test_answer_mode_waits_for_mcp_argument_redaction(self):
        self.harness = Harness()
        result = self.harness.run("answer", "--arm=b0", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "false"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("VIK-1403", result.stdout)
        self.assertEqual(self.harness.litellm.mcp_calls, [])

    def test_b0_answers_are_judged_and_calibration_templates_written(self):
        self.harness = Harness()
        result = self.harness.run("answer", "--arm=b0", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"}, global_args=("--day=2026-09-28",))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        document = json.loads(self.harness.results("answer-b0")[0].read_text())
        self.assertEqual(len(document["cases"]), len(CASES))
        self.assertTrue(document["run"]["control"]["supported"] >= 0.8)
        self.assertIn("tools/call", self.harness.litellm.mcp_calls)
        pending = list((self.harness.repo / "calibration" / "pending").glob("*.json"))
        self.assertEqual(len(pending), len(CASES))
        metrics = (self.harness.out / "metrics.prom").read_text()
        self.assertIn("brain_eval_judge_control_ok 1", metrics)
        self.assertIn('brain_eval_cost_usd{mode="answer"}', metrics)

    def test_a_judge_that_passes_the_unsupported_control_answer_blocks_the_run(self):
        self.harness = Harness(judge_mode="broken")
        result = self.harness.run("answer", "--arm=b0", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.harness.results("answer"), [])
        pushed = "".join(self.harness.vmagent.bodies)
        self.assertIn("brain_eval_judge_control_ok 0", pushed)
        self.assertNotIn("brain_eval_score", pushed)
        self.assertEqual(self.harness.litellm.mcp_calls, [])

    def test_a_judge_whose_verdict_is_not_json_fails_the_control_pair(self):
        self.harness = Harness(judge_mode="garbled")
        result = self.harness.run("answer", "--arm=b0", "--control-only", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('"supported": 0.0', result.stdout)
        self.assertIn('"unsupported": 1.0', result.stdout)
        self.assertIn("brain_eval_judge_control_ok 0", "".join(self.harness.vmagent.bodies))

    def test_a_cut_off_verdict_is_asked_again_once_and_the_answer_still_scores(self):
        self.harness = Harness(judge_mode="cut-off-first-attempt")
        result = self.harness.run("answer", "--arm=b0", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        document = json.loads(self.harness.results("answer-b0")[0].read_text())
        self.assertEqual(document["judge_unreadable"], 0)
        self.assertEqual(self.harness.litellm.case_verdicts, 2 * len(CASES))
        self.assertIsNotNone(next(case for case in document["cases"] if case["id"] == "c01")["metrics"]["key_fact_recall"])

    def test_a_judge_that_cannot_read_most_answers_invalidates_the_run(self):
        self.harness = Harness(judge_mode="cut-off-always")
        result = self.harness.run("answer", "--arm=b0", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(f"no readable verdict for {len(CASES)} of {len(CASES)} answers", result.stdout)
        self.assertIn('"finish_reason": "length"', result.stdout)
        self.assertIn('brain_eval_run_valid{mode="answer"} 0', "".join(self.harness.vmagent.bodies))
        self.assertEqual(self.harness.results("answer"), [])

    def test_the_spend_cap_aborts_the_run_and_marks_it_invalid(self):
        self.harness = Harness()
        result = self.harness.run("answer", "--arm=b0", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"}, global_args=("--max-spend-usd=0.035",))
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn('brain_eval_run_valid{mode="answer"} 0', "".join(self.harness.vmagent.bodies))
        self.assertEqual(self.harness.results("answer"), [])
        self.assertLessEqual(self.harness.litellm.chat_calls, 4)

    def test_graded_calibration_files_give_an_agreement(self):
        self.harness = Harness()
        folder = self.harness.repo / "calibration"
        folder.mkdir()
        (folder / "c01-b0.json").write_text(json.dumps({"case_id": "c01", "question": Q1, "answerable": True, "key_facts": ["run flux reconcile"],
                                                        "answer": "Run flux reconcile [doc:x].", "tool_outputs": "flux reconcile",
                                                        "grade": {"key_facts_present": [True], "faithful": True, "abstained": False}}))
        result = self.harness.run("answer", "--arm=b0", "--control-only", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"})
        self.assertEqual(result.returncode, 0, result.stdout)
        result = self.harness.run("calibration")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("brain_eval_judge_agreement 1", (self.harness.out / "metrics.prom").read_text())


class Redaction(unittest.TestCase):
    def test_the_sentinel_never_reaches_stdout_stderr_or_a_metric(self):
        harness = Harness()
        try:
            outputs = []
            for command, env in ((("retrieval", "--missing-vectors"), {}), (("answer", "--arm=b0"), {"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"}),
                                 (("push-metrics",), {})):
                result = harness.run(*command, env=env, global_args=(f"--snapshot={SNAPSHOT}",))
                self.assertEqual(result.returncode, 0, command)
                outputs += [result.stdout, result.stderr]
            stale = harness.run("retrieval", "--scratch-stale", global_args=("--omnigraph-token-file=/nonexistent",))
            outputs += [stale.stdout, stale.stderr]
            for text in outputs + harness.vmagent.bodies + [(harness.out / "metrics.prom").read_text()]:
                self.assertNotIn(SENTINEL, text)
                for slug in ("obsidian/gamma", "obsidian/alpha", RUNBOOK):
                    self.assertNotIn(slug, text)
            written = "".join(path.read_text() for path in (harness.repo / "results").rglob("*.json"))
            self.assertIn("obsidian/gamma", written)
            self.assertTrue(any(SENTINEL in body for body in harness.litellm.bodies))
        finally:
            harness.close()


class McpClientParsing(unittest.TestCase):
    def test_json_and_event_stream_responses_and_the_session_header(self):
        fake = FakeLiteLLM()
        server, url = serve(litellm_handler(fake))
        try:
            client = be.McpClient(f"{url}/omnigraph_brain_eval/mcp", "sk")
            client.initialize()
            self.assertEqual(client.session, "session-1")
            tools = client.tools()
            self.assertEqual(tools[0]["name"], "omnigraph_brain_eval-query")
            converted, mapping = be.openai_tools(tools)
            self.assertEqual(mapping[converted[0]["function"]["name"]], "omnigraph_brain_eval-query")
            text, failed = client.call("omnigraph_brain_eval-query", {"query": "x"})
            self.assertFalse(failed)
            self.assertIn("rows about", text)
        finally:
            server.shutdown()


class CandidateCut(unittest.TestCase):
    def candidate(self, category, index, paraphrase=0, long_note=False, answerable=True):
        source = cand.Source(category, "en", f"{category}-{index}", "t", "e", "note", beyond_first_1024_tokens=long_note)
        return cand.Candidate(source, paraphrase, f"question {category} {index} {paraphrase}", ["fact"], answerable=answerable)

    def test_the_cut_meets_every_quota_with_one_holdout_per_category_and_long_dutch_notes_first(self):
        pool = []
        for category in be.CATEGORIES:
            for index in range(5):
                for paraphrase in (0, 1):
                    pool.append(self.candidate(category, index, paraphrase, long_note=(category == "notes-nl" and index in (3, 4)),
                                               answerable=category != "unanswerable"))
        chosen = cand.cut_to_quota(pool, __import__("random").Random(1))
        self.assertEqual(len(chosen), sum(be.CATEGORY_QUOTA.values()))
        for category, quota in be.CATEGORY_QUOTA.items():
            mine = [(candidate, split) for candidate, split in chosen if candidate.source.category == category]
            self.assertEqual(len(mine), quota, category)
            self.assertEqual(sum(1 for _, split in mine if split == "holdout"), 1, category)
        long_notes = [candidate for candidate, _ in chosen if candidate.source.category == "notes-nl" and candidate.source.beyond_first_1024_tokens]
        self.assertGreaterEqual(len(long_notes), 2)
        self.assertEqual({candidate.source.slug for candidate in long_notes}, {"notes-nl-3", "notes-nl-4"})
        firsts = [candidate for candidate, _ in chosen if candidate.source.category == "docs-en"]
        self.assertEqual(sum(1 for candidate in firsts if candidate.paraphrase == 0), 5)

    def test_candidates_never_overwrite_existing_cases(self):
        harness = Harness()
        try:
            result = harness.run("candidates")
            self.assertEqual(result.returncode, 2)
            self.assertIn("never overwrite", result.stdout)
        finally:
            harness.close()

    def test_pooling_falls_back_once_when_the_judge_provider_is_out_of_budget(self):
        calls = []

        class Llm:
            def chat(self, payload):
                calls.append(payload["model"])
                if payload["model"] == be.JUDGE_MODEL:
                    raise be.UpstreamError("litellm", 429)
                return {"choices": [{"message": {"content": json.dumps({"grades": [{"index": 0, "grade": 2}]})}}]}, 0.0

        args = be.build_parser().parse_args(["candidates"])
        counts, refused = {}, set()
        pooled = [("doc-a", "A", "text")]
        for _ in range(3):
            graded, model = cand.grade_with_fallback(Llm(), [args.pool_model, args.pool_fallback_model], "prompt", "q", pooled, counts, refused)
            self.assertEqual((graded, model), ({"doc-a": 2}, be.POOL_FALLBACK_MODEL))
        self.assertEqual(calls.count(be.JUDGE_MODEL), 1)
        self.assertEqual(counts["pooled_by_fallback"], 3)

    def test_every_case_the_cut_writes_validates(self):
        source = cand.Source("temporal", "nl", "temporal-recent_notes", "", "", "temporal")
        candidate = cand.Candidate(source, 0, "Wat schreef ik?", [], temporal={"kind": "recent_notes", "days": 7})
        case = cand.case_document("c01", candidate, "dev")
        self.assertEqual(be.load_case(be.dump_case(be.validate_case(case, "c01"))), case)


class FakeForgejo:
    def __init__(self, status):
        self.status = status
        self.authorization = []


def forgejo_handler(fake):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            fake.authorization.append(self.headers.get("authorization"))
            data = json.dumps({"private": fake.status == 404}).encode()
            self.send_response(fake.status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


class RepoPrivacy(unittest.TestCase):
    def check(self, status, mode="answer", stale_verdict=False):
        harness = Harness()
        self.addCleanup(harness.close)
        forgejo = FakeForgejo(status)
        server, url = serve(forgejo_handler(forgejo))
        self.addCleanup(server.shutdown)
        verdict = harness.root / "work" / "privacy-publish"
        if stale_verdict:
            verdict.write_text("private\n")
        result = harness.run("repo-privacy", f"--repo-api-url={url}/api/v1/repos/ryangr0/brain-eval", f"--for-mode={mode}", f"--verdict-file={verdict}")
        return result, verdict, "".join(harness.vmagent.bodies), forgejo

    def test_a_repo_hidden_from_anonymous_readers_may_be_pushed_to(self):
        result, verdict, pushed, forgejo = self.check(404)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(verdict.read_text().strip(), "private")
        self.assertIn("brain_eval_repo_private 1", pushed)
        self.assertEqual(forgejo.authorization, [None])

    def test_a_repo_anyone_can_read_stops_the_run_and_alerts(self):
        result, verdict, pushed, _ = self.check(200, stale_verdict=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(verdict.exists())
        self.assertIn("brain_eval_repo_private 0", pushed)
        self.assertIn('brain_eval_run_valid{mode="answer"} 0', pushed)
        self.assertIn("readable without signing in", result.stdout)

    def test_privacy_that_cannot_be_proven_stops_the_run(self):
        result, verdict, pushed, _ = self.check(503, mode="smoke", stale_verdict=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(verdict.exists())
        self.assertIn('brain_eval_run_valid{mode="smoke"} 0', pushed)
        self.assertNotIn("brain_eval_repo_private", pushed)
        self.assertIn("HTTP 503", result.stdout)


FAKE_GIT = """#!/bin/sh
echo "git $*" >> "$FAKE_GIT_LOG"
case "$*" in
  *ls-remote*) printf '%s' "$FAKE_REMOTE_REFS"; exit 0 ;;
  *"diff --cached --quiet"*) exit 1 ;;
  *"diff --cached --name-only"*) echo results/2026-09-29/retrieval-p0.json; exit 0 ;;
  *rev-parse*) echo abc1234; exit 0 ;;
esac
exit 0
"""


class StoreScripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="brain-eval-store-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bin, self.store, self.work, self.scratch = root / "bin", root / "store", root / "work", root / "scratch"
        for folder in (self.bin, self.store / "brain-eval.git", self.work / "repo", self.work / "out", self.scratch):
            folder.mkdir(parents=True)
        (self.bin / "git").write_text(FAKE_GIT)
        (self.bin / "git").chmod(0o755)
        self.key = root / "deploy-key"
        self.key.write_text("not a real key\n")
        self.git_log = root / "git.log"
        self.git_log.write_text("")

    def run_script(self, name):
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "TMPDIR": str(self.scratch), "EVAL_STORE_DIR": str(self.store),
               "EVAL_WORK_DIR": str(self.work), "EVAL_DEPLOY_KEY_FILE": str(self.key), "FAKE_GIT_LOG": str(self.git_log),
               "FAKE_REMOTE_REFS": "", "EVAL_REPO_URL": "ssh://git@forgejo-ssh.invalid/ryangr0/brain-eval.git"}
        return subprocess.run(["sh", str(APP / name)], capture_output=True, text=True, timeout=60, env=env)

    def pushes(self):
        return [line for line in self.git_log.read_text().split("\n") if " push " in f"{line} "]

    def test_the_store_moves_into_forgejo_only_after_a_proven_private_read(self):
        refused = self.run_script("store.sh")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("refusing", refused.stderr)
        self.assertEqual(self.pushes(), [])
        self.assertFalse((self.store / "moved-to-forgejo").exists())
        (self.work / "privacy-store").write_text("private\n")
        moved = self.run_script("store.sh")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        self.assertIn("moved the provisional in-cluster store", moved.stdout)
        self.assertEqual(len(self.pushes()), 1)
        self.assertEqual((self.work / "store-kind").read_text().strip(), "forgejo")

    def test_the_provisional_store_needs_no_privacy_proof(self):
        self.key.write_text("")
        result = self.run_script("store.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work / "store-kind").read_text().strip(), "provisional")
        self.assertEqual(self.pushes(), [])

    def test_publish_pushes_to_forgejo_only_after_a_proven_private_read(self):
        (self.work / "store-kind").write_text("forgejo\n")
        (self.work / "out" / "commit-message").write_text("results: retrieval p0\n")
        refused = self.run_script("publish.sh")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("refusing", refused.stderr)
        self.assertEqual(self.pushes(), [])
        (self.work / "privacy-publish").write_text("private\n")
        published = self.run_script("publish.sh")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertEqual(len(self.pushes()), 1)


class KeyFactLeaks(unittest.TestCase):
    def test_key_facts_of_private_sources_are_scanned_and_facts_quoting_this_repo_are_not(self):
        private_fact = "the greenhouse heater runs on its own twelve volt circuit since spring"
        public_fact = "flux reconciles the whole cluster from the forgejo repository every hour"
        short_fact = "heater on twelve volt"
        cases = [
            {"id": "k1", "category": "notes-en", "question": "Why?", "expected": [{"slug": "obsidian/greenhouse", "grade": 2}], "key_facts": [private_fact]},
            {"id": "k2", "category": "docs-en", "question": "How?", "expected": [{"slug": RUNBOOK, "grade": 2}], "key_facts": [public_fact]},
            {"id": "k3", "category": "notes-en", "question": "What?", "expected": [{"slug": "obsidian/shed", "grade": 2}], "key_facts": [short_fact]},
        ]
        with tempfile.TemporaryDirectory(prefix="brain-eval-leaks-") as public:
            Path(public, "docs.md").write_text(f"{public_fact.upper()}.\n{short_fact}\n")
            self.assertEqual(be.public_repo_leaks(cases, public).cases_found, 0)
            Path(public, "notes.md").write_text(f"Pasted: {private_fact}\n")
            self.assertEqual(be.public_repo_leaks(cases, public).cases_found, 1)


class ExpectedSlugLeaks(unittest.TestCase):
    def test_slugs_named_after_notes_captures_and_people_are_scanned_and_public_or_generic_slugs_are_not(self):
        cases = [
            {"id": "s1", "category": "notes-nl", "question": "Waarom?", "expected": [{"slug": "obsidian/kas-verwarming", "grade": 2}], "key_facts": []},
            {"id": "s2", "category": "docs-en", "question": "How?", "expected": [{"slug": RUNBOOK, "grade": 2}, {"slug": "forge/webgrip/homelab-cluster", "grade": 1}],
             "key_facts": []},
            {"id": "s3", "category": "about", "question": "Who?", "expected": [{"slug": "derived/person/jan-de-vries", "grade": 2}, {"slug": TOPIC, "grade": 1}],
             "key_facts": []},
            {"id": "s4", "category": "notes-en", "question": "When?", "expected": [{"slug": "nt-20260929-0a1b2c3d4e", "grade": 2}], "key_facts": []},
            {"id": "s5", "category": "temporal", "question": "Wat?", "expected": [{"slug": "obsidian/weekplanning", "grade": 1}], "key_facts": []},
        ]
        with tempfile.TemporaryDirectory(prefix="brain-eval-slugs-") as public:
            Path(public, "runbook.md").write_text(f"See {RUNBOOK}, forge/webgrip/homelab-cluster and {TOPIC}. Not obsidian/kas-verwarming-oud, "
                                                  "vault-obsidian/kas-verwarming or derived/person/jan-de-vries-2. obsidian/weekplanning\n")
            scan = be.public_repo_leaks(cases, public)
            self.assertEqual((scan.cases_found, scan.cases_found_by_slug, scan.slugs_checked), (0, 0, 4))
            Path(public, "explorer-link.md").write_text("https://graph.example/?graph=brain&node=obsidian-file/kas-verwarming\n")
            scan = be.public_repo_leaks(cases, public)
            self.assertEqual((scan.cases_found, scan.cases_found_by_slug), (1, 1))
            Path(public, "fixture.json").write_text('{"about": "derived/person/jan-de-vries", "capture": "nt-20260929-0a1b2c3d4e"}')
            scan = be.public_repo_leaks(cases, public)
            self.assertEqual((scan.cases_found, scan.cases_found_by_slug), (3, 3))


class RepoGuides(unittest.TestCase):
    def test_every_stored_run_rewrites_the_repo_guides_from_this_repo_and_a_dry_run_leaves_them(self):
        harness = Harness()
        try:
            stale = "stale guide\n"
            (harness.repo / "README.md").write_text(stale)
            self.assertEqual(harness.run("retrieval", global_args=(f"--snapshot={SNAPSHOT}", "--dry-run")).returncode, 0)
            self.assertEqual((harness.repo / "README.md").read_text(), stale)
            result = harness.run("retrieval", global_args=(f"--snapshot={SNAPSHOT}",))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((harness.repo / "README.md").read_text(), (APP / "repo-readme.md").read_text())
            self.assertEqual((harness.repo / "calibration" / "README.md").read_text(), (APP / "calibration-readme.md").read_text())
            self.assertIn("brain_eval_calibration_grades 0", (harness.out / "metrics.prom").read_text())
        finally:
            harness.close()


def litellm_routes():
    return dict(re.findall(r"- model_name: (\S+)\n\s+litellm_params:\n\s+model: (\S+)", LITELLM_CONFIG.read_text()))


def model_family(route):
    return re.match(r"[a-z]+", route.rsplit("/", 1)[-1]).group(0)


class ModelPolicy(unittest.TestCase):
    def test_the_jobs_call_only_non_anthropic_models_on_the_eval_key_and_the_judge_is_another_family(self):
        args = be.build_parser().parse_args(["candidates"])
        routes = litellm_routes()
        key_models = json.loads(re.search(r"name: MODELS, value: '([^']+)'", EVAL_KEY_JOB.read_text()).group(1))
        called = {args.answer_model, args.judge_model, args.draft_model, args.pool_model, args.pool_fallback_model}
        for model in called | set(key_models):
            self.assertIn(model, routes, model)
            self.assertNotRegex(f"{model} {routes[model]}", r"claude|anthropic", model)
        self.assertLessEqual(called, set(key_models))
        family = {model: model_family(routes[model]) for model in called}
        self.assertNotIn(family[args.judge_model], {family[args.answer_model], family[args.draft_model]})
        self.assertNotEqual(family[args.pool_model], family[args.draft_model])
        self.assertNotEqual(family[args.pool_fallback_model], family[args.draft_model])
        for path in APP.glob("*.yaml"):
            self.assertNotRegex(path.read_text(), r"--(judge|pool|answer|draft)-model|claude-", path.name)


def cronjobs():
    documents = []
    for path in sorted(APP.glob("*.yaml")):
        for chunk in path.read_text().split("\n---\n"):
            if "kind: CronJob" not in chunk:
                continue
            field = lambda pattern: (re.search(pattern, chunk, re.M) or [None, None])[1]
            documents.append({"name": field(r"^  name: (\S+)"), "schedule": field(r'^  schedule: "([^"]+)"'), "zone": field(r"^  timeZone: (\S+)"),
                              "suspended": field(r"^  suspend: (\S+)") == "true", "deadline": int(field(r"activeDeadlineSeconds: (\d+)")),
                              "store": "claimName: omnigraph-brain-eval-store" in chunk, "hold": field(r"sleep (\d+)")})
    return documents


WINTER_AND_SUMMER_UTC_OFFSET_HOURS = {"Etc/UTC": (0, 0), "Europe/Amsterdam": (1, 2)}
DAY_MINUTES = 24 * 60


def utc_minutes(schedule, offset_hours):
    minute, hour = (int(part) for part in schedule.split()[:2])
    return (hour * 60 + minute - offset_hours * 60) % DAY_MINUTES


class StoreBackupWindow(unittest.TestCase):
    def test_no_scheduled_eval_job_holds_the_store_volume_during_its_backup_window_in_winter_or_summer(self):
        jobs = cronjobs()
        window = next(job for job in jobs if job["hold"])
        self.assertEqual(window["zone"], "Etc/UTC")
        opens = utc_minutes(window["schedule"], 0)
        closes = opens + math.ceil(int(window["hold"]) / 60)
        scheduled = [job for job in jobs if job["store"] and not job["suspended"] and not job["hold"]]
        self.assertTrue(scheduled)
        for job in scheduled:
            self.assertIn(job["zone"], WINTER_AND_SUMMER_UTC_OFFSET_HOURS, job["name"])
            for offset in WINTER_AND_SUMMER_UTC_OFFSET_HOURS[job["zone"]]:
                start = utc_minutes(job["schedule"], offset)
                end = start + math.ceil(job["deadline"] / 60)
                for day in (-DAY_MINUTES, 0, DAY_MINUTES):
                    self.assertFalse(start < closes + day and opens + day < end,
                                     f"{job['name']} may run from {start // 60:02d}:{start % 60:02d} UTC until its deadline, inside the store backup window")


class ThrottlingLiteLLM:
    def __init__(self, throttled, retry_after="0.25", mcp_throttled=0):
        self.throttled = throttled
        self.retry_after = retry_after
        self.mcp_throttled = mcp_throttled
        self.requests = []

    def handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, status, payload, headers=()):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                fake.requests.append(self.path)
                throttled = fake.mcp_throttled if self.path.endswith("/mcp") else fake.throttled
                if len([path for path in fake.requests if path == self.path]) <= throttled:
                    headers = [("retry-after", fake.retry_after)] if fake.retry_after is not None else []
                    self.send(429, {"error": {"message": "Rate limit exceeded", "type": "throttling_error", "code": "429"}}, headers)
                elif self.path.endswith("/mcp"):
                    self.send(200, {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": "rows"}], "isError": False}})
                else:
                    self.send(200, {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}},
                              [("x-litellm-response-cost", "0.001")])
        return Handler


class RecordedSleep:
    def __init__(self):
        self.pauses = []

    def __call__(self, seconds):
        self.pauses.append(seconds)


class RateLimits(unittest.TestCase):
    def client(self, fake):
        server, url = serve(fake.handler())
        self.addCleanup(server.shutdown)
        sleep = RecordedSleep()
        return be.LiteLLM(url, "sk", be.Spend(None), pacer=be.Pacer(sleep=sleep)), sleep, url

    def test_a_throttled_call_waits_as_long_as_retry_after_says_and_then_succeeds(self):
        fake = ThrottlingLiteLLM(throttled=be.RATE_LIMITED_ATTEMPTS - 1)
        llm, sleep, _ = self.client(fake)
        response, cost = llm.chat({"model": "chat-default", "messages": []})
        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        self.assertEqual(cost, 0.001)
        self.assertEqual(len(fake.requests), be.RATE_LIMITED_ATTEMPTS)
        self.assertEqual(sleep.pauses, [1.25] * (be.RATE_LIMITED_ATTEMPTS - 1))
        self.assertEqual(llm.pacer.rate_limited, be.RATE_LIMITED_ATTEMPTS - 1)

    def test_a_call_throttled_every_time_gives_up_with_the_throttling_error(self):
        fake = ThrottlingLiteLLM(throttled=100)
        llm, sleep, _ = self.client(fake)
        with self.assertRaises(be.UpstreamError) as raised:
            llm.chat({"model": "chat-default", "messages": []})
        self.assertEqual((raised.exception.status, raised.exception.code), (429, "throttling_error"))
        self.assertLessEqual(len(fake.requests), be.RATE_LIMITED_ATTEMPTS + 3)

    def test_a_retry_after_beyond_the_cap_is_never_slept(self):
        fake = ThrottlingLiteLLM(throttled=100, retry_after=str(be.MAX_RETRY_AFTER_SECONDS * 30))
        llm, sleep, _ = self.client(fake)
        with self.assertRaises(be.UpstreamError):
            llm.chat({"model": "chat-default", "messages": []})
        self.assertLess(max(sleep.pauses), be.MAX_RETRY_AFTER_SECONDS)
        self.assertEqual(llm.pacer.rate_limited, 0)

    def test_an_unthrottled_call_never_waits(self):
        fake = ThrottlingLiteLLM(throttled=0)
        llm, sleep, _ = self.client(fake)
        for _ in range(5):
            llm.chat({"model": "chat-default", "messages": []})
        self.assertEqual(sleep.pauses, [])

    def test_a_throttled_tool_call_waits_for_retry_after_too(self):
        fake = ThrottlingLiteLLM(throttled=0, mcp_throttled=2)
        server, url = serve(fake.handler())
        self.addCleanup(server.shutdown)
        sleep = RecordedSleep()
        client = be.McpClient(f"{url}/omnigraph_brain_eval/mcp", "sk", pacer=be.Pacer(sleep=sleep))
        text, failed = client.call("query", {"query": "x"})
        self.assertEqual((text, failed), ("rows", False))
        self.assertEqual(sleep.pauses, [1.25, 1.25])

    def test_the_pacer_holds_calls_until_the_minute_has_room_again(self):
        now = [1000.0]
        sleep = RecordedSleep()

        def advance(seconds):
            sleep(seconds)
            now[0] += seconds
        pacer = be.Pacer(tokens_per_minute=100, requests_per_minute=50, clock=lambda: now[0], sleep=advance)
        pacer.record(60)
        now[0] += 10
        pacer.wait_for_room()
        self.assertEqual(sleep.pauses, [])
        pacer.record(50)
        now[0] += 5
        pacer.wait_for_room()
        self.assertEqual(len(sleep.pauses), 1)
        self.assertAlmostEqual(sleep.pauses[0], be.RATE_LIMIT_WINDOW_SECONDS - 15 + 0.05)

    def test_the_pacer_counts_requests_as_well_as_tokens(self):
        now = [0.0]
        sleep = RecordedSleep()

        def advance(seconds):
            sleep(seconds)
            now[0] += seconds
        pacer = be.Pacer(tokens_per_minute=10 ** 9, requests_per_minute=3, clock=lambda: now[0], sleep=advance)
        for _ in range(3):
            pacer.record(0)
        pacer.wait_for_room()
        self.assertEqual(len(sleep.pauses), 1)

    def test_the_default_pace_stays_under_the_eval_key_limits(self):
        job = EVAL_KEY_JOB.read_text()
        key_tpm = int(re.search(r"name: TPM_LIMIT, value: \"(\d+)\"", job).group(1))
        key_rpm = int(re.search(r"name: RPM_LIMIT, value: \"(\d+)\"", job).group(1))
        args = be.build_parser().parse_args(["answer"])
        self.assertLessEqual(args.tokens_per_minute, 0.8 * key_tpm)
        self.assertLessEqual(args.requests_per_minute, 0.8 * key_rpm)
        self.assertGreater(args.tokens_per_minute, 0)
        self.assertGreater(args.requests_per_minute, 0)


def bridge_error(message, status=400):
    return json.dumps({"error": message, "status": status, "code": "bad_request", "body": {"error": message, "code": "bad_request"}}, indent=2)


class ToolErrorClasses(unittest.TestCase):
    def test_each_raw_bridge_failure_shape_gets_its_own_class(self):
        shapes = {
            bridge_error("parse error:  --> 1:1\n  |\n1 | MATCH (n) RETURN n\n  | ^---\n  |\n  = expected query_file"): "gq_foreign",
            bridge_error("parse error:  --> 3:14\n  |\n3 |   $n.name = x\n  |              ^---\n  |\n  = expected operator"): "gq_parse",
            bridge_error("type error: T6: type `Note` has no property `title`"): "gq_type",
            bridge_error("parameter 'q' not provided"): "gq_parameter",
            bridge_error("lint error: limit must be an integer literal"): "gq_rejected",
            bridge_error("forbidden", 403): "policy_denied",
            bridge_error("not found", 404): "not_found",
            bridge_error("length limit exceeded", 413): "resource_limit",
            bridge_error("internal", 500): "server_error",
            json.dumps({"error": "fetch failed", "status": 0}): "server_unreachable",
            "MCP error -32602: Invalid arguments for tool query": "tool_arguments",
            "something else entirely": "other",
        }
        for text, expected in shapes.items():
            self.assertEqual(be.tool_error_class(text), expected, text)
        self.assertEqual(set(shapes.values()) | {"unknown_tool", "bridge_transport"}, set(be.TOOL_ERROR_CLASSES))
        self.assertEqual(be.failed_call_class(json.JSONDecodeError("x", "y", 0)), "tool_arguments")
        self.assertEqual(be.failed_call_class(be.McpRpcError("tools/call", be.MCP_INVALID_PARAMS)), "tool_arguments")
        self.assertEqual(be.failed_call_class(be.UpstreamError("litellm-mcp", 0, "TimeoutError")), "bridge_transport")

    def test_an_answer_counts_failed_calls_by_class_and_the_run_publishes_them(self):
        class Llm:
            def __init__(self):
                self.turn = 0

            def chat(self, payload):
                self.turn += 1
                if self.turn == 1:
                    calls = [{"id": "a", "function": {"name": "query", "arguments": json.dumps({"query": "MATCH (n) RETURN n"})}},
                             {"id": "b", "function": {"name": "query", "arguments": "{not json"}},
                             {"id": "c", "function": {"name": "cypher", "arguments": "{}"}},
                             {"id": "d", "function": {"name": "query", "arguments": json.dumps({"query": "fine"})}}]
                    return {"choices": [{"message": {"content": "", "tool_calls": calls}}], "usage": {}}, 0.0
                return {"choices": [{"message": {"content": "done"}}], "usage": {}}, 0.0

        class Mcp:
            def call(self, name, arguments):
                if arguments["query"] == "fine":
                    return "rows", False
                return bridge_error("parse error:  --> 2:5\n  = expected match_block"), True

        answer = be.answer_case("q", Llm(), Mcp(), [{"type": "function", "function": {"name": "query"}}], {"query": "query"}, model="m", prompt=None)
        self.assertEqual((answer.tool_calls, answer.tool_errors), (4, 3))
        self.assertEqual(answer.tool_error_classes, {"gq_parse": 1, "tool_arguments": 1, "unknown_tool": 1})

    def test_a_b0_run_pushes_tool_errors_per_class(self):
        harness = Harness()
        try:
            result = harness.run("answer", "--arm=b0", env={"BRAIN_EVAL_MCP_ARGUMENTS_REDACTED": "true"}, global_args=("--day=2026-09-28",))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            metrics = (harness.out / "metrics.prom").read_text()
            for error_class in be.TOOL_ERROR_CLASSES:
                self.assertIn(f'brain_eval_tool_errors{{class="{error_class}",profile="b0"}} 0', metrics)
            self.assertIn('brain_eval_paced_seconds{mode="answer"} 0', metrics)
            self.assertIn('"tool_error_classes": {}', result.stdout)
        finally:
            harness.close()


class CrashReports(unittest.TestCase):
    def test_an_unexpected_error_names_the_harness_line_as_well_as_the_library_line(self):
        try:
            be.parse_json_content({"choices": [{"message": {"content": "not json"}}]})
        except json.JSONDecodeError as error:
            location = be.error_location(error)
        self.assertRegex(location, r"^brain_eval\.py:\d+ in parse_json_content \(decoder\.py:\d+\)$")


def progress(stage):
    print(f"real-server shapes: {stage}", file=sys.stderr, flush=True)


@unittest.skipUnless(os.environ.get("BRAIN_EVAL_REAL_SERVER") == "1", "needs the pinned omnigraph and omnigraph-server on PATH (set BRAIN_EVAL_REAL_SERVER=1)")
class RealServerShapes(unittest.TestCase):
    def test_every_query_the_harness_sends_runs_on_the_pinned_server(self):
        faulthandler.dump_traceback_later(420, exit=True)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        sys.path.insert(0, str(ROOT / "scripts"))
        rehearsal = importlib.import_module("omnigraph_rehearsal")
        with tempfile.TemporaryDirectory(prefix="brain-eval-real-") as scratch:
            workdir = Path(scratch)
            rendered = rehearsal.kustomize(ROOT / rehearsal.APP_PATH, "working")
            bundle = rehearsal.Bundle(rendered.bundle_files(), "working")
            init_env = rendered.plain_env(rehearsal.INIT_CONTAINER, init=True)
            embedder = rehearsal.FakeEmbedder(init_env.get("OMNIGRAPH_EMBED_MODEL", "x"))
            embed_url = embedder.start()
            server = None
            try:
                (workdir / "cluster").mkdir()
                cluster = rehearsal.Rehearsal(workdir / "cluster", embed_url, init_env.get("OMNIGRAPH_OPERATOR_ACTOR", "act-gitops"))
                progress("first bootstrap")
                cluster.bootstrap(bundle, rendered, "first")
                cluster.load("brain", rehearsal.seed_rows(bundle.schema("brain")), "seed")
                progress("second bootstrap")
                bundle_dir, _, _ = cluster.bootstrap(bundle, rendered, "second")
                tokens = {actor: f"token-{actor}" for actor in bundle.policy_actors()}
                env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", scratch), **rendered.plain_env(rehearsal.SERVER_CONTAINER), "OMNIGRAPH_EMBED_API_KEY": "x"}
                server = rehearsal.Server(bundle_dir, tokens, env, workdir / "cluster")
                server.wait_ready(len(bundle.graphs()), 180)
                progress("server ready")
                actor = "act-brain-eval" if "act-brain-eval" in tokens else "act-ryan"
                omnigraph = be.Omnigraph(server.base, "brain", tokens[actor])
                head = omnigraph.head()
                self.assertTrue(omnigraph.commit_time(head))
                catalog = be.Catalog.read(omnigraph, head)
                self.assertTrue(catalog.slugs["Note"] and catalog.slugs["Artifact"])
                scans = be.temporal_scans(omnigraph, head, set(be.TEMPORAL_KINDS))
                self.assertTrue(scans["notes"] and scans["artifacts"])
                self.assertTrue(be.profile_p0(omnigraph, "rehearsal", head).ranked)
                for source in [leg[0] for leg in cand.POOL_LEGS.values()] + [be.E1_POOL_SOURCE, be.E1_KEYWORD_SOURCE]:
                    self.assertTrue(omnigraph.inline(source, {"q": "rehearsal"}, snapshot=head).get("rows"), source.split("(")[0])
                for source in (cand.LINKED_ARTIFACTS_SOURCE, cand.LINKED_NOTES_SOURCE, cand.RELATED_TOPICS_SOURCE, cand.PERSON_MENTIONS_SOURCE, cand.PERSON_NOTES_SOURCE):
                    self.assertIn("rows", omnigraph.inline(source, snapshot=head), source.split("(")[0])
                self.assertEqual(set(be.missing_vector_ratios(omnigraph, head)), set(be.VECTOR_TYPES))
                self.assertTrue(set(be.P0_QUERIES) <= omnigraph.stored_catalog())
                progress("every query ran")
            finally:
                if server:
                    server.stop()
                embedder.stop()


if __name__ == "__main__":
    unittest.main(verbosity=1)
