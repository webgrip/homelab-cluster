# RFC: Dark factory — agent-driven ticket execution

> Status: **Accepted in part** · Date: 2026-07-14 · The backbone loop and review gate were
> ratified 2026-07-12 (Decisions 1–2). The **SOTA extension** — a metered inference plane,
> `opencode` runtime, skills profiles, spec-first authoring and an independent AI pre-review —
> was ratified 2026-07-14 (Decisions 3–5). The pilot must still answer the remaining open
> questions before the unattended loop switches on.

> **TL;DR.** The Vikunja board is the roadmap system of record
> ([ADR-0043](../adr/adr-0043-vikunja-roadmap-system-of-record.md)) and every ticket now meets a
> Definition of Ready. The next step is closing the execution loop: **ticket → scheduled agent →
> Forgejo PR → human merge → ticket auto-closes**. This RFC records the loop's architecture, the
> two decisions already made, the phase map, and what the pilot must prove.

## Why

101 tickets are refined to actionable (evidence-cited problem, checkbox acceptance criteria,
approach, live verification), and agents already do the work interactively. What's missing is the
machinery to hand a ticket to an agent *unattended* and get reviewable work back with a full audit
trail. The pieces all exist in-cluster: Vikunja (webhooks + API + MCP), Forgejo (webhooks, bot
users, external-tracker linkification), n8n (glue), and a proven local scheduled-agent pattern
(`scripts/cluster-health/` — headless claude on a systemd user timer, LAN MCP access).

## Decisions (ratified 2026-07-12)

1. **Review gate — Forgejo PRs, cutover first.** Unattended agents never push `main`; they open
   Forgejo PRs the owner merges. That makes the Forgejo-leading cutover of this repo (Forgejo CI
   parity, then the ADR-0011/ADR-0013 cutover pack) the program's critical path. Interactive
   (attended) agent work on `main` continues unchanged.
2. **Dispatcher runtime — local first, in-cluster later.** The dispatcher (the scheduled agent
   that picks up tickets) starts as a systemd **user timer** on the owner's workstation, extending
   the `scripts/cluster-health/digest.sh` pattern: the MCPs are LAN-only and no Anthropic
   credential exists in-cluster today. An in-cluster CronJob (API key via ESO/OpenBao, in-cluster
   MCP endpoints) is a follow-up gated on the pilot proving the loop.

## The loop

```
Vikunja ticket (ready + agent-ready + do-next)
   │  dispatcher (systemd timer) picks top ticket, claims it (label + comment)
   ▼
claude --worktree (isolated), works the ticket per its own AC/verification
   │  pushes branch to Forgejo, opens PR with VIK-<taskID> trailer
   ▼
Forgejo PR  ──(external-tracker regexp VIK-(\d+))──▶ renders link to the ticket
   │  owner reviews & merges
   ▼
Forgejo org webhook ─▶ n8n: extract VIK-id ─▶ Vikunja API: comment with commit/PR links,
                                              mark done (+ nightly reconciler sweep,
                                              because Vikunja webhooks are single-attempt)
```

Assignment is **label-based** (`agent/*` + claim/progress/completion comments), not native
Vikunja assignees: accounts come from Authentik OIDC, and an Authentik `service_account` cannot
perform the interactive OIDC login Vikunja requires before a user is assignable. Native
assignment is deferred until that's worth solving.

## SOTA extension (ratified 2026-07-14)

The backbone above hands *one* headless claude a ticket. The SOTA target generalises it into a
**metered production line** that a developer and an agent operate identically — and, in doing so,
closes the credential gap that blocks the in-cluster dispatcher.

**Design thesis — human/agent parity.** Build one pipeline; a developer and an agent are
interchangeable operators of it. Both pull a ticket, load the same skills profile, run the same
`opencode` + `openspec`, spend metered tokens on their own key, and open the same Forgejo PR. If
the two paths ever diverge we are maintaining two systems — so they stay identical; only *who*
pulls the ticket differs.

### Decisions (ratified 2026-07-14)

Numbered 3–5 to continue Decisions 1–2 above; other sections cross-reference them by number.

