# LiteLLM — the metered inference plane

The self-hosted LiteLLM proxy ([ADR-0044](../adr/adr-0044-metered-inference-plane-litellm.md)) is
the single, budgeted front door to LLM providers *and* to the in-cluster MCP servers. Runs in the
`ai` namespace (`kubernetes/apps/ai/litellm/`), backed by a CNPG spend ledger and a Valkey cache.

## Endpoints

| Surface | URL | Auth |
|---|---|---|
| OpenAI-compatible API | `https://litellm.<domain>/v1/...` | virtual key (`Authorization: Bearer`) |
| **MCP gateway (agents)** | `https://litellm.<domain>/mcp` | virtual key — sees only its access group's tools |
| Admin UI | `https://litellm.<domain>/ui` | Authentik SSO (auto-redirect) |

Models come **only from git** (`litellm-config.configmap.yaml`); the Admin UI cannot add one
(`supported_db_objects` limits DB objects to MCP registrations).

## MCP access groups

Registered servers (`mcp_servers:` in the config) and their groups:

| Group | Servers | Capability |
|---|---|---|
| `observability` | grafana, victorialogs, kubernetes, opencost | read-only |
| `board` | vikunja | **write** (task CRUD) |

A key with no explicit MCP grant sees an **empty tool list** (deny-by-default,
`require_key_mcp_access_defined`). Grant on mint via
`object_permission: {mcp_access_groups: ["observability"]}`.

Interactive human use (Claude Code `.mcp.json`) deliberately stays **direct** to the LAN
`mcp-*.<domain>` hostnames — the gateway's per-key scoping and spend attribution is for agents.

## Rules of the road

- Every key mint **requires `key_alias`** (and ideally a team) — anonymous keys are rejected.
- Budgets: SSO-created users get 10 USD/30d automatically; teams default to 25 USD/30d;
  provider daily caps 5 USD (Anthropic) / 2 USD (DeepSeek). Amounts are owner dials in
  `litellm-config.configmap.yaml`.
- Prompts are **not** stored in the spend ledger (recorded privacy posture); spend-log retention 90d.
- Dashboards: Grafana → **AI** folder → *LiteLLM — Inference Spend & Budgets* and
  *LiteLLM — Latency & Reliability*. Traces: Explore → Jaeger datasource, service `litellm`.
