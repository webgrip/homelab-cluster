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

## Admin UI sign-in

SSO is the only way into the Admin UI. `disable_env_credential_login` refuses the shared
`UI_USERNAME`/`UI_PASSWORD` login and the master key typed as a UI password, and
`disable_password_login_when_sso_enabled` refuses every username/password login while the Authentik
client is configured. Admin rights come from the `litellm_role` claim, which Authentik sets to
`proxy_admin` for `homelab-admins`. If Authentik is down, administer the proxy over the API with
`Authorization: Bearer <master key>`, which neither setting touches. To get UI password login
back, remove both settings and restart the proxy. Keep both: the SSO-only setting switches itself off
when any `GENERIC_*` value is missing from the pod, and the env-credential one still holds then.

Without an Enterprise license, SSO sign-in stops for everyone once `LiteLLM_UserTable` holds more
than 5 rows. `default_user_id` is one of them, and every Authentik user who signs in adds one:
`homelab-admins` through `litellm-admin`, and `homelab-users` through `llm-use`.
`LiteLLMSSOUserCapNear` fires at 5 rows, when the next new user would lock the UI.

## MCP access groups

Registered servers (`mcp_servers:` in the config) and their groups:

| Group | Servers | Capability |
|---|---|---|
| `observability` | grafana, victorialogs, kubernetes, opencost | read-only |
| `board` | vikunja | **write** (task CRUD) |
| `memory` | omnigraph_memory (HTTP, `omnigraph-mcp:8001/mcp`, `act-agent`) | read `memory`, write on its own branches |
| `brain` | omnigraph_brain (HTTP, `omnigraph-mcp:8002/mcp`, `act-brain-agent`) | read and write `brain`, including `main` |
| `glide` | omnigraph_glide_memory, omnigraph_glide_brain, omnigraph_glide_webgrip (HTTP, `omnigraph-mcp:8004`, `:8005` and `:8006`, `act-glide`) | read every branch of `memory`, `brain` and `webgrip`; write only on unprotected branches (`glide/<run-id>`); never merge ([runbooks/omnigraph](../runbooks/omnigraph.md#glide-agents)) |
| `brain-dogfood` | brain_tools (HTTP, `brain-tools:8080/mcp`, `act-brain-reader`) | `search` and `read` over `brain` with plain questions, read-only; the dogfood grant of brain retrieval P4, held by `claude-code` only until P6 regroups it ([runbooks/omnigraph](../runbooks/omnigraph.md#brain-tools)) |
| `brain-eval-raw` | omnigraph_brain_eval (HTTP, `omnigraph-mcp:8003/mcp`, `act-brain-eval`) | read every branch of `brain` and run stored queries; `mutate`, `load` and the branch writes are hidden by `disallowed_tools` and refused by policy. Only the brain eval key holds it, to score today's raw-query chat path as baseline B0 ([runbooks/omnigraph](../runbooks/omnigraph.md#brain-eval)) |

A key with no explicit MCP grant sees an **empty tool list** (deny-by-default,
`require_key_mcp_access_defined`). Grant on mint via
`object_permission: {mcp_access_groups: ["observability"]}`.

Interactive human use (Claude Code `.mcp.json`) deliberately stays **direct** to the LAN
`mcp-*.<domain>` hostnames — the gateway's per-key scoping and spend attribution is for agents.
The Omnigraph graphs are the exception: they have no LAN MCP endpoint of their own, so Claude
Code and Open WebUI reach `memory` and `brain` through the gateway with the keys below
([runbooks/open-webui](../runbooks/open-webui.md#claude-code)).

## Omnigraph bridges

The six `omnigraph_*` servers are the stdio bridge `@modernrelay/omnigraph-mcp` 0.10.0, which has no
HTTP mode. Each runs behind supergateway 4.0.0 as one container of the `omnigraph-mcp` Deployment
([app](../../../../kubernetes/apps/ai/omnigraph-mcp/app/)), and LiteLLM reaches it over streamable
HTTP. LiteLLM itself runs no stdio server, and `LITELLM_ENABLE_MCP_STDIO` is unset, so the proxy
also refuses to register one through its API.

| Server | Container and port | Graph | Token (Secret, OpenBao path) |
|---|---|---|---|
| `omnigraph_memory` | `memory` :8001 | `memory` | `omnigraph-mcp-memory`, `omnigraph/agent` |
| `omnigraph_brain` | `brain` :8002 | `brain` | `omnigraph-mcp-brain`, `omnigraph/brain-agent` |
| `omnigraph_brain_eval` | `brain-eval` :8003 | `brain` | `omnigraph-mcp-brain-eval`, `omnigraph/brain-eval` |
| `omnigraph_glide_memory` | `glide-memory` :8004 | `memory` | `omnigraph-mcp-glide`, `omnigraph/glide` |
| `omnigraph_glide_brain` | `glide-brain` :8005 | `brain` | `omnigraph-mcp-glide`, `omnigraph/glide` |
| `omnigraph_glide_webgrip` | `glide-webgrip` :8006 | `webgrip` | `omnigraph-mcp-glide`, `omnigraph/glide` |

Why it is built this way:

- **Why not stdio in LiteLLM.** From 1.104 LiteLLM runs stdio servers only with
  `LITELLM_ENABLE_MCP_STDIO=true`. With the flag on, whoever can register an MCP server (a
  `proxy_admin`, or a config change) can make the proxy run `node`, `npx`, `uvx`, `python`,
  `docker` or `deno` inside the pod that holds every provider key, the master key and the database
  URL. The bridges were the only reason for the flag.
- **One container per bridge, one token each.** A container sees only its own `OMNIGRAPH_TOKEN`
  (`envFrom` its own Secret). The pod does not share a process namespace, so a bridge cannot read another
  bridge's environment. The three `glide` bridges are one actor, `act-glide`, and share its token
  by design. The provider keys never enter this pod.
- **Only LiteLLM gets in.** `omnigraph-mcp-ingress` admits the `litellm` pod alone, on 8001–8006.
  The pods and the Service carry `mcp.webgrip.io/access: litellm-gateway-only`, so
  `scripts/validate_mcp_gateway_only.py` fails the build if a route, a non-ClusterIP Service or a
  wider ingress rule ever reaches them. The bridges' write grants (`memory`, `brain`, `glide`) are
  only as narrow as the access group in front of them, which is why the gateway has to be the only
  way in.
- **The bridges reach Omnigraph and the npm registry, nothing else.** `omnigraph-mcp-egress` allows
  `omnigraph` :8080. `omnigraph-mcp-npm-registry` (Cilium `toFQDNs`) allows `registry.npmjs.org`
  :443, which the `install-omnigraph-mcp` init container needs for `npm ci` from the lockfile in
  [bridge/](../../../../kubernetes/apps/ai/omnigraph-mcp/app/bridge/). A network policy covers the
  whole pod, so the bridge containers can reach the registry too. LiteLLM no longer reaches
  Omnigraph directly.
- **Stateless supergateway.** Each POST starts a fresh bridge process and ends it with the
  response, the same mode as `mcp-vikunja`. supergateway 3.4.3 kept one child per request alive
  (the 2026-09-27 `mcp-vikunja` memory climb), and 4.0.0 does not.
- **`--logLevel none`.** At `info` supergateway logs every JSON-RPC message, which would put query
  text, loaded notes and results into VictoriaLogs and undo PATCH 3
  ([MCP tool arguments](#mcp-tool-arguments)). The cost is that a bridge failure shows up only as
  an MCP error in LiteLLM's log and as a container restart.
- **Ingress through LiteLLM keeps PATCH 2.** LiteLLM caps the MCP protocol version it proposes at
  `2025-06-18` ([runtime patches](#mcp-tool-arguments)), which supergateway serves.

A bridge that cannot start shows as a container in `CrashLoopBackOff` or not ready
(`AppContainerCrashLooping`), and its tools vanish from `tools/list`. The other bridges keep
working. A wrong or rotated-out token shows only on the first graph read: `tools/list` and
`health` need no token, `graphs_list` answers 401 `invalid bearer token`.

### Checked before the move

On 2026-10-17, locally, against the pinned images: the six bridge containers ran as they do in
the Deployment (supergateway 4.0.0, user 65534, read-only root, all capabilities dropped,
`npm ci` from the lockfile) against a port-forward to `svc/omnigraph` with an invalid token.
LiteLLM 1.105.1 ran this repository's `config.yaml` and `sitecustomize.py` with
`LITELLM_ENABLE_MCP_STDIO` unset, with the bridge URLs pointed at localhost. A key holding
`memory`, `brain`, `brain-eval-raw` and `glide` called `/mcp`:

- `initialize` answered with protocol `2025-06-18`.
- `tools/list` returned 15 tools for each bridge and 10 for `omnigraph_brain_eval` (`mutate`,
  `load` and the three `branches_*` writes hidden).
- `omnigraph_memory-health` reached Omnigraph and returned `ok` (server 0.11.0).
  `omnigraph_glide_webgrip-graphs_list` returned 401 `invalid bearer token`, so the token
  travels from the container to Omnigraph.
- `omnigraph_brain_eval-mutate` and `-branches_create` were refused by LiteLLM ("not allowed for
  server omnigraph_brain_eval").
- Registering a stdio server through `POST /v1/mcp/server` was refused: "stdio MCP servers are
  disabled on this proxy".

## Virtual keys from git

`kubernetes/apps/ai/litellm/keys/` (Flux Kustomization `litellm-keys`, after `litellm`) mints
keys that are declared in git rather than clicked in the Admin UI. Per key: an ExternalSecret
generates `sk-<random>` into `litellm-key-<name>`, a PushSecret copies it to
`secret/litellm/keys/<name>` (field `key`), and the `litellm-key-register-<name>` Job registers
it with the master key. The Job is idempotent: it looks the key up with itself, updates it when
alias, models, budget, limits or `object_permission.mcp_access_groups` drifted, and when LiteLLM
does not know the key it deletes whatever still holds the alias before generating.

| Key | Models | Budget | MCP groups | Consumer |
|---|---|---|---|---|
| `open-webui` | all | USD 20 / 30d, 60 rpm | `memory`, `brain` | Open WebUI |
| `claude-code` | none (`no-default-models`) | USD 1 / 30d | `memory`, `brain`, `brain-dogfood` | Claude Code on Ryan's workstation |
| `omnigraph-distill` | `fireworks-gpt-oss-120b`, `deepseek-chat`, `granite-embedding-97m-multilingual-r2` | USD 5 / 30d, 600 rpm | none | The [Omnigraph distiller](../runbooks/omnigraph.md#distiller) |
| `brain-tools` | `granite-embedding-97m-multilingual-r2` | USD 1 / 30d, 600 rpm | none | [brain-tools](../runbooks/omnigraph.md#brain-tools), one embedding per search question |
| `omnigraph-eval` | `chat-default`, `fireworks-gpt-oss-120b`, `fireworks-deepseek-v4p1-flash`, `deepseek-chat`, `granite-embedding-97m-multilingual-r2` | USD 10 / 30d, 120 rpm | `brain-eval-raw` | The [brain eval harness](../runbooks/omnigraph.md#brain-eval) |

Add a key with a new ExternalSecret, PushSecret and Job in that directory. Rotate one by
deleting its Secret and its Job.

### Teams from git

LiteLLM teams are declared in the same directory. The `litellm-team-register-<name>` Job runs
[`register-team.sh`](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/kubernetes/apps/ai/litellm/keys/app/register-team.sh)
with the master key: it reads `/team/info`, creates the team with a fixed `team_id` when LiteLLM
does not know it, and updates it when alias, models, limits or
`object_permission.mcp_access_groups` drifted. `/team/new` fills an unset budget, rpm and tpm from
`default_team_params` (25 USD / 30d, 500 rpm, 100k tpm), so the Job clears them with an explicit
`/team/update` right after creating the team.

| Team | Models | Budget and limits | MCP groups | Consumer |
|---|---|---|---|---|
| `ploeg-crews` | all (each key carries its own model list) | none: ploegd mints every Run key with its own budget and TTL | `observability` | Ploeg executor teams that set `litellmTeamId: ploeg-crews`, today only `bronze`, whose `acp` harness passes the gateway's `/mcp` to OpenHands; `openhands`, `exec` and `claude-environment` Runs load no gateway MCP server ([Ploeg ADR-0078](https://github.com/ploeg-hq/ploeg/blob/main/docs/adrs/0078-runs-reach-read-only-mcp-tools-only-through-the-gateway-bounded-by-a-litellm-team.md)) |

A key minted into a team may only request MCP groups that team allows; LiteLLM refuses the mint
with HTTP 403 otherwise, so the team is the ceiling on what Ploeg's master key can grant a Run.
Keys still see no tools unless their own mint names the groups (`require_key_mcp_access_defined`).
Recreating a team under the same `team_id` keeps the chart value valid.

## Rules of the road

- Every key mint **requires `key_alias`** (and ideally a team) — anonymous keys are rejected.
- Budgets: SSO-created users get 10 USD/30d automatically; teams default to 25 USD/30d;
  provider daily caps 10 USD (Anthropic) / 5 USD (DeepSeek) / 10 USD (Fireworks). Amounts are owner dials in
  `litellm-config.configmap.yaml`.
- Prompts are **not** stored in the spend ledger (recorded privacy posture); spend-log retention 90d. MCP tool arguments are not stored either: see [MCP tool arguments](#mcp-tool-arguments).
- Dashboards: Grafana → **AI** folder → *LiteLLM — Inference Spend & Budgets* and
  *LiteLLM — Latency & Reliability*. Traces: Explore → Jaeger datasource, service `litellm`.
- Refusals surface to the caller. `litellm_settings.content_policy_fallbacks: []` makes a
  content-policy error end the request instead of walking `fallbacks` and `default_fallbacks`.
  It must stay in `litellm_settings`: the Router takes `router_settings.content_policy_fallbacks or
  litellm.content_policy_fallbacks`, so an empty list under `router_settings` turns back into
  "not set", and "not set" means "use the ordinary fallbacks" (`router.py`, v1.102.1).
- Admission control caps the proxy at 100 requests in flight and 50 queued for up to 30 s; past
  that it answers 503 with `retry-after: 1`. A request holds its slot until its response ends, so
  a stream or an open MCP session holds one too. `global_max_parallel_requests` looks similar and
  does nothing: only the legacy limiter reads it, and that limiter is not loaded.
- Nobody can switch logging off per request (`global_disable_no_log_param`), and prompts stay out
  of the spend log even if someone flips the Admin UI toggle (`store_prompts_in_spend_logs: false`).

## Settings that keep 1.104+ defaults off

LiteLLM 1.104 and 1.105 changed defaults that homelab depends on. One setting puts the old
behaviour back, with a condition for removing it. 1.104 also turned stdio MCP servers off; homelab
keeps them off, because the [Omnigraph bridges](#omnigraph-bridges) run over HTTP.

| Setting | Where | Why | Remove when |
| --- | --- | --- | --- |
| `litellm_settings.budget_exceeded_status_code: 429` | `litellm-config.configmap.yaml` | From 1.104.0 a spent budget answers HTTP 422 instead of 429. Unfold's Ask (`gatewayFailure` in `apps/unfold/src/ask/service.ts`) reports a spent per-Ask budget only on 400 or 429 and would call a 422 a provider error. Ploeg's ACP adapter counts `429` in a session-start failure as `infra_llm`, while a 422 would count as `infra_node`. Both are infra failures and get retried the same way | Unfold accepts 422 and Ploeg's start-failure needles include it. Then drop the line, so harnesses stop retrying a spent budget as if it were a rate limit |

Other changes in the move from 1.102.4 to 1.105.1 that need no setting:

- **Master key.** The proxy refuses to start with an unset, empty or publicly known key (`sk-1234`).
  The OpenBao key passes this check. Rotating it to a weak value now stops the proxy instead of
  just weakening it.
- **Failing migrations stop the proxy** (1.105.0), and `ENFORCE_PRISMA_MIGRATION_CHECK=false` is
  ignored. A pod whose `prisma migrate deploy` fails crash-loops, and the old ReplicaSet keeps
  serving (`unavailable: 0`).
- **Spend-log indexes.** `LiteLLM_SpendLogs(api_key, startTime)` and `(litellm_call_id)` are
  built after the migrations, `CONCURRENTLY`, on a background thread once the proxy serves, so
  spend-log writes never block. At 85 199 rows (58 MB heap, 2026-10-17) each build takes seconds.
  Check afterwards with
  `SELECT indexrelname FROM pg_stat_user_indexes WHERE relname = 'LiteLLM_SpendLogs'`.
- **Config file wins.** A runtime write to a key `config.yaml` declares answers 400 (1.103.0).
  `LiteLLM_Config` holds only `auto_router_tuning_baseline_v2`, which the file does not declare.
- **Admin UI sessions** use a new token format (1.104.0): everyone signs in again once.
- **`/sso/debug/*` answers 404** unless `ENABLE_SSO_DEBUG=true` (1.105.0). Nothing here uses it.
- **Organisation and project `max_budget: 0` means zero** (1.103.0). There are no organisations or
  projects, and the team Job sets `max_budget: null`.
- **Pinned prices still apply.** Every chat model with pinned `model_info` prices, the
  `*_above_100k_tokens` rates of `claude-haiku-5-5` included, was priced from the pin in the
  1.105.1 image through the Router's own cost path. The bundled map now has DeepSeek V4.1 Flash
  at 0.30 / 0.006 / 1.20 per million tokens, the same as the pin.
- **Per-key `metadata.disable_fallbacks`** is still copied onto each request and still stops
  every fallback (checked in the 1.105.1 image). Ploeg mints every Run key with it.

## What was checked for the move to 1.105.1

Each check ran on 2026-10-17 against the pinned image digests, locally or read-only against the
cluster. None made a paid model call.

### Rollback to 1.102.4 keeps the 1.105.1 schema and data

Rollback is the previous image pin. On a scratch PostgreSQL 18, the version CNPG runs:

1. 1.105.1 migrated an empty database (195 migrations), minted a key with `tpd_limit`, served
   three calls, and wrote a budget row with `temp_budget_increase` and `tpd_limit` and a
   `LiteLLM_Lens` row.
2. 1.102.4 started on that database. `prisma migrate deploy` found its own 171 migrations,
   reported `No pending migrations to apply`, and skipped its post-migration drift fix. The 1.105.1
   key still worked, a new key worked, and spend logs were written. Every column, table, index and
   `_prisma_migrations` row was unchanged, and so was the data in the new columns. 1.102.4 does
   not update the columns it does not know: key `total_spend` stayed at its 1.105.1 value, and
   1.102.4's spend logs have no `litellm_call_id`.
3. 1.105.1 started again on the same database with nothing to migrate. Both keys worked,
   `total_spend` grew again, and the schema matched step 1.

The risk is 1.102.4's drift fix, a `prisma migrate diff` from the database to its own
`schema.prisma` that it then applies. Against a 1.105.1 database it drops 13 tables and 38 columns,
among them key `total_spend` and `tpd_limit`, the daily response-time columns, and
`LiteLLM_SpendLogs.litellm_call_id`. 1.102.4 runs it only after `migrate deploy` applied
something, after an "already exists" migration failure, or when it has to baseline a database
without migration history. None of these happens on a plain rollback, because every 1.102.4
migration is already applied. If one happens anyway, 1.105.1 will not add the dropped columns back,
because its migrations are already marked applied. Restore the database from the daily CNPG backup
before rolling forward.

### Omnigraph stdio bridges with the real config (before the move to HTTP)

The bridges were installed as the `install-omnigraph-mcp` init container does (the
`supergateway` image, `npm ci` from `omnigraph-mcp/package-lock.json`, `@modernrelay/omnigraph-mcp`
0.10.0). The proxy ran this repository's `config.yaml` and `sitecustomize.py` with
`LITELLM_ENABLE_MCP_STDIO=true`. `OMNIGRAPH_BASE_URL` pointed at a port-forward to
`svc/omnigraph`, and every `OMNIGRAPH_*_TOKEN` was set to an invalid value. A key holding the
`memory`, `brain`, `brain-eval-raw` and `glide` groups called the `/mcp` gateway. 1.102.4 and
1.105.1 gave the same results:

- `initialize` succeeds, and LiteLLM spawns all six bridges.
- `tools/list` returns 15 tools for each bridge, and 10 for `omnigraph_brain_eval`. Its
  `disallowed_tools` still hides `mutate`, `load` and the three `branches_*` writes, and calling
  `mutate` is refused. On 1.105.1 that refusal is a 403 before the bridge is reached.
- Listing tools needs no omnigraph token, and neither does `health`. Anything that reads a graph
  answers 401 `invalid bearer token`, so a bad token shows up on the first real call, not in
  `tools/list`.

### Fireworks spend does not change

1.103.0 sends Fireworks cost through the shared calculator, which bills cache writes and
reasoning tokens. The last 7 days of Fireworks calls (5 462 successful, US$2.16) were replayed
through `Router.completion` with each row's recorded usage in both images. 1.102.4 reproduces
every recorded cost exactly, and 1.105.1 gives the same total, to the cent and per model.
The reason is that Fireworks never reports cache-write tokens (0 of 5 462 rows), and its
`completion_tokens` already include the reasoning tokens, which both versions bill at the output
rate.

### Provider caps stay at US$10 a day

The highest daily spend in the spend log, which holds data from 2026-07-19 on, is
US$10.40 for Anthropic on 2026-09-28 and US$4.02 for Fireworks on 2026-09-29. Anthropic reached
its cap on 2026-09-28, when the cap was US$5, and on 2026-09-29 at US$10. It has had no calls
since. Fireworks has never reached its cap, and in October it peaked at US$1.91 on 2026-10-05.

1.105.0 counts provider spend "on every API surface". The budget limiter now takes the provider
from the logging payload instead of the request's `litellm_params`. On 1.102.4 every embedding
call to `tei-embeddings` (provider `openai`, priced at 0) logged a `custom_llm_provider is
required` traceback, about 400 a day. Every chat call already carried its provider. So the
change counts no spend that was not counted before, and only removes those tracebacks.

### `stream_timeout: 120` on `/v1/messages`

`stream_timeout` is the httpx read timeout: the longest wait for the next bytes, both before the
first chunk and between chunks. It does not limit the length of the stream. With
`stream_timeout: 5` and a fake Anthropic upstream, a 20-second stream with a chunk every 2 seconds
completed on both routes in both versions. A first chunk after 8 seconds, or an 8-second gap
mid-stream, cut chat completions off after 5 seconds in both versions. `/v1/messages` was cut off
only on 1.105.1. 1.102.4 waited for the whole stream there.

Nothing here streams through `/v1/messages` or a pass-through route. The spend log has only
`acompletion`, `aembedding` and MCP rows, and the LiteLLM logs of the last 30 days have no
`/v1/messages` request and no stream timeout. Unfold's Ask uses `/chat/completions`. Pewter's
`claude-runner` talks to Anthropic directly. No Ploeg team on homelab uses the `claude-code`
harness, which would send `/v1/messages` here. While Claude works, Anthropic's stream keeps
sending thinking deltas and `ping` events, so a 120-second gap would mean the stream has stalled. The setting stays as it is. If a
`/v1/messages` client arrives and hits it, give that model its own `stream_timeout` in
`litellm_params`.

### 1.106 stops forwarding the caller's LiteLLM key to MCP servers

From 1.106.0 ([BerriAI/litellm#45401](https://github.com/BerriAI/litellm/pull/45401)) LiteLLM
removes the caller's key from every header it sends to an MCP server. Nothing here needs that key:

- `grafana`, `victorialogs`, `kubernetes`, `opencost`, `vikunja`, `brain_tools` and the six
  `omnigraph_*` [bridges](#omnigraph-bridges) are HTTP
  servers without `auth_type`, `extra_headers` or a pass-through setting, so LiteLLM forwards no
  caller credential to them. A header-recording HTTP MCP server registered the same way received
  no LiteLLM key on `initialize`, `tools/list` or `tools/call`, with the key in `Authorization`
  (as the owner's Claude Code `omnigraph` entry sends it) or in `x-litellm-api-key` (as Ploeg and
  Unfold send it), on 1.102.4 and on 1.105.1.
- `LiteLLM_MCPServerTable` is empty, so there are no MCP servers registered in the database.

Check again if a server gains `extra_headers`, `auth_type` or a pass-through setting.

### Security advisories

All 17 advisories at `repos/BerriAI/litellm/security-advisories` (one page), the GitHub advisory
database for `litellm`, `litellm-proxy-extras` and `litellm-enterprise`, and OSV were checked. No
advisory affects 1.102.4 or 1.105.1. The newest, GHSA-7hp6-4w63-5g45 (salt-key privilege
escalation), was fixed in 1.102.2 and 1.103.1.

## Metrics

Two sources, both scraped by the `litellm` VMServiceScrape:

| Port | Source | What it answers |
|---|---|---|
| 4001 `native-metrics` | LiteLLM's own `prometheus` callback, served by a separate process (`--prometheus_metrics_port`), no key auth | Requests, failures, tokens, spend, latency and time-to-first-token histograms, `litellm_deployment_*` state and fallback counters, provider remaining budget, key and team budget gauges, cache hits, MCP tool calls, admission queue |
| 9187 `metrics` | postgres-exporter over the ledger ([queries](../../../../kubernetes/apps/ai/litellm/app/litellm-exporter-queries.configmap.yaml)) | What only SQL answers: per-run and per-key spend, the MCP redaction check, 24-hour percentiles, provider spend per calendar day |

Only `observability` reaches either port (`litellm-allow-internal`); the HTTPRoute sends nothing but
:4000. `prometheus_exclude_labels` drops `hashed_api_key`, `client_ip` and `user_agent` from every
native series: Ploeg mints a key per run, so the hash and the pod IP would start new series on
every run, and the key alias already identifies the key. `/metrics` on :4000 exists too and needs a virtual key. Prometheus in LiteLLM is open source
since v1.80; ADR-0044's original note that it was Enterprise-only predates that.

## MCP tool arguments

LiteLLM 1.102.1 copies every MCP tool call's arguments into its standard logging payload, whatever
`turn_off_message_logging` or the OTEL callback's `message_logging: false` say. From there they
reached two stores: `LiteLLM_SpendLogs.metadata.mcp_tool_call_metadata.arguments` (90 days, and the
`litellm-db` backups) and the `metadata.mcp_tool_call_metadata` attribute of every `litellm` span in
VictoriaTraces (14 days). For the `omnigraph_*` bridges that meant queries, loads with note text and
captures, outside every forgetting path.

Since VIK-1403 the runtime patch replaces `arguments`, and `result` when present, with
`{"redacted": true}` before any callback reads the payload. The tool itself still gets its
arguments, and the ledger keeps tool name, server and status, so spend attribution is unchanged.

| What | Where |
|---|---|
| The patch | PATCH 3 in [litellm-runtime-patches](../../../../kubernetes/apps/ai/litellm/app/litellm-runtime-patches.configmap.yaml): an import hook wraps `StandardLoggingPayloadSetup.get_standard_logging_metadata` (spend log, OTEL spans and every other callback) and `_get_spend_logs_metadata` (the spend log again, in case another path builds it) once LiteLLM imports those modules. It never imports LiteLLM itself |
| The test | `bash scripts/test-litellm-runtime-patches.sh --pinned-image` builds a real standard logging payload and spend-log row inside the image pinned in `helmrelease.yaml` with a sentinel argument. The sentinel must not appear, and 6 mutants (hook not registered, one module unpatched, arguments or result kept, the live call rewritten) must each fail. Without `--pinned-image` it runs against fake modules in seconds. It runs in pre-commit and in the e2e job *LiteLLM runtime patches*, which also runs for Renovate's LiteLLM bumps |
| The signal | The exporter query `litellm_mcp_last_hour` counts the last hour's `call_mcp_tool` rows and those whose arguments are not redacted: `litellm_mcp_last_hour_stored_arguments` must be 0. Alerts `LiteLLMMCPArgumentsStored` and `LiteLLMMCPRedactionCheckMissing` ([prometheusrule](../../../../kubernetes/apps/ai/litellm/app/prometheusrule.yaml)) |
| Rows from before the patch | They age out: spend logs after 90 days, spans after 14. Deleting them sooner is a database write and Ryan's decision |
| Removal | When LiteLLM gains an option to keep MCP arguments out of the logging payload, set it, keep the test and the alert, and delete PATCH 3 |

The other two patches in the same file: PATCH 1 widens the default `httpx.AsyncClient` timeout to 30 s
for the Admin UI's Authentik SSO exchange (remove once fastapi-sso makes the timeout configurable or
Authentik answers in under 5 s); PATCH 2 caps the MCP client's proposed protocol version at
`2025-06-18` because supergateway echoes versions it cannot serve (remove once supergateway
negotiates properly).

## Network (namespace `ai`)

Namespace `ai` is zero-trust ([ADR-0006](../adr/adr-0006-default-deny-network-policies.md)): Kyverno
generates `default-deny` and `allow-dns`, and every workload carries its own allows. No policy in the
namespace selects every pod, so a new workload starts with DNS only and gets exactly the flows it
declares.

| Workload | Egress (beyond DNS) | Ingress | Policy objects |
|---|---|---|---|
| `litellm` | valkey :6379, `litellm-db` instances :5432, `tei-embeddings` and `brain-tools` :8080, `omnigraph-mcp` :8001–8006, namespaces `observability` and `vikunja` (MCP backends, OTLP to alloy-gateway), namespace `network` (gateway hairpin: Authentik OIDC, own hostname), internet TCP 443 outside RFC1918, CGNAT and link-local | :4000 from `ai`, `network`, `ploeg`, `unfold-workspaces`, LAN; :9187 from `observability` | `litellm-allow-egress`, `litellm-allow-gateway-egress`, `litellm-private-ingress`, `litellm-allow-internal` |
| `litellm-valkey` | none | :6379 from `litellm` | `litellm-valkey-ingress` |
| `litellm-db` (CNPG instances and jobs) | kube-apiserver, the off-site store `116.202.53.185/32` :443, other `litellm-db` instances :5432 | :5432 from `litellm`, `observability` (Grafana SQL datasource) and its own instances; :9187 from `observability`; :8000 and :5432 from `cnpg-system` | `litellm-db-ingress`, `litellm-db-replication-egress` (DB layer) plus `components/cnpg-netpol` |
| `omnigraph` | `litellm` :4000 (embeddings, init and server) | :8080 from `omnigraph-mcp`, `omnigraph-explorer`, `omnigraph-vault-import`, `omnigraph-forge-import`, `omnigraph-distill`, `omnigraph-brain-eval`, `brain-tools`, `network` | `omnigraph-egress`, `omnigraph-ingress` |
| `omnigraph-mcp` | `omnigraph` :8080, `registry.npmjs.org` :443 (`npm ci` in the init container) | :8001–8006 from `litellm` only | `omnigraph-mcp-ingress`, `omnigraph-mcp-egress`, `omnigraph-mcp-npm-registry` |
| `brain-tools` | `omnigraph` :8080, `litellm` :4000 | :8080 (MCP) from `litellm`; :8081 (REST and metrics) from `omnigraph-brain-eval` and `observability` | `brain-tools` |
| `omnigraph-explorer` | `omnigraph` :8080 | :8080 from `network` and the blackbox exporter | `omnigraph-explorer` |
| `omnigraph-embed-key-register` Job | `litellm` :4000 | none | `omnigraph-embed-key-register-egress` |
| `litellm-key-register-*` Jobs | `litellm` :4000 | none | `litellm-key-register-egress` |
| `litellm-team-register-*` Jobs | `litellm` :4000 | none | `litellm-key-register-egress` |
| `open-webui` | `litellm` :4000, namespace `network` (gateway hairpin: Authentik OIDC) | :8080 from `network` and the blackbox exporter | `open-webui`, `open-webui-allow-gateway-egress` |
| `omnigraph-maintenance-restart` CronJob | kube-apiserver | none | `omnigraph-maintenance-restart-apiserver` |
| `omnigraph-vault-import` CronJob | `omnigraph` :8080, Forgejo SSH :2222 (`forgejo` pods, admitted by `forgejo-allow-ingress`) | none | `omnigraph-vault-import-egress` |
| `omnigraph-forge-import` CronJob | `omnigraph` :8080, Forgejo HTTP :3000 (`forgejo` pods, admitted by `forgejo-allow-ingress`) | none | `omnigraph-forge-import-egress` |
| `omnigraph-distill` CronJob | `omnigraph` :8080, `litellm` :4000 | none | `omnigraph-distill-egress` |
| `omnigraph-brain-eval-*` CronJobs | `omnigraph` :8080, `litellm` :4000, `brain-tools` :8081, Forgejo SSH :2222 and HTTP :3000 (`forgejo` pods, admitted by `forgejo-allow-ingress`), `vmagent` :8429 in `observability` | none | `omnigraph-brain-eval-egress` |
| `tei-embeddings` | HTTPS to `huggingface.co`, `*.huggingface.co` and up to three labels under `hf.co` (model download in `fetch-model`); every pod outside `kube-system` is denied | :8080 from `litellm`, `observability` | `tei-embeddings-model-fetch`, `tei-embeddings-litellm-only`, `tei-embeddings-ingress` |
| `docs-mcp-server` | namespace `network` (it indexes `docs.<domain>` through envoy-internal) | :6280 from `ai`, `network` | `docs-mcp-server-allow-gateway-egress`, `docs-mcp-server-ingress` |

Rules that shaped it:

- **In-cluster peers are granted by identity.** Cilium enforces on the post-DNAT backend identity, so
  Services, the gateway VIP and pods in other namespaces need a `podSelector` or `namespaceSelector`.
  The LAN `ipBlock` sources on `litellm-private-ingress` admit laptops, never pods: a namespace such as
  `ploeg` reaches the proxy only through its own `namespaceSelector`. Registering an MCP backend in a
  new namespace therefore needs a `namespaceSelector` entry on `litellm-allow-egress`.
- **The gateway allow is the shared component, scoped per app.** `components/gateway-egress` renders a
  namespace-wide `allow-gateway-egress`; the litellm and docs-mcp-server kustomizations rename it and
  narrow its `podSelector` with a JSON patch. Two Kustomizations used to render the same namespace-wide
  object, which also handed the gateway to every other pod in `ai`.
- **The internet is a port-443 allow for LiteLLM only.** Provider APIs and the model price map are
  both HTTPS. Adding a provider on
  another port, or on a LAN address, needs an edit to `litellm-allow-egress`.
- **`tei-embeddings` uses `toFQDNs`.** Hugging Face redirects model files to CDN hosts that have
  changed name over time (`cdn-lfs.huggingface.co`, `cas-bridge.xethub.hf.co`, `us.aws.cdn.hf.co`), so
  the policy allows HF's own domains rather than one host. A Cilium `*` never crosses a dot, which is
  why `*.hf.co`, `*.*.hf.co` and `*.*.*.hf.co` are listed separately. The policy also sends the pod's
  DNS through the Cilium DNS proxy, which is how the allowed IPs are learned.
- **docs-mcp-server runs with `DOCS_MCP_TELEMETRY=false`.** It sent PostHog events to
  `app.posthog.com` until the namespace-wide internet allow was removed.

Check a flow live with Hubble from the Cilium agent on the pod's node, for example
`kubectl -n kube-system exec <cilium-pod> -c cilium-agent -- hubble observe --namespace ai --verdict DROPPED -f`.
