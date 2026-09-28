# Open WebUI

Open WebUI is a chat front end for Ryan at `https://chat.<domain>` (LAN only, envoy-internal). It runs as `open-webui` in namespace `ai` and talks to nothing but LiteLLM: models on `/v1`, embeddings for uploads, and the Omnigraph `memory` and `brain` tools through LiteLLM's MCP gateway. Manifests: [kubernetes/apps/ai/open-webui](../../../../kubernetes/apps/ai/open-webui/).

## How it runs

- Image `ghcr.io/open-webui/open-webui` through the Harbor proxy, the `-slim` variant pinned by tag and digest. Slim ships without the local embedding, speech and document models; everything model-shaped goes to LiteLLM.
- bjw-s app-template, one replica, `strategy: Recreate`, worker pool, UID 1000, read-only root filesystem. The `seed-static` init container copies the image's static assets into an `emptyDir`, because Open WebUI rewrites that directory at every start.
- SQLite, uploads and the Chroma vector store live on the `open-webui-data` Longhorn volume (`longhorn`, 5Gi) at `/app/backend/data`.
- Configuration comes from the environment only: `ENABLE_PERSISTENT_CONFIG=false`, so a change made in the admin panel is gone after the next restart. Change the HelmRelease instead.
- `OFFLINE_MODE=true`: no update check and no Hugging Face downloads. The pod has no internet egress anyway.

## Who gets in

Two OIDC layers, one Authentik client (`open-webui`, access-plane entry in `tofu/broker/applications.tf`, secret generated in `authentik` and pushed to `secret/authentik/open-webui-oidc`):

1. **Gateway.** The `open-webui-oidc` `SecurityPolicy` sends every anonymous request to Authentik ([ADR-0060](../adr/adr-0060-gateway-oidc-for-apps-without-a-login.md)). Callback `/oauth2/callback`.
2. **App.** Open WebUI's own OIDC login (`/oauth/oidc/callback`) creates the account. The login form and local signup are off; OAuth signup is on and merges by email.

Authentik only issues a token to members of `knowledge-graph-chatters`, the group of the `knowledge-graph-chat` capability, granted to Ryan by name in [people.yaml](../../../../kubernetes/apps/security/access-plane/model/people.yaml) because the chat reads and proposes changes to the brain. Inside the app, `ENABLE_OAUTH_ROLE_MANAGEMENT` reads the `groups` claim: `knowledge-graph-chatters` maps to `admin`; a login whose groups miss it is refused, and one with no groups claim stays `pending`. Admin matters: the MCP tool server has no access grants, which in Open WebUI means admins only.

## Models, embeddings and tools

