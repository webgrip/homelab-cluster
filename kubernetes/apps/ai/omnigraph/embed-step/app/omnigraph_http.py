import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HTTP_TIMEOUT_SECONDS = 300


class Refused(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def base_url():
    return os.environ["OMNIGRAPH_URL"].rstrip("/")


def headers(content_type="application/json"):
    token = Path(os.environ.get("OMNIGRAPH_TOKEN_FILE", "/run/secrets/omnigraph/token")).read_text(encoding="utf-8").strip()
    sent = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": content_type}
    contract = os.environ.get("OMNIGRAPH_HTTP_API", "").strip()
    if contract:
        sent["Omnigraph-Http-Api"] = contract
    return sent


def call(path, body, content_type="application/json"):
    request = urllib.request.Request(base_url() + path, data=body, headers=headers(content_type), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        error.close()
        raise Refused(error.code, text) from None


def ready(timeout, poll):
    deadline = time.monotonic() + timeout
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base_url() + "/readyz", timeout=5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError) as error:
            last = str(error)
        time.sleep(poll)
    raise SystemExit(f"omnigraph not ready: {base_url()}/readyz did not answer 200 within {timeout}s: {last}")


def query(graph, branch, source_file, name, params_file):
    params = json.loads(Path(params_file).read_text(encoding="utf-8")) if params_file else {}
    body = json.dumps({"query": Path(source_file).read_text(encoding="utf-8"), "name": name, "params": params, "branch": branch}).encode()
    return call(f"/graphs/{graph}/query", body)


def mutate(graph, branch, source_file, name):
    body = json.dumps({"query": Path(source_file).read_text(encoding="utf-8"), "name": name, "params": {}, "branch": branch}).encode()
    return call(f"/graphs/{graph}/mutate", body)


def load(graph, branch, mode, data_file):
    return call(f"/graphs/{graph}/load/ndjson?mode={mode}&branch={branch}", Path(data_file).read_bytes(), "application/x-ndjson")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read and write an Omnigraph server over its HTTP API, for 0.11 and for 0.14 (set OMNIGRAPH_HTTP_API).")
    commands = parser.add_subparsers(dest="command", required=True)
    ready_parser = commands.add_parser("ready")
    ready_parser.add_argument("--timeout", type=int, default=int(os.environ.get("OMNIGRAPH_READY_TIMEOUT_SECONDS", "300")))
    ready_parser.add_argument("--poll", type=float, default=float(os.environ.get("OMNIGRAPH_READY_POLL_SECONDS", "5")))
    for name in ("query", "mutate", "load"):
        sub = commands.add_parser(name)
        sub.add_argument("--graph", required=True)
        sub.add_argument("--branch", default="main")
        if name == "load":
            sub.add_argument("--mode", required=True, choices=["merge", "append", "overwrite"])
            sub.add_argument("--data", required=True)
        else:
            sub.add_argument("--query", required=True)
            sub.add_argument("name")
        if name == "query":
            sub.add_argument("--params-file")
    args = parser.parse_args(argv)
    try:
        if args.command == "ready":
            ready(args.timeout, args.poll)
            return 0
        if args.command == "query":
            sys.stdout.write(query(args.graph, args.branch, args.query, args.name, args.params_file).decode("utf-8"))
        elif args.command == "mutate":
            mutate(args.graph, args.branch, args.query, args.name)
        else:
            load(args.graph, args.branch, args.mode, args.data)
    except Refused as refused:
        print(f"omnigraph refused: HTTP {refused.status}: {refused.body[:2000]}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as error:
        print(f"omnigraph unreachable: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
