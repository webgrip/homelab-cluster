# RFC: Using the LiteLLM we already run

> Status: **Proposed** · Date: 2026-09-29 · Extends
> [ADR-0044](../adr/adr-0044-metered-inference-plane-litellm.md) (metered inference plane) ·
> Operating doc: [general/litellm](../general/litellm.md)

> **TL;DR.** We run LiteLLM v1.102.1 as a spend meter and MCP gateway, and we use perhaps a fifth
> of it. A source-level sweep of v1.102.1 and v1.103.0 turned up four things worth knowing before
> anything else. **Prometheus `/metrics` is open source since v1.80**, so ADR-0044's premise that
> it is Enterprise-only is stale, and the native metrics carry what our ledger exporter cannot
> see: fallbacks, deployment state and cache hits. **Two settings we count on do nothing.**
> `success_callback: ["postgres"]` never ran (the ledger is written by a logger LiteLLM registers
> on its own), and `global_max_parallel_requests` is read only by a legacy limiter we do not load,
> so the VIK-277 stampede guard was never active. **Refusals still fall back** to other models
> although the owner decided on 2026-07-18 that they should surface. **The free tier
> refuses every SSO login once `LiteLLM_UserTable` holds more than 5 rows**, and since 62ce372d SSO
> is the only Admin UI login. **v1.103.0 drops Anthropic beta-header passthrough and Claude Code's
> auto-mode `safeguards` field**, which matters only if Claude-native traffic moves onto the proxy.
> The proposals come in four waves: see what the proxy does (native metrics and the alerts
> ADR-0044 promised), control cost (teams, key lifecycle, same-model deployments across
> providers), add capabilities that stay in-cluster (SearXNG web search for every model, MCP tool
> search, rerank, PII masking before prompts leave), and harden the platform (a second replica,
> route-scoped keys, the upgrade path). Nothing here needs an Enterprise license.

| Term | Meaning |
| --- | --- |
| **OSS / Ent** | Works without a license / needs `LITELLM_LICENSE`. Every tier claim below was checked against the source, not the docs badge; the gate is quoted where it matters |
| **Model group** | The public `model_name` a client asks for. Today every group has exactly one deployment |
| **Deployment** | One upstream behind a model group (a provider plus its model id) |
| **Ledger** | `LiteLLM_SpendLogs` and friends in `litellm-db`, read by the postgres-exporter sidecar |
| **Native metrics** | LiteLLM's own `prometheus` callback and `/metrics` endpoint |

## 1. Where we stand

Measured 2026-09-29 from the ledger exporter (90-day spend-log window) and the live pod:

| Signal | Value |
| --- | --- |
| Spend on record | about USD 30. Sonnet 5 15.32 (Glide before fe95bed4), DeepSeek flash 7.05, Fireworks gpt-oss-120b 3.75, Fireworks DeepSeek V4.1 flash 1.90 |
| Requests | gpt-oss-120b 20,781 (the distiller), granite embeddings 19,431, DeepSeek flash 2,897; 6,357 in the last 24 hours |
| Prompt-cache reads as a share of input tokens | DeepSeek 95%, Fireworks DeepSeek V4.1 flash 95%, gpt-oss 81%, Sonnet 5 49% |
| Keys | 74 live `ploeg-*` per-run keys plus the git-declared ones. **Every key has `team_id` none** |
| Users | 2 rows: `default_user_id` and `ryan@webgrip.nl` (`proxy_admin`) |
| Consumers | Ploeg/Glide, Unfold, Open WebUI, Omnigraph (server, distiller, brain eval), the key-register Jobs, and Ryan's opencode and Claude Code (MCP only) |

What is already on, and stays on: virtual keys minted from git, provider day caps, per-group
fallbacks with retry policy per error class, pre-call context checks, prompt-cache injection for
Anthropic, Valkey auth cache and transaction buffer, OTEL traces with message logging off, the MCP
gateway with access groups and deny-by-default, the MCP-argument redaction patch, a drain endpoint
and a rolling update, and (today) SSO as the only Admin UI login.

What hurt, from the incident record: the 2026-09-28 silent cross-provider fallback when day caps
ran out (keys scoped to Sonnet were answered by gpt-oss with no error); uncached Anthropic prompts
(run 182); Fireworks retiring a model so `chat-default` was served by its fallback for days
(VIK-1251); an 11 MB request body crashing the pod; the Recreate rollout that cost three Glide
runs; MCP tool arguments landing in the ledger (VIK-1403).

## 2. Findings to fix whatever else we decide

