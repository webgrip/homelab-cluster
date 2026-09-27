# mcp-vikunja — the write-capable Vikunja MCP bridge

Instance operations for the `vikunja` MCP server. The product-owner *role* (conventions, DoR,
refinement, prioritization) is the `vikunja-product-owner` skill from
[`webgrip/ai-skills`](https://forgejo.webgrip.dev/webgrip/ai-skills); the board contract lives in [AGENTS.md](https://github.com/webgrip/homelab-cluster/blob/main/AGENTS.md).

## Bridge internals

`kubernetes/apps/vikunja/mcp-vikunja/` — a `supercorp/supergateway` Deployment (ns `vikunja`)
bridging the stdio-only npm server `@aimbitgmbh/vikunja-mcp` (pinned in `deployment.yaml` args) to
streamable HTTP at `https://mcp-vikunja.${SECRET_DOMAIN}/mcp` (envoy-internal,
external-dns-excluded, LAN-only, no client auth — same trust model as the other MCPs, but this one
**writes**, acting as the token owner's Vikunja user).

- Talks to Vikunja in-cluster: `http://vikunja.vikunja.svc.cluster.local:3456/api/v1` (the
  `/api/v1` suffix is required by vikunja-mcp).
- **STATELESS since 2026-07-18** (VIK-314/VIK-263): a fresh vikunja-mcp child per request.
  An initContainer npm-installs `supergateway` and `@aimbitgmbh/vikunja-mcp` into the `/tmp`
  emptyDir once per pod (hence the internet-egress carve-out in `app/networkpolicy.yaml`); the
  main container runs that local install with `node`, never `npx`. Stateful session mode was
  retired after it broke strict MCP SDK clients (LiteLLM: `Session termination failed: 400`) and
  after the 2026-07-12 session-leak OOM.
- **supergateway 4.0.0 since 2026-09-27** (VIK-440). 3.4.3 never released a stateless child: the
  SDK transport only closes on `DELETE` (which the gateway answers 405), so the child spawned for
  every POST lived until the pod died. Live evidence 2026-09-20..27: 1462 child spawns
  (`Non-initialize message detected`) against 70 `Child exited` lines; the working set climbed in
  steps with request bursts and plateaued between them (1.6-2.7 GiB) until the 3Gi limit
  OOMKilled it. Reproduced locally: 5 POSTs to 3.4.3 left 5 `sh -c` wrappers + 5 node children
  (~75 MiB each) alive; the same load on 4.0.0 leaves none (upstream fixes #158/#187, process-group
  kill in `ownedChildProcesses`). 4.0.0 also pins SDK 1.30.0 itself (protocol 2025-11-25) and
  survives client hang-ups mid-call, so the npm SDK override and the `transport.send` patch that
  3.4.3 needed (2026-09-04/09-11) are gone.
- Memory sizing: the gateway idles well under 128Mi; each in-flight call costs one child (~75 MiB,
  ~130 MiB with a 2 MB payload). Six parallel 2 MB `task_get` calls peaked at 847 MiB total
  locally, so the 1536Mi limit covers ~10 large calls at once. `NODE_OPTIONS=--max-old-space-size=384`
  is inherited by every child: a runaway response fails that one call instead of OOM-killing the
  pod for every session. `AppContainerMemoryNearLimit` warns before the kernel kills it.
- Hard-delete opt-ins: `ENABLE_LABEL_DELETE=true` is set (label deletes only unlink metadata;
  needed for duplicate-label dedup — a delete **cascades**: the server removes the label from
  every task that carried it, so consolidate tasks onto the keeper id first). `ENABLE_{PROJECT,TASK}_DELETE` stay unset (soft mode:
  `project_delete`→archive, `task_delete`→complete — Vikunja has no trash/undo).
- Version bump = edit the pinned `@aimbitgmbh/vikunja-mcp@<ver>` in `deployment.yaml` args
  (Renovate doesn't see inside args).
- The Vikunja server itself carries `VIKUNJA_SERVICE_MAXITEMSPERPAGE: "250"`
  (`kubernetes/apps/vikunja/vikunja/app/helmrelease.yaml`) so one list page holds the whole
  roadmap board — the MCP cannot paginate.

## Token bootstrap / rotation

The bridge authenticates with a personal API token — created by a **human** (agents cannot write
OpenBao, and token creation needs an Authentik login):

1. Vikunja UI → avatar → **Settings → API Tokens → Create a token**. Grant the route groups the
   MCP tools use: tasks, projects, labels, task comments/assignees/relations, project views,
   buckets, filters, notifications, subscriptions (or select all). Pick a long expiry and note it.
2. Seed OpenBao (provided-value flow of the `external-secrets` skill — BAO_ADDR/read-rs footguns
   documented there):
   `bao kv put secret/vikunja/mcp api_token=<token>`
3. ESO syncs `ExternalSecret/mcp-vikunja-token` within 15 min (or force:
   `kubectl -n vikunja annotate externalsecret mcp-vikunja-token force-sync=$(date +%s) --overwrite`);
   reloader restarts the pod on the change.

Rotation = same steps; step 2's `bao kv put` overwrites version-safely.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| pod `CreateContainerConfigError` | token never seeded — `mcp-vikunja-token` Secret missing; do bootstrap above; `refreshTime: null` on the ExternalSecret = never synced |
| MCP tools return 401 | token expired/revoked — rotate |
| task ops fail with 403 | token missing that route-group permission — recreate token with wider scope |
| `/mcp` connect timeout | not on LAN, or pod not Ready (`kubectl -n vikunja get pods`) |
| first tool call slow / npx errors in logs | npm download on session spawn — check egress netpol + npmjs reachability; pinned version yanked? |
| pod OOMKilled (137) / `AppContainerMemoryNearLimit` | child-process pile-up. Confirm supergateway is >= 4.0.0 (3.4.3 leaks one child per request) and still stateless; compare `Non-initialize message detected` with `Child exited` counts in VictoriaLogs, they should match |
| log `Failed to send to StreamableHttp ... No connection established for request ID` | a client hung up before its response was ready. Harmless on 4.0.0 (logged, gateway survives); on 3.4.3 it exited the whole gateway (VIK-314) |

**Client etiquette**: keep parallel calls to a handful (each one is a live child process; the
limit covers ~10 large ones at once), and re-`init()` on 404/410/503. Client hang-ups no longer
take the bridge down (supergateway 4.0.0).
