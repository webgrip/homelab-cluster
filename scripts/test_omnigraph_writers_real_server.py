#!/usr/bin/env python3
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
OMNIGRAPH = ROOT / "kubernetes/apps/ai/omnigraph"
EMBED_APP = OMNIGRAPH / "embed-step/app"
VAULT_APP = OMNIGRAPH / "vault-import/app"
FORGE_APP = OMNIGRAPH / "forge-import/app"
NOW = "2026-09-30T08:00:00Z"
LATER = "2026-09-30T08:15:00Z"
LONG_NOTE = ("---\ntitle: Garden plan\n---\nIntro about the garden and why it matters to the household this year.\n\n"
             "## Soil\n\n" + "\n\n".join(f"Soil paragraph {index} " + "loam " * 60 for index in range(4)) + "\n\n"
             "## Watering\n\n" + "Water deeply twice a week in summer. " * 20 + "\n")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


embed_step = load("embed_step", EMBED_APP / "embed_step.py")
vault_import = load("vault_import", VAULT_APP / "vault_import.py")
forge_import = load("forge_import", FORGE_APP / "forge_import.py")


class UnitEmbedder:
    def __call__(self, texts):
        return [[((index * 31 + len(text)) % 17 - 8) / 8.0 + 0.01 for index in range(384)] for text in texts], len(texts)


def pod_script(source, sandbox, app_mount):
    text = source.read_text(encoding="utf-8")
    for old, new in ((app_mount, str(sandbox / "app")), ("/etc/omnigraph-embed-step/", f"{EMBED_APP}/"), ("/run/secrets/omnigraph/token", str(sandbox / "token")),
                     ("/work/", f"{sandbox}/work/"), ("/tmp/vector-probe.json", str(sandbox / "vector-probe.json"))):
        text = text.replace(old, new)
    path = sandbox / source.name
    path.write_text(text, encoding="utf-8")
    return path