| # | Finding | Evidence | Fix |
| --- | --- | --- | --- |
| F1 | `success_callback` and `failure_callback: ["postgres"]` are inert | The proxy loader appends the string to `litellm.success_callback` (`proxy_server.py:5628-5650` at v1.102.1) and no handler matches `"postgres"` anywhere in `litellm/`. The ledger is written by `_ProxyDBLogger`, registered whenever a DB is connected (`proxy_server.py:2496-2497`) | Delete both lines and the comment that claims they persist the ledger |
| F2 | ADR-0044's telemetry clause and the config comment say OSS has no `/metrics` | `PrometheusLogger` has no license check at v1.102.1 (`integrations/prometheus.py:210`; the one "premium" is a comment at `:237`). It moved out of `enterprise/` at v1.80.0 | Amend ADR-0044 (dated history line), fix the comment, and act on it in W1.1 |
| F3 | Cap figures are stale in docs and dashboards | Config has Anthropic 10, DeepSeek 5, Fireworks 10 USD/day. `general/litellm.md` "Rules of the road", `runbooks/omnigraph.md:574`, the dashboard tiles "cap 5 USD/day" and "cap 2 USD/day", two config comments and `litellm-exporter-queries` still say 5/2; there is no Fireworks tile | Correct the text; add the Fireworks tile |
| F4 | `claude-opus-4-1` is still served | The config's own note says it retires upstream 2026-08-05; one request in 90 days | Drop it from `model_list` and `fallbacks` after one live 404 check |
| F5 | The two Glide models inherit `default_fallbacks` | `fireworks-deepseek-v4p1-flash` and `fireworks-glm-5p3-flash` have no `fallbacks:` entry, so `default_fallbacks: ["deepseek-chat"]` applies to any caller that does not send `disable_fallbacks`. For the GLM reviewer that is a silent switch to the builder's model family, which ADR-0045 forbids | Give both an explicit entry. See D5 |
| F6 | The proxy fetches from GitHub and a blog feed at run time | The model price map and the Anthropic beta-header allowlist come from `raw.githubusercontent.com` at every start, and the Admin UI's news panel fetches a remote RSS feed, unless `LITELLM_LOCAL_MODEL_COST_MAP`, `LITELLM_LOCAL_ANTHROPIC_BETA_HEADERS` and `LITELLM_LOCAL_BLOG_POSTS` are set | Owner decision D1 |
| F8 | `global_max_parallel_requests: 100` protects nothing | Only the legacy limiter reads it (`hooks/parallel_request_limiter.py:259`), and that limiter is registered only when `LEGACY_MULTI_INSTANCE_RATE_LIMITING=true` (`hooks/__init__.py:31-32`); the default v3 limiter never reads it. The VIK-277 stampede guard has not been active | Replace it with admission control: `max_in_flight_requests_per_worker` and `max_queued_requests_per_worker` (`middleware/admission_control_middleware.py:285`), which answer 503 with `retry-after` over the limit |
| F9 | Privacy defaults can be flipped from outside git | Any key can skip OTEL and every other logger for one request with `"no-log": true` (`litellm_logging.py:2035`); `store_prompts_in_spend_logs` also turns on from the env var or the UI toggle; router fallback wiring is echoed in client errors (`expose_router_debug_in_errors` defaults true) | Set `global_disable_no_log_param: true`, pin `store_prompts_in_spend_logs: false` in YAML, set `expose_router_debug_in_errors: false` |
| F10 | Refusals are routed around, against the 2026-07-18 decision | With `content_policy_fallbacks` unset the Router holds `None`, and a `ContentPolicyViolationError` logs "No content_policy_fallback set. Defaulting to fallbacks" and continues into the ordinary chain, `default_fallbacks` included (`router.py:7468-7497` at v1.102.1). A refusal from the GLM reviewer can be answered by DeepSeek | Set `litellm_settings.content_policy_fallbacks: []`. The list must be set there: the Router computes `content_policy_fallbacks or litellm.content_policy_fallbacks` (`router.py:1040`), so an empty list in `router_settings` becomes `None` again. With `[]` the lookup finds no group and the original error is raised. Prove it with `mock_testing_content_policy_fallbacks` behind `dangerously_allow_mock_testing_request_params` in a test run |
| F11 | The `prompt_caching` pre-call check costs work and does nothing yet | It keeps a conversation on the deployment holding its cache, which means nothing while every group has one deployment, but it still counts tokens and reads Valkey on every request | Drop it from `optional_pre_call_checks` until W2.3 gives a group a second deployment |
| F7 | The SSO user cap has no headroom rule | `_raise_if_sso_exceeds_free_user_limit` (`ui_sso.py:976`) counts every `LiteLLM_UserTable` row except those with `metadata.scim_active == false` (`repositories/user_repository.py:86-98`). `homelab-users` can sign in through the `llm-use` capability | **Shipped 0e6f8b31**: `LiteLLMSSOUserCapNear` fires at 5 rows. Longer term: people without admin rights get a git-declared key or an end-user id (W1.4), not a user row |

## 3. The catalogue, filtered for us

The full sweep covered roughly 860 routes and every `litellm_settings`, `router_settings` and
`general_settings` key. The tables keep what could matter here; the verdict column says what to do
with it.

