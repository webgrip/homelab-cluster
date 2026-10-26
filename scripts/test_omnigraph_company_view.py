#!/usr/bin/env python3
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "kubernetes/apps/ai/omnigraph/company-view/app"
DEFAULT_TIERS = APP / "default-tiers.json"

spec = importlib.util.spec_from_file_location("company_view", APP / "company_view.py")
company_view = importlib.util.module_from_spec(spec)
sys.modules["company_view"] = company_view
spec.loader.exec_module(company_view)


def project(full_name, status="active", description=None):
    return {"p.slug": "forge/" + full_name, "p.name": full_name, "p.status": status, "p.brief": None, "p.description": description}


def brain(projects, artifacts=(), records=(), topics=(), topic_sources=None, record_urls=None):
    return company_view.Brain(
        projects=list(projects),
        artifact_projects={f"forge/{full_name}/readme": f"forge/{full_name}" for full_name in artifacts},
        records=[{"n.slug": f"forge/{full_name}/adr/{name}", "n.name": name, "n.content": f"{name} text", "n.when": "2026-01-02", "p.slug": f"forge/{full_name}"}
                 for full_name, name in records],
        record_urls=record_urls or {},
        topics={slug: {"t.slug": slug, "t.name": slug.rsplit("/", 1)[-1], "t.description": None, "t.aliases": []} for slug in topics},
        topic_sources={slug: set(sources) for slug, sources in (topic_sources or {}).items()},
    )


def tiers(overrides):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        handle.write(overrides if isinstance(overrides, str) else json.dumps(overrides))
    try:
        return company_view.read_tiers(DEFAULT_TIERS, handle.name)
    finally:
        Path(handle.name).unlink()


def empty_company():
    return company_view.Current(nodes={}, vectors=set(), edges={})


def applied(view):
    vectors = {key for key in view.nodes if key[0] in company_view.EMBEDDED}
    return company_view.Current(nodes=dict(view.nodes), vectors=vectors, edges={key: set(value) for key, value in view.edges.items()})


class TierLookup(unittest.TestCase):
    def test_owner_defaults_apply_when_no_override_names_the_repository(self):
        lookup = tiers({"other/x": "personal"})
        self.assertEqual(lookup.of("webgrip/anything"), "internal")
        self.assertEqual(lookup.of("ryangr0/anything"), "personal")
        self.assertIsNone(lookup.of("someone/else"))

    def test_a_repository_override_wins_over_an_owner_wildcard_and_the_owner_default(self):
        lookup = tiers({"webgrip/*": "excluded", "webgrip/alpha": "internal", "WebGrip/Beta-Poc": "client:beta"})
        self.assertEqual(lookup.of("webgrip/alpha"), "internal")
        self.assertEqual(lookup.of("webgrip/beta-poc"), "client:beta")
        self.assertEqual(lookup.of("webgrip/gamma"), "excluded")

    def test_unknown_tiers_and_malformed_keys_are_refused_without_naming_them(self):
        for overrides in ({"webgrip/x": "secret"}, {"webgrip/x": "client:Upper"}, {"no-owner": "internal"}, {"webgrip/x": 3}, "[]", "not json", ""):
            with self.subTest(overrides=overrides):
                with self.assertRaises(company_view.Refused) as raised:
                    tiers(overrides)
                self.assertEqual(raised.exception.exit_code, company_view.EXIT_BAD_TIERS)
                self.assertNotIn("webgrip/x", str(raised.exception))


class Taint(unittest.TestCase):
    def setUp(self):
        self.tiers = tiers({"webgrip/beta-poc": "client:beta", "webgrip/old": "excluded"})

    def test_only_internal_repositories_with_documents_become_repositories(self):
        view = company_view.build_view(brain([project("webgrip/alpha"), project("webgrip/fork-only"), project("webgrip/beta-poc"), project("ryangr0/hobby"), project("webgrip/old")],
                                             artifacts=["webgrip/alpha", "webgrip/beta-poc", "ryangr0/hobby", "webgrip/old"]), self.tiers)
        self.assertEqual(sorted(slug for kind, slug in view.nodes if kind == "Repository"), ["repo/webgrip/alpha"])

    def test_decision_records_come_only_from_internal_repositories(self):
        view = company_view.build_view(brain([project("webgrip/alpha"), project("webgrip/beta-poc")], artifacts=["webgrip/alpha", "webgrip/beta-poc"],
                                             records=[("webgrip/alpha", "0001-flux"), ("webgrip/beta-poc", "0001-client")]), self.tiers)
        self.assertEqual([slug for kind, slug in view.nodes if kind == "DecisionRecord"], ["record/webgrip/alpha/adr/0001-flux"])
        self.assertEqual(view.edges[("RecordOf", "record/webgrip/alpha/adr/0001-flux")], {"repo/webgrip/alpha"})

    def test_a_topic_any_non_internal_source_is_about_stays_out(self):
        topics = ["derived/topic/flux", "derived/topic/kubernetes", "derived/topic/client", "derived/topic/garden", "derived/topic/unknown"]
        sources = {
            "derived/topic/flux": ["forge/webgrip/alpha/readme", "forge/webgrip/alpha/adr/0001-flux", "forge/webgrip/alpha"],
            "derived/topic/kubernetes": ["forge/webgrip/alpha/readme", "obsidian/diary"],
            "derived/topic/client": ["forge/webgrip/alpha/readme", "forge/webgrip/beta-poc/readme"],
            "derived/topic/garden": ["forge/ryangr0/hobby/readme"],
            "derived/topic/unknown": ["forge/webgrip/alpha/readme", "forge/someone/else/readme"],
        }
        view = company_view.build_view(brain([project("webgrip/alpha"), project("webgrip/beta-poc"), project("ryangr0/hobby"), project("someone/else")],
                                             artifacts=["webgrip/alpha", "webgrip/beta-poc", "ryangr0/hobby", "someone/else"],
                                             records=[("webgrip/alpha", "0001-flux")], topics=topics, topic_sources=sources), self.tiers)
        self.assertEqual([slug for kind, slug in view.nodes if kind == "Topic"], ["derived/topic/flux"])
        self.assertEqual(view.mixed_topics, 3)
        self.assertEqual(view.edges[("RecordAbout", "record/webgrip/alpha/adr/0001-flux")], {"derived/topic/flux"})
        self.assertEqual(view.edges[("RepositoryAbout", "repo/webgrip/alpha")], {"derived/topic/flux"})

    def test_untiered_repositories_are_listed_and_left_out(self):
        view = company_view.build_view(brain([project("webgrip/alpha"), project("someone/else"), project("another/one")],
                                             artifacts=["webgrip/alpha", "someone/else", "another/one"]), self.tiers)
        self.assertEqual(view.untiered, ["another/one", "someone/else"])
        self.assertNotIn(("Repository", "repo/someone/else"), view.nodes)

    def test_repository_rows_read_url_and_activity_from_the_importer_description(self):
        description = "Forgejo repository webgrip/alpha\nURL: https://forge.example/webgrip/alpha\nLast activity: 2026-10-20T10:00:00Z"
        row = company_view.repository_row(project("webgrip/alpha", status="exploring", description=description))
        self.assertEqual((row["url"], row["last_activity"], row["status"]), ("https://forge.example/webgrip/alpha", "2026-10-20T10:00:00Z", "active"))


