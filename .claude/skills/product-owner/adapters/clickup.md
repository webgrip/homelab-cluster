# ClickUp adapter — MCP mechanics (instance-independent)

Tools `mcp__clickup__clickup_*`; schemas are deferred: `ToolSearch
"select:mcp__clickup__clickup_get_list,mcp__clickup__clickup_create_task"` before calling.
Workspace/space/list ids, status sets, custom-field catalogs and tag sets are **instance
facts** — the Board contract carries them (or you resolve them live); this file carries
only behavior that holds on any ClickUp workspace.

## How the generic concepts map here

| Skill concept | ClickUp realization |
|---|---|
| Ticket body | `markdown_description` (create and update) — **markdown, not HTML**; sending HTML gets you literal tags |
| Skeleton headings | `##` markdown headings; criteria as `- [ ] …` (not in ClickUp's documented list but round-trips and renders as a checklist). A horizontal rule `---` needs a **blank line above it** — text directly above turns into a heading (CommonMark setext). No collapsible/toggle block via the API — `/toggle` is UI-only |
| Status/stage | real ClickUp statuses, **per list** — `clickup_get_list {list_id}` returns that list's own set; never assume two lists share one |
| Priority | a word — `urgent\|high\|normal\|low` (+ `none` on update to clear), not the API's integer. Mapping: urgent=P0, high=P1, normal=P2 |
| Taxonomy | tags (must already exist in the space — an unknown tag is **silently dropped**) + space-scoped custom fields (dropdowns take the **option UUID** as `value`, not the label) |
| Dependencies | `clickup_add_task_dependency {task_id: <blocked>, depends_on: <blocker>, type: "waiting_on"}` — never prose; check with `clickup_get_task {include:["dependencies"]}` |
| Estimate | `time_estimate` in **minutes as a string**: `"150"` = 2h30 |
| Children | `clickup_create_task {parent: <parent-id>}` |
| Commit trailer | `Refs CU-<task-id>` (the short id from `app.clickup.com/t/<id>`) |
| Cross-reference | full URL `https://app.clickup.com/t/<task-id>` in descriptions and comments; a markdown link when you need inline label text |
| Reading a description | **`include: ["description"]`, always.** Without it `markdown_description` is silently cut at 10k chars and ends `[truncated]` — writing that back deletes every section past the cut |

## Resolving this board's vocabulary

`clickup_get_list {list_name}` or `clickup_get_workspace_hierarchy` → the list id (**ask
which one** when the name is ambiguous — "the backlog" can match dozens);
`clickup_get_list {list_id}` → *that* list's statuses; `clickup_get_custom_fields
{space_id}` → which fields exist there.

**Status *types* vs meaning**: every status has a ClickUp type (open/unstarted/custom/done/
closed). Teams routinely keep type-"done" statuses (e.g. `merged`, `testing`, `carryover`)
that their working agreement treats as intermediate stations — ClickUp's own filters and
widgets count them as done-group anyway. Any completion count must use the agreement's real
finished status alone and say that it did. The same status name can even have different
types on different spaces (e.g. `carryover` done-typed on one, custom on another) —
cross-space queries must not assume one model.

## The payload trap

`clickup_get_task {include:["custom_fields"]}` returns every field *definition* with its full
option catalog — **98% of a 70k-char response** was dropdown options, none of them set.
`clickup_get_custom_fields {space_id}` is likewise ~67k chars.

- Resolve field and option ids **once per session** (from the contract, else one
  `clickup_get_custom_fields` call) and reuse them.
- Both calls exceed the tool output cap and get written to a file — read with `jq` or a small
  `python3` filter, never with a line-based read.
- Never put `include:["custom_fields"]` inside a loop over tasks.

## Descriptions replace, reads come first

`markdown_description` **replaces the entire description**. Read the current one first
(`clickup_get_task {include:["description"]}`), merge, then write — a blind write destroys
whatever a colleague wrote. ClickUp *checklists* are a separate object the MCP cannot create;
acceptance criteria live in the description as markdown.

## Markdown on the round trip

What `markdown_description` gives back is not what you sent: bullets come back as
`*   `, a horizontal rule as `* * *`, an `N.` that is not a list item as `N\.`, a hyphen after inline code as `\-`,
a bare URL as a markdown link to itself, and a bare file name ending in a TLD-like suffix
(`CLAUDE.md`, `README.md`) **as a link to `http://CLAUDE.md`**. So: put file names in
backticks, and on read → merge → write keep the escapes as they are rather than
escaping again.

**A fenced code block strips links from the paragraphs just above it** —
named and bare links alike come back as plain text, without the URL. Quote prose with `>`, keep
links out of the paragraphs right before a fence, and after every description write
read it back and check that each URL you sent is still there.

## Pagination

| Tool | Page size | Continue with |
|---|---|---|
| `clickup_filter_tasks` | 100 | `has_more` → call again with `page: next_page` |
| `clickup_search` | caller's `count` | `next_cursor` → pass as `cursor` |
| `clickup_get_bulk_tasks_time_in_status` | 100 ids per call | chunk the id list yourself |

One call is not the board. Loop until exhausted before quoting any count. Naming a
done/closed status explicitly in `statuses` returns those tasks without `include_closed`;
`include_closed` matters for queries that don't name statuses.

## Time in status (flow-metrics source)

`clickup_get_task_time_in_status` / `..._bulk_...` need the **"Total time in Status"
ClickApp**. `since` is a millisecond epoch **string**; `total_time_minutes` an integer.
History covers only statuses the task actually visited since tracking began — a
single-entry history means "no measured start", not zero.

Save the raw tool output to files and feed it straight to
[../scripts/flow_metrics.py](../scripts/flow_metrics.py) (`--tasks open.json done.json
--status-history history.json`) — no normalization step; usage and interpretation in
[../flow.md](../flow.md).

## Other behaviours worth knowing

- ClickUp's public docs say the Update Task endpoint doesn't handle custom fields; the MCP's
  `custom_fields` parameter works anyway (it uses the dedicated set-field route). Trust the
  tool, not that sentence.
- Task templates (`/temp`, named per space) are UI-only — no MCP tool applies one; write the
  skeleton from [../refine.md](../refine.md) yourself.
- `clickup_get_task` takes custom ids (`DEV-1234`) as well as the short id; boards with
  `custom_id: null` use the short id from the URL.
- Deletion is real (`clickup_delete_task`) — prefer a rejected/won't-do status with a reason
  comment; ask before deleting anything.
- Comments: `clickup_create_comment {entity_type:"task", entity_id, comment_text}` renders
  markdown — unless you @mention someone, which forces plain text.
- Two ways into a sprint list: `clickup_move_task` changes the *home* list;
  `clickup_add_task_to_list` keeps the backlog as home and adds the sprint list alongside
  (needs the **Tasks in Multiple Lists** ClickApp; without it, move is the only option).
