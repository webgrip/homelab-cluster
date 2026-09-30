#!/usr/bin/env python3
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OMNIGRAPH = ROOT / "kubernetes/apps/ai/omnigraph"
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


def executable(path, body):
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class SnapshotWaitsForOmnigraph(unittest.TestCase):
    def run_snapshot(self, writer, not_ready_polls, query_refused=False, timeout_seconds="300"):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        scratch = Path(holder.name)
        bin_dir = scratch / "bin"
        bin_dir.mkdir()
        (scratch / "work").mkdir()
        (scratch / "token").write_text("token", encoding="utf-8")
        (scratch / "polls").write_text("", encoding="utf-8")
        executable(bin_dir / "curl", f'echo x >> "{scratch}/polls"\n'
                                     f'[ "$(wc -l < "{scratch}/polls")" -gt {not_ready_polls} ] && exit 0\n'
                                     'echo "curl: (7) Failed to connect to omnigraph port 8080: Connection refused" >&2\nexit 7\n')
        executable(bin_dir / "omnigraph", 'echo "HTTP 403: act refused by policy" >&2\nexit 1\n' if query_refused else 'echo \'{"rows": []}\'\n')
        text = (OMNIGRAPH / writer / "app/snapshot.sh").read_text(encoding="utf-8")
        for old, new in (("/tmp/", f"{scratch}/"), (WRITERS[writer], f"{OMNIGRAPH / writer / 'app'}/"),
                         ("/run/secrets/omnigraph/token", str(scratch / "token")), ("/work/", f"{scratch}/work/")):
            text = text.replace(old, new)
        script = scratch / "snapshot.sh"
        script.write_text(text, encoding="utf-8")
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "OMNIGRAPH_URL": "http://omnigraph.test:8080",
               "OMNIGRAPH_READY_TIMEOUT_SECONDS": timeout_seconds, "OMNIGRAPH_READY_POLL_SECONDS": "0"}
        result = subprocess.run(["sh", str(script)], capture_output=True, text=True, env=env, timeout=60)
        polls = len((scratch / "polls").read_text(encoding="utf-8").splitlines())
        return result, polls

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
                result, _ = self.run_snapshot(writer, not_ready_polls=10**6, timeout_seconds="0")
                self.assertEqual(result.returncode, 1)
                self.assertIn("omnigraph not ready", result.stderr)
                self.assertIn("Connection refused", result.stderr)

    def test_a_refused_query_shows_what_omnigraph_answered(self):
        for writer in WRITERS:
            with self.subTest(writer):
                result, _ = self.run_snapshot(writer, not_ready_polls=0, query_refused=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn("HTTP 403: act refused by policy", result.stderr)


if __name__ == "__main__":
    unittest.main()
