# product-owner

Run any ticket board as product owner — one discipline, per-tool adapters. Ticket
intake, refinement to a research-backed Definition of Ready, binary acceptance criteria
with verification, an **agent-ready gate** for work AI coding agents execute,
prioritization and pick-up ordering, WIP limits anchored on review capacity, dependency
sequencing, splitting, backlog sweeps, a **Definition of Mergeable** gating every PR/MR
before it lands, evidence-based closing on a Definition of Done, and flow metrics (Work
Item Age, Cycle Time, Throughput, SLE).

The skill carries the **role** (loop, gates, heuristics, protocols — every major rule
traced to 2026 evidence in `rationale.md`). Adapters carry the **tool mechanics**
(Vikunja MCP, ClickUp MCP — both verified live). Your contract layers carry the
**instance facts** — template and layer shapes in `contracts.md`, philosophy in
[docs/contract-pattern.md](../../docs/contract-pattern.md). Instance *operations* (MCP
deployment, token rotation) stay in your instance's ops runbook.

It consolidates and supersedes the earlier `vikunja-product-owner` plugin (this repo).
**This skill is the parent-most source of the PO craft**: org estates vendor it as-is
(pinned + sync-checked) and layer their facts in
as a `product-owner-contract` sibling skill; craft improvements land here, once, for
every downstream.

## Install

**Claude Code plugin** — wires the webgrip `vikunja` MCP server for you:

```json
// .claude/settings.json
"enabledPlugins": { "product-owner@ai-skills": true }
```

The bundled `.mcp.json` points at LiteLLM's MCP gateway `https://litellm.webgrip.dev/mcp/` (needs
`LITELLM_MCP_KEY`, a key with the board access group; tools appear as `vikunja-<tool>`); a
repo- or user-level `mcpServers` entry named `vikunja` overrides it, so give a server for
another Vikunja instance its own name. ClickUp boards: add your own
ClickUp MCP server to the consuming repo's `.mcp.json`. Scripts override via
`VIKUNJA_MCP_URL`.

**`npx skills`** — works in every agent, but registers no MCP server; add one yourself:

```bash
npx skills add https://forgejo.webgrip.dev/webgrip/ai-skills.git -s product-owner -g
```

## Board contract

The skill pins the context, then merges four contract layers (repo file → `AGENTS.md`
block → user contexts → org contract skill), most specific fact wins. The template and
what each layer's file looks like ship **inside the skill**: `contracts.md`. Facts go
in contracts; a genuinely different per-team *procedure* is a team overlay skill in the
org's estate. Without any layer, the skill inspects the connected MCP, lists
projects/boards, and asks.

## Example prompts

- "make a ticket for the flaky backup job" · "maak een ticket voor de trage pipeline"
- "what should we work on next?" · "refine the next 10 tickets" · "split this, it's too big"
- "is this ticket ready for an agent to pick up?" · "prepare these tickets for Copilot/Claude"
- "run a board-health audit" · "what's our cycle time — can we state an SLE?"
- "is dit ticket klaar voor de sprint?" · "groom the customer backlog"
- "is PR #87 mergeable?" · "the agent's PR is green, merge it" · "mag deze MR gemerged worden?"

## Files

`SKILL.md` (role core: contract resolution, loop, skeleton, gates, DoD, invariants) ·
`refine.md` (refinement execution: interview, criteria craft, EARS, templates,
splitting, triage, bulk fan-out, antipattern gallery) · `agents.md` (AI-executor layer:
agent-ready gate, claim/evidence/accept, risk tiers, anti-reward-hacking) · `merge.md`
(Definition of Mergeable: criteria, forge enforcement and traps, agent-authored extras,
merge-check procedure, merge folklore) ·
`playbook.md` (operation recipes incl. prioritization and queue ops) · `flow.md` (flow
metrics + SLE) · `contracts.md` (contract template + layer file shapes) ·
`rationale.md` (the 2026 evidence base, sourced) · `adapters/vikunja.md` +
`adapters/clickup.md` (tool mechanics) · `scripts/ticket_lint.py` (offline
DoR/agent-ready gate check, EN+NL, markdown+HTML) · `scripts/merge_check.py` (offline
mechanical half of the DoM, reads git only) · `scripts/flow_metrics.py` (offline
flow metrics — raw ClickUp payloads via `--tasks`, normalized items from any tracker
via `--items`) · `scripts/mcp_client.py` (streamable-HTTP MCP client for bulk work).
