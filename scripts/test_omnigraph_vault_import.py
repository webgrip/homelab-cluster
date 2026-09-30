#!/usr/bin/env python3
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
IMPORTER = ROOT / "kubernetes/apps/ai/omnigraph/vault-import/app/vault_import.py"
BRAIN_SCHEMA = ROOT / "kubernetes/apps/ai/omnigraph/app/bundle/brain.pg"
NOW = "2026-09-27T12:00:00Z"

spec = importlib.util.spec_from_file_location("vault_import", IMPORTER)
vault_import = importlib.util.module_from_spec(spec)
sys.modules["vault_import"] = vault_import
spec.loader.exec_module(vault_import)
EMBED_STEP = ROOT / "kubernetes/apps/ai/omnigraph/embed-step/app/embed_step.py"
CONTRACT = ROOT / "kubernetes/apps/ai/omnigraph/embed-step/app/contract.json"
embed_spec = importlib.util.spec_from_file_location("embed_step", EMBED_STEP)
embed_step = importlib.util.module_from_spec(embed_spec)
sys.modules["embed_step"] = embed_step
embed_spec.loader.exec_module(embed_step)
LATER = "2026-09-27T12:15:00Z"


def graph_output(rows):
    return json.dumps({"rows": rows})


class VaultFixture:
    def __init__(self, files, terms="Acme Corp\nclient-x.example\n", graph_notes=(), graph_links=()):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.vault = self.root / "vault"
        for relpath, text in files.items():
            path = self.vault / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.vault.mkdir(exist_ok=True)
        self.terms = self.root / "terms"
        if terms is not None:
            self.terms.write_text(terms, encoding="utf-8")
        self.snapshot = self.root / "snapshot"
        self.snapshot.mkdir()
        (self.snapshot / "vault_notes.json").write_text(graph_output(list(graph_notes)), encoding="utf-8")
        (self.snapshot / "vault_links.json").write_text(graph_output(list(graph_links)), encoding="utf-8")
        self.out = self.root / "out"

    def args(self):
        return vault_import.parse_args([
            "--vault", str(self.vault), "--client-terms-file", str(self.terms),
            "--snapshot-dir", str(self.snapshot), "--out", str(self.out)])

    def plan(self):
        return vault_import.run(self.args(), NOW)

    def load_rows(self):
        rows = []
        for path in sorted(self.out.glob("load-*.ndjson")):
            rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
        return rows

    def prune(self):
        return "".join(path.read_text(encoding="utf-8") for path in sorted(self.out.glob("prune-*.gq")))

    def close(self):
        self.dir.cleanup()


def graph_note(slug, name, kind="idea", content=None, when=None, tags=None, created="2026-01-01T08:00:00"):
    row = {"n.slug": slug, "n.name": name, "n.kind": kind, "n.createdAt": created}
    row.update({key: value for key, value in (("n.content", content), ("n.when", when), ("n.tags", tags)) if value is not None})
    return row


def nodes_by_slug(rows):
    return {row["data"]["slug"]: row["data"] for row in rows if row.get("type") == "Note"}


def edges(rows):
    return sorted((row["from"], row["to"]) for row in rows if row.get("edge") == "RelatedNote")


class SchemaParity(unittest.TestCase):
    def test_note_kinds_match_brain_schema(self):
        schema = BRAIN_SCHEMA.read_text(encoding="utf-8")
        note_block = schema.split("node Note {", 1)[1].split("}", 1)[0]
        enum_values = re.search(r"kind: enum\(([^)]*)\)", note_block).group(1)
        self.assertEqual(vault_import.NOTE_KINDS, {value.strip() for value in enum_values.split(",")})


