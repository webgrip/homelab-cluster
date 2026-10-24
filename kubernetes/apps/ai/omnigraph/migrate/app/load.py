import collections
import json
import os
import sys
import time
import urllib.error
import urllib.request

SERVER = os.environ["OMNIGRAPH_URL"].rstrip("/")
GRAPHS = os.environ["OMNIGRAPH_GRAPHS"].split()
CONTRACT = os.environ["OMNIGRAPH_HTTP_API"]
BATCH_BYTES = int(os.environ.get("OMNIGRAPH_LOAD_BATCH_BYTES", str(16 * 1024 * 1024)))
TOKEN = open(os.environ["OMNIGRAPH_TOKEN_FILE"]).read().strip()


def log(message):
    print(message, flush=True)


def call(method, path, body=None, content_type="application/json", timeout=600):
    headers = {"Authorization": f"Bearer {TOKEN}", "Omnigraph-Http-Api": CONTRACT}
    if body is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(f"{SERVER}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def wait_for_write_access(graph, deadline_seconds=1800):
    deadline = time.monotonic() + deadline_seconds
    last = ""
    while time.monotonic() < deadline:
        try:
            status, body = call("GET", f"/graphs/{graph}/access?branch=main")
            last = f"HTTP {status} {body[:200]!r}"
            if status == 200 and "change" in json.loads(body).get("actions", []):
                return
        except OSError as error:
            last = str(error)
        time.sleep(10)
    sys.exit(f"{graph}: act-migrate never got change on main of omnigraph-next ({last})")


def type_of(row):
    return row.get("type") or row.get("edge")


def counts(lines):
    found = collections.Counter()
    for line in lines:
        if line.strip():
            found[type_of(json.loads(line))] += 1
    return found


def batches(lines):
    batch, size = [], 0
    for line in lines:
        encoded = line.encode()
        if batch and size + len(encoded) > BATCH_BYTES:
            yield b"".join(batch)
            batch, size = [], 0
        batch.append(encoded)
        size += len(encoded)
    if batch:
        yield b"".join(batch)


def load(graph):
    with open(f"/work/{graph}.jsonl") as source:
        lines = [line if line.endswith("\n") else line + "\n" for line in source if line.strip()]
    nodes = [line for line in lines if '"edge":' not in line[:40]]
    edges = [line for line in lines if '"edge":' in line[:40]]
    expected = counts(lines)
    wait_for_write_access(graph)
    sent = 0
    for part in list(batches(nodes)) + list(batches(edges)):
        status, body = call("POST", f"/graphs/{graph}/load/ndjson?mode=merge&branch=main", part, "application/x-ndjson")
        if status >= 300:
            sys.exit(f"{graph}: load answered HTTP {status}: {body[:600]!r}")
        sent += part.count(b"\n")
    status, body = call("POST", f"/graphs/{graph}/export", json.dumps({}).encode(), timeout=1800)
    if status != 200:
        sys.exit(f"{graph}: export for the count check answered HTTP {status}: {body[:300]!r}")
    served = counts(body.decode().splitlines())
    if served != expected:
        differing = {name: (expected.get(name, 0), served.get(name, 0)) for name in set(expected) | set(served) if expected.get(name, 0) != served.get(name, 0)}
        sys.exit(f"{graph}: counts differ after the load (exported, served): {differing}")
    log(f"loaded {graph}: {sent} rows, {len(expected)} types, counts equal on omnigraph-next")


for graph in GRAPHS:
    load(graph)
log("migration complete")
