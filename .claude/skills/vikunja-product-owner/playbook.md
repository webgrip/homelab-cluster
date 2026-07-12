# Playbook — exact call sequences for common PO operations

All via MCP tools (or `scripts/mcp_client.py` `call(tool, args)` for bulk). Response parsing:
creates → `ID: <n>`; lists → `[ID: <n>, Project: <m>]`; strip ` (xxxxxx)` from label titles.

## Create a ticket end-to-end

1. `task_create {title, projectId: 3, priority: <5|4|3|2>, description: "<HTML first para: theme + tag>"}`
2. `labels_bulk_set_on_task {taskId, labelIds: [<theme>, <impact>, <effort>, <needs-refinement>]}`
   — REPLACES the whole set; always pass everything.
3. New tickets are `needs-refinement`; refinement ([refine.md](refine.md)) is a separate pass.

## Split an oversized ticket

1. `task_create` each child (inherit theme/impact labels; honest per-child effort).
2. `relation_create {taskId: <parent>, otherTaskId: <child>, relationKind: "subtask"}` per child.
3. `relation_create {taskId: <first>, otherTaskId: <second>, relationKind: "precedes"}` where order matters.
4. Parent keeps the outcome; children carry the ACs. Re-label parent `effort` honestly.

## Close with evidence

1. `comment_create {taskId, comment: "<p>Done: <evidence — commit hash, live check output, link>.</p>"}`
2. `task_complete {id}` — never without the ticket's own Verification satisfied.

## Stale-premise verify-and-close

1. Research says the work already shipped → `task_update` the description: Problem becomes
   "Premise stale — shipped in <commit/date>; remaining work = verify"; ACs become the
   verification checks.
2. Run the checks now if cheap → close with evidence; else leave `ready` as a quick win.

## Board-health audit (invariants from SKILL.md)

With `mcp_client.py`, fetch `tasks_list {projectId: 3, show: "all", limit: 200}` once, then:

- **Count check**: reported "Found N" ≈ expected (~100 open) — pagination sanity.
- **Label coverage**: every open ticket parses `theme/`, `impact/`, `effort/` from its `Labels:`
  line (`task_get` per suspect, or maintain a title→labels map from the list output).
- **do-next ≤ 10**: count tickets whose labels include `do-next`.
- **ready ⇒ DoR**: for `ready` tickets, `task_get` description contains `<h3>Problem</h3>`,
  `data-type="taskList"`, `<h3>Verification</h3>`.
- **Relations**: spot-verify via duplicate-create → expect
  `409: The task relation already exists` (relations never render in `task_get`).

## do-next rebalance

1. List current holders; drop any now-blocked/stale (`label_remove_from_task`).
2. Add highest-leverage unblocked (`label_add_to_task`) up to the cap of 10.
3. Say what changed and why in the run report.

## Bulk relabel / bulk update

- Same label to many: loop `label_add_to_task` (safe, additive).
- Same field to many: `tasks_bulk_update {taskIds: [...], fields: ["priority"], values: {priority: 3}}`.
- Full label-set rewrite: `labels_bulk_set_on_task` with the COMPLETE intended set per task.

## Dedupe sweep

1. Build a title map from the full list; near-duplicates (same outcome, different words) →
   keep the better-refined one.
2. Loser: `comment_create` pointing at the survivor by exact title → `task_complete`
   (soft "closed as duplicate" — `task_delete` only completes anyway; `duplicateof` relation
   optional for the record).