- **Key.** Open WebUI authenticates to LiteLLM with the virtual key `open-webui` (all models, USD 20 per 30 days, 60 requests per minute, `object_permission.mcp_access_groups` `memory` and `brain`). It is generated and registered by `litellm-keys`, see [LiteLLM: virtual keys from git](../general/litellm.md#virtual-keys-from-git). The `open-webui-litellm` ExternalSecret reads it back from `secret/litellm/keys/open-webui` into `OPENAI_API_KEY`, `RAG_OPENAI_API_KEY` and `TOOL_SERVER_CONNECTIONS`.
- **Models.** `OPENAI_API_BASE_URL` is `http://litellm.ai.svc.cluster.local:4000/v1`; the Ollama API and direct connections are off. Default chat model `chat-default`, a LiteLLM alias that points at Fireworks Qwen (`qwen3p7-plus`, the cheaper of Qwen and Kimi on 2026-09-28) and falls back to `deepseek-chat`. Clients only know the alias, so moving the default to another provider or an in-cluster model is one LiteLLM entry. Titles and tags use `fireworks-gpt-oss-120b` (`TASK_MODEL_EXTERNAL`), the cheapest model with tool support. Owner rule: Fireworks first, the cheapest DeepSeek model as the fallback.
- **Uploads.** `RAG_EMBEDDING_ENGINE=openai` with `granite-embedding-97m-multilingual-r2` through LiteLLM, the same model Omnigraph uses.
- **Tools.** One MCP tool server, id `omnigraph`, streamable HTTP at `http://litellm.ai.svc.cluster.local:4000/mcp/`, declared in `TOOL_SERVER_CONNECTIONS`. It shows 30 tools: `omnigraph_memory-*` and `omnigraph_brain-*`. Turn it on per chat with the tools button under the message box.
- **Memory.** Open WebUI's own memory feature is off (`ENABLE_MEMORIES=false`). Omnigraph is the only memory.

What the tools may do is decided by Omnigraph policy, not here: `omnigraph_memory` runs as `act-agent`, `omnigraph_brain` as `act-brain-agent` (see [Omnigraph: actors and tokens](omnigraph.md#actors-and-tokens)). `act-brain-agent` reads and writes `main` directly (owner decision 2026-09-27): "remember …" lands in the brain at once, and every write is a commit that can be reverted. It cannot merge, export or delete branches.

## Network

`open-webui` NetworkPolicy: ingress on 8080 from namespace `network` and the blackbox exporter; egress to `litellm` on 4000. `open-webui-allow-gateway-egress` (the `gateway-egress` component, narrowed to this pod) lets the server reach Authentik for OIDC through envoy-internal. LiteLLM already admits every pod in `ai` on 4000.

## Monitoring

- `blackbox-open-webui` sends an anonymous request with `Host: chat.<domain>` to envoy-internal and expects a 302 to Authentik (`gate: oidc`, `synthetic: route`). A 2xx fires `SyntheticOidcGateOpen`; anything else fires `SyntheticRouteDown`.
- `blackbox-open-webui-backend` checks `/health` on the Service. Alert `OpenWebUIBackendDown`.

## Operations

- **Logs.** `kubectl -n ai logs deploy/open-webui -c app`.
- **Rotate the LiteLLM key.** Delete the `litellm-key-open-webui` Secret and the `litellm-key-register-open-webui` Job. ESO generates a new key and pushes it to OpenBao, the recreated Job revokes the old one, `open-webui-litellm` refreshes within 15 minutes and Reloader restarts the pod.
- **Rotate the session secret.** Delete `open-webui-secret`. Everyone is logged out.
- **Rotate the OIDC client.** Delete the `open-webui-oidc-client` Secret in `authentik`, as for any Authentik client.
- **Upgrade.** Renovate bumps the tag and digest. Open WebUI migrates SQLite on start; read the release notes for env renames, because a renamed variable is silently ignored.

## Backup

The volume is not yet enrolled in Longhorn's `gitops-backup` job. Enrolment is a line `ai/open-webui-data` in the `enrol-irreplaceable` list of [longhorn-backup-enrollment.yaml](../../../../kubernetes/apps/kyverno/policies/app/longhorn-backup-enrollment.yaml). Until then a lost volume loses chat history and uploads, not knowledge: that lives in Omnigraph.

## Claude Code

The same two graphs reach Claude Code on Ryan's workstation through LiteLLM with its own key, `claude-code`: MCP only (`models: ["no-default-models"]`), USD 1 per 30 days, groups `memory` and `brain`, stored at `secret/litellm/keys/claude-code`. Add it once per workstation; the key goes from OpenBao straight into Claude Code's config without being printed:

```bash
export BAO_ADDR="$(just bao-addr)"
bao token lookup >/dev/null 2>&1 || bao login -method=oidc
claude mcp add --transport http --scope user omnigraph \
  "https://$(kubectl get httproute litellm -n ai -o jsonpath='{.spec.hostnames[0]}')/mcp/" \
  --header "Authorization: Bearer $(bao kv get -mount=secret -field=key litellm/keys/claude-code)"
claude mcp list
```

`claude mcp list` should show `omnigraph` connected. Claude Code stores the header in `~/.claude.json`, so treat that file as a secret. After a key rotation, run `claude mcp remove omnigraph --scope user` and the commands above again.
