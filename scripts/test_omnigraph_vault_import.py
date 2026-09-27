#!/usr/bin/env python3
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMPORTER = ROOT / "kubernetes/apps/ai/omnigraph/vault-import/app/vault_import.py"
BRAIN_SCHEMA = ROOT / "kubernetes/apps/ai/omnigraph/app/bundle/brain.pg"
NOW = "2026-09-27T12:00:00Z"

spec = importlib.util.spec_from_file_location("vault_import", IMPORTER)
vault_import = importlib.util.module_from_spec(spec)
sys.modules["vault_import"] = vault_import
spec.loader.exec_module(vault_import)


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
        self.notes = self.root / "notes.json"
        self.notes.write_text(graph_output(list(graph_notes)), encoding="utf-8")
        self.links = self.root / "links.json"
        self.links.write_text(graph_output(list(graph_links)), encoding="utf-8")
        self.out = self.root / "out"

    def args(self):
        return vault_import.parse_args([
            "--vault", str(self.vault), "--client-terms-file", str(self.terms),
            "--graph-notes", str(self.notes), "--graph-links", str(self.links), "--out", str(self.out)])

    def plan(self):
        return vault_import.run(self.args(), NOW)

    def load_rows(self):
        rows = []
        for path in sorted(self.out.glob("load-*.ndjson")):
            rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
        return rows

    def prune(self):
        path = self.out / "prune.gq"
        return path.read_text(encoding="utf-8") if path.exists() else ""

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


class ClientFilter(unittest.TestCase):
    def test_client_notes_are_withheld_and_previously_imported_ones_deleted(self):
        fixture = VaultFixture({
            "Work/Kickoff.md": "Call with ACME corp about the rollout.",
            "Work/client-x.example notes.md": "Domain in the path only.",
            "Personal/Acmeville trip.md": "Not a client: acme corporation is a different word boundary.",
            "Personal/Links.md": "See [[Kickoff]].",
        }, graph_notes=[graph_note("obsidian/work/kickoff", "Kickoff", content="old")])
        try:
            plan = fixture.plan()
            nodes = nodes_by_slug(fixture.load_rows())
            self.assertEqual(plan.counts.withheld_client, 2)
            self.assertEqual(sorted(nodes), ["obsidian/personal/acmeville-trip", "obsidian/personal/links"])
            self.assertIn('delete Note where slug = "obsidian/work/kickoff"', fixture.prune())
            self.assertEqual(edges(fixture.load_rows()), [])
        finally:
            fixture.close()

    def test_output_never_contains_client_terms(self):
        fixture = VaultFixture({"Kickoff.md": "Acme Corp budget", "Other.md": "fine"})
        try:
            fixture.plan()
            written = "".join(path.read_text(encoding="utf-8") for path in fixture.out.iterdir())
            self.assertNotIn("acme", written.lower())
        finally:
            fixture.close()


class FailClosed(unittest.TestCase):
    def assert_refused(self, terms):
        fixture = VaultFixture({"Note.md": "anything"}, terms=terms)
        try:
            with self.assertRaises(vault_import.FailClosed) as raised:
                fixture.plan()
            self.assertEqual(raised.exception.exit_code, vault_import.EXIT_NO_CLIENT_TERMS)
            self.assertFalse(fixture.out.exists())
            self.assertEqual(vault_import.main([
                "--vault", str(fixture.vault), "--client-terms-file", str(fixture.terms),
                "--graph-notes", str(fixture.notes), "--graph-links", str(fixture.links), "--out", str(fixture.out)]),
                vault_import.EXIT_NO_CLIENT_TERMS)
            self.assertFalse(fixture.out.exists())
        finally:
            fixture.close()

    def test_missing_terms_secret_imports_nothing(self):
        self.assert_refused(None)

    def test_zero_terms_imports_nothing(self):
        self.assert_refused("\n  \n")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
