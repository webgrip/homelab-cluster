# Claude Code setup for this repo

This directory configures Claude Code (claude.ai/code) for the homelab cluster. Most of it works out of the box; the MCP servers need a one-time secret/env setup (below).

## What's here

| Path | Purpose |
| --- | --- |
| `../CLAUDE.md` | Always-loaded operating rules (kept deliberately minimal). |
| `agents/` | Subagent: `cluster-health` (read-only audit). `renovate-trigger` now comes from the org `webgrip` plugin. |
| `skills/` | Task recipes that load only when relevant — all of `.claude/skills/`; see each `SKILL.md` description. |
| `commands/` | Slash commands — one per file in `.claude/commands/`. |
| `hooks/` | Safety + validation + `session-context` hooks (see below). |
| `statusline.sh` | Cluster-aware statusline (model / git / kube-context / Flux not-ready / context%). |
| `settings.json` | Permissions + hook + statusline wiring, and `enabledPlugins` for the org plugin (committed, team-shared). |
| `settings.local.json` | Personal/machine overrides (gitignored). Secrets live in `../.mise.local.toml`. |
| `../.mcp.json` | MCP servers: `grafana`, `kubernetes`, `opencost` (committed; secrets via env). |

## Org plugin

This repo enables the shared **`webgrip`** plugin from [`webgrip/claude-config`](https://github.com/webgrip/claude-config) via `extraKnownMarketplaces` + `enabledPlugins` in `settings.json`. It contributes org-wide guidelines (injected at session start), a SOPS secret guard, and the `renovate-trigger` agent. Repo-specific skills/agents stay here; org-generic ones live in the plugin.

## Shared skills (`webgrip/ai-skills`)

Org-generic skills (`skillsmith`, `adr-writer`, `harvest-knowledge`, `vikunja-product-owner`, …) come from [`webgrip/ai-skills`](https://forgejo.webgrip.dev/webgrip/ai-skills) and are installed **user-level, not via this repo** — so they're available to every agent, not just Claude Code:

```bash
npx skills add https://forgejo.webgrip.dev/webgrip/ai-skills.git --all -g   # install/refresh
npx skills update -g                                                       # pull latest
```

They land in `~/.agents/skills/` and are symlinked into each agent's skills dir (`~/.claude/skills/`, opencode, Cursor, Codex, …). They invoke unprefixed (`/skillsmith`), not namespaced like plugin skills. Note the CLI ships only the SKILL.md trees — a skill's bundled `hooks/hooks.json` (`guard-secrets`, `skill-usage`) or `.mcp.json` (`vikunja-product-owner`) is **not** auto-wired; wire those by hand in `settings.json` / `.mcp.json` if you want them.

Operational notes:

- **Check what actually landed, not the installer's summary** — compare the installed skill against the remote source of truth:
  `for d in ~/.agents/skills/*/; do s=$(basename "$d"); a=$(md5sum "$d/SKILL.md" | cut -d' ' -f1); b=$(git show origin/main:skills/$s/SKILL.md | md5sum | cut -d' ' -f1); [ "$a" = "$b" ] && echo "MATCH $s" || echo "DIFFER $s"; done` (run from an `ai-skills` checkout).
- **Version skew ≠ behaviour skew.** A release can touch only READMEs and `plugin.json` metadata, leaving every `SKILL.md` byte-identical — an "outdated" install is then functionally current. Check `git diff --name-only <old>..<new> | grep SKILL.md` before treating a stale pin as urgent. And because `npx skills add <git-url>` clones `main` directly, the npx route gets a fix the moment it merges; the release train only governs `.skill` packages, Forgejo releases, and version numbers.
- **Dropping a plugin marketplace takes two steps.** Removing it from `settings.json` does not deregister it: `~/.claude/plugins/known_marketplaces.json` keeps its own entry (potentially with `autoUpdate: true`, still fetching). That registry is CLI-owned — use `/plugin marketplace remove <name>` rather than hand-editing it mid-session. Even then, `~/.claude/plugins/cache/<name>/` is left behind and must be deleted manually.

## Hooks (enforced safety)

- **`guard-secrets.sh`** (PreToolUse Edit/Write) — blocks decrypted artifacts and plaintext written into `*.sops.yaml`; runs `gitleaks` on new content if installed. The gitleaks pass can false-positive on secrets-free *prose* (seen 2026-07-12 on documentation text mentioning secrets next to quoted paths); diagnose with the hook's own invocation — `mise exec -- gitleaks detect --no-banner --no-git -s <file>` against the content written to `/tmp` — and reword the flagged phrase rather than bypassing the hook. Editing `*.sops.yaml` is also blocked by `permissions.deny`.
- **`guard-destructive.sh`** (PreToolUse Bash) — blocks direct cluster mutation (`kubectl apply/patch/scale/...`, protected `kubectl delete`, `helm install/upgrade`, `flux delete`, destructive `talosctl`). Allows read-only ops, `--dry-run`, recoverable `pod`/`job` deletes, and `task talos:apply-node-safe`.
- **`validate-manifest.sh`** (PostToolUse Edit/Write) — runs `yamllint` + `kubeconform` (with the datreeio CRDs-catalog) on edited `kubernetes/**` manifests; failures are fed back to fix.
- **`guard-skills.sh`** (PostToolUse Edit/Write) — enforces the mechanically-checkable invariants extracted from `skills/` so those skills stay terse (saves tokens): Grafana `$$`-escaping (both single-`$` greps) + `instanceSelector`/`editable`/`allValue`/ConfigMap-dashboard hygiene, CNPG `walStorage` + storageClass, Gateway-API-not-Ingress, app `ks.yaml` not re-declaring `decryption:`, and Authentik blueprint `<nn>-` ordering.

Validation linters are **optional** — hooks skip them if absent. To enable enforcement, add to `.mise.toml`:

```toml
"aqua:yannh/kubeconform" = "<version>"
"aqua:gitleaks/gitleaks" = "<version>"
"pipx:yamllint"          = "<version>"
```

## MCP servers — GitOps (in-cluster over HTTP)

The MCP servers are **Flux-managed workloads in the cluster**; Claude Code connects to them over HTTP. Config is committed in [`../.mcp.json`](../.mcp.json) — no secrets, no local processes.

| Server | In-cluster app | Endpoint (LAN-only via envoy-internal) |
| --- | --- | --- |
| `grafana` | `kubernetes/apps/observability/mcp-grafana/` | `https://mcp-grafana.${SECRET_DOMAIN}/mcp` — VictoriaMetrics (PromQL) / Loki grace-period history (traces = VictoriaTraces via the `victoriatraces` Jaeger datasource — the MCP's Tempo tools are dead since ADR-0042; Pyroscope suspended pending ADR-0037) |
| `kubernetes` | `kubernetes/apps/observability/k8s-mcp/` | `https://k8s-mcp.${SECRET_DOMAIN}/mcp` — **read-only**, bound to the built-in `view` ClusterRole (no Secrets) |
| `opencost` | `kubernetes/apps/observability/opencost/` | `https://opencost-mcp.${SECRET_DOMAIN}/` — cost allocation/efficiency queries |
| `victorialogs` | `kubernetes/apps/observability/mcp-victorialogs/` | `https://mcp-victorialogs.${SECRET_DOMAIN}/mcp` — LogsQL log queries |
| `vikunja` | `kubernetes/apps/vikunja/mcp-vikunja/` | `https://mcp-vikunja.${SECRET_DOMAIN}/mcp` — task/project CRUD, the one **write-capable** MCP (acts as the token owner's user; hard deletes disabled server-side). Conventions: `vikunja-product-owner` skill (from `webgrip/ai-skills`); instance ops/token: `docs/techdocs/docs/runbooks/mcp-vikunja.md` |

How it works: the servers run in-cluster (image digests pinned, RBAC/config in Git); their HTTPRoutes are `external-dns`-excluded so the hostnames resolve only on the LAN via split-DNS. The endpoints require no client auth on the LAN, so `.mcp.json` holds just the URLs.

**Why hostnames are hardcoded in `.mcp.json`:** Claude Code expands `${VAR}` in `.mcp.json` only from the *launch* environment, not from `settings.local.json`. Since `direnv` isn't installed and mise env isn't guaranteed to reach the VSCode extension, hardcoding the LAN hostname is the reliable choice (the route is LAN-only/open, so the domain is the only thing revealed). If you launch Claude from a `mise`/`direnv` shell that exports `SECRET_DOMAIN`, you can instead use `https://mcp-grafana.${SECRET_DOMAIN}/mcp`.

**Activate:** restart Claude Code (it reads `.mcp.json` at startup), approve the servers, then `/mcp` → all `✓ Connected`. Requires being on the LAN.

> Editing the in-cluster `k8s-mcp` tool scope (e.g. granting read of Flux CRDs) is a values change in `k8s-mcp/app/helmrelease.yaml` — keep it read-only and never grant Secrets.

## Notes

- Versions/nodes are in `talos/talenv.yaml`, `talos/talconfig.yaml`, `.mise.toml` — not in CLAUDE.md (which would go stale).
- The CI counterpart (Claude review of PRs/Renovate) lives in `../.github/workflows/claude-review.yml`.
