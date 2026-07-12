---
name: vikunja
description: CRUD Vikunja projects/tasks/labels through the in-cluster `vikunja` MCP (mcp-vikunja bridge), and the roadmap↔Vikunja mapping that mirrors docs/techdocs/docs/general/roadmap.md onto a real ticket board.
when_to_use: Use when creating/updating/completing/listing Vikunja tasks or tickets, syncing the roadmap to the Vikunja board, "make a ticket for X", "what's on the board", or when the vikunja MCP fails to connect / returns 401 / needs its token rotated.
---

# Vikunja tickets via MCP

## Connect

- MCP server `vikunja` in `.mcp.json` → `kubernetes/apps/vikunja/mcp-vikunja/` (LAN-only, **write-capable** — it acts as Ryan's Vikunja user).
- Tool schemas are deferred: `ToolSearch "select:mcp__vikunja__tasks_list,mcp__vikunja__tasks_create"` (etc.) before calling. Full tool catalog + bridge internals + token bootstrap/rotation → [reference.md](reference.md).
- Deletes are soft (server safe mode): `project_delete` archives, `task_delete` completes, `label_delete` is blocked. Vikunja has no trash/undo — keep it that way; close tickets with `task_complete`.

## Roadmap ↔ board mapping (the point of this skill)

One Vikunja project **`Homelab Roadmap`** mirrors the open items of `docs/techdocs/docs/general/roadmap.md` (SoT for *content* stays git; Vikunja is the execution board).

| roadmap.md | Vikunja |
|---|---|
| item title (text after `N. `, before ` — [`) | task title, verbatim — **the match key** |
| Priority P0/P1/P2/P3 | task `priority` 5/4/3/2 |
| Impact H/M/L · Effort S/M/L | labels `impact/H` … `effort/L` |
| theme heading the item sits under | label `theme/<kebab-slug>` + first line of task description |
| listed in **▶ Do next** | label `do-next` |
| moved to **✅ Done log** | `task_complete` |

**Never key on the `#NN` ordinal** — `roadmap-topup` renumbers all 100 items every run; titles are the stable identity. Put ordinals nowhere (not in titles, not in descriptions).

## Sync procedure (idempotent reconcile)

1. `projects_list` → find `Homelab Roadmap` (`project_create` once, description pointing at `docs/techdocs/docs/general/roadmap.md`).
2. `tasks_list` for that project **including done**; index by exact title.
3. Parse roadmap.md's open items. Then, per title:
   - missing on board → `tasks_create` with priority/labels/description per the table;
   - present but tags/priority/do-next drifted → `tasks_update` / label tools (roadmap.md wins);
   - open on board but item moved to Done log or vanished from the 100 → `task_complete`.
4. **Reverse signal:** tasks completed *on the board* while still open in roadmap.md — don't reopen; report them as done-candidates for the next `roadmap-topup` run.
5. Report counts (created/updated/completed/reverse-flagged); paste nothing secret — the MCP already authenticates server-side.

## Gotchas

- **401 / auth errors** → the API token expired or was rotated: rotation steps in [reference.md](reference.md). Token is seeded by a human (agent can't write OpenBao — external-secrets skill).
- Vikunja `priority` scale is 0–5 (5 = "DO NOW"); the mapping above deliberately leaves 0–1 unused.
- Accounts come from Authentik OIDC (registration disabled) — assignees only work for users who logged in at least once.
- Bulk edits: prefer `tasks_bulk_update` / `labels_bulk_set_on_task` over per-task loops.
