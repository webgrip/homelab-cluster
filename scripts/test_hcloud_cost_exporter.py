import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTER = Path(os.environ.get(
    "EXPORTER_SCRIPT",
    REPO_ROOT / "kubernetes/apps/observability/hcloud-cost-exporter/app/hcloud_cost_exporter.py"))

spec = importlib.util.spec_from_file_location("hcloud_cost_exporter", EXPORTER)
exporter = importlib.util.module_from_spec(spec)
sys.modules["hcloud_cost_exporter"] = exporter
spec.loader.exec_module(exporter)


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def iso(text):
    return text + "+00:00"


def price(location, hourly, monthly):
    return {"location": location,
            "price_hourly": {"net": hourly, "gross": hourly},
            "price_monthly": {"net": monthly, "gross": monthly}}


CX23 = {"name": "cx23", "prices": [price("nbg1", "0.0090000000", "5.9900000000"),
                                   price("fsn1", "0.0088000000", "5.4900000000")]}
CX33 = {"name": "cx33", "prices": [price("fsn1", "0.0136000000", "8.4900000000")]}

PRICING = {
    "currency": "EUR",
    "image": {"price_per_gb_month": {"net": "0.0143000000", "gross": "0.0143000000"}},
    "volume": {"price_per_gb_month": {"net": "0.0440000000", "gross": "0.0440000000"}},
    "server_backup": {"percentage": "20.0000000000"},
    "primary_ips": [
        {"type": "ipv4", "prices": [price("fsn1", "0.0008000000", "0.5000000000")]},
        {"type": "ipv6", "prices": [price("fsn1", "0.0000000000", "0.0000000000")]},
    ],
    "floating_ips": [],
}


def server(server_id, name, server_type, created, labels, backup_window=None):
    return {"id": server_id, "name": name, "created": iso(created), "labels": labels,
            "server_type": server_type, "backup_window": backup_window,
            "datacenter": {"location": {"name": "fsn1"}}}


def primary_ip(ip_id, ip_type, assignee_id, created, labels=None):
    return {"id": ip_id, "name": f"ip-{ip_id}", "ip": f"192.0.2.{ip_id}", "type": ip_type,
            "assignee_id": assignee_id, "created": iso(created), "labels": labels or {},
            "datacenter": {"location": {"name": "fsn1"}}}


SINCE_SEPTEMBER = "2026-09-20T10:00:00"
CLUSTER = {"cluster": "unfold-main"}


def unfold_inventory():
    servers = [
        server(1, "unfold-cp-1", CX23, SINCE_SEPTEMBER, {**CLUSTER, "role": "controlplane"}),
        server(2, "unfold-cp-2", CX23, SINCE_SEPTEMBER, {**CLUSTER, "role": "controlplane"}),
        server(3, "unfold-cp-3", CX23, SINCE_SEPTEMBER, {**CLUSTER, "role": "controlplane"}),
        server(4, "unfold-app-1", CX33, SINCE_SEPTEMBER, {**CLUSTER, "role": "worker"}),
        server(5, "unfold-headscale", CX23, SINCE_SEPTEMBER, {**CLUSTER, "role": "headscale"}),
    ]
    ips = [primary_ip(10 + n, "ipv4", n, SINCE_SEPTEMBER) for n in range(1, 6)]
    ips.append(primary_ip(20, "ipv6", 1, SINCE_SEPTEMBER))
    images = [{"id": 99, "type": "snapshot", "description": "talos", "image_size": 0.4289,
               "created": iso(SINCE_SEPTEMBER), "labels": {"os": "talos"}},
              {"id": 98, "type": "system", "description": "debian", "image_size": None,
               "created": iso(SINCE_SEPTEMBER), "labels": {}}]
    return {"pricing": PRICING, "servers": servers, "primary_ips": ips, "images": images,
            "volumes": [], "load_balancers": [], "floating_ips": []}


def by_name(resources, kind, name):
    return next(r for r in resources if r.kind == kind and r.name == name)


