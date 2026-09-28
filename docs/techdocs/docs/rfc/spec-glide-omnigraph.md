# Spec: Glide runs read and write Omnigraph through LiteLLM

Ticket: VIK-1259. Target repo: `webgrip/glide`, app `apps/ploeg`. Cluster side is live as of 2026-09-28
(homelab-cluster commits `a63a6182`, `983e9a7d`).

## 1. What already exists (cluster side, verified live)

| Piece | Value |
|---|---|
| Omnigraph actor | `act-glide`, on graphs `memory`, `brain`, `webgrip` |
| Policy | read on any branch; `change` only on unprotected branches; `branch_create` and `branch_delete` on unprotected; `invoke_query`. No `branch_merge`, no `export`. `main` is protected on all three |
| LiteLLM MCP servers | `omnigraph_glide_memory`, `omnigraph_glide_brain`, `omnigraph_glide_webgrip` (stdio bridge `@modernrelay/omnigraph-mcp`, 15 tools each) |
| Access group | `glide` (all three servers) |
| MCP endpoint | `http://litellm.ai.svc.cluster.local:4000/mcp/` (streamable HTTP, `Authorization: Bearer <key>`) |
| Tool names through `/mcp/` | `<server>-<tool>`, e.g. `omnigraph_glide_brain-query`, `omnigraph_glide_memory-branches_create` |
| Tools per server | `health`, `snapshot`, `query`, `schema_get`, `branches_list`, `graphs_list`, `commits_list`, `commits_get`, `commits_changes`, `changes_poll`, `mutate`, `load`, `branches_create`, `branches_delete`, `branches_merge` |
| Network | LiteLLM `:4000` already admits namespace `ploeg` |

Live proof on 2026-09-28 (per graph, through LiteLLM as `act-glide`): read `main` OK; `branches_create glide/probe`
from `main` OK; `mutate` on `glide/probe` OK (1 node); `mutate` on `main` 403; `branches_merge glide/probe -> main` 403;
`branches_delete glide/probe` OK; every graph back to `["main"]`.

A key minted on LiteLLM 1.102.1 with
`{"key_type":"llm_api","models":["no-default-models"],"object_permission":{"mcp_access_groups":["glide"]}}` saw
exactly the three glide servers (45 tools) on `/mcp-rest/tools/list`, and `initialize` on `/mcp/` answered 200.
`/mcp`, `/mcp/`, `/mcp/{subpath}` and `/mcp-rest/*` are in LiteLLM's `llm_api_routes`, so Ploeg's existing
`key_type: "llm_api"` keeps working for MCP.

**What the policy cannot do.** Omnigraph policy scopes by protected vs unprotected, not by branch prefix. `act-glide`
can write and delete any unprotected branch, including another run's `glide/*` branch or an `ingest/*`/`agent/*`
branch on the same graph. The `glide/<run-id>` rule holds only by convention: the prompt, the tool descriptions and
the tests below. Merging into `main` is structurally impossible for the agent: Ryan merges after review.

## 2. Credential: mint with the `glide` MCP group

### 2.1 `pkg/litellm.MintRequest`

Add one field. The LiteLLM 1.102.1 field is `object_permission`, an object whose `mcp_access_groups` is a list of
strings (the same shape `homelab-cluster/kubernetes/apps/ai/litellm/keys/app/register-key.sh` uses).

```go
type ObjectPermission struct {
	MCPAccessGroups []string `json:"mcp_access_groups,omitempty"`
}

type MintRequest struct {
	KeyType          string            `json:"key_type,omitempty"`
	KeyAlias         string            `json:"key_alias"`
	MaxBudget        float64           `json:"max_budget,omitempty"`
	Models           []string          `json:"models,omitempty"`
	Duration         string            `json:"duration,omitempty"`
	ObjectPermission *ObjectPermission `json:"object_permission,omitempty"`
}
```

Send `object_permission` only when the group list is non-empty. A key without it sees an empty tool list
(`require_key_mcp_access_defined`), which is today's behaviour, so runs without the grant are unchanged.

### 2.2 `pkg/llmbroker.MintRequest`

Add `MCPAccessGroups []string`. `LiteLLM.Mint` maps it to `litellm.MintRequest.ObjectPermission`. `Static` ignores it.

### 2.3 Where the groups come from

Two mint paths exist, and both need the field:

1. **Managed** (deployed today: `executor.workerAuth.mode: managed`). ploegd mints in
   `pkg/httpapi/llm_control.go` from `LLMPolicy` records rendered by the chart into `PLOEG_WORKER_LLM_POLICIES`.
   - Add `MCPAccessGroups []string \`json:"mcpAccessGroups,omitempty"\`` to `LLMPolicy`.
   - Persist it on the account: add `MCPAccessGroups []string` to `store.LLMAccount` plus a migration adding a
     `mcp_access_groups text[] not null default '{}'` column to the LLM accounts table. `Reserve` writes it from the
     policy, `issue` passes it to `Broker.Mint`. Persisting (not re-reading the policy at issue time) keeps a
     reserved account's grant stable across a ploegd config change, the same reason `Models` is persisted.
   - Chart: `_worker_control.tpl` adds `"mcpAccessGroups" ($role.mcpAccessGroups | default $team.mcpAccessGroups | default list)`
     to each rendered policy; add `mcpAccessGroups` to `values.schema.json` for teams and roles
     (array of `^[a-z0-9-]+$` strings) and document it in `docs/reference/configuration.md` and
     `configuration-descriptions.yaml`.
