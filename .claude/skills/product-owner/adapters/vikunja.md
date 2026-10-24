# Vikunja adapter — MCP mechanics (instance-independent)

Tools `mcp__vikunja__*`. Two kinds of MCP server answer to that name, with **different tool
names and argument casing** — identify which one you are talking to before the first
write (next section). Schemas are deferred: `ToolSearch "select:mcp__vikunja__tasks_list,mcp__vikunja__task_create"`
before calling. Instance operations (deployment, token creation/rotation) belong to the
instance's ops runbook — the Board contract points there.

## Two servers, two surfaces

| | **npm surface** | **single-file surface** |
|---|---|---|
| Server | upstream `@aimbitgmbh/vikunja-mcp` behind `supergateway` | a single-file Python MCP server |
| Where | the plugin `.mcp.json` default: LiteLLM's MCP gateway `litellm.webgrip.dev/mcp/` (tools named `vikunja-<tool>`) | a self-hosted HTTP deployment, or stdio on one machine |
| Tell-tale in `tools/list` | `relation_create`, `comment_create`, `tasks_list_all`, `label_add_to_task` | `task_relation_add`, `task_comment_add`, `whoami` |
| Argument casing | camelCase: `projectId`, `taskId`, `otherTaskId`, `relationKind`, `labelId(s)` | snake_case: `project_id`, `task_id`, `other_task_id`, `relation_kind` |

Same operation, both surfaces:

| Operation | npm surface | single-file surface |
|---|---|---|
| List a board | `tasks_list {projectId, show: incomplete\|completed\|all, search}` | `tasks_list {project_id, done, search, filter, page}` |
| Create | `task_create {projectId, title, description, priority}` — no labels | `task_create {project_id, title, description, priority, labels: [titles]}` |
| Labels | `label_add_to_task {taskId, labelId}` / `label_remove_from_task`; `labels_bulk_set_on_task {taskId, labelIds}` | `labels_bulk_set_on_task {task_id, labels: [titles], create_missing}` |
| Dependency | `relation_create {taskId, otherTaskId, relationKind}` | `task_relation_add {task_id, other_task_id, relation_kind}` |
| Comment | `comment_create {taskId, comment}` | `task_comment_add {task_id, comment}` |
| Archive a project | `project_archive {id}` | `project_delete {id}` (archives in safe mode) |

A user- or repo-scoped `mcpServers` entry named `vikunja` **shadows the plugin's**: a
session can be wired to a different instance than the Board contract names, and a "No
token" error then concerns that other server. Check the server's URL before blaming the
token; give a second instance its own name (`vikunja-<instance>`).

## How the generic concepts map here

| Skill concept | Vikunja realization |
|---|---|
| Ticket body | `description`, TipTap **HTML only** — raw markdown renders literally |
| Skeleton headings | `<h3>` sections; criteria as the taskList checkbox markup below; section set per [refine.md](../refine.md)'s templates |
| Status/stage | DERIVED from labels + done, never stored: Backlog (`needs-refinement`) → To Do (`ready`) → Doing (`agent/<name>` claim) → Reviewing (`review`) → Done (completed + DoD). Stock-UI kanban buckets, if used, mirror this — labels are authoritative |
| Priority | P0/P1/P2/P3 → `priority` 5/4/3/2 (Vikunja shows 4+ as "Urgent") |
| Taxonomy | labels: `theme/<kebab>`, `impact/H\|M\|L`, `effort/S\|M\|L`, `time/hours\|days\|weeks`, `uncertainty/low\|med\|high`, `do-next`, `agent-ready`, `agent/<name>` |
| Dependencies | the relation tool of your surface — kinds `precedes`/`follows`/`blocked`/`blocking`/`subtask`/`parenttask`/`related` |
| Pick-up order | the pick-up-queue section in the **project description** (below) — no position tools exist |
| Evidence comment | the comment tool of your surface — TipTap HTML |
| Completion | `task_complete {id}` (agents never complete their own work — [agents.md](../agents.md)) |
| Commit trailer | `<PREFIX>-<taskID>` from the contract (webgrip default `VIK`); bare task URLs autolink in Forgejo/Gitea |
| Cross-reference | full URL `<task web base><taskID>` from the contract, in descriptions and comments |

Titles are **plain text, no links**; rename only with a reason + a comment (others
reference tickets by title).

## HTML description template

Verified round-trip on the webgrip instance: `<h3>`, `<p>`, `<code>`, `<ul>`, and the
checkbox markup survive sanitization; the checklist renders with an x/y counter. Escape
`&` as `&amp;`, shell `<`/`>` as `&lt;`/`&gt;`. 1500–3500 chars. Sections per
[refine.md](../refine.md)'s templates; the load-bearing markup:

```html
<p><strong>&lt;theme&gt;</strong> — <code>[P1 · impact H · effort M · time d · unc low]</code></p>
<h3>Problem</h3><p>… evidence as <code>path/file:12</code> …</p>
<h3>Acceptance criteria</h3>
<ul data-type="taskList">
  <li data-checked="false" data-type="taskItem"><label><input type="checkbox"><span></span></label><div><p>criterion</p></div></li>
</ul>
```

(`data-checked="true"` + `checked` on the input for a pre-ticked box.)

## The pick-up queue (ordering without a position API)

Neither surface orders tasks — UI drag-order is cosmetic, and the npm surface's buckets
are kanban columns, not a queue. The total order lives as `<h3>Pick-up queue</h3>` +
`<ol>` of `<PREFIX>-<id> — title` in the **project description** (top = picked up first;
composition and refresh triggers per [playbook.md](../playbook.md)). A consuming repo's
board UI may rewrite this same section on drag (marker `refreshed <date> (board)`) —
treat whichever write is newest as current and never fight it.