class BillingModelTest(unittest.TestCase):
    def test_partial_hours_bill_as_started_hours(self):
        created = at("2026-10-25T12:00:00")
        self.assertEqual(exporter.started_hours(created, created + 1), 1)
        self.assertEqual(exporter.started_hours(created, created + 3600), 1)
        self.assertEqual(exporter.started_hours(created, created + 3601), 2)
        self.assertEqual(exporter.started_hours(created, created), 0)

    def test_resource_created_today_costs_its_started_hours(self):
        resource = exporter.Resource("server", "1", "s", "worker", "unfold-main", "fsn1", "cx23",
                                     at("2026-10-25T08:00:00"), 0.0088, 5.49)
        now = at("2026-10-25T12:30:00")
        self.assertAlmostEqual(exporter.month_to_date_eur(resource, now), 5 * 0.0088)
        self.assertAlmostEqual(exporter.projected_month_eur(resource, now), 160 * 0.0088)

    def test_resource_from_last_month_bills_from_the_first_of_this_month(self):
        resource = exporter.Resource("server", "1", "s", "worker", "unfold-main", "fsn1", "cx23",
                                     at("2026-09-20T10:00:00"), 0.0088, 5.49)
        now = at("2026-10-02T00:00:00")
        self.assertEqual(exporter.billable_hours_so_far(resource, now), 24)
        self.assertAlmostEqual(exporter.month_to_date_eur(resource, now), 24 * 0.0088)

    def test_monthly_price_caps_a_full_month(self):
        resource = exporter.Resource("server", "1", "s", "worker", "unfold-main", "fsn1", "cx23",
                                     at("2026-09-20T10:00:00"), 0.0088, 5.49)
        now = at("2026-10-31T23:30:00")
        self.assertAlmostEqual(exporter.month_to_date_eur(resource, now), 5.49)
        self.assertAlmostEqual(exporter.projected_month_eur(resource, at("2026-10-01T00:30:00")), 5.49)

    def test_december_projects_to_the_first_of_january(self):
        self.assertEqual(exporter.next_month_start(at("2026-12-15T00:00:00")), at("2027-01-01T00:00:00"))
        self.assertEqual(exporter.month_start(at("2026-12-15T00:00:00")), at("2026-12-01T00:00:00"))


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.resources = exporter.inventory_to_resources(unfold_inventory())

    def test_server_price_follows_its_location(self):
        cp = by_name(self.resources, "server", "unfold-cp-1")
        self.assertEqual((cp.hourly_eur, cp.monthly_cap_eur, cp.role, cp.cluster),
                         (0.0088, 5.49, "controlplane", "unfold-main"))
        self.assertEqual(by_name(self.resources, "server", "unfold-app-1").monthly_cap_eur, 8.49)

    def test_primary_ipv4_inherits_its_server_role_and_free_ipv6_is_skipped(self):
        ips = [r for r in self.resources if r.kind == "primary_ip"]
        self.assertEqual(len(ips), 5)
        self.assertEqual(by_name(self.resources, "primary_ip", "ip-14").role, "worker")
        self.assertEqual(by_name(self.resources, "primary_ip", "ip-14").cluster, "unfold-main")

    def test_snapshot_bills_per_gigabyte_and_system_images_are_free(self):
        snapshot = by_name(self.resources, "snapshot", "talos")
        self.assertAlmostEqual(snapshot.monthly_cap_eur, 0.4289 * 0.0143)
        self.assertEqual(snapshot.role, "image")
        self.assertEqual([r for r in self.resources if r.kind == "system"], [])

    def test_full_month_of_the_unfold_project_matches_the_usage_page(self):
        total = sum(exporter.projected_month_eur(r, at("2026-10-01T00:30:00")) for r in self.resources)
        self.assertAlmostEqual(total, 4 * 5.49 + 8.49 + 5 * 0.50 + 0.4289 * 0.0143, places=6)

    def test_enabled_backups_add_the_backup_percentage(self):
        inventory = unfold_inventory()
        inventory["servers"][3]["backup_window"] = "22-02"
        backup = by_name(exporter.inventory_to_resources(inventory), "server_backup", "unfold-app-1")
        self.assertAlmostEqual(backup.monthly_cap_eur, 8.49 * 0.2)

    def test_unlabelled_server_has_no_cluster_label(self):
        inventory = unfold_inventory()
        inventory["servers"].append(server(7, "hcloud-upload-image-tmp", CX23, "2026-10-25T08:00:00", {}))
        temp = by_name(exporter.inventory_to_resources(inventory), "server", "hcloud-upload-image-tmp")
        self.assertEqual((temp.cluster, temp.role), ("", "none"))


