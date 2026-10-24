"""Minimal streamable-HTTP MCP client — drive the vikunja MCP (or any streamable-HTTP MCP)
from a script when its tools aren't loaded in the session (e.g. `.mcp.json` changed mid-session,
bulk board operations, the dark-factory dispatcher).

Usage:
    from mcp_client import init, call
    init()                                   # or init("https://other-mcp.example/mcp")
    print(call("tasks_list", {"projectId": 3, "show": "all"}))

Protocol notes (the parts that are easy to get wrong):
- POST JSON-RPC with Accept: application/json, text/event-stream.
- Capture the `mcp-session-id` response header on initialize; echo it on every later request.
- Send the `notifications/initialized` notification after initialize.
- Responses may be SSE — take the last `data:` line.
- tools/call results arrive as text content (formatted text, not JSON — parse ids from
  `[ID: n]`; adapters/vikunja.md "Scripted access").
- Tool names and argument casing differ per server: adapters/vikunja.md "Two servers, two surfaces".
- Endpoint: the webgrip board is reached through LiteLLM's MCP gateway (the direct LAN route
  was closed 2026-10-17 because it answered anonymous calls). The gateway needs
  `Authorization: Bearer <LiteLLM virtual key with the board access group>` on every request,
  from $LITELLM_MCP_KEY, else $VIKUNJA_API_TOKEN, else the file named by $VIKUNJA_TOKEN_FILE.
- The gateway prefixes each tool with its server name (`vikunja-tasks_list`); `call()` adds
  $VIKUNJA_MCP_TOOL_PREFIX (default `vikunja-`, empty for a direct server) so callers keep
  using the bare names.
"""
import json
import os
import urllib.request

DEFAULT_URL = os.environ.get("VIKUNJA_MCP_URL", "https://litellm.webgrip.dev/mcp/")
TOOL_PREFIX = os.environ.get("VIKUNJA_MCP_TOOL_PREFIX", "vikunja-")
session = {"id": None, "url": DEFAULT_URL}
_id = [0]


def _token():
    tok = (os.environ.get("LITELLM_MCP_KEY", "") or os.environ.get("VIKUNJA_API_TOKEN", "")).strip()
    if not tok:
        path = os.environ.get("VIKUNJA_TOKEN_FILE", "").strip()
        if path and os.path.exists(path):
            with open(path) as f:
                tok = f.read().strip()
    return tok or None


def post(payload, timeout=90):
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
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
    name = tool if tool.startswith(TOOL_PREFIX) else TOOL_PREFIX + tool
    r = post({"jsonrpc": "2.0", "id": _id[0], "method": "tools/call",
              "params": {"name": name, "arguments": args}}, timeout)
    if r is None:
        return None
    if "error" in r:
        raise RuntimeError(f"{tool}: {r['error']}")
    res = r["result"]
    if res.get("isError"):
        raise RuntimeError(f"{tool}: {res['content']}")
    return "".join(c.get("text", "") for c in res.get("content", []))