class Mapping(unittest.TestCase):
    def setUp(self):
        self.fixture = VaultFixture({
            "Ideas/Bike Chain.md": "---\ntitle: Replace the chain\ntags: [bike, Maintenance]\nkind: decision\ncreated: 2026-05-01T09:30:00+02:00\n---\nDo it before #winter and #bike.\n\n```\n#not-a-tag\n```\nSee [[Tools|my tools]] and [[Ideas/Bike Chain#Parts]] and [[Nowhere]].\n",
            "Tools.md": "---\ntags:\n  - gear\n  - '#bike'\ntype: shopping-list\n---\nA #123 number is not a tag, #chain/links is.\n",
            "2026-09-25.md": "Rode 40km. [[Tools#Pump]]\n",
            "Journal/Evening.md": "---\ndate: 2026-09-20\n---\nQuiet day.\n",
            ".obsidian/workspace.md": "internal",
            ".trash/Old.md": "deleted",
            "Templates/Daily.md": "{{date}}",
            "Large.md": "x" * (vault_import.MAX_NOTE_BYTES + 1),
        })
        self.plan = self.fixture.plan()
        self.nodes = nodes_by_slug(self.fixture.load_rows())

    def tearDown(self):
        self.fixture.close()

    def test_slugs_are_prefixed_lowercase_and_url_safe(self):
        self.assertEqual(sorted(self.nodes), [
            "obsidian/2026-09-25", "obsidian/ideas/bike-chain", "obsidian/journal/evening", "obsidian/tools"])

    def test_frontmatter_title_kind_and_tags_merge_with_inline_tags(self):
        note = self.nodes["obsidian/ideas/bike-chain"]
        self.assertEqual(note["name"], "Replace the chain")
        self.assertEqual(note["kind"], "decision")
        self.assertEqual(note["tags"], ["bike", "maintenance", "winter"])
        self.assertTrue(note["content"].startswith("Do it before"))
        self.assertNotIn("title:", note["content"])
        self.assertEqual(note["createdAt"], "2026-05-01T07:30:00Z")
        self.assertEqual(note["updatedAt"], NOW)

    def test_invalid_kind_falls_back_to_idea_and_numeric_hashes_are_not_tags(self):
        note = self.nodes["obsidian/tools"]
        self.assertEqual(note["kind"], "idea")
        self.assertEqual(note["name"], "Tools")
        self.assertEqual(note["tags"], ["gear", "bike", "chain/links"])

    def test_dated_filename_is_a_journal_entry(self):
        note = self.nodes["obsidian/2026-09-25"]
        self.assertEqual((note["kind"], note["when"]), ("journal", "2026-09-25"))

    def test_daily_folder_is_a_journal_entry_with_frontmatter_date(self):
        note = self.nodes["obsidian/journal/evening"]
        self.assertEqual((note["kind"], note["when"]), ("journal", "2026-09-20"))

    def test_wikilinks_with_alias_and_heading_resolve_to_existing_notes_only(self):
        self.assertEqual(edges(self.fixture.load_rows()), [
            ("obsidian/2026-09-25", "obsidian/tools"),
            ("obsidian/ideas/bike-chain", "obsidian/tools"),
        ])

    def test_hidden_template_and_oversized_files_are_skipped(self):
        self.assertEqual(self.plan.counts.skipped_large, 1)
        self.assertEqual(self.plan.counts.new, 4)
        self.assertEqual(self.fixture.prune(), "")


class ConfiguredFolders(unittest.TestCase):
    def test_daily_notes_and_templates_folders_come_from_obsidian_config(self):
        fixture = VaultFixture({
            ".obsidian/daily-notes.json": json.dumps({"folder": "Log/Days"}),
            ".obsidian/templates.json": json.dumps({"folder": "Meta/Skeletons"}),
            "Log/Days/Monday.md": "Worked.",
            "Meta/Skeletons/Meeting.md": "{{title}}",
        })
        try:
            fixture.plan()
            nodes = nodes_by_slug(fixture.load_rows())
            self.assertEqual(list(nodes), ["obsidian/log/days/monday"])
            self.assertEqual(nodes["obsidian/log/days/monday"]["kind"], "journal")
        finally:
            fixture.close()


