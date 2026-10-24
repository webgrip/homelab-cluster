#!/usr/bin/env python3
import http.server
import os
import re
import socket
import subprocess
import threading
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OMNIGRAPH = ROOT / "kubernetes/apps/ai/omnigraph"
EMBED_APP = OMNIGRAPH / "embed-step/app"
RESTART = OMNIGRAPH / "app/maintenance-restart.cronjob.yaml"
WRITERS = {"vault-import": "/etc/vault-import/", "forge-import": "/etc/forge-import/", "distill": "/etc/distill/"}
OBSERVED_RESTART_TO_READY_MINUTES = 3
RESTART_QUIET_MINUTES = OBSERVED_RESTART_TO_READY_MINUTES + 2
DAY_MINUTES = 24 * 60


def cronjob_field(text, pattern):
    match = re.search(pattern, text, re.M)
    if match is None:
        raise AssertionError(f"no match for {pattern}")
    return match[1]


def expand(field, low, high):
    values = set()
    for part in field.split(","):
        base, _, step = part.partition("/")
        if base == "*":
            first, last = low, high
        elif "-" in base:
            first, last = (int(bound) for bound in base.split("-"))
        else:
            first = int(base)
            last = high if step else first
        values.update(range(first, last + 1, int(step or 1)))
    return values


def start_minutes(schedule):
    minute, hour = schedule.split()[:2]
    return {h * 60 + m for h in expand(hour, 0, 23) for m in expand(minute, 0, 59)}


def schedule_of(path):
    text = path.read_text(encoding="utf-8")
    return cronjob_field(text, r'^  schedule: "([^"]+)"'), cronjob_field(text, r"^  timeZone: (\S+)")


class RestartWindow(unittest.TestCase):
    def test_expand_reads_steps_ranges_and_lists(self):
        self.assertEqual(expand("*/15", 0, 59), {0, 15, 30, 45})
        self.assertEqual(expand("5-59/15", 0, 59), {5, 20, 35, 50})
        self.assertEqual(expand("5,20", 0, 59), {5, 20})
        self.assertEqual(expand("3", 0, 23), {3})

    def test_no_writer_starts_while_the_nightly_restart_takes_omnigraph_down(self):
        restart_schedule, restart_zone = schedule_of(RESTART)
        (restart,) = start_minutes(restart_schedule)
        quiet = {(restart + offset) % DAY_MINUTES for offset in range(RESTART_QUIET_MINUTES)}
        for writer in WRITERS:
            schedule, zone = schedule_of(OMNIGRAPH / writer / "app/cronjob.yaml")
            self.assertEqual(zone, restart_zone, writer)
            clashes = sorted(start_minutes(schedule) & quiet)
            self.assertFalse(clashes, f"{writer} ({schedule}) starts at {[f'{m // 60:02d}:{m % 60:02d}' for m in clashes]}, "
                                      f"while the {restart_schedule} restart has Omnigraph down")


class FakeOmnigraph:
    def __init__(self, not_ready_polls, query_refused):
        self.polls = 0
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                data = body.encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/readyz":
                    owner.polls += 1
                    self.reply(200 if owner.polls > not_ready_polls else 503, '{"ready": false}' if owner.polls <= not_ready_polls else '{"ready": true}')
                else:
                    self.reply(404, "{}")

            def do_POST(self):
                self.rfile.read(int(self.headers.get("content-length", "0")))
                if query_refused:
                    self.reply(403, '{"error": "act refused by policy", "code": "forbidden"}')
                else:
                    self.reply(200, '{"rows": []}')

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def closed_port_url():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return f"http://127.0.0.1:{port}"


class SnapshotWaitsForOmnigraph(unittest.TestCase):
    def run_snapshot(self, writer, not_ready_polls, query_refused=False, timeout_seconds="300", reachable=True):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        scratch = Path(holder.name)
        (scratch / "work").mkdir()
        (scratch / "token").write_text("token", encoding="utf-8")
        fake = FakeOmnigraph(not_ready_polls, query_refused)
        self.addCleanup(fake.stop)
        text = (OMNIGRAPH / writer / "app/snapshot.sh").read_text(encoding="utf-8")
        for old, new in (("/tmp/", f"{scratch}/"), (WRITERS[writer], f"{OMNIGRAPH / writer / 'app'}/"), ("/etc/omnigraph-embed-step/", f"{EMBED_APP}/"),
                         ("/run/secrets/omnigraph/token", str(scratch / "token")), ("/work/", f"{scratch}/work/")):
            text = text.replace(old, new)
        script = scratch / "snapshot.sh"
        script.write_text(text, encoding="utf-8")
        env = {"PATH": os.environ["PATH"], "OMNIGRAPH_URL": fake.url if reachable else closed_port_url(),
               "OMNIGRAPH_READY_TIMEOUT_SECONDS": timeout_seconds, "OMNIGRAPH_READY_POLL_SECONDS": "0"}
        result = subprocess.run(["sh", str(script)], capture_output=True, text=True, env=env, timeout=60)
        return result, fake.polls

    def test_a_restarting_omnigraph_is_waited_out_before_the_snapshot_reads(self):
        for writer in WRITERS:
            with self.subTest(writer):
                result, polls = self.run_snapshot(writer, not_ready_polls=3)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(polls, 4)
                self.assertIn("brain snapshot read", result.stdout)

    def test_an_omnigraph_that_never_gets_ready_fails_with_the_readiness_error(self):
        for writer in WRITERS:
            with self.subTest(writer):
                result, _ = self.run_snapshot(writer, not_ready_polls=10**6, timeout_seconds="1", reachable=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("omnigraph not ready", result.stderr)
                self.assertIn("Connection refused", result.stderr)

    def test_a_refused_query_shows_what_omnigraph_answered(self):
        for writer in WRITERS:
            with self.subTest(writer):
                result, _ = self.run_snapshot(writer, not_ready_polls=0, query_refused=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn("HTTP 403", result.stderr)
                self.assertIn("act refused by policy", result.stderr)


if __name__ == "__main__":
    unittest.main()