Emitting it: `project_get {id}` → take the current description, replace **only** the
queue section, keep everything else verbatim → `project_update {id, description}` —
naming `description` replaces that whole field. **Verify the extracted description is
non-empty before writing** (a failed extraction clobbers the project description), and
spot-check with `project_get` after.

## Semantics worth knowing

Both surfaces:

- `task_update` / `project_update` **read first — fields you do not name survive.** A
  named `description` still replaces that field wholesale: read → merge → write.
- A bulk label **set** replaces the task's whole label set — read its current labels
  first, merge, then set the complete list. Prefer single-label add/remove where the
  surface has them.
- **Auth is per caller, at the gateway**: every request needs `Authorization: Bearer
  <LiteLLM virtual key with the board access group>`; an anonymous call is refused (401).
  The plugin's `.mcp.json` sends `Bearer ${LITELLM_MCP_KEY}` (export it before launching the
  client); [mcp_client.py](../scripts/mcp_client.py) reads `$LITELLM_MCP_KEY`, else
  `$VIKUNJA_API_TOKEN`, else the file named by `$VIKUNJA_TOKEN_FILE`, and prefixes tool names
  with `vikunja-`; a stdio single-file server reads `VIKUNJA_TOKEN_FILE`. The webgrip direct
  route `mcp-vikunja.webgrip.dev` was closed on 2026-10-17 because it accepted anonymous
  writes.
  Token minting/rotation stays with the instance (the contract's ops-runbook pointer). A
  connect timeout or a name that no longer resolves means the endpoint is unreachable
  from here (VPN/LAN?) or the service is down — also instance ops, and no reason to
  retry in a loop.

npm surface:

- `tasks_list` **needs `projectId`** — without it the call fails with `Vikunja API
  error (400): Invalid model provided`, whatever else you pass; `tasks_list_all` fails
  the same way. Search one board at a time: `{projectId, search, show: "all"}`.
- `page` does not exist and `limit` is ignored: one call returns up to the instance's
  `maxitemsperpage` (250 on webgrip). A board with more tasks than that cannot be listed
  completely — narrow with `search` or `show`, or walk ids with `task_get`.
- `task_create` takes **no labels**: create, read the id from `[ID: n]`, then attach
  each label by **id** (`labels_list {search}` resolves a title to its id). There is no
  create-missing — a label the board lacks stays off; say so instead of creating it.
- `task_get` returns description, priority, done state and **label titles, but no
  relations**. A relation write is confirmed only by the tool's own reply; read
  relations back in the web UI.
- `task_delete`, `project_delete` and `label_delete` advertise no safe mode — treat them
  as real, irreversible deletes. `task_complete` or `project_archive` is almost always
  what was meant.
- `priority` is documented as 0 none, 1 low, 2 medium, 3 high, 4+ urgent.

Single-file surface:

- `task_get` returns the task **with its description and relations**.
- `task_create {labels: [...]}` and `labels_bulk_set_on_task {create_missing}` address
  labels **by title** and can create missing ones.
- Safe-mode deletes: `task_delete` → completes instead, `project_delete` → archives
  instead, `label_delete` → **refuses** (a label delete would strip it instance-wide).
- `tasks_list` returns **ONE server page** — check the reported count against expected
  board size; `page` continues, `filter` takes Vikunja filter syntax, `search` matches
  task text. `projects_list` hides archived unless `include_archived`.

**Flow-metrics normalization** (for [../scripts/flow_metrics.py](../scripts/flow_metrics.py)):
Vikunja records no started timestamp — use `created` from the task and `finished` from
its done date, and label the result the lead-time proxy it is; where the claim protocol
posts a claim comment, that comment's date is the honest `started`.

## Scripted access (bulk work)

Run [../scripts/mcp_client.py](../scripts/mcp_client.py) — minimal streamable-HTTP MCP
client (`init()` + `call(tool, args)`); handles the session-id handshake and SSE
parsing, and works against either HTTP surface. Endpoint: `VIKUNJA_MCP_URL` env, else
the webgrip default baked into the script. Results come back as formatted text, not
JSON — parse ids from `[ID: n]`. Bulk passes: **sequential calls, generous timeouts** —
parallel sessions stress bridged MCP deployments — a threaded sweep has crash-looped a
gateway.

## Tool catalog (indicative — `tools/list` is the truth)

| Area | npm surface | single-file surface |
|---|---|---|
| Tasks | `tasks_list`, `tasks_list_all`, `task_get`, `task_create`, `task_update`, `task_complete`, `task_delete`, `tasks_bulk_update` | `tasks_list`, `task_get`, `task_create`, `task_update`, `task_complete`, `task_delete`* |
| Relations | `relation_create`, `relation_delete` | `task_relation_add` |
| Comments | `comments_list`, `comment_get`, `comment_create`, `comment_update`, `comment_delete` | `task_comment_add` |
| Projects | `projects_list`, `project_get`, `project_create`, `project_update`, `project_archive`, `project_delete`, `project_duplicate` | `projects_list`, `project_get`, `project_update`, `project_delete`* |
| Labels | `labels_list`, `label_get`, `label_create`, `label_update`, `label_delete`, `label_add_to_task`, `label_remove_from_task`, `labels_bulk_set_on_task` | `labels_list`, `label_create`, `label_delete`*, `labels_bulk_set_on_task` |
| Other | assignees, filters, notifications, subscriptions, views, buckets | `whoami` |

\* safe-mode behavior as above. Never call a name `tools/list` did not return.
