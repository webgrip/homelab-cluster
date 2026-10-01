# Agent guide — homelab-cluster

GitOps homelab: Flux + HelmRelease + Kustomize, Talos nodes; secrets via External Secrets
Operator + OpenBao (migrating off SOPS — a minimal SOPS floor remains). These rules apply to
all agents, not just Claude; `CLAUDE.md` is a symlink to this file.

## Rules

- **GitOps-first.** Every change is a manifest edit reconciled by Flux. Avoid imperative `kubectl apply/delete/patch` (hooks block the dangerous ones). Keep diffs minimal and reversible.
- **Secrets → ESO + OpenBao** (use the `external-secrets` skill); **don't add new `*.sops.yaml`**. New secret = `password-generator` (random) or OpenBao KV + an `ExternalSecret` (provided value). Never edit existing `*.sops.yaml` or print decoded values (hooks/permissions block this). Consume via `existingSecret`/`extraEnvFrom`/`envFromSecret`. Minimal SOPS floor stays: age key, `cluster-secrets`, `talsecret`, `github-deploy-key`, openbao unseal.
- **Run tooling via mise** — `mise exec -- <cmd>`; PATH binaries aren't configured for this cluster.
- **Validate before commit:** `./scripts/run-flux-local-test.sh` (a bare run auto-scopes to the kustomizations your uncommitted/unpushed changes can affect — seconds, not the full ~20min render; edits to the flux root/`components/`/the validator itself still force a full render. `--full` or `just flux-local-full` renders the whole tree). Commit with `git -c commit.gpgsign=false commit`; if the `format-yaml` hook reformats, `git add -A` and recommit.
- **Work trunk-based on `main`.** Commit and push changes directly to `main` — do NOT create feature branches or open PRs. Still validate first; keep commits scoped and reversible. `main` **is protected** (ADR-0050): direct push is whitelisted to `ryangr0` only, force-push and branch deletion are blocked, and PRs must pass four `e2e /` status checks. Sessions push as `ryangr0` over the owner's SSH key, so trunk push works — but if a push is rejected with `Not allowed to push to protected branch main`, do **not** switch to a PR: the whitelist has been overwritten. A `forgejo-sync.sh --all --only protect` sweep writes the product-repo default (`webgrip-ci`) to every repo it touches and locks the owner out until the homelab override re-runs. Fix is step 3 of [the rollout runbook](docs/techdocs/docs/runbooks/forgejo-branch-protection-rollout.md) (`PUSH_WHITELIST=ryangr0 MERGE_WHITELIST=ryangr0,renovate STATUS_CHECK_CONTEXTS=… --repo homelab-cluster --only protect --apply`), then verify the rule reads `main ['ryangr0'] ['ryangr0','renovate']`. Happened 2026-08-05.
- **Editing manifests:** Flux reconciles 3 layers — root `kubernetes/flux/cluster/ks.yaml` → per-app `kubernetes/apps/<ns>/<app>/ks.yaml` (wiring: `dependsOn`, `targetNamespace`, `postBuild.substituteFrom`) → `<app>/app/` (resources). Escape runtime shell vars in manifests as `$${...}` — **except inside inline shell scripts under `postBuild.substituteFrom`, where `$${...}` errors the Kustomization; there reference container env vars unbraced (`$VAR`)** (see the `provisioner-job` skill; flux-local won't catch it). ConfigMap **file payloads** with `$`-text (JS template literals, nginx `$uri`) under a substituting ks: annotate the generated ConfigMap `kustomize.toolkit.fluxcd.io/substitute: disabled` (via `configMapGenerator[].options.annotations`) — else envsubst fails the build (`missing closing brace`).
- **Verify against real state, not a proxy.** Before claiming "done/works," cite the actual check — a live run, read-only `kubectl`/MCP/logs, or source at the *deployed* tag; a green pipeline or an edited manifest is not a running resource. A new validator/gate counts only after a mutation test: break what it checks each way it claims to catch, watch it fire — **plus one case that must PASS** (a crashing checker also exits non-zero, so failure-only tests can't tell a working gate from a broken one), and confirm its trigger actually runs (a `pull_request`-only job fires for agent-fleet and Renovate PRs, but **never for the owner's trunk pushes** — so a check wired only to PRs does not gate a direct commit to `main`). Question what a metric actually measures, and respect deliberate deferrals (surface the trade-off, don't silently "fix"). For hook-blocked steps, triage read-only, then hand over an ordered, copy-pasteable command set.
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
- **Live cluster (read-only) → MCP** (in-cluster, Flux-managed, connect over HTTP; committed `.mcp.json`): `grafana` (PromQL→VictoriaMetrics; its Loki tools only reach grace-period history; traces are VictoriaTraces via the Jaeger datasource, not the MCP Tempo tools) + `victorialogs` (LogsQL log queries) + `kubernetes` (read-only `view` role) + `opencost` (cost/efficiency) + `vikunja` (task CRUD — the one **write-capable** MCP; **the roadmap board lives there**, ADR-0043; `vikunja-product-owner` skill). LAN-only; see `.claude/README.md`.
- **Safety is enforced** by hooks + permissions in `.claude/` (block SOPS edits, plaintext secrets, destructive cluster commands; validate manifests on edit).
- **Deep docs → `docs/techdocs/docs/`** (+ `runbooks/`). Endpoints: API VIP `10.0.0.25`, envoy-internal `10.0.0.27` (LAN), envoy-external `10.0.0.28` (public), k8s-gateway `10.0.0.26`, Garage S3 `10.0.0.110:3900`. Hostnames template as `<app>.${SECRET_DOMAIN}` (literal is SOPS-encrypted; docs disagree — don't hardcode it).

## The roadmap lives in Vikunja, not in this repo

The backlog/roadmap is the **`Homelab Roadmap` project on the Vikunja board**, reached through the
`vikunja` MCP server configured in [.mcp.json](.mcp.json) (LAN-only, write-capable). There is no
roadmap file in git — see
[ADR-0043](docs/techdocs/docs/adr/adr-0043-vikunja-roadmap-system-of-record.md).

- **Find work**: `tasks_list` on the Homelab Roadmap project. `do-next` label = top of the stack;
  `ready` label = meets the Definition of Ready (actionable as-is); `needs-refinement` = do not
  start, refine first.
- **Everything board-related** — conventions, Definition-of-Ready refinement, prioritization/top-up,
  and the agent claim/completion protocols — is the `vikunja-product-owner` skill (from
  [`webgrip/ai-skills`](https://forgejo.webgrip.dev/webgrip/ai-skills), installed user-level via
  `npx skills add`). It reads the contract below.
- **Completing**: `task_complete` + a closing comment citing the commit/evidence — never claim
  done without the verification the ticket's own Verification section names.

## Board contract (vikunja-product-owner)

- MCP server: `vikunja` · project: `Homelab Roadmap` (id 3) · instance list cap
  (maxitemsperpage): 250
- The custom board front end has its own project: `Vellum` (id 6, since 2026-07-18) —
  the board page itself (`kubernetes/apps/vikunja/board`, served at
  `vikunja.<domain>/board`); same conventions/labels as the main board
- The agent-execution program has one project: `Unfold` (id 10, formerly Glide). It holds Unfold itself (Ploeg +
  Vloer, repo `webgrip/unfold`, formerly `webgrip/glide`) and everything around it: LiteLLM inference plane, MCP gateway,
  agent identity/budgets, classifiers, factory observability. Merged into it: `De Vloer` (id 14,
  2026-09-29), `Dark Factory` (id 5), `Ploeg Test` and `Ploeg Bench` tickets (2026-09-30). Each
  ticket's `repo/*` label names the repo its work lands in; ploegd routes by that label once Unfold
  ADR-0038 ships, and until then routes the whole board to `webgrip/unfold`, so never assign an
  Unfold team to a ticket whose `repo/*` is not `repo/unfold`
- Fixture boards, never backlogs: `Ploeg Test` (id 11, Vloer's test task source and the `vloer`
  team's route) and `Ploeg Bench` (id 49, benchmark trials, one fresh ticket per trial; id 48 is
  an archived empty duplicate). Pinned by id in the ploegd routing config
- Enumerating a board: `tasks_list` returns one capped page and reports the page size as
  "Found N" (95 of 267 on Glide, 2026-09-30), and search is unreliable. For inventory or
  counts, query the `vikunja-db` primary read-only (`cnpg.io/cluster=vikunja-db`,
  `cnpg.io/instanceRole=primary`; never the `cnpg-disaster-recovery` copy, which is a stale restore)
- CI/CD improvement work lives in its own project: `CI/CD` (id 9, since 2026-07-18) — runner pool, image supply
  chain, pipeline efficiency (mechanics
  reference: docs/techdocs/docs/general/ci-image-flow.md); same conventions/labels as the
  main board. The techdocs *serving* decision stays on Homelab Roadmap (#340)
- Product boards exist alongside the infra boards: `Erfbeeld` (id 4, repo
  `webgrip/nuala-nalatenschap`) is the factory's pilot product (ADR-0048 pilots on its tickets)
  and the target of the product-research intake lane (VIK-462); product boards keep their own
  label taxonomy (`area/*`, `wave/*`, `status/*`) and their docs live in the product repo, not
  in this repo's techdocs
- Ticket prefix: `VIK` (commit trailers `VIK-<taskID>`; see
  [rfc-dark-factory](docs/techdocs/docs/rfc/rfc-dark-factory.md) for the full agent-execution program)
- Labels — **the board is authoritative, not this file.** Enumerate with `labels_list` before
  applying any. Only the *dimensions* below are contract; the values are board state and are not
  transcribed here.
  - `theme/<kebab>` — one per ticket, from whatever the board currently defines
  - `impact/H|M|L`
  - **3D estimation** (since 2026-07-18): `effort/S|M|L` (work size) ·
    `time/hours|days|weeks` (wall-clock lead incl. soaks/waits) · `uncertainty/low|med|high`
    (how well-understood; `high` ⇒ never `agent-ready` — spike/de-risk first)
  - `do-next` (≤10) · `ready` / `needs-refinement` / `review` / `agent-ready` ·
    `agent/<name>` (claims)
  - If no existing `theme/*` fits, that is a taxonomy decision for a human — raise it; do not
    create a label to unblock a write.
  - *Why this is not a list:* it was one until 2026-08-01, naming nine `theme/security-*` values,
    **none of which existed on the instance**. An agent trusting it either fails to label or
    invents taxonomy to make the write succeed. Enumerated state does not belong in a file that
    nothing validates.
- **Stages** (since 2026-07-18) are DERIVED from labels + done, never stored separately —
  every surface (MCP agents, Vellum board, stock UI) reads the same truth:
  **Backlog** (`needs-refinement` or unlabelled) → **To Do** (`ready`; DoR incl. all three
  estimation labels) → **Doing** (`agent/<name>` claim) → **Reviewing** (`review` label;
  agent finished, human accepts) → **Done** (completed). **DoD**: a completion is accepted only
  with an evidence comment proving (1) **deployed** — verified against real state, not a proxy,
  and (2) **monitored** — names the signal that would catch regression (alert/dashboard/
  scheduled check), or states why none applies (docs-only)
- **Epics = parent tasks** (since 2026-07-18): a ticket titled `Epic: …` carries `subtask`
  relations to its children and the `meta` label; epics keep theme+impact labels but are EXEMPT
  from estimation/lifecycle labels, are never agent-workable themselves, and close only when every
  subtask closes. Wire membership with `relation_create(kind: subtask)` (parent→child); a child
  has at most ONE parent. `theme/*` labels stay the cross-project dimension; the Vellum front
  end renders the hierarchy ("By epic" view with roll-up progress)
- Open target: ≈100 tickets · stock-UI kanban buckets, if used, mirror the derived stages
  (Backlog / To Do / Doing / Reviewing / Done) — labels are authoritative, buckets are display
- **Pick-up order** (since 2026-07-18): each project's **description** carries a
  `Pick-up queue` — an ordered list (`VIK-<id> — title`), **top = picked up first**, covering
  every `do-next` holder plus a next-up tail. Agents take the topmost eligible entry; the PO
  inserts new tickets where they fit and drops entries on close. The MCP has no position API
  (skill's reference.md), so raw Vikunja drag-order alone is NOT the queue — but the **Vellum
  board's Stages view keeps them in sync**: dragging in its To Do column rewrites the
  description queue (marker: `refreshed <date> (board)`), so PO ordering happens there or via
  the MCP round-trip, never in the stock Vikunja UI
- Top-up ground truth: `git log --oneline <last-sweep>..HEAD` · `./scripts/posture-counts.sh` ·
  live read-only MCP checks · audit dimensions: security/hardening · reliability/HA/backup-DR ·
  CI/shift-left/DX
- Instance ops (token rotation, bridge/OOM issues):
  [runbooks/mcp-vikunja.md](docs/techdocs/docs/runbooks/mcp-vikunja.md)

Decisions are still recorded in git (`docs/techdocs/docs/adr/`, `rfc/`); the board holds work
items, not decision records.