### 3.1 Observability

| Feature | Tier | What it gives us | Verdict |
| --- | --- | --- | --- |
| `prometheus` callback, `/metrics` | OSS | Request, failure, token and spend counters; latency and time-to-first-token histograms; `litellm_deployment_*` state, cooldown and **fallback** counters; cache hit and miss; remaining budget per key, team and provider; `litellm_mcp_tool_calls_total`; guardrail metrics | **Adopt (W1.1)** |
| `--prometheus_metrics_port` | OSS | Serves `/metrics` from its own process on its own port, without key auth, so the scrape never touches an inference worker or the public route | **Adopt with W1.1** |
| `LITELLM_OTEL_INTEGRATION_ENABLE_METRICS` | OSS | Six `gen_ai.*` histograms over the OTEL pipe we already have | Trial after W1.1 |
| OTEL v2 engine (`LITELLM_OTEL_V2`) | OSS | Server, auth, Postgres, Redis and guardrail spans under each request | Trial; would explain slow requests the flat span cannot |
| Request tags (`x-litellm-tags`), `x-litellm-trace-id`, `x-litellm-spend-logs-metadata` | OSS for request-level use; tags **on keys** and tag budgets are Ent | Attribution beyond the key alias: team, role, tier, ticket | **Adopt (W1.4)** |
| End-user ids (`user`, `x-litellm-end-user-id`) | OSS | Per-person spend in `LiteLLM_EndUserTable`, which does not count toward the SSO cap | **Adopt (W1.4)** |
| `generic_api`, `s3_v2`, `focus` loggers | OSS | Payload export to a webhook, Garage, or FOCUS files for FinOps | Skip for now; the ledger answers our questions |
| Audit logs | **Ent** (`audit_logs.py:214-217`) | Who changed keys, teams, config | Substitute: git history plus the deleted-token tables |

### 3.2 Routing, reliability and cost

| Feature | Tier | What it gives us | Verdict |
| --- | --- | --- | --- |
| Several deployments per model group | OSS | One public name served by two providers, e.g. DeepSeek V4 flash direct **and** on Fireworks. When one provider's day cap or health fails, the router moves to the other deployment of **the same model**, instead of falling back to a different model family | **Adopt (W2.3)** |
| Routing strategies (`simple-shuffle`, `usage-based-routing-v2`, `latency-based-routing`, `cost-based-routing`) | OSS | Choose between deployments by load, latency or price | Adopt with W2.3; start with `simple-shuffle` plus weights |
| Cooldowns, `allowed_fails_policy` | OSS | Take a failing deployment out for a while | Re-enable once a group has two deployments (the reason for `disable_cooldowns` goes away) |
| `prompt_caching` pre-call check | OSS | Keeps a conversation on the deployment that holds its cache | Already set; starts doing something with W2.3 |
| Teams, team budgets, team tpm/rpm | OSS | A ceiling per consumer group; `litellm_team_*` metrics light up | **Adopt (W2.1)** |
| Organizations, team-admin role, projects | **Ent** | Tenant layers above and below teams | Skip; one owner does not need them |
| Key `duration`, `/key/delete` sweeps | OSS | Per-run keys that expire and leave | **Adopt (W2.2)** |
| Key regenerate, scheduled auto-rotation | **Ent** (`key_management_endpoints.py:5323` at v1.102.1) | Rotation that keeps settings | Substitute: the register Jobs re-mint under the same alias |
| Response cache (opt-in, Valkey) | OSS | Identical deterministic calls answered from cache | Measure first (W2.4); the distiller is the only candidate |
| Semantic cache (Qdrant, Redis semantic) | OSS | Near-duplicate prompts answered from cache | Skip: agent prompts rarely repeat, and a wrong hit is expensive |
| `model_max_budget`, tag budgets, `enforced_params` | **Ent** | Per-model and per-tag money limits | Substitute: provider day caps plus per-key model lists |
| Batch API (`/v1/batches`) | OSS | Provider batch discounts for non-interactive work | Revisit for brain eval if it moves to a batch-capable provider |
| `upperbound_key_generate_params` | OSS (`key_management_endpoints.py:1110-1160`) | A hard ceiling on `max_budget`, tpm/rpm and `duration` of every minted key, **the master key's mints included** | **Adopt (W2.2)**: a bug in a minter can no longer create a USD 500 key |
| Complexity auto-router (`auto_router/complexity_router`, `heuristic` classifier) | OSS, unlimited; the `capability` and `llm_v2` classifiers are licence-metered to one router each | Scores each request with regexes and keywords and sends simple ones to a cheap group, hard ones to a strong group; CPU only | Trial as a `chat-auto` group for Open WebUI; never for agents, whose model is part of their contract |
| Background health checks | OSS | Real completions to every deployment on a timer | Skip: tokens and power for a signal the native metrics give for free |
| Scheduler / priority queue | OSS, beta | Holds requests only while **no** deployment is healthy | Skip |

