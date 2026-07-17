# mcp-vikunja — the write-capable Vikunja MCP bridge

Instance operations for the `vikunja` MCP server. The product-owner *role* (conventions, DoR,
refinement, prioritization) is the `vikunja-product-owner` skill from the `webgrip-ai-skills`
plugin; the board contract lives in [AGENTS.md](https://github.com/webgrip/homelab-cluster/blob/main/AGENTS.md).

## Bridge internals

`kubernetes/apps/vikunja/mcp-vikunja/` — a `supercorp/supergateway` Deployment (ns `vikunja`)
bridging the stdio-only npm server `@aimbitgmbh/vikunja-mcp` (pinned in `deployment.yaml` args) to
streamable HTTP at `https://mcp-vikunja.${SECRET_DOMAIN}/mcp` (envoy-internal,
external-dns-excluded, LAN-only, no client auth — same trust model as the other MCPs, but this one
**writes**, acting as the token owner's Vikunja user).

- Talks to Vikunja in-cluster: `http://vikunja.vikunja.svc.cluster.local:3456/api/v1` (the
  `/api/v1` suffix is required by vikunja-mcp).
- `--stateful`: one npx child per MCP session; the first session after a pod restart downloads the
  npm package (internet-egress carve-out in `app/networkpolicy.yaml`), later spawns hit the `/tmp`
  cache. Idle sessions are reaped after 15 min (`--sessionTimeout 900000`) — an expired client
  gets a 404 and must re-initialize. **Without the timeout, accumulated sessions OOMKilled the pod
  (2026-07-12, exit 137 at 512Mi; limit now 768Mi).**
- Hard-delete opt-ins: `ENABLE_LABEL_DELETE=true` is set (label deletes only unlink metadata;
  needed for duplicate-label dedup). `ENABLE_{PROJECT,TASK}_DELETE` stay unset (soft mode:
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
| pod OOMKilled (137) | session leak — confirm `--sessionTimeout` still in the deployment args |
