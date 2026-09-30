#!/usr/bin/env python3
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/ai/omnigraph/embed-step/app"
STEP = APP / "embed_step.py"
CONTRACT = APP / "contract.json"
WRITE_HELPER = APP / "omnigraph_write.sh"
DIMENSIONS = 384

spec = importlib.util.spec_from_file_location("embed_step", STEP)
embed_step = importlib.util.module_from_spec(spec)
sys.modules["embed_step"] = embed_step
spec.loader.exec_module(embed_step)


def fake_vector(text):
    seed = sum(ord(char) for char in text) or 1
    return [math.sin(seed * (index + 1)) * 3.0 for index in range(DIMENSIONS)]


class FakeEmbedder:
    def __init__(self, fail_after=None, error="litellm answered HTTP 503"):
        self.batches = []
        self.fail_after = fail_after
        self.error = error

    def __call__(self, texts):
        if self.fail_after is not None and len(self.batches) >= self.fail_after:
            raise embed_step.EmbeddingUnavailable(self.error)
        self.batches.append(list(texts))
        return [fake_vector(text) for text in texts], sum(len(text) for text in texts) // 4


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class NoPause:
    paused = 0.0

    def spend(self, tokens):
        pass


def note(slug, content, **extra):
    return {"type": "Note", "data": dict({"slug": slug, "name": slug, "kind": "idea", "content": content,
                                          "createdAt": "2026-09-01T00:00:00Z", "updatedAt": "2026-09-01T00:00:00Z"}, **extra)}


def passage(pid, text):
    return {"type": "Passage", "id": pid, "data": {"text": text, "chunk_index": 0, "createdAt": "2026-09-01T00:00:00Z"}}