class ClientTagging(unittest.TestCase):
    def test_client_notes_are_imported_with_the_client_tag(self):
        fixture = VaultFixture({
            "Work/Kickoff.md": "---\ntags: [meeting]\n---\nCall with ACME corp about the rollout.",
            "Work/client-x.example notes.md": "Domain in the path only.",
            "Personal/Acmeville trip.md": "Not a client: acme corporation is a different word boundary.",
            "Personal/Links.md": "See [[Kickoff]].",
        })
        try:
            plan = fixture.plan()
            nodes = nodes_by_slug(fixture.load_rows())
            self.assertEqual(plan.counts.tagged_client, 2)
            self.assertEqual(sorted(nodes), [
                "obsidian/personal/acmeville-trip", "obsidian/personal/links",
                "obsidian/work/client-x-example-notes", "obsidian/work/kickoff"])
            self.assertEqual(nodes["obsidian/work/kickoff"]["tags"], ["meeting", vault_import.CLIENT_TAG])
            self.assertEqual(nodes["obsidian/work/client-x-example-notes"]["tags"], [vault_import.CLIENT_TAG])
            self.assertNotIn(vault_import.CLIENT_TAG, nodes["obsidian/personal/acmeville-trip"]["tags"] or [])
            self.assertEqual(edges(fixture.load_rows()), [("obsidian/personal/links", "obsidian/work/kickoff")])
        finally:
            fixture.close()

    def test_plan_summary_never_names_a_client_term(self):
        fixture = VaultFixture({"Kickoff.md": "Acme Corp budget", "Other.md": "fine"})
        try:
            self.assertNotIn("acme", fixture.plan().counts.line().lower())
        finally:
            fixture.close()


class WithoutClientTerms(unittest.TestCase):
    def assert_imports_everything_untagged(self, terms):
        fixture = VaultFixture({"Note.md": "Acme Corp anything"}, terms=terms)
        try:
            plan = fixture.plan()
            nodes = nodes_by_slug(fixture.load_rows())
            self.assertEqual(plan.counts.tagged_client, 0)
            self.assertEqual(sorted(nodes), ["obsidian/note"])
            self.assertIsNone(nodes["obsidian/note"]["tags"])
        finally:
            fixture.close()

    def test_missing_terms_secret_imports_everything(self):
        self.assert_imports_everything_untagged(None)

    def test_zero_terms_imports_everything(self):
        self.assert_imports_everything_untagged("\n  \n")

    def test_empty_vault_never_wipes_existing_notes(self):
        fixture = VaultFixture({}, graph_notes=[graph_note("obsidian/a", "A")])
        try:
            with self.assertRaises(vault_import.FailClosed) as raised:
                fixture.plan()
            self.assertEqual(raised.exception.exit_code, vault_import.EXIT_EMPTY_VAULT)
        finally:
            fixture.close()


