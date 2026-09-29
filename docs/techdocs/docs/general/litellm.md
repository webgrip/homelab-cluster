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

SSO is the only way into the Admin UI. `disable_env_credential_login` refuses the shared
`UI_USERNAME`/`UI_PASSWORD` login and the master key typed as a UI password, and
`disable_password_login_when_sso_enabled` refuses every username/password login while the Authentik
client is configured. Admin rights come from the `litellm_role` claim, which Authentik sets to
`proxy_admin` for `homelab-admins`. If Authentik is down, administer the proxy over the API with
`Authorization: Bearer <master key>`, which neither setting touches. To get UI password login
back, remove both settings and restart the proxy.

## MCP access groups

Registered servers (`mcp_servers:` in the config) and their groups:

| Group | Servers | Capability |
|---|---|---|
| `observability` | grafana, victorialogs, kubernetes, opencost | read-only |
| `board` | vikunja | **write** (task CRUD) |
| `memory` | omnigraph_memory (stdio bridge, `act-agent`) | read `memory`, write on its own branches |
| `brain` | omnigraph_brain (stdio bridge, `act-brain-agent`) | read and write `brain`, including `main` |
| `glide` | omnigraph_glide_memory, omnigraph_glide_brain, omnigraph_glide_webgrip (stdio bridges, `act-glide`) | read every branch of `memory`, `brain` and `webgrip`; write only on unprotected branches (`glide/<run-id>`); never merge ([runbooks/omnigraph](../runbooks/omnigraph.md#glide-agents)) |
| `brain-eval-raw` | omnigraph_brain_eval (stdio bridge, `act-brain-eval`) | read every branch of `brain` and run stored queries; `mutate`, `load` and the branch writes are hidden by `disallowed_tools` and refused by policy. Only the brain eval key holds it, to score today's raw-query chat path as baseline B0 ([runbooks/omnigraph](../runbooks/omnigraph.md#brain-eval)) |

A key with no explicit MCP grant sees an **empty tool list** (deny-by-default,
`require_key_mcp_access_defined`). Grant on mint via
`object_permission: {mcp_access_groups: ["observability"]}`.

Interactive human use (Claude Code `.mcp.json`) deliberately stays **direct** to the LAN
`mcp-*.<domain>` hostnames — the gateway's per-key scoping and spend attribution is for agents.
The Omnigraph graphs are the exception: they have no LAN MCP endpoint of their own, so Claude
Code and Open WebUI reach `memory` and `brain` through the gateway with the keys below
([runbooks/open-webui](../runbooks/open-webui.md#claude-code)).

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
| `claude-code` | none (`no-default-models`) | USD 1 / 30d | `memory`, `brain` | Claude Code on Ryan's workstation |
| `omnigraph-distill` | `fireworks-gpt-oss-120b`, `deepseek-chat`, `granite-embedding-97m-multilingual-r2` | USD 5 / 30d, 600 rpm | none | The [Omnigraph distiller](../runbooks/omnigraph.md#distiller) |
| `omnigraph-eval` | `chat-default`, `fireworks-gpt-oss-120b`, `claude-haiku-4-5`, `granite-embedding-97m-multilingual-r2` | USD 10 / 30d, 120 rpm | `brain-eval-raw` | The [brain eval harness](../runbooks/omnigraph.md#brain-eval) |

Add a key with a new ExternalSecret, PushSecret and Job in that directory. Rotate one by
deleting its Secret and its Job.

## Rules of the road

- Every key mint **requires `key_alias`** (and ideally a team) — anonymous keys are rejected.
- Budgets: SSO-created users get 10 USD/30d automatically; teams default to 25 USD/30d;
  provider daily caps 5 USD (Anthropic) / 2 USD (DeepSeek). Amounts are owner dials in
  `litellm-config.configmap.yaml`.
- Prompts are **not** stored in the spend ledger (recorded privacy posture); spend-log retention 90d. MCP tool arguments are not stored either: see [MCP tool arguments](#mcp-tool-arguments).
- Dashboards: Grafana → **AI** folder → *LiteLLM — Inference Spend & Budgets* and
  *LiteLLM — Latency & Reliability*. Traces: Explore → Jaeger datasource, service `litellm`.

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
| `litellm` | valkey :6379, `litellm-db` instances :5432, `tei-embeddings` and `omnigraph` :8080, namespaces `observability` and `vikunja` (MCP backends, OTLP to alloy-gateway), namespace `network` (gateway hairpin: Authentik OIDC, own hostname), internet TCP 443 outside RFC1918, CGNAT and link-local | :4000 from `ai`, `network`, `ploeg`, `de-vloer-workspaces`, LAN; :9187 from `observability` | `litellm-allow-egress`, `litellm-allow-gateway-egress`, `litellm-private-ingress`, `litellm-allow-internal` |
| `litellm-valkey` | none | :6379 from `litellm` | `litellm-valkey-ingress` |
| `litellm-db` (CNPG instances and jobs) | kube-apiserver, the off-site store `116.202.53.185/32` :443, other `litellm-db` instances :5432 | :5432 from `litellm`, `observability` (Grafana SQL datasource) and its own instances; :9187 from `observability`; :8000 and :5432 from `cnpg-system` | `litellm-db-ingress`, `litellm-db-replication-egress` (DB layer) plus `components/cnpg-netpol` |
| `omnigraph` | `litellm` :4000 (embeddings, init and server) | :8080 from `litellm`, `omnigraph-explorer`, `omnigraph-vault-import`, `omnigraph-forge-import`, `omnigraph-distill`, `omnigraph-brain-eval`, `network` | `omnigraph-egress`, `omnigraph-ingress` |
| `omnigraph-explorer` | `omnigraph` :8080 | :8080 from `network` and the blackbox exporter | `omnigraph-explorer` |
| `omnigraph-embed-key-register` Job | `litellm` :4000 | none | `omnigraph-embed-key-register-egress` |
| `litellm-key-register-*` Jobs | `litellm` :4000 | none | `litellm-key-register-egress` |
| `open-webui` | `litellm` :4000, namespace `network` (gateway hairpin: Authentik OIDC) | :8080 from `network` and the blackbox exporter | `open-webui`, `open-webui-allow-gateway-egress` |
| `omnigraph-maintenance-restart` CronJob | kube-apiserver | none | `omnigraph-maintenance-restart-apiserver` |
| `omnigraph-vault-import` CronJob | `omnigraph` :8080, Forgejo SSH :2222 (`forgejo` pods, admitted by `forgejo-allow-ingress`) | none | `omnigraph-vault-import-egress` |
| `omnigraph-forge-import` CronJob | `omnigraph` :8080, Forgejo HTTP :3000 (`forgejo` pods, admitted by `forgejo-allow-ingress`) | none | `omnigraph-forge-import-egress` |
| `omnigraph-distill` CronJob | `omnigraph` :8080, `litellm` :4000 | none | `omnigraph-distill-egress` |
| `omnigraph-brain-eval-*` CronJobs | `omnigraph` :8080, `litellm` :4000, Forgejo SSH :2222 and HTTP :3000 (`forgejo` pods, admitted by `forgejo-allow-ingress`), `vmagent` :8429 in `observability` | none | `omnigraph-brain-eval-egress` |
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
- **The internet is a port-443 allow for LiteLLM only.** Provider APIs, `registry.npmjs.org` (the
  `install-omnigraph-mcp` init container) and the model price map are all HTTPS. Adding a provider on
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
