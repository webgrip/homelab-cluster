#!/usr/bin/env python3
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_MAIN = ROOT / "kubernetes/apps/ai/brain-tools/app/server/main.ts"
CONTRACT = ROOT / "kubernetes/apps/ai/omnigraph/embed-step/app/contract.json"
QUESTION = "kustomization reconciliation drift"
STAMP = "2026-09-30T08:00:00Z"


def http(url, payload=None, token=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, body


def brain_rows(unit_vector):
    def node(type_name, **data):
        return {"type": type_name, "data": {"createdAt": STAMP, **data}}

    def passage(artifact, index, text, vector_seed):
        return [
            {"type": "Passage", "id": f"{artifact}#{index}", "data": {"text": text, "chunk_index": index, "createdAt": STAMP, "embedding": unit_vector(vector_seed, 384)}},
            {"edge": "PassageOf", "from": f"{artifact}#{index}", "to": artifact},
        ]

    runbook = "forge/acme/app/doc/runbook"
    pull = "forge/acme/app/pull/7"
    shadow = "obsidian-file/garden"
    units = [
        [node("Artifact", slug=runbook, name="Runbook", kind="document", source="other", url="https://forge.example.test/runbook", timestamp=STAMP, updatedAt=STAMP)],
        [node("Artifact", slug=pull, name="Bump the kustomization", kind="post", source="other", url="https://forge.example.test/pull/7", timestamp=STAMP, updatedAt=STAMP)],
        [node("Artifact", slug=shadow, name="Garden", kind="document", source="notes-app", timestamp=STAMP, updatedAt=STAMP)],
        [node("Person", slug="forge/user/renovate", name="renovate", relation="professional", updatedAt=STAMP)],
        [node("Note", slug="obsidian/garden", name="Garden", kind="idea", content="Garden plans and kustomization notes", updatedAt=STAMP,
              embedding=unit_vector("note garden", 384))],
        [node("Note", slug="nt-20260930-abc", name="Kustomization drift capture", kind="idea", content="A capture about kustomization reconciliation drift",
              updatedAt=STAMP, embedding=unit_vector(QUESTION, 384))],
        [node("Topic", slug="derived/topic/kustomization", name="kustomization", updatedAt=STAMP, embedding=unit_vector(QUESTION, 384))],
        passage(runbook, 0, "Runbook › Drift\nWhen a kustomization reconciliation shows drift, compare the rendered manifests with the live objects first.", QUESTION),
        passage(runbook, 1, "Runbook › Suspend\nSuspend the kustomization before a manual change and resume it afterwards so Flux does not revert it.", "runbook one"),
        passage(runbook, 2, "Runbook › Logs\nThe controller logs name the kustomization and the object that failed to apply, with the reason.", "runbook two"),
        passage(pull, 0, "Bumps the kustomization controller image; reconciliation drift fixes from upstream are included in this release.", "pull"),
        passage(shadow, 0, "Garden › Soil\nThe soil needs compost before planting; a note that also mentions kustomization drift for the test.", "garden zero"),
        passage(shadow, 1, "Garden › Water\nWater deeply twice a week in summer, less in spring and autumn, and never at noon.", "garden one"),
        [{"edge": "NoteFromArtifact", "from": "obsidian/garden", "to": shadow}],
        [{"edge": "ArtifactFromPerson", "from": pull, "to": "forge/user/renovate"}],
    ]
    return units


def free_port():
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(os.environ.get("BRAIN_TOOLS_REAL_SERVER") == "1", "needs node 24 and the pinned omnigraph and omnigraph-server on PATH (set BRAIN_TOOLS_REAL_SERVER=1)")
class RealServerBrainTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "scripts"))
        rehearsal = importlib.import_module("omnigraph_rehearsal")
        cls.scratch = tempfile.TemporaryDirectory(prefix="brain-tools-real-")
        workdir = Path(cls.scratch.name)
        rendered = rehearsal.kustomize(ROOT / rehearsal.APP_PATH, "working")
        bundle = rehearsal.Bundle(rendered.bundle_files(), "working")
        init_env = rendered.plain_env(rehearsal.INIT_CONTAINER, init=True)
        cls.embedder = rehearsal.FakeEmbedder(init_env.get("OMNIGRAPH_EMBED_MODEL", "x"))
        embed_url = cls.embedder.start()
        (workdir / "cluster").mkdir()
        cluster = rehearsal.Rehearsal(workdir / "cluster", embed_url, init_env.get("OMNIGRAPH_OPERATOR_ACTOR", "act-gitops"))
        cluster.bootstrap(bundle, rendered, "first")
        cluster.load("brain", brain_rows(rehearsal.unit_vector), "brain-tools")
        bundle_dir, _, _ = cluster.bootstrap(bundle, rendered, "second")
        cls.tokens = {actor: f"token-{actor}" for actor in bundle.policy_actors()}
        env = {"PATH": os.environ["PATH"], "HOME": str(workdir), **rendered.plain_env(rehearsal.SERVER_CONTAINER), "OMNIGRAPH_EMBED_API_KEY": "x"}
        cls.server = rehearsal.Server(bundle_dir, cls.tokens, env, workdir / "cluster")
        cls.server.wait_ready(len(bundle.graphs()), 180)
        cls.mcp_port, cls.rest_port = free_port(), free_port()
        cls.rest = f"http://127.0.0.1:{cls.rest_port}"
        cls.mcp = f"http://127.0.0.1:{cls.mcp_port}/mcp"
        cls.log_path = workdir / "brain-tools.log"
        cls.log = cls.log_path.open("w")
        tool_env = {
            "PATH": os.environ["PATH"],
            "HOME": str(workdir),
            "OMNIGRAPH_URL": cls.server.base,
            "OMNIGRAPH_TOKEN": cls.tokens["act-brain-reader"],
            "LITELLM_URL": embed_url.rsplit("/v1", 1)[0],
            "LITELLM_KEY": "sk-real-server-test",
            "EMBEDDING_CONTRACT_FILE": str(CONTRACT),
            "MCP_LISTEN": f"127.0.0.1:{cls.mcp_port}",
            "REST_LISTEN": f"127.0.0.1:{cls.rest_port}",
            "BRAIN_EXPLORER_URL": "https://graph.example.test",
            "BRAIN_TOOLS_PROFILE": "p1",
        }
        cls.tools = subprocess.Popen([shutil.which("node") or "node", str(SERVER_MAIN)], env=tool_env, stdout=cls.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 60
        last = None
        while time.monotonic() < deadline:
            if cls.tools.poll() is not None:
                raise AssertionError(f"brain-tools exited {cls.tools.returncode}:\n{cls.log_path.read_text()}")
            try:
                status, last = http(f"{cls.rest}/readyz", timeout=5)
                if status == 200:
                    break
            except (urllib.error.URLError, ConnectionError):
                pass
            time.sleep(0.3)
        else:
            raise AssertionError(f"brain-tools never became ready: {last}\n{cls.log_path.read_text()}")

    @classmethod
    def tearDownClass(cls):
        cls.tools.terminate()
        cls.tools.wait(timeout=10)
        cls.log.close()
        cls.server.stop()
        cls.embedder.stop()
        cls.scratch.cleanup()

    def search(self, **params):
        status, body = http(f"{self.rest}/api/search?{urllib.parse.urlencode(params)}")
        self.assertEqual(status, 200, body)
        return body

    def test_ready_means_every_stored_query_is_served_to_the_reader_and_the_contract_matches_the_schema(self):
        status, body = http(f"{self.rest}/readyz")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["missing_queries"], [])
        self.assertTrue(body["embedding_contract_ok"], body)

    def test_p1_runs_every_leg_on_the_pinned_server_and_ranks_the_planted_passage_first(self):
        body = self.search(q=QUESTION, profile="p1", debug="1", limit=40)
        legs = body["debug"]["legs"]
        for name in ("docs_vec", "docs_kw", "notes_vec", "notes_kw", "captures_vec", "captures_kw", "topics_vec", "topics_kw"):
            self.assertIn(name, legs)
            self.assertIsNone(legs[name]["failed"], name)
            self.assertGreater(legs[name]["rows"], 0, name)
        self.assertEqual(body["mode"], "fused")
        self.assertIsNone(body["degraded"])
        self.assertEqual(body["results"][0]["ref"], "doc:forge/acme/app/doc/runbook#0")
        self.assertEqual(body["results"][0]["link"], "https://forge.example.test/runbook")
        documents = [result["document"] for result in body["results"]]
        self.assertIn("obsidian/garden", documents)
        self.assertIn("nt-20260930-abc", documents)
        self.assertLessEqual(documents.count("forge/acme/app/doc/runbook"), 2)
        bots = {entry["key"]: entry["bot"] for entry in body["debug"]["fused"]}
        self.assertTrue(bots.get("forge/acme/app/pull/7#0"), bots)
        self.assertEqual(body["related"][0]["ref"], "topic:derived/topic/kustomization")
        self.assertTrue(body["graph_commit"])

    def test_a_pinned_snapshot_answers_from_that_commit_and_the_same_way_every_time(self):
        head = self.search(q=QUESTION, profile="p1", limit=40)
        first = self.search(q=QUESTION, profile="p1", limit=40, snapshot=head["graph_commit"])
        second = self.search(q=QUESTION, profile="p1", limit=40, snapshot=head["graph_commit"])
        self.assertEqual(first["graph_commit"], head["graph_commit"])
        self.assertEqual(first["results"][0]["ref"], "doc:forge/acme/app/doc/runbook#0")
        self.assertEqual([result["ref"] for result in second["results"]], [result["ref"] for result in first["results"]])

    def test_p0_through_brain_tools_ranks_what_the_stored_recall_queries_rank(self):
        body = self.search(q=QUESTION, profile="p0", limit=40)
        token = self.tokens["act-brain-eval"]
        direct = []
        for name, column in (("recall_notes", "n.slug"), ("recall_passages", "a.slug"), ("recall_topics", "t.slug")):
            status, result = http(f"{self.server.base}/graphs/brain/queries/{name}", {"params": {"q": QUESTION}, "snapshot": body["graph_commit"]}, token)
            self.assertEqual(status, 200, result)
            direct.append([row[column] for row in result["rows"]])
        interleaved = []
        for position in range(max(len(items) for items in direct)):
            for items in direct:
                if position < len(items):
                    interleaved.append(items[position])
        self.assertEqual([result["document"] for result in body["results"]], interleaved)

    def test_read_opens_doc_note_and_capture_refs(self):
        status, doc = http(f"{self.rest}/api/read?ref={urllib.parse.quote('doc:forge/acme/app/doc/runbook#1')}")
        self.assertEqual(status, 200, doc)
        self.assertEqual(doc["chunks"], [0, 1, 2])
        status, note = http(f"{self.rest}/api/read?ref={urllib.parse.quote('note:obsidian/garden#1')}")
        self.assertEqual(status, 200, note)
        self.assertEqual(note["chunks"], [0, 1])
        self.assertIn("Water deeply", note["text"])
        status, capture = http(f"{self.rest}/api/read?ref={urllib.parse.quote('note:nt-20260930-abc')}")
        self.assertEqual(status, 200, capture)
        self.assertIn("capture about kustomization", capture["text"])

    def test_mcp_lists_and_calls_the_tools(self):
        status, init = http(self.mcp, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
        self.assertEqual(status, 200, init)
        status, listed = http(self.mcp, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual([tool["name"] for tool in listed["result"]["tools"]], ["search", "read"])
        status, called = http(self.mcp, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search", "arguments": {"query": QUESTION}}})
        self.assertFalse(called["result"]["isError"], called)
        text = called["result"]["content"][0]["text"]
        self.assertIn("doc:forge/acme/app/doc/runbook#0", text)
        self.assertLessEqual(len(text), 6000)

    def test_the_log_never_carries_the_question_or_a_slug(self):
        self.search(q=QUESTION, profile="p1")
        text = self.log_path.read_text()
        self.assertNotIn("reconciliation", text)
        self.assertNotIn("forge/acme", text)
        self.assertNotIn("obsidian/garden", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