class FakeClient:
    def __init__(self, outcome):
        self.outcome = outcome

    def inventory(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class ExporterTest(unittest.TestCase):
    def exporter_with(self, token, outcome):
        handle = tempfile.NamedTemporaryFile("w", delete=False)
        handle.write(token)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return exporter.Exporter(lambda _: FakeClient(outcome), handle.name, "unfold")

    def test_missing_token_reports_unconfigured_without_calling_the_api(self):
        subject = exporter.Exporter(lambda _: self.fail("API called without a token"), "/nonexistent/token", "unfold")
        subject.refresh()
        text = subject.metrics()
        self.assertIn('hcloud_cost_token_configured{project="unfold"} 0', text)
        self.assertIn('hcloud_cost_refresh_success{project="unfold"} 0', text)

    def test_rejected_token_reports_unauthorized_and_drops_stale_resources(self):
        subject = self.exporter_with("token", unfold_inventory())
        subject.refresh()
        subject.client_factory = lambda _: FakeClient(exporter.Unauthorized("401"))
        subject.refresh()
        text = subject.metrics()
        self.assertIn('hcloud_cost_token_configured{project="unfold"} 1', text)
        self.assertIn('hcloud_cost_api_authorized{project="unfold"} 0', text)
        self.assertNotIn("hcloud_cost_resource_hourly_eur{", text)

    def test_transient_failure_keeps_the_last_inventory(self):
        subject = self.exporter_with("token", unfold_inventory())
        subject.refresh()
        subject.client_factory = lambda _: FakeClient(OSError("timeout"))
        subject.refresh()
        text = subject.metrics()
        self.assertIn('hcloud_cost_refresh_success{project="unfold"} 0', text)
        self.assertIn('hcloud_cost_api_authorized{project="unfold"} 1', text)
        self.assertIn('name="unfold-app-1"', text)

    def test_successful_refresh_renders_every_resource_series(self):
        subject = self.exporter_with("token\n", unfold_inventory())
        subject.refresh()
        text = subject.metrics()
        self.assertIn('hcloud_cost_refresh_success{project="unfold"} 1', text)
        for metric, _, _ in exporter.RESOURCE_SERIES:
            self.assertEqual(text.count(metric + "{"), 11, metric)
        self.assertIn('hcloud_cost_resource_monthly_cap_eur{project="unfold",kind="server",id="4",'
                      'name="unfold-app-1",role="worker",cluster="unfold-main",location="fsn1",type="cx33"} 8.49', text)

    def test_label_values_are_escaped(self):
        self.assertEqual(exporter.render_labels({"name": 'a"b\\c\nd'}), '{name="a\\"b\\\\c\\nd"}')


class FakeHetzner(BaseHTTPRequestHandler):
    pages = {1: ([{"id": 1}], 2), 2: ([{"id": 2}], None)}

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer good":
            self.send_response(401)
            self.end_headers()
            return
        query = parse_qs(urlparse(self.path).query)
        items, next_page = self.pages[int(query["page"][0])]
        body = json.dumps({"servers": items, "meta": {"pagination": {"next_page": next_page}}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


class HetznerClientTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHetzner)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def test_list_follows_every_page(self):
        client = exporter.HetznerClient(self.url, "good", 5)
        self.assertEqual(client.list_all("/servers", "servers"), [{"id": 1}, {"id": 2}])

    def test_rejected_token_raises_unauthorized(self):
        client = exporter.HetznerClient(self.url, "bad", 5)
        with self.assertRaises(exporter.Unauthorized):
            client.list_all("/servers", "servers")


if __name__ == "__main__":
    unittest.main()
