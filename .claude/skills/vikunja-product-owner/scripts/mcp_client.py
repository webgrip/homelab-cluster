"""Minimal streamable-HTTP MCP client — drive the vikunja MCP (or any streamable-HTTP MCP)
from a script when its tools aren't loaded in the session (e.g. `.mcp.json` changed mid-session,
bulk board operations, the dark-factory dispatcher).

Usage:
    from mcp_client import init, call
    init()                                   # or init("https://other-mcp.example/mcp")
    print(call("tasks_list", {"projectId": 3, "limit": 200}))

Protocol notes (the parts that are easy to get wrong):
- POST JSON-RPC with Accept: application/json, text/event-stream.
- Capture the `mcp-session-id` response header on initialize; echo it on every later request.
- Send the `notifications/initialized` notification after initialize.
- Responses may be SSE — take the last `data:` line.
- tools/call results arrive as text content (this MCP returns formatted text, not JSON —
  see reference.md "Response formats").
"""
import json
import urllib.request

DEFAULT_URL = "https://mcp-vikunja.webgrip.dev/mcp"
session = {"id": None, "url": DEFAULT_URL}
_id = [0]


def post(payload, timeout=90):
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if session["id"]:
        headers["mcp-session-id"] = session["id"]
    req = urllib.request.Request(session["url"], data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        sid = r.headers.get("mcp-session-id")
        if sid:
            session["id"] = sid
        body = r.read().decode()
        ctype = r.headers.get("Content-Type", "")
    if not body:
        return None
    if "text/event-stream" in ctype:
        msgs = [json.loads(l[5:].strip()) for l in body.splitlines() if l.startswith("data:")]
        return msgs[-1] if msgs else None
    return json.loads(body)


def rpc(method, params=None):
    _id[0] += 1
    return post({"jsonrpc": "2.0", "id": _id[0], "method": method, "params": params or {}})


def init(url=None):
    """Start a session. Sessions are reaped server-side after 15 min idle (supergateway
    --sessionTimeout); on a 404/410 mid-run, reset session['id'] = None and init() again."""
    if url:
        session["url"] = url
    session["id"] = None
    r = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "mcp-client-script", "version": "1.0"}})
    post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return r


def call(tool, args, timeout=90):
    """Call a tool; returns its text content (raises on tool error)."""
    _id[0] += 1
    r = post({"jsonrpc": "2.0", "id": _id[0], "method": "tools/call",
              "params": {"name": tool, "arguments": args}}, timeout)
    if r is None:
        return None
    if "error" in r:
        raise RuntimeError(f"{tool}: {r['error']}")
    res = r["result"]
    if res.get("isError"):
        raise RuntimeError(f"{tool}: {res['content']}")
    return "".join(c.get("text", "") for c in res.get("content", []))
