# Claude Code setup for this repo

This directory configures Claude Code (claude.ai/code) for the homelab cluster. Most of it works out of the box; the MCP servers need a one-time secret/env setup (below).

## What's here

| Path | Purpose |
| --- | --- |
| `../CLAUDE.md` | Always-loaded operating rules (kept deliberately minimal). |
| `agents/` | Subagent: `cluster-health` (read-only audit). `renovate-trigger` now comes from the org `webgrip` plugin. |
| `skills/` | Task recipes that load only when relevant: `add-app`, `grafana-dashboard`, `cnpg-database`, `authentik-oidc`, `flux-validate`, `talos`, `longhorn`, `workload-placement`. |
| `commands/` | Slash commands: `/cluster-status`, `/triage-renovate`, `/restore-drill`. |
| `hooks/` | Safety + validation + `session-context` hooks (see below). |
| `statusline.sh` | Cluster-aware statusline (model / git / kube-context / Flux not-ready / context%). |
| `settings.json` | Permissions + hook + statusline wiring, and `enabledPlugins` for the org plugin (committed, team-shared). |
| `settings.local.json` | Personal/machine overrides (gitignored). Secrets live in `../.mise.local.toml`. |
| `../.mcp.json` | MCP servers: `grafana`, `kubernetes` (committed; secrets via env). |

## Org plugin

This repo enables the shared **`webgrip`** plugin from [`webgrip/claude-config`](https://github.com/webgrip/claude-config) via `extraKnownMarketplaces` + `enabledPlugins` in `settings.json`. It contributes org-wide guidelines (injected at session start), a SOPS secret guard, and the `renovate-trigger` agent. Repo-specific skills/agents stay here; org-generic ones live in the plugin.

## Hooks (enforced safety)

- **`guard-secrets.sh`** (PreToolUse Edit/Write) — blocks decrypted artifacts and plaintext written into `*.sops.yaml`; runs `gitleaks` on new content if installed. Editing `*.sops.yaml` is also blocked by `permissions.deny`.
- **`guard-destructive.sh`** (PreToolUse Bash) — blocks direct cluster mutation (`kubectl apply/patch/scale/...`, protected `kubectl delete`, `helm install/upgrade`, `flux delete`, destructive `talosctl`). Allows read-only ops, `--dry-run`, recoverable `pod`/`job` deletes, and `task talos:apply-node-safe`.
- **`validate-manifest.sh`** (PostToolUse Edit/Write) — runs `yamllint` + `kubeconform` (with the datreeio CRDs-catalog) on edited `kubernetes/**` manifests; failures are fed back to fix.
- **`guard-skills.sh`** (PostToolUse Edit/Write) — enforces the mechanically-checkable invariants extracted from `skills/` so those skills stay terse (saves tokens): Grafana `$$`-escaping (both single-`$` greps) + `instanceSelector`/`editable`/`allValue`/ConfigMap-dashboard hygiene, CNPG `walStorage` + storageClass, `release: kube-prometheus-stack` on ServiceMonitor/PrometheusRule, Gateway-API-not-Ingress, app `ks.yaml` not re-declaring `decryption:`, and Authentik blueprint `<nn>-` ordering.

Validation linters are **optional** — hooks skip them if absent. To enable enforcement, add to `.mise.toml`:

```toml
"aqua:yannh/kubeconform" = "<version>"
"aqua:gitleaks/gitleaks" = "<version>"
"pipx:yamllint"          = "<version>"
```

## MCP servers — GitOps (in-cluster over HTTP)

Both MCP servers are **Flux-managed workloads in the cluster**; Claude Code connects to them over HTTP. Config is committed in [`../.mcp.json`](../.mcp.json) — no secrets, no local processes.

| Server | In-cluster app | Endpoint (LAN-only via envoy-internal) |
| --- | --- | --- |
| `grafana` | `kubernetes/apps/observability/mcp-grafana/` | `https://mcp-grafana.${SECRET_DOMAIN}/mcp` — Prom/Loki/Tempo/Mimir/Pyroscope |
| `kubernetes` | `kubernetes/apps/observability/k8s-mcp/` | `https://k8s-mcp.${SECRET_DOMAIN}/mcp` — **read-only**, bound to the built-in `view` ClusterRole (no Secrets) |

How it works: the servers run in-cluster (image digests pinned, RBAC/config in Git); their HTTPRoutes are `external-dns`-excluded so the hostnames resolve only on the LAN via split-DNS. The endpoints require no client auth on the LAN, so `.mcp.json` holds just the URLs.

**Why hostnames are hardcoded in `.mcp.json`:** Claude Code expands `${VAR}` in `.mcp.json` only from the *launch* environment, not from `settings.local.json`. Since `direnv` isn't installed and mise env isn't guaranteed to reach the VSCode extension, hardcoding the LAN hostname is the reliable choice (the route is LAN-only/open, so the domain is the only thing revealed). If you launch Claude from a `mise`/`direnv` shell that exports `SECRET_DOMAIN`, you can instead use `https://mcp-grafana.${SECRET_DOMAIN}/mcp`.

**Activate:** restart Claude Code (it reads `.mcp.json` at startup), approve the servers, then `/mcp` → both `✓ Connected`. Requires being on the LAN.

> Editing the in-cluster `k8s-mcp` tool scope (e.g. granting read of Flux CRDs) is a values change in `k8s-mcp/app/helmrelease.yaml` — keep it read-only and never grant Secrets.

## Notes

- Versions/nodes are in `talos/talenv.yaml`, `talos/talconfig.yaml`, `.mise.toml` — not in CLAUDE.md (which would go stale).
- The CI counterpart (Claude review of PRs/Renovate) lives in `../.github/workflows/claude-review.yml`.
