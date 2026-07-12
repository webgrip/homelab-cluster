# Agent guide — homelab-cluster

GitOps homelab: Flux + Talos + Kubernetes. Operating rules, safety hooks, and skills are defined
in [CLAUDE.md](CLAUDE.md) — read it first; it applies to all agents, not just Claude.

## The roadmap lives in Vikunja, not in this repo

The backlog/roadmap is the **`Homelab Roadmap` project on the Vikunja board**, reached through the
`vikunja` MCP server configured in [.mcp.json](.mcp.json) (LAN-only, write-capable). There is no
roadmap file in git — see
[ADR-0043](docs/techdocs/docs/adr/adr-0043-vikunja-roadmap-system-of-record.md).

- **Find work**: `tasks_list` on the Homelab Roadmap project. `do-next` label = top of the stack;
  `ready` label = meets the Definition of Ready (actionable as-is); `needs-refinement` = do not
  start, refine first.
- **Conventions** (labels, priority mapping, lifecycle): the `vikunja` skill
  ([.claude/skills/vikunja/](.claude/skills/vikunja/SKILL.md)).
- **Refining tickets** to the Definition of Ready: the `vikunja-refiner` skill.
- **Topping up / triaging** the backlog: the `roadmap-topup` skill.
- **Completing**: `task_complete` + a closing comment citing the commit/evidence — never claim
  done without the verification the ticket's own Verification section names.

Decisions are still recorded in git (`docs/techdocs/docs/adr/`, `rfc/`); the board holds work
items, not decision records.