### 3.3 Capabilities we do not use yet

| Feature | Tier | What it gives us | Verdict |
| --- | --- | --- | --- |
| `search_tools` with the **searxng** provider, `/v1/search` | OSS | Web search behind a virtual key, served by the SearXNG already running in namespace `searxng` | **Adopt (W3.1)** |
| Web-search interception (`websearch_interception_params`) | OSS (present in v1.102.1) | Turns a model's `web_search` tool call into a LiteLLM search, so DeepSeek and Fireworks models can search the web like Claude can | **Adopt with W3.1** |
| MCP tool search (`object_permission.mcp_tool_search_enabled`, `litellm_settings.mcp_tool_search`) | OSS | A key sees two virtual tools (`mcp_tool_search`, `mcp_tool_call`) instead of every tool of every server; ranking can use our TEI embeddings | **Trial (W3.2)** for Glide keys once VIK-1300 gives them MCP |
| `/v1/rerank` with a TEI reranker | OSS | The `rerank-default` model `rfc-brain-retrieval` plans | **Adopt when brain retrieval needs it (W3.3)** |
| `litellm_content_filter` guardrail | OSS, fully in-process | Prebuilt patterns including `nl_bsn_contextual`, IBAN, card numbers, `passport_netherlands`, API keys; MASK or BLOCK; also runs on MCP arguments (`pre_mcp_call`) and results (`post_mcp_call`) | **Adopt (W3.4)**: mask Dutch personal identifiers before brain and meeting text leaves for Fireworks or DeepSeek |
| `hide-secrets` guardrail (the `guardrails:` entry, hyphenated) | OSS (the legacy `hide_secrets` callback is Ent) | Redacts secrets with detect-secrets before the prompt leaves | **Adopt (W3.4)** for agent traffic, which reads repositories |
| `tool_permission`, `mcp_security`, `custom_code` guardrails | OSS | Tool allow and deny by regex; block requests naming unregistered MCP servers; a sandboxed Python check | Trial where a real rule exists; `disallowed_tools` covers today's cases |
| Guardrails attached per key or team | **Ent** (`litellm_pre_call_utils.py:2957-2969`, returns 403 on every request without a license) | Different guardrails per identity | Substitute: global `default_on` guardrails, with `opted_out_global_guardrails` in key metadata for keys that must skip one. Model-level `guardrails` on a dedicated model group are OSS too, but run only before the call (`async_pre_call_deployment_hook`), so they cannot inspect a reply |
| Agent loop limits (`max_iterations` in key metadata, `max_budget_per_session`) | OSS | Stop a runaway agent loop by iteration count, keyed on the trace id | Trial with W1.4; per-run keys already cap money |
| Prompt registry and dotprompt (`prompts:`) | OSS | Versioned prompts referenced by `prompt_id`, recorded in the ledger | Skip; our prompts already live in git next to the code that sends them |
| A2A gateway, agent registry, workflow runs, memory | OSS | Agent-to-agent calls and durable run logs | Skip; Ploeg and Omnigraph own these jobs. Revisit if kagent resumes (ADR-0063) |
| Claude Code gateway (device-flow SSO, managed settings) | OSS code, new in v1.103.0 | Claude Code signs in through LiteLLM and gets settings pushed | Skip; Claude Code uses the proxy for MCP only, and each SSO user costs a cap slot |
| MCP OAuth sign-in (gateway DCR) | OSS, always on | MCP clients sign in with Authentik instead of a static key | Not now: an admitted human is scoped by their own grants, so Ryan as `proxy_admin` would see every server including the write-capable ones. See §5 |

## 4. Proposals

Each item lists what it changes, how we know it works, and the signal that catches a regression.
Owner decisions are collected in §6.

### Wave 0: done on 2026-09-29

- **62ce372d** `disable_env_credential_login` and `disable_password_login_when_sso_enabled`. Verified
  live: a dummy `/v2/login` went from 401 with the `UI_USERNAME` hint to 403 "disabled because SSO is
  configured"; `/sso/key/generate` still redirects to Authentik.
- **0e6f8b31** `LiteLLMSSOUserCapNear`. Verified live: vmalert loaded it, health `ok`, state inactive
  at 2 rows.
- **6f2c2b33** W1.3 and W1.1 (see below). The refusal fix was proven in the pinned v1.102.1 image
  before it shipped: with the old config a forced content-policy error on the GLM reviewer group was
  answered by the `deepseek-chat` group; with the new config it raised
  `ContentPolicyViolationError`.

### Wave 1: see what the proxy does