class Incremental(unittest.TestCase):
    def test_deleted_file_becomes_a_delete_and_unchanged_notes_are_not_reloaded(self):
        fixture = VaultFixture({"Kept.md": "---\ntags: [a]\n---\nsame body\n"}, graph_notes=[
            graph_note("obsidian/kept", "Kept", content="same body", tags=["a"]),
            graph_note("obsidian/removed", "Removed", content="gone"),
            graph_note("obsidian/bad\"slug", "Unsafe"),
        ])
        try:
            plan = fixture.plan()
            self.assertEqual(fixture.load_rows(), [])
            self.assertEqual((plan.counts.unchanged, plan.counts.deleted), (1, 1))
            self.assertEqual(fixture.prune(), 'query vault_prune() {\n    delete Note where slug = "obsidian/removed"\n}\n')
        finally:
            fixture.close()

    def test_changed_note_keeps_its_created_at(self):
        fixture = VaultFixture({"Kept.md": "new body"}, graph_notes=[graph_note("obsidian/kept", "Kept", content="old body")])
        try:
            plan = fixture.plan()
            note = nodes_by_slug(fixture.load_rows())["obsidian/kept"]
            self.assertEqual(plan.counts.updated, 1)
            self.assertEqual((note["createdAt"], note["updatedAt"]), ("2026-01-01T08:00:00Z", NOW))
        finally:
            fixture.close()

    def test_changed_links_are_unlinked_then_reloaded_keeping_foreign_edges(self):
        fixture = VaultFixture({"A.md": "[[C]]", "B.md": "b", "C.md": "c"}, graph_notes=[
            graph_note("obsidian/a", "A", content="[[C]]"), graph_note("obsidian/b", "B", content="b"),
            graph_note("obsidian/c", "C", content="c"),
        ], graph_links=[{"a.slug": "obsidian/a", "b.slug": "obsidian/b"}, {"a.slug": "obsidian/a", "b.slug": "nt-agent-note"}])
        try:
            plan = fixture.plan()
            self.assertEqual(plan.counts.relinked, 1)
            self.assertIn('delete RelatedNote where from = "obsidian/a"', fixture.prune())
            self.assertEqual(edges(fixture.load_rows()), [("obsidian/a", "nt-agent-note"), ("obsidian/a", "obsidian/c")])
        finally:
            fixture.close()

    def test_matching_links_are_left_alone(self):
        fixture = VaultFixture({"A.md": "[[B]]", "B.md": "b"}, graph_notes=[
            graph_note("obsidian/a", "A", content="[[B]]"), graph_note("obsidian/b", "B", content="b"),
        ], graph_links=[{"a.slug": "obsidian/a", "b.slug": "obsidian/b"}])
        try:
            plan = fixture.plan()
            self.assertEqual((plan.counts.relinked, fixture.prune(), fixture.load_rows()), (0, "", []))
        finally:
            fixture.close()

    def test_colliding_slugs_get_distinct_suffixes(self):
        fixture = VaultFixture({"A b.md": "one", "a-b.md": "two"})
        try:
            fixture.plan()
            slugs = sorted(nodes_by_slug(fixture.load_rows()))
            self.assertEqual(len(slugs), 2)
            self.assertTrue(all(slug.startswith("obsidian/a-b-") for slug in slugs))
        finally:
            fixture.close()



class CardViolation(AssertionError):
    pass