def write(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


class Plan:
    def __init__(self, main=(), heal=(), missing=(), heal_since=None, writer="forge-import"):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        for index, rows in enumerate(main):
            write(self.root / f"load-{index:04d}.ndjson", rows)
        for index, rows in enumerate(heal):
            write(self.root / f"heal-{index:04d}.ndjson", rows)
        (self.root / "embed-plan.json").write_text(json.dumps({"writer": writer, "missing": list(missing), "heal_since": heal_since or {}}), encoding="utf-8")

    def args(self, deadline=600):
        return SimpleNamespace(plan=str(self.root), contract=str(CONTRACT), litellm_url="http://unused", key_file="/nonexistent",
                               tokens_per_second=300.0, deadline_seconds=deadline)

    def run(self, embedder, deadline=600, clock=None, pacer=None):
        clock = clock or FakeClock()
        return embed_step.embed(self.args(deadline), embedder=embedder, pacer=pacer or NoPause(), clock=clock)

    def close(self):
        self.dir.cleanup()


class ContractText(unittest.TestCase):
    def setUp(self):
        self.contract = embed_step.Contract.load(CONTRACT)

    def test_prefix_format_matches_the_backfill(self):
        self.assertEqual(self.contract.text("Passage", "Flux reconciles."), "type: Passage\ntext: Flux reconciles.")
        self.assertEqual(self.contract.text("Note", "Idee"), "type: Note\ncontent: Idee")

    def test_rust_white_space_is_trimmed_and_inner_space_kept(self):
        self.assertEqual(self.contract.text("Note", "　  a  \n b  \u0085"), "type: Note\ncontent: a  \n b")

    def test_separator_controls_are_kept_like_omnigraph_does(self):
        self.assertEqual(self.contract.text("Note", "\u001cvalue\u001f"), "type: Note\ncontent: \u001cvalue\u001f")

    def test_empty_values_are_not_embedded(self):
        for value in (None, "", " \n\t　"):
            self.assertIsNone(self.contract.text("Note", value))

    def test_long_values_are_cut_before_the_request(self):
        text = self.contract.text("Note", "a" * 20000)
        self.assertEqual(len(text), len("type: Note\ncontent: ") + embed_step.MAX_VALUE_CHARS)


class Fill(unittest.TestCase):
    def test_every_note_and_passage_gets_a_normalised_384_float_vector_in_8_digits(self):
        plan = Plan(main=[[note("forge/a/adr/x", "We use Flux."), passage("forge/a/doc#0", "Chunk text"),
                           {"type": "Artifact", "data": {"slug": "forge/a/doc"}}, {"edge": "PassageOf", "from": "forge/a/doc#0", "to": "forge/a/doc"}]])
        try:
            report = plan.run(FakeEmbedder())
            rows = read(plan.root / "load-0000.ndjson")
            for row in rows[:2]:
                vector = row["data"]["embedding"]
                self.assertEqual(len(vector), DIMENSIONS)
                self.assertAlmostEqual(math.sqrt(sum(value * value for value in vector)), 1.0, places=6)
                self.assertTrue(all(float(format(value, ".8g")) == value for value in vector))
            self.assertNotIn("embedding", rows[2]["data"])
            self.assertEqual(report["counts"]["embedded"], 2)
            self.assertEqual(report["missing"], {"Note": 0, "Passage": 0})
        finally:
            plan.close()

    def test_batches_hold_at_most_4_inputs_in_the_contract_format(self):
        plan = Plan(main=[[passage(f"p#{index}", f"chunk {index}") for index in range(10)]])
        try:
            embedder = FakeEmbedder()
            plan.run(embedder)
            self.assertEqual([len(batch) for batch in embedder.batches], [4, 4, 2])
            self.assertEqual(embedder.batches[0][0], "type: Passage\ntext: chunk 0")
        finally:
            plan.close()

    def test_textless_notes_are_written_without_a_vector_and_not_counted_missing(self):
        plan = Plan(main=[[note("obsidian/empty", None), note("obsidian/blank", "  \n")]])
        try:
            report = plan.run(FakeEmbedder())
            self.assertEqual([row["data"].get("embedding") for row in read(plan.root / "load-0000.ndjson")], [None, None])
            self.assertEqual(report["counts"]["textless"], 2)
            self.assertEqual(report["missing"]["Note"], 0)
        finally:
            plan.close()

    def test_jsonl_is_split_on_newlines_only(self):
        plan = Plan(main=[[passage("p#0", "line separator\u0085next"), passage("p#1", "second")]])
        try:
            plan.run(FakeEmbedder())
            rows = read(plan.root / "load-0000.ndjson")
            self.assertEqual([row["id"] for row in rows], ["p#0", "p#1"])
            self.assertEqual(rows[0]["data"]["text"], "line separator\u0085next")
        finally:
            plan.close()


class FailSoft(unittest.TestCase):
    def test_litellm_failure_writes_main_rows_without_a_vector_and_drops_heals(self):
        plan = Plan(main=[[passage(f"p#{index}", f"new {index}") for index in range(20)]],
                    heal=[[passage("old#0", "old text")]], heal_since={"Passage|old#0": "2026-09-20T00:00:00Z"},
                    missing=[{"type": "Note", "since": "2026-09-25T00:00:00Z"}])
        try:
            report = plan.run(FakeEmbedder(fail_after=4))
            rows = read(plan.root / "load-0000.ndjson")
            self.assertEqual(sum("embedding" in row["data"] for row in rows), 16)
            self.assertEqual(len(rows), 20)
            self.assertFalse((plan.root / "heal-0000.ndjson").exists())
            self.assertEqual((report["counts"]["skipped"], report["counts"]["heal_dropped"]), (4, 1))
            self.assertEqual(report["missing"], {"Note": 1, "Passage": 5})
            self.assertGreater(report["oldest_missing_seconds"]["Passage"], 9 * 86400)
            self.assertIn("503", report["reason"])
        finally:
            plan.close()

    def test_the_deadline_stops_embedding_and_keeps_every_row(self):
        clock = FakeClock()
        pacer = embed_step.Pacer(10.0, clock=clock, sleep=clock.sleep)
        plan = Plan(main=[[passage(f"p#{index}", "x" * 400) for index in range(64)]])
        try:
            report = plan.run(FakeEmbedder(), deadline=30, clock=clock, pacer=pacer)
            rows = read(plan.root / "load-0000.ndjson")
            self.assertEqual(len(rows), 64)
            self.assertEqual(report["reason"], "deadline reached")
            self.assertEqual(report["counts"]["embedded"], 4)
            self.assertEqual(report["counts"]["skipped"], 60)
        finally:
            plan.close()

    def test_heal_rows_that_got_a_vector_are_kept(self):
        plan = Plan(heal=[[passage("old#0", "old text"), note("forge/x", "adr")]])
        try:
            report = plan.run(FakeEmbedder())
            self.assertEqual(len(read(plan.root / "heal-0000.ndjson")), 2)
            self.assertEqual(report["counts"]["healed"], 2)
        finally:
            plan.close()

    def test_an_unknown_writer_is_refused(self):
        plan = Plan(writer="someone")
        try:
            with self.assertRaises(SystemExit):
                plan.run(FakeEmbedder())
        finally:
            plan.close()


class Pacing(unittest.TestCase):
    def test_pacer_holds_the_token_rate(self):
        clock = FakeClock()
        pacer = embed_step.Pacer(300.0, clock=clock, sleep=clock.sleep)
        for _ in range(10):
            pacer.spend(600)
        self.assertAlmostEqual(clock.now - 1000.0, 20.0, places=6)
        self.assertAlmostEqual(pacer.paused, 20.0, places=6)

    def test_the_embed_step_spends_real_usage_on_the_pacer(self):
        clock = FakeClock()
        pacer = embed_step.Pacer(100.0, clock=clock, sleep=clock.sleep)
        plan = Plan(main=[[passage(f"p#{index}", "y" * 400) for index in range(32)]])
        try:
            plan.run(FakeEmbedder(), clock=clock, pacer=pacer)
            self.assertGreaterEqual(clock.now - 1000.0, 32 * 420 / 4 / 100.0 - 1)
        finally:
            plan.close()


class Server:
    def __init__(self, handler):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def litellm_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            state["requests"].append((self.path, self.headers.get("Authorization"), body))
            status = state["statuses"].pop(0) if state["statuses"] else 200
            if status != 200:
                self.send_response(status)
                if status == 429:
                    self.send_header("retry-after", "0")
                self.end_headers()
                return
            data = [{"index": index, "embedding": fake_vector(text)} for index, text in enumerate(body["input"])]
            payload = json.dumps({"data": list(reversed(data)), "usage": {"prompt_tokens": 7}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
    return Handler


class LiteLLMClient(unittest.TestCase):
    def setUp(self):
        self.state = {"requests": [], "statuses": []}
        self.server = Server(litellm_handler(self.state))
        self.contract = embed_step.Contract.load(CONTRACT)
        self.embedder = embed_step.LiteLLMEmbedder(self.server.url, "sk-embed", self.contract, sleep=lambda seconds: None)

    def tearDown(self):
        self.server.close()

    def test_request_carries_model_dimensions_key_and_orders_by_index(self):
        vectors, tokens = self.embedder(["type: Note\ncontent: a", "type: Note\ncontent: bb"])
        path, auth, body = self.state["requests"][0]
        self.assertEqual((path, auth), ("/v1/embeddings", "Bearer sk-embed"))
        self.assertEqual((body["model"], body["dimensions"]), (self.contract.model, 384))
        self.assertEqual(vectors[1], fake_vector("type: Note\ncontent: bb"))
        self.assertEqual(tokens, 7)

    def test_one_throttle_is_waited_out(self):
        self.state["statuses"] = [429]
        vectors, _ = self.embedder(["type: Note\ncontent: a"])
        self.assertEqual(len(vectors), 1)
        self.assertEqual(len(self.state["requests"]), 2)

    def test_server_errors_make_the_embedding_unavailable(self):
        self.state["statuses"] = [500]
        with self.assertRaises(embed_step.EmbeddingUnavailable):
            self.embedder(["type: Note\ncontent: a"])


class Report(unittest.TestCase):
    def test_metrics_are_pushed_with_writer_and_type_labels_only(self):
        pushed = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                pushed.append((self.path, self.rfile.read(int(self.headers["content-length"])).decode()))
                self.send_response(204)
                self.end_headers()

        server = Server(Handler)
        plan = Plan(main=[[passage("obsidian-file/private-title#0", "secret sentence about a person")]], writer="vault-import")
        try:
            plan.run(FakeEmbedder())
            self.assertEqual(embed_step.report(SimpleNamespace(plan=str(plan.root), vmagent_url=server.url)), 0)
            path, text = pushed[0]
            self.assertEqual(path, "/api/v1/import/prometheus?extra_label=job=omnigraph-embed-step")
            self.assertIn('omnigraph_embed_rows_missing{type="Passage",writer="vault-import"} 0', text)
            self.assertIn('omnigraph_embed_run_rows{outcome="embedded",writer="vault-import"} 1', text)
            self.assertNotIn("private", text)
            self.assertNotIn("secret", text)
        finally:
            plan.close()
            server.close()

    def test_an_unreachable_vmagent_never_fails_the_import(self):
        plan = Plan(main=[[passage("p#0", "text")]])
        try:
            plan.run(FakeEmbedder())
            self.assertEqual(embed_step.report(SimpleNamespace(plan=str(plan.root), vmagent_url="http://127.0.0.1:9")), 0)
        finally:
            plan.close()


class WriteRetry(unittest.TestCase):
    def run_helper(self, outcomes, attempts=8):
        with tempfile.TemporaryDirectory() as scratch:
            fake = Path(scratch, "fake-omnigraph")
            state = Path(scratch, "calls")
            fake.write_text("#!/bin/sh\n"
                            f"n=$(cat {state} 2>/dev/null || echo 0); n=$((n + 1)); echo $n > {state}\n"
                            f"line=$(sed -n \"${{n}}p\" {scratch}/outcomes)\n"
                            "[ \"$line\" = ok ] && exit 0\n"
                            "echo \"error: $line\" >&2; exit 1\n", encoding="utf-8")
            fake.chmod(0o755)
            Path(scratch, "outcomes").write_text("\n".join(outcomes) + "\n", encoding="utf-8")
            script = (f". {WRITE_HELPER}\n"
                      f"if omnigraph_write {fake}; then echo \"ok retries=$omnigraph_write_retries\"; "
                      "else echo \"failed class=$omnigraph_write_failure retries=$omnigraph_write_retries\"; fi\n")
            env = dict(os.environ, OMNIGRAPH_WRITE_FIRST_DELAY="0.01", OMNIGRAPH_WRITE_ATTEMPTS=str(attempts), TMPDIR=scratch)
            result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env, timeout=60)
            calls = int(state.read_text()) if state.exists() else 0
            return result.stdout.strip(), calls

    def test_read_set_conflicts_are_retried_until_the_write_lands(self):
        self.assertEqual(self.run_helper(["409 read_set_conflict", "409 read_set_conflict", "ok"]), ("ok retries=2", 3))

    def test_key_conflicts_are_never_retried(self):
        self.assertEqual(self.run_helper(["409 key_conflict", "ok"]), ("failed class=key_conflict retries=0", 1))

    def test_recovery_required_fails_at_once(self):
        self.assertEqual(self.run_helper(["HTTP 503 recovery required", "ok"]), ("failed class=recovery_required retries=0", 1))

    def test_retries_stop_at_the_attempt_limit(self):
        self.assertEqual(self.run_helper(["409 read_set_conflict"] * 5, attempts=3), ("failed class=read_set_conflict retries=2", 3))


if __name__ == "__main__":
    unittest.main(verbosity=1)
