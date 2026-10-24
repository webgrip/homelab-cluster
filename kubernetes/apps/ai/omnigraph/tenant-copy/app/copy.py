import collections
import json
import os
import sys
import urllib.error
import urllib.request

SOURCE = os.environ["OMNIGRAPH_SOURCE_URL"].rstrip("/")
TARGET = os.environ["OMNIGRAPH_TARGET_URL"].rstrip("/")
GRAPHS = os.environ["OMNIGRAPH_GRAPHS"].split()
CONTRACT = os.environ["OMNIGRAPH_HTTP_API"]
BATCH_ROWS = int(os.environ.get("OMNIGRAPH_LOAD_BATCH_ROWS", "4000"))
BATCH_BYTES = int(os.environ.get("OMNIGRAPH_LOAD_BATCH_BYTES", str(16 * 1024 * 1024)))
TOKEN = open(os.environ["OMNIGRAPH_TOKEN_FILE"]).read().strip()


def log(message):
    print(message, flush=True)


def call(server, method, path, body=None, content_type="application/json", timeout=900):
    headers = {"Authorization": f"Bearer {TOKEN}", "Omnigraph-Http-Api": CONTRACT}
    if body is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(f"{server}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def export(server, graph):
    status, body = call(server, "POST", f"/graphs/{graph}/export", json.dumps({}).encode())
    if status != 200:
        sys.exit(f"{graph}: export from {server} answered HTTP {status}: {body[:400]!r}")
    return [line + "\n" for line in body.decode().splitlines() if line.strip()]


def type_of(line):
    row = json.loads(line)
    return row.get("type") or row.get("edge")


def batches(lines):
    batch, size = [], 0
    for line in lines:
        encoded = line.encode()
        if batch and (size + len(encoded) > BATCH_BYTES or len(batch) >= BATCH_ROWS):
            yield b"".join(batch)
            batch, size = [], 0
        batch.append(encoded)
        size += len(encoded)
    if batch:
        yield b"".join(batch)


def copy(graph):
    lines = export(SOURCE, graph)
    expected = collections.Counter(type_of(line) for line in lines)
    nodes = [line for line in lines if '"edge":' not in line[:40]]
    edges = [line for line in lines if '"edge":' in line[:40]]
    for part in list(batches(nodes)) + list(batches(edges)):
        status, body = call(TARGET, "POST", f"/graphs/{graph}/load/ndjson?mode=merge&branch=main", part, "application/x-ndjson")
        if status >= 300:
            sys.exit(f"{graph}: load into {TARGET} answered HTTP {status}: {body[:600]!r}")
    served = collections.Counter(type_of(line) for line in export(TARGET, graph))
    missing = {name: (count, served.get(name, 0)) for name, count in expected.items() if served.get(name, 0) < count}
    if missing:
        sys.exit(f"{graph}: rows of the source are missing on the target after the merge (source, target): {missing}")
    extra = {name: served[name] - expected.get(name, 0) for name in served if served[name] > expected.get(name, 0)}
    log(f"copied {graph}: {len(lines)} rows over {len(expected)} types merged into {TARGET}; rows only on the target: {extra or 'none'}")


for graph in GRAPHS:
    copy(graph)
log("tenant copy complete")