class VaultGraph:
    def __init__(self):
        self.notes = {}
        self.artifacts = {}
        self.passages = {}
        self.related = set()
        self.note_artifact = {}
        self.mutations = 0

    def snapshot(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        def put(name, rows):
            (directory / f"{name}.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
        strip = lambda value: value.rstrip("Z") if isinstance(value, str) else value
        put("vault_notes", [{f"n.{key}": strip(value) for key, value in data.items() if key != "embedding"} for data in self.notes.values()])
        put("vault_links", [{"a.slug": source, "b.slug": target} for source, target in sorted(self.related) if source.startswith("obsidian/")])
        put("vault_notes_with_vectors", [{"n.slug": slug} for slug, data in self.notes.items() if data.get("embedding")])
        put("vault_shadow_artifacts", [{"a.slug": slug, "a.content_sha256": data.get("content_sha256"), "a.createdAt": strip(data["createdAt"])}
                                       for slug, data in self.artifacts.items() if slug.startswith("obsidian-file/")])
        put("vault_passages", [{"p.@id": pid, "a.slug": row["to"], "p.chunk_index": row["chunk_index"], "p.text": row["text"], "p.createdAt": strip(row["createdAt"])}
                               for pid, row in self.passages.items() if row["to"].startswith("obsidian-file/")])
        put("vault_passages_with_vectors", [{"p.@id": pid} for pid, row in self.passages.items() if row["to"].startswith("obsidian-file/") and row.get("embedding")])
        put("vault_note_artifacts", [{"n.slug": note, "a.slug": artifact} for note, artifact in self.note_artifact.items()])

    def delete(self, statement):
        passage = re.fullmatch(r'delete Passage where @id = "(.+)"', statement)
        node = re.fullmatch(r'delete (Note|Artifact) where slug = "(.+)"', statement)
        edge = re.fullmatch(r'delete RelatedNote where from = "(.+)"', statement)
        if passage:
            self.passages.pop(passage.group(1))
        elif node and node.group(1) == "Artifact":
            slug = node.group(2)
            if any(row["to"] == slug for row in self.passages.values()):
                raise CardViolation(f"artifact {slug} deleted while passages still point at it")
            self.artifacts.pop(slug)
            self.note_artifact = {key: value for key, value in self.note_artifact.items() if value != slug}
        elif node:
            slug = node.group(2)
            self.notes.pop(slug)
            self.related = {pair for pair in self.related if slug not in pair}
            self.note_artifact.pop(slug, None)
        elif edge:
            self.related = {pair for pair in self.related if pair[0] != edge.group(1)}
        else:
            raise AssertionError(f"unexpected statement {statement}")

    def mutate(self, path):
        statements = re.findall(r"^\s+(delete .+)$", path.read_text(encoding="utf-8"), re.M)
        saved = (dict(self.notes), dict(self.artifacts), dict(self.passages), set(self.related), dict(self.note_artifact))
        try:
            for statement in statements:
                self.delete(statement)
            orphans = [pid for pid, row in self.passages.items() if row["to"] not in self.artifacts]
            if orphans:
                raise CardViolation(f"passages left without their artifact: {orphans}")
        except CardViolation:
            self.notes, self.artifacts, self.passages, self.related, self.note_artifact = saved
            raise
        self.mutations += 1

    def load(self, row):
        if row.get("type") == "Note":
            self.notes[row["data"]["slug"]] = dict(row["data"])
        elif row.get("type") == "Artifact":
            self.artifacts[row["data"]["slug"]] = dict(row["data"])
        elif row.get("type") == "Passage":
            existing = self.passages.get(row["id"], {})
            self.passages[row["id"]] = dict(row["data"], to=existing.get("to"))
        elif row["edge"] == "PassageOf":
            if self.passages[row["from"]].get("to"):
                raise AssertionError(f"@unique violation on PassageOf for {row['from']}")
            assert row["to"] in self.artifacts, row
            self.passages[row["from"]]["to"] = row["to"]
        elif row["edge"] == "NoteFromArtifact":
            assert row["from"] in self.notes and row["to"] in self.artifacts, row
            if row["from"] in self.note_artifact:
                raise CardViolation(f"second NoteFromArtifact for {row['from']}")
            self.note_artifact[row["from"]] = row["to"]
        else:
            assert row["from"] in self.notes, row
            self.related.add((row["from"], row["to"]))

    def apply(self, out):
        for path in sorted(out.glob("prune-*.gq")):
            self.mutate(path)
        for pattern in ("load-*.ndjson", "heal-*.ndjson"):
            for path in sorted(out.glob(pattern)):
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
                for row in rows:
                    self.load(row)
                dangling = [pid for pid, row in self.passages.items() if not row.get("to")]
                assert not dangling, f"passages without PassageOf after {path.name}: {dangling}"


class Embedder:
    def __init__(self, fail=False):
        self.texts = []
        self.fail = fail

    def __call__(self, texts):
        if self.fail:
            raise embed_step.EmbeddingUnavailable("litellm answered HTTP 503")
        self.texts.extend(texts)
        return [[0.0, 1.0] + [0.0] * 382 for _ in texts], len(texts)


class VaultRun:
    def __init__(self, files):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.write(files)
        self.graph = VaultGraph()
        self.embedder = Embedder()
        self.runs = 0

    def write(self, files):
        for relpath, text in files.items():
            path = self.vault / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def remove(self, relpath):
        (self.vault / relpath).unlink()

    def run(self, now=NOW, apply=True):
        self.runs += 1
        snapshot = self.root / f"snapshot-{self.runs}"
        self.graph.snapshot(snapshot)
        self.out = self.root / f"plan-{self.runs}"
        args = vault_import.parse_args(["--vault", str(self.vault), "--client-terms-file", str(self.root / "no-terms"),
                                        "--snapshot-dir", str(snapshot), "--out", str(self.out)])
        plan = vault_import.run(args, now)
        embed_args = SimpleNamespace(plan=str(self.out), contract=str(CONTRACT), litellm_url="http://unused", key_file="/nonexistent",
                                     tokens_per_second=1e9, deadline_seconds=600)
        self.report = embed_step.embed(embed_args, embedder=self.embedder)
        if apply:
            self.graph.apply(self.out)
        return plan

    def written(self):
        rows = []
        for path in sorted(self.out.glob("load-*.ndjson")):
            rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip())
        return rows

    def chunks_of(self, shadow):
        return sorted(((row["chunk_index"], row["text"]) for row in self.graph.passages.values() if row["to"] == shadow))

    def vectorless(self):
        return sorted([pid for pid, row in self.graph.passages.items() if not row.get("embedding")] +
                      [slug for slug, data in self.graph.notes.items() if data.get("content") and not data.get("embedding")])

    def close(self):
        self.dir.cleanup()


LONG_NOTE = ("---\ntitle: Garden plan\n---\nIntro about the garden and why it matters to the household this year.\n\n"
             "## Soil\n\n" + "\n\n".join(f"Soil paragraph {index} " + "loam " * 60 for index in range(4)) + "\n\n"
             "## Watering\n\n```\n# not a heading inside code\n```\n\n" + "Water deeply twice a week in summer. " * 20 + "\n")
SHADOW = "obsidian-file/garden"
NOTE = "obsidian/garden"


class ObsidianChunks(unittest.TestCase):
    def setUp(self):
        self.run = VaultRun({"Garden.md": LONG_NOTE, "Tiny.md": "too short to chunk"})
        self.plan = self.run.run()

    def tearDown(self):
        self.run.close()

    def test_a_long_note_becomes_a_shadow_artifact_with_heading_chunks_linked_to_its_note(self):
        shadow = self.run.graph.artifacts[SHADOW]
        self.assertEqual((shadow["kind"], shadow["source"], shadow.get("content")), ("document", "notes-app", None))
        self.assertEqual(self.run.graph.note_artifact[NOTE], SHADOW)
        chunks = self.run.chunks_of(SHADOW)
        self.assertEqual([index for index, _ in chunks], list(range(len(chunks))))
        firsts = [text.split("\n", 1)[0] for _, text in chunks]
        self.assertEqual(firsts[0], "Garden plan")
        self.assertIn("Garden plan \u203a Soil", firsts)
        self.assertTrue([text for _, text in chunks if "\nWatering\n" in text])
        self.assertTrue([text for _, text in chunks if "# not a heading inside code" in text])
        self.assertTrue(all(len(text) <= vault_import.CHUNK_CHARS for _, text in chunks))
        self.assertGreaterEqual(len(chunks), 3)

    def test_notes_under_80_characters_get_no_chunks(self):
        self.assertNotIn("obsidian-file/tiny", self.run.graph.artifacts)
        self.assertIn("obsidian/tiny", self.run.graph.notes)

    def test_every_note_and_passage_is_written_with_a_384_float_vector(self):
        self.assertEqual(self.run.vectorless(), [])
        self.assertEqual(len(self.run.graph.notes[NOTE]["embedding"]), 384)
        self.assertEqual(self.run.report["missing"], {"Note": 0, "Passage": 0})

    def test_a_second_run_writes_and_embeds_nothing(self):
        self.run.embedder.texts.clear()
        plan = self.run.run(LATER)
        self.assertEqual((self.run.written(), plan.prune_statements, self.run.embedder.texts), ([], [], []))
        self.assertEqual(plan.counts.unchanged_chunks, len(self.run.chunks_of(SHADOW)))

    def test_an_edited_paragraph_rewrites_only_its_chunk(self):
        before = dict(self.run.graph.passages)
        self.run.write({"Garden.md": LONG_NOTE.replace("Soil paragraph 3 ", "Soil paragraph three ")})
        plan = self.run.run(LATER)
        rewritten = [unit[0]["id"] for unit in plan.passage_units]
        self.assertEqual(len(rewritten), 1)
        self.assertIn("Soil paragraph three", self.run.graph.passages[rewritten[0]]["text"])
        for pid in set(before) - set(rewritten):
            self.assertEqual(self.run.graph.passages[pid], before[pid])
        self.assertEqual([row["data"]["slug"] for row in self.run.written() if row.get("type") == "Artifact"], [SHADOW])
        self.assertEqual(self.run.vectorless(), [])

    def test_a_rename_prunes_every_chunk_the_shadow_and_the_note_in_one_mutation(self):
        old_chunks = [pid for pid in self.run.graph.passages if pid.startswith(SHADOW + "#")]
        self.run.remove("Garden.md")
        self.run.write({"Tuin.md": LONG_NOTE})
        mutations = self.run.graph.mutations
        plan = self.run.run(LATER)
        self.assertEqual(len(list(self.run.out.glob("prune-*.gq"))), 1)
        self.assertEqual(self.run.graph.mutations, mutations + 1)
        for pid in old_chunks:
            self.assertIn(f'delete Passage where @id = "{pid}"', plan.prune_statements)
        self.assertNotIn(SHADOW, self.run.graph.artifacts)
        self.assertNotIn(NOTE, self.run.graph.notes)
        self.assertEqual(self.run.graph.note_artifact["obsidian/tuin"], "obsidian-file/tuin")
        self.assertFalse([pid for pid in self.run.graph.passages if pid.startswith(SHADOW)])

    def test_a_partially_chunked_note_is_pruned_completely(self):
        self.run.graph.passages[SHADOW + "#40"] = {"text": "leftover chunk from an older layout", "chunk_index": 40, "createdAt": NOW, "to": SHADOW}
        del self.run.graph.passages[SHADOW + "#1"]
        self.run.remove("Garden.md")
        self.run.run(LATER)
        self.assertFalse([pid for pid in self.run.graph.passages if pid.startswith(SHADOW)])
        self.assertNotIn(SHADOW, self.run.graph.artifacts)

    def test_an_orphaned_shadow_is_pruned_even_when_its_note_is_already_gone(self):
        self.run.graph.delete(f'delete Note where slug = "{NOTE}"')
        self.run.remove("Garden.md")
        self.run.run(LATER)
        self.assertNotIn(SHADOW, self.run.graph.artifacts)
        self.assertFalse([pid for pid in self.run.graph.passages if pid.startswith(SHADOW)])

    def test_a_note_shrunk_below_80_characters_loses_its_chunks(self):
        self.run.write({"Garden.md": "Now tiny."})
        self.run.run(LATER)
        self.assertNotIn(SHADOW, self.run.graph.artifacts)
        self.assertFalse([pid for pid in self.run.graph.passages if pid.startswith(SHADOW)])
        self.assertIn(NOTE, self.run.graph.notes)

    def test_a_note_that_already_comes_from_another_artifact_is_not_relinked(self):
        self.run.write({"Other.md": LONG_NOTE.replace("Garden plan", "Other plan")})
        self.run.graph.notes["obsidian/other"] = {"slug": "obsidian/other", "name": "Other plan", "kind": "idea", "content": None,
                                                  "createdAt": NOW, "updatedAt": NOW}
        self.run.graph.artifacts["art-scan"] = {"slug": "art-scan", "createdAt": NOW}
        self.run.graph.note_artifact["obsidian/other"] = "art-scan"
        plan = self.run.run(LATER)
        self.assertEqual(plan.counts.link_conflicts, 1)
        self.assertEqual(self.run.graph.note_artifact["obsidian/other"], "art-scan")


class ChunkShape(unittest.TestCase):
    def test_short_sections_share_a_chunk_under_the_first_heading(self):
        body = "\n\n".join(f"## Part {index}\n\nShort text {index}." for index in range(6))
        chunks = vault_import.chunk_note("Notes", "Opening line of the note that is long enough to be chunked on its own.\n\n" + body)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("Notes\nOpening line"))
        self.assertEqual(re.findall(r"^Part \d$", chunks[0], re.M), [f"Part {index}" for index in range(6)])

    def test_a_section_that_does_not_fit_starts_its_own_chunk_with_its_heading(self):
        chunks = vault_import.chunk_note("Notes", "Intro text that is long enough to be chunked on its own, really.\n\n## Big\n\n" + "word " * 400)
        self.assertEqual([chunk.split("\n", 1)[0] for chunk in chunks][:2], ["Notes", "Notes \u203a Big"])

    def test_long_titles_and_unbroken_text_stay_within_the_chunk_limit(self):
        chunks = vault_import.chunk_note("T" * 1500, "x" * 5000 + "\n\n# " + "H" * 900 + "\n\n" + "word " * 900)
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= vault_import.CHUNK_CHARS for chunk in chunks))

    def test_text_is_kept_in_order_and_complete(self):
        body = "\n\n".join(f"para{index} " + "abc " * 50 for index in range(30))
        chunks = vault_import.chunk_note("Title", body)
        rebuilt = " ".join(chunk.split("\n", 1)[1] for chunk in chunks)
        self.assertEqual(re.findall(r"para\d+", rebuilt), [f"para{index}" for index in range(30)])