**W1.1 Native metrics.** Add `prometheus` to `litellm_settings.callbacks`, start the proxy with
`--prometheus_metrics_port 4001` (a separate process reading `PROMETHEUS_MULTIPROC_DIR`, no key
auth), expose 4001 on the Service, scrape it with the existing VMServiceScrape, and admit it only
from `observability` in `litellm-allow-internal`. Set `prometheus_initialize_budget_metrics: true`.
The HTTPRoute keeps routing only :4000, so `/metrics` never reaches the LAN or the internet. Keep
the ledger exporter for what only SQL answers (per-run spend, the MCP redaction check, 24-hour
percentiles); retire the queries the native metrics duplicate once dashboards moved.
*Works when* `litellm_deployment_successful_fallbacks` and `litellm_proxy_total_requests_metric`
have series in VictoriaMetrics. *Regression signal:* `absent_over_time` on the request counter.

**W1.2 The alerts ADR-0044 and ADR-0049 promised.** None of these exist today:

| Alert | Expression shape | Why |
| --- | --- | --- |
| Silent fallback | any increase of the deployment fallback counter in 15 minutes | The 2026-09-28 incident and VIK-1251 |
| Provider cap at 80% | provider remaining budget below 20% of the cap | Warns before the router starts refusing or falling back |
| Budget exhausted | a key or team at or over its budget, excluding per-run keys | ADR-0044 "budget-breach alert" |
| Daily factory spend | ledger sum per day above a set amount | VIK-598 |
| Failure rate | failed / total requests above 10% for 15 minutes, per model group | Nothing pages today when a provider breaks |

Each alert gets a mutation test in the runbook: break the condition, watch it fire, and one case
that must stay quiet.

**W1.3 Correct the record.** F1 to F4 and F8 to F11 in one commit, plus the ADR-0044 amendment.
F10 goes first of all: it is a recorded owner decision the proxy does not carry out. For
F8 the admission limits are set from W1.1's in-flight numbers, not guessed; until then the inert
key goes and a generous `max_in_flight_requests_per_worker` replaces it.

LiteLLM's own alerting (`general_settings.alerting`: Slack-compatible webhooks, SMTP, a generic
webhook for budget events) stays off. Alerts go through vmalert, Alertmanager and ntfy like every
other alert in the cluster, and the native metrics give vmalert what it needs.

**W1.4 Attribution on every request.** Ploeg sends `x-litellm-trace-id` (the run),
`x-litellm-tags` (`team:<glide team>`, `role:builder|reviewer`, `tier:silver`) and
`x-litellm-spend-logs-metadata` (`{"ticket": "VIK-…"}`); Open WebUI forwards the signed-in person as
the end user (`user`). The person on every run (owner decision D4 in
`rfc-agent-runtime-kagent-vs-glide`) lands as an end-user id, which needs no Enterprise JWT auth and
does not use an SSO cap slot. Set `general_settings.missing_session_id: generate` so untagged calls
still group. Ploeg also sends a stable `session_id` per run: Fireworks uses it for prefix-cache
affinity (`x-session-affinity`), and ids the proxy generates itself are not forwarded, so this is
the cheapest cache win left for Glide. *Works when* a Glide run's rows carry its ticket and tags in
`LiteLLM_SpendLogs`.

### Wave 2: control cost

**W2.1 Teams.** One team per consumer group: `ploeg` (Glide runs), `unfold`, `omnigraph` (distiller,
eval, embeddings), `humans` (Open WebUI, opencode). Each team carries a 30-day budget and tpm/rpm
limits; keys are minted into their team. The per-run keys keep their own caps; the team adds the
ceiling a leaking minter cannot exceed. *Works when* `litellm_team_spend` has four series.

**W2.2 Key lifecycle.** Every per-run key gets `duration` (Ploeg already bounds its TTL; check the
live keys carry `expires`), a weekly Job deletes keys that expired more than 7 days ago, and the
exporter counts live keys per alias prefix. 74 `ploeg-*` keys are listed today.
`litellm_settings.upperbound_key_generate_params` caps `max_budget`, `duration` and rpm/tpm for
every mint, the master key's included, at the largest value any git-declared key or Ploeg role
uses today. *Regression signal:* the live per-run key count grows without bound.

**W2.3 Same model, two providers.** Put DeepSeek V4 flash behind one group served by DeepSeek direct
and Fireworks; do the same for any model two providers host. Turn cooldowns back on for those
groups, keep `default_fallbacks` for real outages only, and keep refusals surfacing (no
`content_policy_fallbacks`, as decided 2026-07-18). This turns an exhausted day cap into a provider
switch within the same model, which is what the 2026-09-28 runs needed. The price difference
between the two providers is visible per deployment in the native metrics. *Works when* a forced
failure on one deployment (a wrong key in a test group) is answered by the other with the same
model family, and the fallback alert stays quiet.

**W2.4 Measure the response cache.** The cache is on and opt-in. Log, for one week, how many
distiller calls repeat an identical request; turn it on for the distiller only if the hit rate
would pay for the Valkey memory. Embeddings come from a local TEI server and stay uncached.

