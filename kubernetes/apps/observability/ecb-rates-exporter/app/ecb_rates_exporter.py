#!/usr/bin/env python3
import os
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
CUBE = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube"


@dataclass
class Snapshot:
    rates: dict = field(default_factory=dict)
    rate_date: float = 0.0
    last_success: float = 0.0
    refresh_failures: int = 0


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def parse(document: bytes) -> tuple:
    root = ElementTree.fromstring(document)
    for cube in root.iter(CUBE):
        if cube.get("time"):
            day = datetime.strptime(cube.get("time"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            rates = {child.get("currency"): float(child.get("rate")) for child in cube if child.get("currency")}
            if not rates:
                break
            return rates, day.timestamp()
    raise ValueError("no dated rate cube in the ECB document")


def render(snapshot: Snapshot) -> str:
    lines = [
        "# HELP ecb_reference_rate Units of the currency per 1 EUR, ECB euro foreign exchange reference rate.",
        "# TYPE ecb_reference_rate gauge",
    ]
    for currency, rate in sorted(snapshot.rates.items()):
        lines.append(f'ecb_reference_rate{{currency="{currency}"}} {rate}')
    lines += [
        "# HELP ecb_reference_rate_date_timestamp_seconds Day the ECB published the current rates.",
        "# TYPE ecb_reference_rate_date_timestamp_seconds gauge",
        f"ecb_reference_rate_date_timestamp_seconds {snapshot.rate_date}",
        "# HELP ecb_rates_last_success_timestamp_seconds Time of the last successful fetch.",
        "# TYPE ecb_rates_last_success_timestamp_seconds gauge",
        f"ecb_rates_last_success_timestamp_seconds {snapshot.last_success}",
        "# HELP ecb_rates_refresh_failures_total Failed fetches since start.",
        "# TYPE ecb_rates_refresh_failures_total counter",
        f"ecb_rates_refresh_failures_total {snapshot.refresh_failures}",
    ]
    return "\n".join(lines) + "\n"


class Exporter:
    def __init__(self, fetch):
        self.fetch = fetch
        self.snapshot = Snapshot()
        self.lock = threading.Lock()

    def refresh(self) -> None:
        with self.lock:
            previous = self.snapshot
        snapshot = Snapshot(rates=previous.rates, rate_date=previous.rate_date,
                            last_success=previous.last_success, refresh_failures=previous.refresh_failures)
        try:
            snapshot.rates, snapshot.rate_date = parse(self.fetch())
            snapshot.last_success = time.time()
        except Exception as error:
            snapshot.refresh_failures += 1
            log(f"refresh failed: {type(error).__name__}: {error}")
        with self.lock:
            self.snapshot = snapshot

    def metrics(self) -> str:
        with self.lock:
            return render(self.snapshot)


def fetch_ecb(url: str, timeout: int):
    def fetch() -> bytes:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    return fetch


def make_handler(exporter: Exporter):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                body, status, kind = exporter.metrics().encode(), 200, "text/plain; version=0.0.4"
            elif self.path == "/healthz":
                body, status, kind = b"ok\n", 200, "text/plain"
            else:
                body, status, kind = b"not found\n", 404, "text/plain"
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    return Handler


def main() -> None:
    exporter = Exporter(fetch_ecb(os.environ.get("ECB_URL", ECB_DAILY), int(os.environ.get("FETCH_TIMEOUT_SECONDS", "30"))))
    interval = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "3600"))

    def loop():
        while True:
            exporter.refresh()
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()
    ThreadingHTTPServer(("", int(os.environ.get("LISTEN_PORT", "9803"))), make_handler(exporter)).serve_forever()


if __name__ == "__main__":
    main()