@unittest.skipUnless(os.environ.get("OMNIGRAPH_WRITERS_REAL_SERVER") == "1", "needs the pinned omnigraph and omnigraph-server on PATH (set OMNIGRAPH_WRITERS_REAL_SERVER=1)")
class RealServerWriters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "scripts"))
        rehearsal = importlib.import_module("omnigraph_rehearsal")
        cls.scratch = tempfile.TemporaryDirectory(prefix="omnigraph-writers-real-")
        workdir = Path(cls.scratch.name)
        rendered = rehearsal.kustomize(ROOT / rehearsal.APP_PATH, "working")
        bundle = rehearsal.Bundle(rendered.bundle_files(), "working")
        init_env = rendered.plain_env(rehearsal.INIT_CONTAINER, init=True)
        cls.embedder = rehearsal.FakeEmbedder(init_env.get("OMNIGRAPH_EMBED_MODEL", "x"))
        embed_url = cls.embedder.start()
        (workdir / "cluster").mkdir()
        cluster = rehearsal.Rehearsal(workdir / "cluster", embed_url, init_env.get("OMNIGRAPH_OPERATOR_ACTOR", "act-gitops"))
        cluster.bootstrap(bundle, rendered, "first")
        cluster.load("brain", rehearsal.seed_rows(bundle.schema("brain")), "seed")
        bundle_dir, _, _ = cluster.bootstrap(bundle, rendered, "second")
        cls.tokens = {actor: f"token-{actor}" for actor in bundle.policy_actors()}
        env = {"PATH": os.environ["PATH"], "HOME": str(workdir), **rendered.plain_env(rehearsal.SERVER_CONTAINER), "OMNIGRAPH_EMBED_API_KEY": "x"}
        cls.server = rehearsal.Server(bundle_dir, cls.tokens, env, workdir / "cluster")
        cls.server.wait_ready(len(bundle.graphs()), 180)
        cls.workdir = workdir

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.embedder.stop()
        cls.scratch.cleanup()

    def sandbox(self, name, actor, app_dir, app_mount):
        sandbox = self.workdir / name
        (sandbox / "work").mkdir(parents=True)
        (sandbox / "app").symlink_to(app_dir)
        (sandbox / "token").write_text(self.tokens[actor], encoding="utf-8")
        scripts = {script: pod_script(app_dir / script, sandbox, app_mount) for script in ("snapshot.sh", "apply.sh")}
        return sandbox, scripts

    def sh(self, script, sandbox):
        env = {"PATH": os.environ["PATH"], "HOME": str(sandbox), "TMPDIR": str(sandbox), "OMNIGRAPH_URL": self.server.base, "NO_COLOR": "1"}
        return subprocess.run(["sh", str(script)], capture_output=True, text=True, env=env, timeout=300)

    def fresh_plan_dir(self, sandbox):
        plan = sandbox / "work" / "plan"
        if plan.exists():
            for path in plan.iterdir():
                path.unlink()
        return plan

    def rows(self, sandbox, name):
        return json.loads((sandbox / "work" / "snapshot" / f"{name}.json").read_text(encoding="utf-8")).get("rows", [])

    def vault_cycle(self, sandbox, scripts, vault, now):
        snapshot = self.sh(scripts["snapshot.sh"], sandbox)
        self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
        plan_dir = self.fresh_plan_dir(sandbox)
        args = vault_import.parse_args(["--vault", str(vault), "--client-terms-file", str(sandbox / "no-terms"),
                                        "--snapshot-dir", str(sandbox / "work" / "snapshot"), "--out", str(plan_dir)])
        plan = vault_import.run(args, now)
        embed_step.embed(SimpleNamespace(plan=str(plan_dir), contract=str(EMBED_APP / "contract.json"), litellm_url="x", key_file="/nonexistent",
                                         tokens_per_second=1e9, deadline_seconds=600), embedder=UnitEmbedder())
        applied = self.sh(scripts["apply.sh"], sandbox)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        return plan, applied

    def test_vault_import_chunks_embeds_is_idempotent_and_prunes_a_rename_on_the_pinned_server(self):
        sandbox, scripts = self.sandbox("vault", "act-vault-import", VAULT_APP, "/etc/vault-import")
        vault = sandbox / "vault"
        vault.mkdir()
        (vault / "Garden.md").write_text(LONG_NOTE, encoding="utf-8")
        (vault / "Idea.md").write_text("A short idea.", encoding="utf-8")
        plan, _ = self.vault_cycle(sandbox, scripts, vault, NOW)
        self.assertGreater(plan.counts.passages_written, 3)
        self.sh(scripts["snapshot.sh"], sandbox)
        passages = {row["p.@id"] for row in self.rows(sandbox, "vault_passages")}
        self.assertEqual(len(passages), plan.counts.passages_written)
        self.assertEqual({row["p.@id"] for row in self.rows(sandbox, "vault_passages_with_vectors")}, passages)
        self.assertIn("obsidian/garden", {row["n.slug"] for row in self.rows(sandbox, "vault_notes_with_vectors")})
        self.assertEqual([(row["n.slug"], row["a.slug"]) for row in self.rows(sandbox, "vault_note_artifacts")], [("obsidian/garden", "obsidian-file/garden")])
        again, applied = self.vault_cycle(sandbox, scripts, vault, LATER)
        self.assertEqual((again.node_rows, again.passage_units, again.edge_rows, again.prune_statements, again.heal_rows), ([], [], [], [], []))
        self.assertIn("load_batches=0", applied.stdout)
        (vault / "Garden.md").rename(vault / "Tuin.md")
        renamed, _ = self.vault_cycle(sandbox, scripts, vault, LATER)
        self.assertEqual(renamed.counts.deleted, 1)
        self.sh(scripts["snapshot.sh"], sandbox)
        remaining = {row["a.slug"] for row in self.rows(sandbox, "vault_passages")}
        self.assertEqual(remaining, {"obsidian-file/tuin"})
        self.assertEqual({row["a.slug"] for row in self.rows(sandbox, "vault_shadow_artifacts")}, {"obsidian-file/tuin"})
        incomplete = sorted(row["p.@id"] for row in self.rows(sandbox, "vault_passages"))[1:]
        prune = self.fresh_plan_dir(sandbox) / "prune-0000.gq"
        body = "\n".join([f'    delete Passage where @id = "{pid}"' for pid in incomplete] + ['    delete Artifact where slug = "obsidian-file/tuin"'])
        prune.write_text(f"query vault_prune() {{\n{body}\n}}\n", encoding="utf-8")
        refused = self.sh(scripts["apply.sh"], sandbox)
        self.assertNotEqual(refused.returncode, 0)
        self.sh(scripts["snapshot.sh"], sandbox)
        self.assertEqual({row["a.slug"] for row in self.rows(sandbox, "vault_shadow_artifacts")}, {"obsidian-file/tuin"})

    def test_forge_snapshot_chunk_reader_and_a_node_only_heal_keep_the_passage_edge(self):
        sandbox, scripts = self.sandbox("forge", "act-forge-import", FORGE_APP, "/etc/forge-import")
        snapshot = self.sh(scripts["snapshot.sh"], sandbox)
        self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
        for name in ("forge_passages", "forge_passages_with_vectors", "forge_notes_with_vectors", "forge_notes"):
            self.assertTrue((sandbox / "work" / "snapshot" / f"{name}.json").exists(), name)
        reader = forge_import.ChunkReader(self.server.base, self.tokens["act-forge-import"])
        artifact = "r-artifact-0"
        chunks = reader.fetch(artifact)
        self.assertTrue(chunks)
        pid, chunk = sorted(chunks.items())[0]
        self.assertTrue(chunk["text"] and chunk["createdAt"])
        plan_dir = self.fresh_plan_dir(sandbox)
        plan_dir.mkdir(parents=True, exist_ok=True)
        heal = {"type": "Passage", "id": pid, "data": {"text": chunk["text"], "chunk_index": chunk["chunk_index"], "createdAt": chunk["createdAt"]}}
        (plan_dir / "heal-0000.ndjson").write_text(json.dumps(heal) + "\n", encoding="utf-8")
        (plan_dir / "embed-plan.json").write_text(json.dumps({"writer": "forge-import", "missing": [], "heal_since": {}}), encoding="utf-8")
        embed_step.embed(SimpleNamespace(plan=str(plan_dir), contract=str(EMBED_APP / "contract.json"), litellm_url="x", key_file="/nonexistent",
                                         tokens_per_second=1e9, deadline_seconds=600), embedder=UnitEmbedder())
        applied = self.sh(scripts["apply.sh"], sandbox)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        self.assertIn("heal_batches=1", applied.stdout)
        self.assertIn(pid, forge_import.ChunkReader(self.server.base, self.tokens["act-forge-import"]).fetch(artifact))


if __name__ == "__main__":
    unittest.main(verbosity=1)
