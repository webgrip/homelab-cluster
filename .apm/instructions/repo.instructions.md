---
description: Rules for this repository
---
# Agent guide — homelab-cluster

GitOps homelab: Flux + HelmRelease + Kustomize, Talos nodes; secrets via External Secrets
Operator + OpenBao (migrating off SOPS — a minimal SOPS floor remains). These rules apply to
all agents, not just Claude; `CLAUDE.md` is a symlink to this file.

## Rules

- **GitOps-first.** Every change is a manifest edit reconciled by Flux. Avoid imperative `kubectl apply/delete/patch` (hooks block the dangerous ones). Keep diffs minimal and reversible.
- **Secrets → ESO + OpenBao** (use the `external-secrets` skill); **don't add new `*.sops.yaml`**. New secret = `password-generator` (random) or OpenBao KV + an `ExternalSecret` (provided value). Never edit existing `*.sops.yaml` or print decoded values (hooks/permissions block this). Consume via `existingSecret`/`extraEnvFrom`/`envFromSecret`. Minimal SOPS floor stays: age key, `cluster-secrets`, `talsecret`, `github-deploy-key`, openbao unseal.
- **Run tooling via mise** — `mise exec -- <cmd>`; PATH binaries aren't configured for this cluster.
- **Validate before commit:** `./scripts/run-flux-local-test.sh` (a bare run auto-scopes to the kustomizations your uncommitted/unpushed changes can affect — seconds, not the full ~20min render; edits to the flux root/`components/`/the validator itself still force a full render. `--full` or `just flux-local-full` renders the whole tree). Commit with `git -c commit.gpgsign=false commit`; if the `format-yaml` hook reformats, `git add -A` and recommit.
- **Deliver through a pull request.** Nobody pushes to `main`, the owner included (ADR-0083): branch from `main`, push the branch, open a pull request and let it merge once its required checks are green and, because homelab-cluster is a core repository, another developer has approved it. An author cannot approve their own pull request. `main` requires the four `e2e /` contexts the model lists (the owner declined requiring all seven, 2026-10-18), so a merged change has passed them. Branch protection is data: `kubernetes/apps/repo-config` (tofu-controller, applied hourly) owns every rule and tag rule, with a lock-out guard (schema + precondition: homelab-cluster `main` keeps `ryangr0` on the merge list) and a drift alert. A rejected push to `main` is the rule working: push a branch instead. `forgejo-sync.sh --only protect` and `--only settings` refuse to run; change the model instead (runbook, including break-glass: [forgejo-branch-protection-rollout](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/docs/techdocs/docs/runbooks/forgejo-branch-protection-rollout.md)).
- **Editing manifests:** Flux reconciles 3 layers — root `kubernetes/flux/cluster/ks.yaml` → per-app `kubernetes/apps/<ns>/<app>/ks.yaml` (wiring: `dependsOn`, `targetNamespace`, `postBuild.substituteFrom`) → `<app>/app/` (resources). Escape runtime shell vars in manifests as `$${...}` — **except inside inline shell scripts under `postBuild.substituteFrom`, where `$${...}` errors the Kustomization; there reference container env vars unbraced (`$VAR`)** (see the `provisioner-job` skill; flux-local won't catch it). ConfigMap **file payloads** with `$`-text (JS template literals, nginx `$uri`) under a substituting ks: annotate the generated ConfigMap `kustomize.toolkit.fluxcd.io/substitute: disabled` (via `configMapGenerator[].options.annotations`) — else envsubst fails the build (`missing closing brace`).
- **Verify against real state, not a proxy.** Before claiming "done/works," cite the actual check — a live run, read-only `kubectl`/MCP/logs, or source at the *deployed* tag; a green pipeline or an edited manifest is not a running resource. A new validator/gate counts only after a mutation test: break what it checks each way it claims to catch, watch it fire — **plus one case that must PASS** (a crashing checker also exits non-zero, so failure-only tests can't tell a working gate from a broken one), and confirm its trigger actually runs (a `pull_request`-only job fires for every change since nobody pushes to `main` (ADR-0083), but not for scheduled or `workflow_dispatch` runs). Question what a metric actually measures, and respect deliberate deferrals (surface the trade-off, don't silently "fix"). For hook-blocked steps, triage read-only, then hand over an ordered, copy-pasteable command set.
- **`main` has concurrent writers.** Other agents push `main` mid-task. Before every push: `git fetch origin main`, rebase if behind, stage **explicit pathspecs** (never a bare `git add -A` — it sweeps other streams' in-flight files), and check `git status` for already-staged entries first — an earlier `git rm` rides into your next commit even with pathspec `git add`. After pushing confirm your files survived (`git ls-tree origin/main <path>`). When *diagnosing* remote/branch state, trust only a fresh `git ls-remote`/fetch — session-old state misleads (release bots push mid-task too). See `docs/techdocs/docs/general/worktrees.md`.
- **Comments are NOT allowed.** Always communicate intent with code: a precise name, a type, a
  smaller function, a test that states the case. A comment is a failure. This holds for every
  language in the repo, prose in YAML and TOML included. Machine-read directives stay, because the
  toolchain acts on them as syntax: `// @ts-check`, `eslint-disable`, `<!-- prettier-ignore -->`,
  `# syntax=`, `# renovate:`, `# yaml-language-server:`, and shebangs. Doc-comment forms the
  toolchain itself reads are not comments either and stay: godoc directly above an exported
  identifier, rustdoc `///` and `//!`, and PHPDoc blocks carrying type tags. Anything that outlives
  a single expression belongs in `docs/` or an ADR, where it gets reviewed, linked and kept
  current. The estate decision is
  [ADR 0006](https://forgejo.webgrip.dev/webgrip/workflows/src/branch/main/docs/adrs/0006-no-comments-in-code.md).

## Where things are

- **Task recipes → skills** (auto-load when relevant; full set in `.claude/skills/`): `add-app`, `external-secrets`, `cnpg-database`, `talos`, `longhorn`, `victoriametrics`, `workload-placement`, `network-policy`, and more — trust the skill descriptions over this list.
- **Debug/health → `cluster-health` subagent**; trigger Renovate → `renovate-trigger` subagent.
- **Live cluster (read-only) → MCP** (in-cluster, Flux-managed, connect over HTTP; committed `.mcp.json`): `grafana` (PromQL→VictoriaMetrics; its Loki tools only reach grace-period history; traces are VictoriaTraces via the Jaeger datasource, not the MCP Tempo tools) + `victorialogs` (LogsQL log queries) + `kubernetes` (read-only, no `pods/log`, no Secrets) — these three only through LiteLLM's gateway with an `observability`-group key (`LITELLM_MCP_KEY`) + `opencost` (cost/efficiency, LAN) + `vikunja` (task CRUD — the one **write-capable** MCP, NOT in `.mcp.json`: reached through LiteLLM's gateway with a `board`-group key; **the roadmap board lives there**, ADR-0043). See `.claude/README.md`.
- **Safety is enforced** by hooks + permissions in `.claude/` (block SOPS edits, plaintext secrets, destructive cluster commands; validate manifests on edit).
- **Deep docs → `docs/techdocs/docs/`** (+ `runbooks/`). Endpoints: API VIP `10.0.0.25`, envoy-internal `10.0.0.27` (LAN), envoy-external `10.0.0.28` (public), k8s-gateway `10.0.0.26`, Garage S3 `10.0.0.110:3900`. Hostnames template as `<app>.${SECRET_DOMAIN}` (literal is SOPS-encrypted; docs disagree — don't hardcode it).

## The roadmap lives in Vikunja, not in this repo

The backlog/roadmap is the **`Homelab Roadmap` project on the Vikunja board**, reached through the
`vikunja` MCP tools, reached through LiteLLM's authenticated MCP gateway with a key that holds the
`board` group (write-capable; [runbooks/mcp-vikunja.md](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/docs/techdocs/docs/runbooks/mcp-vikunja.md)). There is no
roadmap file in git — see
[ADR-0043](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/docs/techdocs/docs/adr/adr-0043-vikunja-roadmap-system-of-record.md).

- **Find work**: `tasks_list` on the Homelab Roadmap project. `do-next` label = top of the stack;
  `ready` label = meets the Definition of Ready (actionable as-is); `needs-refinement` = do not
  start, refine first.
- **Everything board-related** — conventions, Definition-of-Ready refinement, prioritization/top-up,
  and the agent claim/completion protocols — is the `product-owner` skill (from
  [`webgrip/ai-skills`](https://forgejo.webgrip.dev/webgrip/ai-skills), installed user-level via
  `npx skills add`). It reads the contract below.
- **Completing**: `task_complete` + a closing comment citing the commit/evidence — never claim
  done without the verification the ticket's own Verification section names.

## Board

The board contract for this repository (Vikunja project, labels, MCP gotchas) is in
[`.agents/contracts/product-owner.md`](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/.agents/contracts/product-owner.md). The product-owner-contract skill reads it; read it
before any board write.
