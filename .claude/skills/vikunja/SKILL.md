---
name: vikunja
description: CRUD Vikunja projects/tasks/labels through the in-cluster `vikunja` MCP (mcp-vikunja bridge). The Vikunja "Homelab Roadmap" board is the roadmap system of record (ADR-0043) — label taxonomy, priority mapping, and ticket lifecycle live here.
when_to_use: Use when creating/updating/completing/listing Vikunja tasks or tickets, asking "what's on the roadmap/board", "make a ticket for X", adding a backlog item, or when the vikunja MCP fails to connect / returns 401 / needs its token rotated.
---

# Vikunja — the roadmap board, via MCP

## Connect

- MCP server `vikunja` in `.mcp.json` → `kubernetes/apps/vikunja/mcp-vikunja/` (LAN-only, **write-capable** — it acts as Ryan's Vikunja user).
- Tool schemas are deferred: `ToolSearch "select:mcp__vikunja__tasks_list,mcp__vikunja__task_create"` (etc.) before calling. Full tool catalog (live-verified names), response formats, bridge internals + token bootstrap/rotation → [reference.md](reference.md).
- Tools return **formatted text, not JSON**: creates report `ID: <n>`; list entries end `[ID: <n>, Project: <m>]`.

## The board is the roadmap (ADR-0043)

Project **`Homelab Roadmap`** holds the backlog (~100 open, maintained by `roadmap-topup`;
`docs/techdocs/docs/general/roadmap.md` no longer exists). Conventions:

| Concept | Convention |
|---|---|
| Priority P0/P1/P2/P3 | task `priority` 5/4/3/2 (Vikunja shows 4+ as "Urgent") |
| Impact / Effort | labels `impact/H|M|L` · `effort/S|M|L` |
| Theme | label `theme/<kebab-slug>` + first line of the description |
| Top of the stack | label `do-next` (≤10 tickets) |
| Lifecycle | `needs-refinement` → `ready` (Definition of Ready — `vikunja-refiner` skill) → `task_complete` |
| Description | HTML (TipTap); first paragraph = `<p><strong>theme</strong> — <code>[P · I · E]</code></p>` |

- **New ticket**: `task_create` (title + priority + description first-paragraph) →
  `labels_bulk_set_on_task` (theme/impact/effort + `needs-refinement`). Refinement is a separate
  pass, not inline.
- **Completing**: `task_complete` + a closing comment citing the commit/evidence. Vikunja has no
  trash — deletes stay soft (server safe mode: `project_delete`→archive, `task_delete`→complete,
  `label_delete`→blocked).
- Titles are plain identifiers — editable, but other tickets/comments reference them by title, so
  rename with reason, not casually.

## Gotchas

- **401 / auth errors** → the API token expired or was rotated: rotation steps in [reference.md](reference.md). Token is seeded by a human (agent can't write OpenBao — external-secrets skill).
- **`tasks_list` results are one server page** (`maxitemsperpage`, raised to 250 in the vikunja HelmRelease) and `search` matches only within it; the MCP cannot paginate and `limit: 0` falls back to 50. Always sanity-check the reported "Found N" against expected board size; fall back to `task_get` by ID.
- Accounts come from Authentik OIDC (registration disabled) — assignees only work for users who logged in at least once.
- Bulk edits: prefer `tasks_bulk_update` / `labels_bulk_set_on_task` (the latter REPLACES the whole label set) over per-task loops.