class ChunkBudgetAndHeal(unittest.TestCase):
    def test_at_most_the_per_run_cap_of_notes_is_chunked_and_the_rest_follows(self):
        files = {f"Note {index}.md": LONG_NOTE.replace("Garden plan", f"Plan {index}") for index in range(5)}
        run = VaultRun(files)
        saved = vault_import.NOTES_CHUNKED_PER_RUN
        vault_import.NOTES_CHUNKED_PER_RUN = 2
        try:
            plan = run.run()
            self.assertEqual((plan.counts.chunked_notes, plan.counts.chunk_deferred), (2, 3))
            run.run(LATER)
            plan = run.run(LATER)
            self.assertEqual((plan.counts.chunked_notes, plan.counts.chunk_deferred), (1, 0))
            self.assertEqual(len([slug for slug in run.graph.artifacts if slug.startswith("obsidian-file/")]), 5)
        finally:
            vault_import.NOTES_CHUNKED_PER_RUN = saved
            run.close()

    def test_vectorless_notes_and_passages_are_healed_with_their_stored_text(self):
        run = VaultRun({"Garden.md": LONG_NOTE, "Idea.md": "A short idea that still has text."})
        try:
            run.embedder.fail = True
            run.run()
            missing = run.vectorless()
            self.assertIn(NOTE, missing)
            self.assertEqual(run.report["missing"]["Passage"], len(run.chunks_of(SHADOW)))
            saved = vault_import.HEAL_ROWS_PER_RUN
            vault_import.HEAL_ROWS_PER_RUN = 2
            run.embedder.fail = False
            try:
                plan = run.run(LATER)
                self.assertEqual((plan.node_rows, plan.passage_units, plan.heal_rows[0]["type"] in ("Note", "Passage")), ([], [], True))
                self.assertEqual(len(run.vectorless()), len(missing) - 2)
                self.assertEqual(run.graph.notes[NOTE]["updatedAt"], NOW)
            finally:
                vault_import.HEAL_ROWS_PER_RUN = saved
            run.run(LATER)
            self.assertEqual(run.vectorless(), [])
        finally:
            run.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