### Wave 3: capabilities that stay in the cluster

**W3.1 Web search for every model.** Register SearXNG as a `search_tools` entry
(`http://searxng.searxng.svc.cluster.local`), enable `websearch_interception_params` for the
`deepseek` and `fireworks_ai` providers, and grant the search tool to the keys that should have it
(`object_permission.search_tools`). Needs a `litellm-allow-egress` entry for namespace `searxng`.
Keys decide who may search; SearXNG decides where it searches. *Works when* a DeepSeek request with
a `web_search` tool returns cited results and the ledger shows the search call.

**W3.2 MCP tool search.** For keys that see several servers, enable
`mcp_tool_search_enabled` and rank with `granite-embedding-97m-multilingual-r2`. The agent's
context holds two tools instead of dozens. Trial on one Glide team and compare prompt tokens per run.

**W3.3 Rerank.** A TEI reranker (CPU, a few hundred MB) behind `/v1/rerank` as `rerank-default`, when
`rfc-brain-retrieval` reaches that slice.

**W3.4 Data leaving the cluster.** Two global guardrails, both in-process:

- `litellm_content_filter`, `default_on`, `pre_call` plus `pre_mcp_call`, prebuilt patterns
  `nl_bsn_contextual`, IBAN, card numbers, `passport_netherlands`, action MASK. Brain notes and
  Webgrip meetings go to Fireworks and DeepSeek; a BSN or IBAN in them never needs to.
- `hide-secrets`, `default_on`, `pre_call`: agents read repositories and logs, and a token pasted in
  either should not reach a provider. Its default detect-secrets config includes
  `HexHighEntropyString` (limit 3.0), which matches every `sha256:` image digest in this repo; set
  `detect_secrets_config` without the two high-entropy plugins, or agents see redacted digests and
  can write them back broken.

Start both in `logging_only` for a week and read the hit counts
(`x-litellm-applied-guardrails`, the guardrail metrics from W1.1) before switching to masking. The
brain eval and the distiller get their eval scores compared before and after, because masking can
change answers.

### Wave 4: platform

**W4.1 Two replicas.** Redis already carries router and auth state. A second replica with a
PodDisruptionBudget makes restarts invisible to Glide (1a04cb58 fixed the rollout, not a node
drain). Cost: about 1 GiB of RAM on a worker. Owner decision D3.

**W4.2 Route-scoped keys.** Mint agent keys with `key_type: llm_api` (OSS; enforced in
`route_checks.py`) after checking that `/mcp` is inside `llm_api_routes`, so a leaked agent key
cannot call `/key/*`. The public HTTPRoute stops at `/v1`, `/mcp`, `/ui`, `/sso` and `/health`;
the register Jobs and Ploeg's minter reach `/key/*` in-cluster. That is the OSS substitute for the
Enterprise `admin_only_routes`, `allowed_ips` and `DISABLE_ADMIN_ENDPOINTS`.