* **Decision 3 — metered inference plane — LiteLLM, self-hosted (the keystone).** All inference,
  for devs and agents alike, routes through an in-cluster **LiteLLM** proxy: CNPG-backed; upstream
  provider keys sealed in OpenBao and surfaced via ESO; virtual keys per identity / team / task
  with a hard `max_budget`, tpm/rpm caps and a model allow-list; spend + latency + errors to
  VictoriaMetrics; budget breach to ntfy. This *is* the in-cluster credential Decision 2 lacked —
  with a budget attached — so it unblocks the in-cluster dispatcher, and it hands developers
  metered access on day one. **Envoy AI Gateway** (already in the cluster) was weighed and
  deferred: it does routing / failover / token-rate-limiting but carries no dollar-budget key
  ledger, so it complements LiteLLM *in front* later, it does not replace it. SaaS gateways
  (Portkey / OpenRouter / Cloudflare AI Gateway) are out per the no-SaaS-in-the-ops-path doctrine.
  → **ADR-0044**.
* **Decision 4 — agent runtime — `opencode`, all-in; safety guards move server-side.** Agents and
  devs run `opencode` (headless for unattended runs), driving `openspec` for spec-first changes and
  the `webgrip/ai-skills` skills repo for per-ticket skill profiles (`npx skills add <profile>`).
  Consequence: opencode does **not** execute the `.claude/` PreToolUse guard hooks that are today
  the only thing stopping an unattended agent from committing a plaintext secret or editing a
  `*.sops.yaml`. Those guards must be re-implemented **server-side** (Forgejo `pre-receive` +
  CI checks) before attendance is removed. This answers the RFC's open "permission mode" question:
  the answer is *not* the client hook set — it is server-side enforcement. → **ADR-0045**.
* **Decision 5 — execution substrate — Forgejo Actions + KEDA (v1).** Unattended runs execute on
  the existing KEDA-scaled Forgejo Actions runners — reusing their ESO secrets, autoscaling and
  NetworkPolicy — not a bespoke controller. A dedicated `AgentTask` operator with per-task
  ephemeral budget keys is the v2 graduation, gated on the pilot verdict.

### What the SOTA line adds to the loop

```
Vikunja ticket (ready + agent-ready + do-next)
   │  dispatcher claims it (label + comment)
   ▼
load out ── npx skills add <profile>            (skills chosen by the ticket's label)
   ▼
opencode --worktree + openspec ── spec first, then change ── every token via a budgeted LiteLLM key
   │  pushes branch to Forgejo, opens PR (VIK-<taskID> trailer)
   ▼
inspect ── CI (flux-local + server-side secret/SOPS guards) + an INDEPENDENT reviewer agent
   │  (separate key / model / context, adversarial prompt) ── gates before a human ever looks
   ▼
human merges ─▶ Flux reconciles ─▶ org webhook ─▶ n8n ─▶ Vikunja: comment links + mark done
```

### New gaps this extension must close

* **Guard parity (HAZ-01).** opencode has no `.claude/` hooks — re-implement the secret / SOPS /
  destructive-command block-list as Forgejo `pre-receive` + CI. Load-bearing; see Decision 4.
* **Runaway spend (HAZ-02).** Defence in depth: per-task LiteLLM `max_budget` (hard) + Job
  `activeDeadlineSeconds` + opencode max-turns + a global concurrency cap.
* **Review independence (HAZ-05).** The reviewer agent uses a distinct key, **a different model
  *family* than the author** (not merely a different key — same-family review is measured to inflate
  pass rates 9–17pp, and an LLM fails to fix its own errors ~64.5% of the time), a fresh context with
  no access to the author's session, and an adversarial prompt. The reviewer bot's forge account is
  scoped read + comment only (no write/merge). CI gates independently of any agent verdict; an author
  never self-reviews.
* **Skill portability (HAZ-06).** Prove one profile runs identically under opencode and Claude Code
  before converging, or fork skills; track via the `webgrip/ai-skills` AGENTS.md contract.
* **State fan-out (HAZ-04).** Vikunja (why) / openspec change (how) / Forgejo PR (diff) drift, and
  Vikunja webhooks fire once — cross-link everything on `VIK-<id>`; the nightly reconciler stays.

## Phase map

Revised 2026-07-14 to fold in the SOTA extension. Phases 0–1 and the cutover are done as first
recorded; old phases 2–3 (dispatcher pilot, in-cluster dispatcher) are superseded by phases 3–4
below, now that the inference plane (phase 2) is their prerequisite.