2. **Unmanaged** (worker mints directly, `pkg/worker/worker.go` `runAgent`). Add `PLOEG_LLM_MCP_ACCESS_GROUPS`
   (comma-separated) to `cmd/ploeg-worker/main.go` → `Config.LLMMCPAccessGroups` → `llmbroker.MintRequest`.

Only teams and roles that should touch Omnigraph get `mcpAccessGroups: [glide]`. Do not default it on.

## 3. Hand the MCP server to the harness

### 3.1 Harness-neutral contract

Add to `harness.RunEnv`:

```go
type MCPServer struct {
	Name    string
	URL     string
	Headers map[string]string
}

type RunEnv struct {
	MCPServers []MCPServer
}
```

`runAgent` fills it after the mint (and after key isolation), only when the run's grant is non-empty:

```go
harness.MCPServer{
	Name:    "omnigraph",
	URL:     mcpURL,
	Headers: map[string]string{"Authorization": "Bearer " + harnessKey},
}
```

- **Without key isolation:** `mcpURL` is the LiteLLM root plus `/mcp/`. Derive it from `Config.LLMBaseURL` by
  dropping the path (`http://litellm.ai.svc.cluster.local:4000/v1` → `http://litellm.ai.svc.cluster.local:4000/mcp/`).
  Add `PLOEG_LLM_MCP_URL` as an explicit override; do not guess when the base URL has an unexpected path.
- **With key isolation** (deployed: `executor.litellm.keyIsolation: proxy`, homelab `da9a1917`): the harness holds
  the placeholder, and the loopback proxy in `pkg/worker/llmproxy.go` swaps `Authorization` for the real key on every
  path. `mcpURL` is the proxy's root plus `/mcp/`. The proxy's `baseURL` today carries the upstream path (`/v1`), so
  add a `rootURL` field to `llmKeyProxy` (`"http://" + ln.Addr().String()`) and build the MCP URL from it. The header
  value is the placeholder, never the minted key.
- The Bearer header is the credential. Never put it in argv or a log line; see 3.2.

### 3.2 Adapters

**claude-code** (`pkg/harness/adapters/claudecode/claudecode.go`). It already passes `--strict-mcp-config`, which
makes Claude Code ignore every MCP config except those passed on the command line, so a target repository's
`.mcp.json` cannot add servers. Keep that flag. When `env.MCPServers` is non-empty:

- Write `mcp.<trace>.json` under `env.ScratchDir`, mode `0600`:

  ```json
  {"mcpServers": {"omnigraph": {"type": "http", "url": "<url>", "headers": {"Authorization": "Bearer <key>"}}}}
  ```

- Append `--mcp-config <path>` to argv. The file path is in argv, the key is not.
- Remove the file on a previous run's name before writing (same rule as the drop box).

**acp** (`pkg/harness/adapters/acp/acp.go`, `NewSession` with `McpServers: []sdk.McpServer{}`). With
`github.com/coder/acp-go-sdk v0.13.5`:

```go
sdk.McpServer{Http: &sdk.McpServerHttpInline{
	Type:    "http",
	Name:    "omnigraph",
	Url:     url,
	Headers: []sdk.HttpHeader{{Name: "Authorization", Value: "Bearer " + key}},
}}
```

HTTP MCP is only valid when the agent's `initialize` response has `agentCapabilities.mcpCapabilities.http == true`.
If the grant is non-empty and the agent does not advertise it, fail the run as stuck with a clear reason
(`"acp agent does not support HTTP MCP servers; this role needs Omnigraph"`) instead of starting a session that
silently lacks the tools. Keep `McpServers` empty when the grant is empty.

**openhands** (the deployed default harness). The adapter only writes `task.md` and runs the agent-runner image's
`docker-entrypoint.sh`. OpenHands reads MCP servers from its `config.toml`:

```toml
[mcp]
shttp_servers = [{ url = "<url>", api_key = "<key>" }]
```

Verify against the OpenHands version pinned in the agent-runner image that `api_key` is sent as
`Authorization: Bearer <key>` before shipping. If it is sent under another header, LiteLLM will answer 401 and the
fallback is a placeholder-aware header in the key proxy. The adapter writes the file under `env.ScratchDir` (mode
`0600`) and points the entrypoint at it; the entrypoint change lives in the agent-runner repo and is a separate
ticket.

**exec** (`execbin`). Expose `PLOEG_MCP_URL` and `PLOEG_MCP_AUTHORIZATION` in `ExtraEnv` only when the grant is
non-empty. An exec harness is operator-written and may use them or not.

## 4. Tell the agent its branch

The Omnigraph branch is `glide/<trace-id>`, where the trace id is the existing non-secret `ploeg-<12hex>`
(`litellm.Alias(runToken)`, already `spec.TraceID`). Example: `glide/ploeg-3f9a0c1b2d4e`. Never derive it from the
run token itself: the run token is a credential.

