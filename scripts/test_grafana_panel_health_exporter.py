import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTER = Path(os.environ.get(
    "EXPORTER_SCRIPT",
    REPO_ROOT / "kubernetes/apps/observability/grafana-panel-health/app/panel_health_exporter.py"))

spec = importlib.util.spec_from_file_location("panel_health_exporter", EXPORTER)
exporter = importlib.util.module_from_spec(spec)
sys.modules["panel_health_exporter"] = exporter
spec.loader.exec_module(exporter)

PROM = {"type": "prometheus", "uid": "prometheus"}


def frame(*columns):
    return {"schema": {"fields": []}, "data": {"values": list(columns)}}


DASHBOARD = {
    "uid": "costs",
    "title": "Costs",
    "time": {"from": "now-7d", "to": "now"},
    "templating": {"list": [
        {"name": "namespace", "type": "query", "includeAll": True, "allValue": ".+",
         "current": {"value": ["$__all"]}},
        {"name": "node", "type": "query", "current": {"value": ["worker-1", "worker-2"]}},
        {"name": "rate", "type": "constant", "query": "0.30", "current": {}},
    ]},
    "panels": [
        {"id": 1, "type": "stat", "title": "Has data", "datasource": PROM,
         "targets": [{"refId": "A", "expr": 'sum(up{namespace=~"$namespace", node=~"${node}"}) * $rate'}]},
        {"id": 2, "type": "row", "title": "Collapsed", "panels": [
            {"id": 3, "type": "stat", "title": "Went empty", "datasource": PROM,
             "targets": [{"refId": "A", "expr": "empty_metric"}]},
        ]},
        {"id": 4, "type": "table", "title": "Nothing firing is fine", "datasource": PROM,
         "fieldConfig": {"defaults": {"noValue": "Nothing is firing."}},
         "targets": [{"refId": "A", "expr": "empty_metric"}]},
        {"id": 5, "type": "stat", "title": "Generic no value", "datasource": PROM,
         "fieldConfig": {"defaults": {"noValue": "no data"}},
         "targets": [{"refId": "A", "expr": "empty_metric"}]},
        {"id": 6, "type": "stat", "title": "Broken", "datasource": PROM,
         "targets": [{"refId": "A", "expr": "broken("}]},
        {"id": 7, "type": "text", "title": "Words"},
        {"id": 8, "type": "stat", "title": "Hidden only", "datasource": PROM,
         "targets": [{"refId": "A", "expr": "up", "hide": True}]},
        {"id": 9, "type": "stat", "title": "Last day", "datasource": PROM, "timeFrom": "24h",
         "targets": [{"refId": "A", "expr": "up"}]},
    ],
}