**W4.3 A minter key instead of the master key.** Ploeg and the forgejo agent runner mint with the
master key (#282). Spike: can a `key_type: management` key owned by a service user mint keys with
budgets, and nothing else? If yes, the master key leaves every consumer but the register Jobs.

**W4.4 Body size at the gateway.** `max_request_size_mb` is Ent and a no-op in OSS
(`auth_utils.py`, logs "enterprise only" and returns). An Envoy Gateway buffer limit on the
LiteLLM route closes the 11 MB crash (roadmap #16).

**W4.5 Upgrade path.** v1.103.0 is the latest stable (2026-09-28); v1.104.0 is planned for about
2026-10-03. v1.103.0 brings config-file authority (keys set in `config.yaml` can no longer be
overridden from the UI or the `LiteLLM_Config` table, which v1.102.1 with `STORE_MODEL_IN_DB`
allows; the table holds only `auto_router_tuning_baseline_v2` today) and the MCP fail-closed and
admission fixes. It also drops first-party Anthropic beta passthrough and the `safeguards` field,
which no consumer sends through the proxy today. Thirteen migrations include a blocking
`CREATE INDEX` on `LiteLLM_SpendLogs(api_key, startTime)`; at about 50,000 rows that is seconds.
Behaviour changes to read before merging the bump: `stream_timeout` (120 s here) now also cuts
`/v1/messages` and pass-through streams; `cache_control_injection_points` no longer stand down when
the client marks its own cache breakpoints; Fireworks cache writes and reasoning tokens are now
billed, so Fireworks spend will rise on paper; `enforce_fallback_budget` is on by default, so a
fallback target's budget is checked too; `max_parallel_requests` answers 429 at once instead of
queueing. Recommendation: take v1.103.0 when Renovate proposes it, unless Claude-native traffic has
moved onto the proxy by then. The runtime-patch test runs on LiteLLM bumps and the redaction
targets are unchanged in v1.103.0.

## 5. Threat notes

- **MCP OAuth sign-in is always on.** Any MCP client can register (RFC 7591) and send a person
  through `/authorize` behind the SSO cookie. The admitted subject is the user, scoped by the user's
  own and their teams' grants; `require_key_mcp_access_defined` does not apply. A `proxy_admin`
  human sees the whole registry. Today only Ryan holds a user row; W1.4 keeps it that way.
- **The SSO cap is also a lockout.** A sixth user row blocks every SSO login, and password login is
  off. Recovery is the API with the master key. `LiteLLMSSOUserCapNear` warns at five.
- **The SSO-only gate can switch itself off.** It checks that every `GENERIC_*` value is present in
  the pod, not that Authentik answers. If one goes missing, `disable_env_credential_login` still
  keeps the master key off the login form, which is why both settings stay.
- **Settings in the database override git on v1.102.1.** A UI edit by any `proxy_admin` writes
  `LiteLLM_Config`, and v1.102.1 deep-merges that over `config.yaml`. The table is clean today;
  v1.103.0 closes it (W4.5).
- **MCP arguments still need the patch.** Neither v1.102.1 nor v1.103.0 has a setting that keeps
  `mcp_tool_call_metadata.arguments` out of the logging payload; `turn_off_message_logging` redacts
  results, not arguments. PATCH 3 and its alert stay.

## 6. Owner decisions

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | Pin the price map and beta-header list in the image (`LITELLM_LOCAL_*`) instead of fetching from GitHub at start | Yes. Prices then move with Renovate's image bumps, which are soaked and reviewed; models we price ourselves already carry `model_info` |
| D2 | Mask Dutch personal identifiers and secrets globally before prompts leave (W3.4) | Yes, after the logging-only week |
| D3 | A second LiteLLM replica (about 1 GiB of RAM on a worker, about EUR 0 in power) | Yes, once W1.1 shows the proxy's real load |
| D4 | Team layout and budgets (W2.1) | Four teams as listed; budgets set from 30 days of W1.4 attribution |
| D5 | Fallbacks for the Glide builder and reviewer models | Builder: none beyond W2.3's second provider. Reviewer: none, so a GLM outage fails the review instead of letting the builder's family grade itself |
| D6 | Take v1.103.0 or wait for v1.104.0 | Take v1.103.0 (W4.5) |

## 7. Rollout

W0 is done. W1 goes first because every later wave is judged by its metrics; W1.1 and W1.3 shipped
together on 2026-09-29 in `6f2c2b33`. W2 and W3.1 follow in either order. W3.4 needs two weeks
(logging only, then masking). W4 items are independent and can go whenever there is room. Every
item is a child of [VIK-267](https://vikunja.webgrip.dev/tasks/267) on the Dark Factory board and
closes only with a live check and a named regression signal.

| Item | Ticket |
| --- | --- |
| W1.1 native metrics | [VIK-1433](https://vikunja.webgrip.dev/tasks/1433) |
| W1.2 alerts | [VIK-1434](https://vikunja.webgrip.dev/tasks/1434) (absorbs [VIK-1251](https://vikunja.webgrip.dev/tasks/1251); supersedes the approach of [VIK-265](https://vikunja.webgrip.dev/tasks/265) and [VIK-284](https://vikunja.webgrip.dev/tasks/284)) |
| W1.3 inert settings, refusals | [VIK-1432](https://vikunja.webgrip.dev/tasks/1432) |
| W1.4 attribution | [VIK-1435](https://vikunja.webgrip.dev/tasks/1435) |
| W2.1 teams | [VIK-264](https://vikunja.webgrip.dev/tasks/264) |
| W2.2 key lifecycle | [VIK-1436](https://vikunja.webgrip.dev/tasks/1436) |
| W2.3 same model, two providers | [VIK-285](https://vikunja.webgrip.dev/tasks/285) |
| W3.1 web search | [VIK-1437](https://vikunja.webgrip.dev/tasks/1437) |
| W3.2 MCP tool search | [VIK-1438](https://vikunja.webgrip.dev/tasks/1438) |
| W3.4 masking | [VIK-1439](https://vikunja.webgrip.dev/tasks/1439) |
| W4.1 second replica | [VIK-1440](https://vikunja.webgrip.dev/tasks/1440) |
| W4.2 route-scoped keys | [VIK-1441](https://vikunja.webgrip.dev/tasks/1441) |
| W4.3 minter key | [VIK-1442](https://vikunja.webgrip.dev/tasks/1442) |
| W4.4 body size | [VIK-1443](https://vikunja.webgrip.dev/tasks/1443) |
| W4.5 upgrade | [VIK-1444](https://vikunja.webgrip.dev/tasks/1444) |
| §9 Glide teams per tier | [VIK-1463](https://vikunja.webgrip.dev/tasks/1463) (Ploeg), after VIK-264 |
| §9 Iteration cap per run | [VIK-1464](https://vikunja.webgrip.dev/tasks/1464) (Ploeg) |
| §9 Docs search behind the gateway | [VIK-1465](https://vikunja.webgrip.dev/tasks/1465) |
| §9 Cluster evidence and docs tools per role | [VIK-1466](https://vikunja.webgrip.dev/tasks/1466) (Ploeg), after VIK-1300 and VIK-1465 |
| §9 Protected paths at the gateway | [VIK-1467](https://vikunja.webgrip.dev/tasks/1467) |

JWT auth for agents ([VIK-281](https://vikunja.webgrip.dev/tasks/281)) is Enterprise-only; its
comment lists the OSS alternatives. W2.4 (response cache) and W3.3 (rerank) have no ticket: the
first is a measurement to take once W1.1 has a week of data, the second belongs to
`rfc-brain-retrieval`.

## 8. What this RFC did not verify

- Whether the Fireworks and DeepSeek deployments of DeepSeek V4 flash behave identically enough for
  W2.3 (tool calling, cache pricing); the trial compares them.
- How LiteLLM's HuggingFace rerank provider speaks to TEI (W3.3).
- The SearXNG JSON output format and rate limits against the interception loop (W3.1).
- Anything in v1.104.0 beyond its release candidate's notes, including a reported change to
  master-key handling that the register Jobs depend on.
- Whether the custom `model_info` pricing on `deepseek-chat` stops LiteLLM from applying
  DeepSeek's off-peak rates (read from `router.py`, not run). If it does, provider budgets burn
  faster than the invoice.
- Whether an exhausted provider budget, raised as a plain `ValueError`, is retried with backoff
  before each fallback hop. If it is, `retry_policy.DefaultRetries: 0` makes the hop immediate.
- That `litellm_settings.content_policy_fallbacks: []` is applied before the Router is built; F10's
  mock test settles it.

## 9. Glide

Glide is the biggest consumer by run count and the one that changed most this month: per-run keys
minted by Ploeg with `key_type: llm_api` and a `duration`, builders and reviewers from different
model families (ADR-0045), cheap models since fe95bed4, MCP on the way (VIK-1300). Checked against
Ploeg at `webgrip/glide 6150dd0` and LiteLLM v1.102.1:

| Feature | For Glide | Verdict |
| --- | --- | --- |
| Teams per tier | One LiteLLM team per tier (`bronze`, `silver`, `copper`) plus `unfold`; each run's key minted into its tier's team. The shift pool becomes a LiteLLM team budget that Ploeg cannot miss (its own pool bound "has never once fired"), and each tier gets team metrics. `MintRequest` sends no `team_id` today | **Adopt**: VIK-264 (teams), VIK-1463 (Ploeg) |
| Iteration cap per run | `max_iterations` in the run key's metadata; the limiter is loaded by default and counts calls per `x-litellm-session-id`. Median run 34 calls, p95 about 193, max 252 (ledger, 2026-09-29), so 400 stops loops only. On cheap models the money cap catches a loop after about 15 runs' worth of calls | **Adopt**: VIK-1464. The session header comes from Ploeg's key-isolation proxy, which also carries VIK-1435's tags |
| Read-only cluster evidence tools | The unused `observability` access group (Grafana, VictoriaLogs, Kubernetes view, OpenCost) per role, so builders can verify against live state and reviewers can check the evidence. Tool results go to DeepSeek and Fireworks | **Adopt after VIK-1300**, owner decision on the data: VIK-1466 |
| Docs search | `docs-mcp-server` (SSE :6280) behind the gateway as group `docs` | **Adopt**: VIK-1465 |
| Per-role MCP scope | Reviewers read, builders write on `glide/<run>`; `llm_api` keys already reach `/mcp` (`llm_api_routes` includes `mcp_inference_routes`) | With VIK-1300 and VIK-1466 |
| `tool_permission` guardrail | Blocks model tool calls that write protected paths (CI workflows, SOPS files, agent hooks), streaming included, before the harness runs them. Global `default_on` with `default_action: allow`: its built-in default denies every tool call | **Adopt, narrow**: VIK-1467 |
| `hide-secrets` | Strips tokens from repo and log content, with the digest caveat in W3.4 | With VIK-1439 |
| LLM-as-judge guardrail | A second judge on every request; Glide already has reviewers from another family | Skip |
| LiteLLM skills | ZIPs stored in LiteLLM's database and injected into Anthropic Messages requests (`container.skills`). Glide sends OpenAI chat completions through OpenHands, and `supported_db_objects: ["mcp"]` keeps other database objects out | Skip; OpenHands reads repository instructions itself |
| Agent registry, A2A gateway | Agent-to-agent calls through LiteLLM. Ploeg is the dispatch plane | Skip; revisit if kagent resumes (ADR-0063) |