Add `writeOmnigraphContract(&b, spec)` in `pkg/worker/task.go`, called from `ComposePrompt` and
`ComposePlannerPrompt` only when the run has MCP servers. Text:

```markdown
## Knowledge graphs (Omnigraph)

You have MCP tools for three graphs: omnigraph_glide_memory (shared agent memory), omnigraph_glide_brain
(Ryan's second brain) and omnigraph_glide_webgrip (Webgrip company meetings).

- Read `main` freely with the `query`, `snapshot`, `schema_get` and `commits_*` tools.
- Before your first write to a graph, create the branch glide/ploeg-3f9a0c1b2d4e from main with that graph's
  `branches_create` tool (name "glide/ploeg-3f9a0c1b2d4e", from "main"). Pass branch "glide/ploeg-3f9a0c1b2d4e" to
  every `mutate` and `load`.
- Write nowhere else. Writes to main are refused. Do not touch any other branch.
- Never call `branches_merge`. Ryan reviews your branch and merges it.
- If the branch already exists, you are resuming this run: keep writing to it.
- Report the graphs you wrote to in your outcome summary so the reviewer knows which branches to open.
```

A reading Run (`writes == false`) gets the read bullets only. It still may not write, because the prompt says so and
its outcome is prose; the policy alone would let it write an unprotected branch.

## 5. Branch lifecycle

- A run's branches stay open after the run for Ryan's review. Ploeg does not delete them on success.
- On a run that ends `stuck`, `failed` or cancelled, the worker deletes `glide/<trace>` on every graph where it
  exists (`branches_list`, then `branches_delete`), using the run key before revoke. Best-effort; log, never fail
  the settlement on it.
- Open `glide/*` branches block every schema change on that graph (homelab runbook `runbooks/omnigraph.md`,
  "Open glide/* branches block schema changes"). A ploegd sweep that lists `glide/*` branches older than 7 days and
  reports them (metric `ploeg_omnigraph_open_branches{graph}` or a log line) is follow-up; the cluster has no probe
  for branch age today.

## 6. Tests

| Package | Test | Asserts |
|---|---|---|
| `pkg/litellm` | `TestMintSendsObjectPermissionWhenGroupsGiven` | request body has `"object_permission":{"mcp_access_groups":["glide"]}` |
| `pkg/litellm` | `TestMintOmitsObjectPermissionWithoutGroups` | no `object_permission` key at all |
| `pkg/llmbroker` | `TestLiteLLMMintPassesMCPAccessGroups` | broker maps the field through |
| `pkg/httpapi` | `TestLLMControlIssuesPolicyMCPGroups` | policy `mcpAccessGroups` → reserved account → mint request |
| `pkg/store` | migration test | column exists, default empty, round-trips |
| `pkg/worker` | `TestRunAgentPassesMCPServerWithRunKey` | `env.MCPServers[0]` has the minted key without isolation |
| `pkg/worker` | `TestRunAgentMCPServerUsesProxyPlaceholder` | with `KeyIsolationProxy`: URL is `http://127.0.0.1:<port>/mcp/`, header carries the placeholder, the proxy forwards `/mcp/` with the real key (use an `httptest` upstream that records the header) |
| `pkg/worker` | `TestRunAgentNoMCPServerWithoutGrant` | empty grant → empty `MCPServers` |
| `pkg/worker` | `TestComposePromptNamesGlideBranch` | prompt contains `glide/<trace>`, "Never call `branches_merge`", and no run token |
| `pkg/worker` | `TestComposePromptOmitsOmnigraphWithoutGrant` | section absent |
| `claudecode` | `TestPrepareWritesMCPConfigFile` | argv has `--strict-mcp-config` and `--mcp-config <path>`, argv never contains the key, file mode `0600`, JSON shape as in 3.2 |
| `claudecode` | `TestPrepareWithoutMCPServers` | no `--mcp-config` |
| `acp` | `TestNewSessionSendsHTTPMCPServer` | with a fake agent advertising `mcpCapabilities.http`, `session/new` carries one `type: http` server with the header |
| `acp` | `TestNewSessionRefusesWithoutHTTPCapability` | grant present, capability absent → stuck report, no session |
| `openhands` | `TestPrepareWritesMCPToml` | TOML shape, mode `0600` |
| chart | `helm template` golden | a role with `mcpAccessGroups: [glide]` renders it into `PLOEG_WORKER_LLM_POLICIES` |

One end-to-end check after deploy: a run on a role with `mcpAccessGroups: [glide]` creates `glide/<trace>` on the
graph it touches, `branches_list` shows it, and `main`'s commit id on that graph is unchanged.

## 7. Out of scope

- Any change in `homelab-cluster` beyond enabling `mcpAccessGroups: [glide]` on the chosen Glide roles in
  `kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml` once the chart ships the field.
- Client graphs (`client-*`). `act-glide` must never be added to one: the policy validator fails when one actor
  spans two client graphs, and the runbook's "Add a client" step drops the `glide` group from the copied policy.