class FakeGrafana(BaseHTTPRequestHandler):
    queries = []

    def reply(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer good":
            return self.reply(401, {"message": "Unauthorized"})
        if self.path.startswith("/api/search"):
            return self.reply(200, [{"uid": "costs"}])
        if self.path == "/api/dashboards/uid/costs":
            return self.reply(200, {"dashboard": DASHBOARD})
        return self.reply(404, {"message": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeGrafana.queries.append(body)
        expr = body["queries"][0].get("expr", "")
        if expr.startswith("broken"):
            return self.reply(400, {"results": {"A": {"error": "parse error", "status": 400}}})
        if expr == "empty_metric":
            return self.reply(200, {"results": {"A": {"status": 200, "frames": [frame([], [])]}}})
        return self.reply(200, {"results": {"A": {"status": 200, "frames": [frame([1], [4.0])]}}})

    def log_message(self, *_args):
        return


class GrafanaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGrafana)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeGrafana.queries = []
        self.token_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.token_dir.name, "token")

    def tearDown(self):
        self.token_dir.cleanup()

    def exporter_with(self, token):
        if token is not None:
            with open(self.token_path, "w", encoding="utf-8") as handle:
                handle.write(token + "\n")
        return exporter.Exporter(lambda t: exporter.GrafanaClient(self.url, t, 5), self.token_path)

    def results_by_title(self, instance):
        instance.refresh()
        return {result.panel: result for result in instance.snapshot.results}


class ClassificationTest(GrafanaTest):
    def test_panel_with_values_reads_as_data(self):
        self.assertEqual(self.results_by_title(self.exporter_with("good"))["Has data"].status, "data")

    def test_panel_inside_a_collapsed_row_is_checked_and_reads_empty(self):
        self.assertEqual(self.results_by_title(self.exporter_with("good"))["Went empty"].status, "empty")

    def test_query_error_reads_as_error_with_its_message(self):
        broken = self.results_by_title(self.exporter_with("good"))["Broken"]
        self.assertEqual(broken.status, "error")
        self.assertIn("parse error", broken.detail)

    def test_text_and_hidden_only_panels_are_not_checked(self):
        titles = self.results_by_title(self.exporter_with("good"))
        self.assertNotIn("Words", titles)
        self.assertNotIn("Hidden only", titles)
        self.assertNotIn("Collapsed", titles)

    def test_specific_no_value_text_marks_empty_as_expected_and_generic_does_not(self):
        titles = self.results_by_title(self.exporter_with("good"))
        self.assertTrue(titles["Nothing firing is fine"].empty_expected)
        self.assertFalse(titles["Generic no value"].empty_expected)
        self.assertFalse(titles["Went empty"].empty_expected)


class QueryShapeTest(GrafanaTest):
    def test_variables_are_substituted_before_querying(self):
        self.exporter_with("good").refresh()
        expr = next(q["queries"][0]["expr"] for q in FakeGrafana.queries if "up{" in q["queries"][0]["expr"])
        self.assertEqual(expr, 'sum(up{namespace=~".+", node=~"worker-1|worker-2"}) * 0.30')

    def test_dashboard_time_range_is_used_and_panel_time_override_wins(self):
        self.exporter_with("good").refresh()
        ranges = {q["queries"][0]["expr"]: q["from"] for q in FakeGrafana.queries}
        self.assertEqual(ranges["empty_metric"], "now-7d")
        self.assertEqual(ranges["up"], "now-24h")

    def test_queries_carry_the_panel_datasource(self):
        self.exporter_with("good").refresh()
        self.assertTrue(all(q["queries"][0]["datasource"] == PROM for q in FakeGrafana.queries))


class ExporterTest(GrafanaTest):
    def test_metrics_report_each_state_per_panel(self):
        instance = self.exporter_with("good")
        instance.refresh()
        text = instance.metrics()
        self.assertIn('grafana_panel_has_data{dashboard_uid="costs",dashboard="Costs",panel_id="1",panel="Has data"} 1', text)
        self.assertIn('grafana_panel_has_data{dashboard_uid="costs",dashboard="Costs",panel_id="3",panel="Went empty"} 0', text)
        self.assertIn('grafana_panel_query_error{dashboard_uid="costs",dashboard="Costs",panel_id="6",panel="Broken"} 1', text)
        self.assertIn('grafana_panel_empty_expected{dashboard_uid="costs",dashboard="Costs",panel_id="4",panel="Nothing firing is fine"} 1', text)
        self.assertIn("grafana_panel_check_dashboards 1", text)

    def test_successful_check_sets_last_success(self):
        instance = self.exporter_with("good")
        instance.refresh()
        self.assertGreater(instance.snapshot.last_success, 0)
        self.assertEqual(instance.snapshot.check_failures, 0)

    def test_missing_token_counts_a_failure_and_keeps_last_success_unset(self):
        instance = self.exporter_with(None)
        instance.refresh()
        self.assertFalse(instance.snapshot.token_configured)
        self.assertEqual(instance.snapshot.check_failures, 1)
        self.assertEqual(instance.snapshot.last_success, 0)

    def test_rejected_token_counts_a_failure_instead_of_reporting_no_panels(self):
        instance = self.exporter_with("bad")
        instance.refresh()
        self.assertEqual(instance.snapshot.check_failures, 1)
        self.assertEqual(instance.snapshot.last_success, 0)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *sys.argv[1:]], verbosity=1)