class Writes(unittest.TestCase):
    def setUp(self):
        self.tiers = tiers({"webgrip/beta-poc": "client:beta"})
        self.brain = brain([project("webgrip/alpha")], artifacts=["webgrip/alpha"], records=[("webgrip/alpha", "0001-flux")],
                           topics=["derived/topic/flux"], topic_sources={"derived/topic/flux": ["forge/webgrip/alpha/readme"]})

    def test_a_first_run_writes_nodes_before_edges(self):
        plan = company_view.plan_writes(company_view.build_view(self.brain, self.tiers), empty_company())
        kinds = [row.get("type") or row["edge"] for row in plan.rows]
        self.assertEqual(kinds, ["Repository", "Topic", "DecisionRecord", "RecordOf", "RepositoryAbout"])
        self.assertEqual(plan.prune, [])

    def test_a_second_run_over_the_same_brain_writes_nothing(self):
        view = company_view.build_view(self.brain, self.tiers)
        plan = company_view.plan_writes(view, applied(view))
        self.assertEqual((plan.rows, plan.prune), ([], []))

    def test_a_row_without_a_vector_is_written_again_for_the_embed_step(self):
        view = company_view.build_view(self.brain, self.tiers)
        current = applied(view)
        current.vectors.clear()
        plan = company_view.plan_writes(view, current)
        self.assertEqual(sorted(row["type"] for row in plan.rows), ["DecisionRecord", "Topic"])

    def test_a_repository_retiered_to_a_client_leaves_the_view_with_its_records_and_topics(self):
        before = company_view.build_view(self.brain, self.tiers)
        after = company_view.build_view(self.brain, tiers({"webgrip/alpha": "client:alpha"}))
        plan = company_view.plan_writes(after, applied(before))
        self.assertEqual(plan.rows, [])
        self.assertEqual(plan.prune[-3:], ['delete DecisionRecord where slug = "record/webgrip/alpha/adr/0001-flux"',
                                           'delete Repository where slug = "repo/webgrip/alpha"',
                                           'delete Topic where slug = "derived/topic/flux"'])
        self.assertEqual(plan.prune[:2], ['delete RecordOf where from = "record/webgrip/alpha/adr/0001-flux"',
                                          'delete RepositoryAbout where from = "repo/webgrip/alpha"'])

    def test_the_plan_names_the_company_view_writer_for_the_embed_step(self):
        with tempfile.TemporaryDirectory() as out:
            view = company_view.build_view(self.brain, self.tiers)
            company_view.write_plan(company_view.plan_writes(view, empty_company()), view, out)
            self.assertEqual(json.loads((Path(out) / "embed-plan.json").read_text())["writer"], "company-view")


class Verdict(unittest.TestCase):
    def verdict(self, untiered):
        with tempfile.TemporaryDirectory() as plan:
            if untiered is not None:
                (Path(plan) / company_view.UNTIERED_REPORT).write_text(json.dumps(untiered))
            return company_view.main(["verdict", f"--plan={plan}"])

    def test_the_job_fails_while_a_repository_has_no_tier(self):
        self.assertEqual(self.verdict(["someone/else"]), company_view.EXIT_UNTIERED)

    def test_the_job_fails_when_no_plan_was_written(self):
        self.assertEqual(self.verdict(None), company_view.EXIT_UNTIERED)

    def test_the_job_passes_when_every_repository_has_a_tier(self):
        self.assertEqual(self.verdict([]), company_view.EXIT_OK)


if __name__ == "__main__":
    unittest.main()
