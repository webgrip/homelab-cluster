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
- **Everything board-related** — conventions, Definition-of-Ready refinement, prioritization/top-up,
  and the agent claim/completion protocols — is the `vikunja-product-owner` skill (from
  [`webgrip/ai-skills`](https://forgejo.webgrip.dev/webgrip/ai-skills), installed user-level via
  `npx skills add`). It reads the contract below.
- **Completing**: `task_complete` + a closing comment citing the commit/evidence — never claim
  done without the verification the ticket's own Verification section names.

## Board contract (vikunja-product-owner)

- MCP server: `vikunja` · project: `Homelab Roadmap` (id 3) · instance list cap
  (maxitemsperpage): 250
- Dark-factory work lives in its own project: `Dark Factory` (id 5, since 2026-07-17) — all
  `theme/dark-factory` tickets (agent-execution program, LiteLLM inference plane, MCP gateway,
  agent identity/budgets); same conventions/labels as the main board
- The custom board front end has its own project: `Vellum` (id 6, since 2026-07-18) —
  `theme/vellum` tickets for the board page itself (`kubernetes/apps/vikunja/board`, served at
  `vikunja.<domain>/board`); same conventions/labels as the main board
- CI/CD improvement work lives in its own project: `CI/CD` (id 9, since 2026-07-18) — all
  `theme/ci-cd` tickets (runner pool, image supply chain, pipeline efficiency; mechanics
  reference: docs/techdocs/docs/general/ci-image-flow.md); same conventions/labels as the
  main board. The techdocs *serving* decision stays on Homelab Roadmap (#340)
- Ticket prefix: `VIK` (commit trailers `VIK-<taskID>`; see
  [rfc-dark-factory](docs/techdocs/docs/rfc/rfc-dark-factory.md) for the full agent-execution program)
- Labels: `theme/<kebab>` (security-kyverno-audit-enforce, security-network-containment,
  security-auth-identity, security-pod-hardening, security-supply-chain, security-runtime-detection,
  secrets-endgame, reliability-ha-pdbs-priorities, reliability-backup-dr, reliability-garage,
  observability-alert-delivery, observability-pipeline, observability-programs, storage-tails,
  talos-nodes, flux-gitops-capacity, ci-shift-left, dx-docs-horizon, dark-factory) ·
  `impact/H|M|L` · `effort/S|M|L` · `do-next` (≤10) · `ready` / `needs-refinement` / `agent-ready` ·
  `agent/<name>` (claims)
- **Epics = parent tasks** (since 2026-07-18): a ticket titled `Epic: …` carries `subtask`
  relations to its children and the `meta` label; epics keep theme+impact labels but are EXEMPT
  from effort/lifecycle labels, are never agent-workable themselves, and close only when every
  subtask closes. Wire membership with `relation_create(kind: subtask)` (parent→child); a child
  has at most ONE parent. `theme/*` labels stay the cross-project dimension; the Vellum front
  end renders the hierarchy ("By epic" view with roll-up progress)
- Open target: ≈100 tickets · buckets: Backlog / Ready / In progress (agent) / Review / Done
- **Pick-up order** (since 2026-07-18): each project's **description** carries a
  `Pick-up queue` — an ordered list (`VIK-<id> — title`), **top = picked up first**, covering
  every `do-next` holder plus a next-up tail. Agents take the topmost eligible entry; the PO
  inserts new tickets where they fit and drops entries on close. Vikunja UI drag-order is NOT
  authoritative (the MCP has no position API — see the skill's reference.md)
- Top-up ground truth: `git log --oneline <last-sweep>..HEAD` · `./scripts/posture-counts.sh` ·
  live read-only MCP checks · audit dimensions: security/hardening · reliability/HA/backup-DR ·
  CI/shift-left/DX
- Instance ops (token rotation, bridge/OOM issues):
  [runbooks/mcp-vikunja.md](docs/techdocs/docs/runbooks/mcp-vikunja.md)

Decisions are still recorded in git (`docs/techdocs/docs/adr/`, `rfc/`); the board holds work
items, not decision records.
