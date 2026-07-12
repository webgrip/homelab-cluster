# vikunja MCP — reference

Contents: [Bridge internals](#bridge-internals) · [Token bootstrap / rotation](#token-bootstrap--rotation) ·
[Troubleshooting](#troubleshooting) · [Response formats](#response-formats) · [Tool catalog](#tool-catalog)

## Bridge internals

`kubernetes/apps/vikunja/mcp-vikunja/` — a `supercorp/supergateway` Deployment (ns `vikunja`) that
bridges the stdio-only npm server `@aimbitgmbh/vikunja-mcp` (pinned in `deployment.yaml` args) to
streamable HTTP at `https://mcp-vikunja.${SECRET_DOMAIN}/mcp` (envoy-internal, external-dns-excluded,
LAN-only, no client auth — same trust model as the other MCPs, but this one **writes**).

- Talks to Vikunja in-cluster: `http://vikunja.vikunja.svc.cluster.local:3456/api/v1` (the `/api/v1`
  suffix is required by vikunja-mcp).
- `--stateful`: one npx child per MCP session; first session after a pod restart downloads the npm
  package (internet-egress carve-out in `app/networkpolicy.yaml`), later spawns hit the `/tmp` cache.
- Hard-delete opt-ins `ENABLE_{PROJECT,TASK,LABEL}_DELETE` exist but stay unset (soft mode).
- Bumping the vikunja-mcp version = edit the pinned `@aimbitgmbh/vikunja-mcp@<ver>` in
  `deployment.yaml` args (Renovate doesn't see inside args).

## Token bootstrap / rotation

The bridge authenticates with a personal API token — created by a **human** (agent cannot write
OpenBao, and token creation needs Ryan's Authentik login):

1. Vikunja UI → avatar → **Settings → API Tokens → Create a token**. Grant the route groups the
   tools use: tasks, projects, labels, task comments/assignees/relations, project views, buckets,
   filters, notifications, subscriptions (or simply select all). Pick a long expiry and note it.
2. Seed OpenBao (provided-value flow of the `external-secrets` skill — BAO_ADDR/read-rs footguns
   documented there):
   `bao kv put secret/vikunja/mcp api_token=<token>`
3. ESO syncs `ExternalSecret/mcp-vikunja-token` within 15 min (or force:
   `kubectl -n vikunja annotate externalsecret mcp-vikunja-token force-sync=$(date +%s) --overwrite`);
   reloader restarts the pod on the change.

Rotation = same steps; step 2's `bao kv put` overwrites version-safely.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| pod `CreateContainerConfigError` | token never seeded — `mcp-vikunja-token` Secret missing; do bootstrap above; `refreshTime: null` on the ExternalSecret = never synced |
| MCP tools return 401 | token expired/revoked — rotate |
| `/mcp` connect timeout | not on LAN, or pod not Ready (`mcp__kubernetes__pods_list_in_namespace` ns `vikunja`) |
| first tool call slow / npx errors in logs | npm download on session spawn — check egress netpol + npmjs reachability; pinned version yanked? |
| task ops fail with 403 | token missing that route-group permission — recreate token with wider scope |
| `tasks_list`/`search` misses tasks you know exist | results are one server page (`maxitemsperpage`, raised to 250 in the vikunja HelmRelease) and search matches only within it; the MCP has no page param. `limit: 0` does NOT mean "all" — it falls back to 50. Verify the reported "Found N" against expected board size; fall back to `task_get` by ID |

## Response formats

Verified live against v0.1.0 (2026-07-12). Tools return **formatted text, not JSON**. Parse with these shapes:

- create tools → `Created <thing> "<title>"` then a line `ID: <n>`
- list tools → `Found <N> <thing>(s)` then blocks `<i>. <title>` / detail lines / `[ID: <n>]` (tasks: `[ID: <n>, Project: <m>]`)
- `task_get` → title line, then `Priority: …`, `Labels: <comma-joined>`, `Project ID: <n>` lines
- errors → `isError` content `Error: … Vikunja API error (<code>): …`
- unset due dates render as `Due: 0001-01-01` — not a bug

## Tool catalog

`mcp__vikunja__*`, v0.1.0 — names verified live via tools/list (trust this over the upstream README, whose singular/plural naming is wrong for several tools).

| Area | Tools |
|---|---|
| Tasks | `tasks_list`, `tasks_list_all`, `task_get`, `task_create`, `task_update`, `task_complete`, `task_delete`*, `tasks_bulk_update` |
| Projects | `projects_list`, `project_get`, `project_create`, `project_update`, `project_archive`, `project_delete`*, `project_duplicate` |
| Labels | `labels_list`, `label_get`, `label_create`, `label_update`, `label_delete`*, `label_add_to_task`, `label_remove_from_task`, `labels_bulk_set_on_task` |
| Comments | `comments_list`, `comment_get`, `comment_create`, `comment_update`, `comment_delete` |
| Assignees | `assignees_list`, `assignee_add`, `assignees_add_bulk`, `assignee_remove` |
| Relations | `relation_create`, `relation_delete` |
| Views/Kanban | `views_list`, `view_get`, `view_create`, `view_update`, `view_delete`, `buckets_list`, `bucket_create`, `bucket_update`, `bucket_delete` |
| Filters | `filter_get`, `filter_create`, `filter_update`, `filter_delete` |
| Notifications | `notifications_list`, `notification_get`, `notification_delete` |
| Subscriptions | `subscription_get`, `subscription_create`, `subscription_delete` |

\* soft in safe mode: `project_delete`→archive, `task_delete`→complete, `label_delete`→blocked.