| Phase | Work | Gate |
| --- | --- | --- |
| 0 (done) | `VIK-<taskID>` convention (skill + AGENTS.md + Forgejo external tracker) · Vikunja webhooks enabled · `agent-ready` DoR gate + claim protocol | — |
| 1 (done) | n8n enforcement loop + nightly reconciler | Phase 0 |
| cutover (done) | Forgejo CI parity → Forgejo-leading cutover (existing tickets) | — |
| 2 | **Inference plane**: LiteLLM (CNPG + OpenBao + ESO, Authentik-mapped keys, VM telemetry) · issue developer keys · skills-profile loadout (`npx skills add`) | — (unblocks all) |
| 3 | **Guards + review + author pilot**: server-side secret/SOPS/destructive guards (Forgejo `pre-receive` + CI) · independent reviewer agent · opencode + openspec **attended** pilot | Phase 2 |
| 4 | **Unattended dispatcher**: in-cluster on Forgejo Actions/KEDA · hard per-task budgets · concurrency cap · kill-switch | Phase 3 + pilot verdict |
| 5 | **SOTA graduation** (optional): `AgentTask` CRD + per-task ephemeral keys · Envoy AI Gateway in front · optional local-model fallback | Phase 4 |

The full work breakdown lives on the board: `theme/dark-factory` label, Homelab Roadmap project,
with `precedes`/`blocked` relations encoding this table.

## Open questions the pilot must answer

* **Concurrency/claim** — one ticket per dispatcher run to start; is the claim comment + label
  enough to prevent double-pickup once more than one dispatcher exists?
* **Failure reporting** — a failed run must comment on the ticket and notify (ntfy); is that
  enough, or does the board need a `blocked/agent-failed` state?
* ~~**Budget & cadence**~~ — *resolved 2026-07-14 by Decision 3:* per-task budget is a hard LiteLLM
  `max_budget`; the kill-switch is key revocation / dropping a team budget to €0. Timer cadence
  remains a phase-4 dispatcher tuning parameter.
* ~~**Permission mode**~~ — *resolved 2026-07-14 by Decision 4:* the answer is **not** the client
  hook set (opencode doesn't run it) — it is server-side enforcement (Forgejo `pre-receive` + CI),
  a phase-3 prerequisite before attendance is removed.
* **Worktree hygiene** — unattended worktrees must be cleaned up; PR-per-ticket keeps `main`
  serialization out of scope (the concurrent-writers doctrine stays for attended work).

## Decisions this RFC feeds

| State | ADR | Decision |
| --- | --- | --- |
| proposed | [ADR-0044](../adr/adr-0044-metered-inference-plane-litellm.md) | Metered inference plane — LiteLLM, self-hosted (Decision 3) |
| proposed | [ADR-0045](../adr/adr-0045-opencode-runtime-server-side-guards.md) | `opencode` agent runtime; safety guards move server-side (Decision 4) |
| candidate | — | Execution-substrate graduation: `AgentTask` operator + per-task ephemeral keys (post-pilot, Decision 5 v2) |
| candidate | — | Dark-factory dispatcher: trigger, claim protocol, guardrails (post-pilot) |

## Links

* [ADR-0044](../adr/adr-0044-metered-inference-plane-litellm.md) — metered inference plane ·
  [ADR-0045](../adr/adr-0045-opencode-runtime-server-side-guards.md) — opencode runtime + guards
* [ADR-0040](../adr/adr-0040-vikunja-task-management.md) — Vikunja adoption ·
  [ADR-0043](../adr/adr-0043-vikunja-roadmap-system-of-record.md) — board = roadmap SoT
* [ADR-0013](../adr/adr-0013-forgejo-leading-application-repos.md) (accepted) ·
  [ADR-0011](../adr/adr-0011-flux-source-forgejo.md) (proposed) — the cutover this program rides on
* `scripts/cluster-health/` — the scheduled-agent pattern the dispatcher extends
* `scripts/forgejo-sync.sh` — idempotent repo-settings/webhook tool that gains the
  external-tracker and n8n-webhook legs
* `webgrip/ai-skills` skills repo + `openspec` + `opencode` — the operator toolchain both devs and
  agents share (Decision 4)
