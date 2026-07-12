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
- **Everything board-related** — conventions (labels, priority mapping, lifecycle), Definition-of-Ready
  refinement, prioritization/top-up, and the agent claim/completion protocols — is the
  `vikunja-product-owner` skill
  ([.claude/skills/vikunja-product-owner/](.claude/skills/vikunja-product-owner/SKILL.md)).
- **Completing**: `task_complete` + a closing comment citing the commit/evidence — never claim
  done without the verification the ticket's own Verification section names.

Decisions are still recorded in git (`docs/techdocs/docs/adr/`, `rfc/`); the board holds work
items, not decision records.
