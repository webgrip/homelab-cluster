import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

SERVER = os.environ["OMNIGRAPH_URL"].rstrip("/")
CONTRACT = os.environ["OMNIGRAPH_HTTP_API"]
TOKEN = Path(os.environ["OMNIGRAPH_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
TARGETS = json.loads(Path(os.environ["SCRUB_TARGETS_FILE"]).read_text(encoding="utf-8"))
PATTERNS = {
    name: re.compile(expression)
    for name, expression in json.loads(Path(os.environ["SCRUB_PATTERNS_FILE"]).read_text(encoding="utf-8")).items()
}


def call(method, path, body=None, timeout=300):
    headers = {"Authorization": f"Bearer {TOKEN}", "Omnigraph-Http-Api": CONTRACT, "Content-Type": "application/json", "Accept": "application/json"}
    request = urllib.request.Request(f"{SERVER}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def branches(graph):
    status, body = call("GET", f"/graphs/{graph}/branches")
    if status != 200:
        sys.exit(f"omnigraph scrub: listing branches of {graph} answered HTTP {status}: {body[:300]!r}")
    return json.loads(body)["branches"]


def rows(graph, branch, type_name):
    status, body = call("POST", f"/graphs/{graph}/export", json.dumps({"branch": branch, "type_names": [type_name]}).encode())
    if status != 200:
        sys.exit(f"omnigraph scrub: export of {graph}@{branch} answered HTTP {status}: {body[:300]!r}")
    for line in body.decode().splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("type") == type_name:
                yield row


def matched_pattern(row, fields):
    data = row.get("data") or {}
    for field in fields:
        value = data.get(field)
        if isinstance(value, str):
            for name, pattern in PATTERNS.items():
                if pattern.search(value):
                    return name, field
    return None


def delete(graph, branch, type_name, key_field, key):
    query = f"query scrub($key: String) {{ delete {type_name} where {key_field} = $key }}"
    body = json.dumps({"query": query, "name": "scrub", "params": {"key": key}, "branch": branch}).encode()
    status, answer = call("POST", f"/graphs/{graph}/mutate", body)
    if status >= 300:
        sys.exit(f"omnigraph scrub: deleting {type_name} {key} from {graph}@{branch} answered HTTP {status}: {answer[:300]!r}")


def main():
    removed = 0
    for target in TARGETS:
        graph, type_name, key_field, fields = target["graph"], target["type"], target["key"], target["fields"]
        for branch in branches(graph):
            for row in list(rows(graph, branch, type_name)):
                hit = matched_pattern(row, fields)
                if hit is None:
                    continue
                key = (row.get("data") or {}).get(key_field) or row.get("id")
                delete(graph, branch, type_name, key_field, key)
                removed += 1
                print(f"omnigraph scrub removed {type_name} {key} from {graph}@{branch}: {hit[1]} matched {hit[0]}", flush=True)
    print(f"omnigraph scrub complete: {removed} rows removed", flush=True)


if __name__ == "__main__":
    main()
