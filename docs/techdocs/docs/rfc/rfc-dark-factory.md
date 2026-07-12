# RFC: Dark factory — agent-driven ticket execution

> Status: **Accepted in part** · Date: 2026-07-12 · Two core decisions ratified by the owner
> (review gate, dispatcher runtime); the pilot must answer the remaining open questions before the
> unattended loop switches on.

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

Assignment is **label-based** (`agent/claude` + claim/progress/completion comments), not native
Vikunja assignees: accounts come from Authentik OIDC, and an Authentik `service_account` cannot
perform the interactive OIDC login Vikunja requires before a user is assignable. Native
assignment is deferred until that's worth solving.

## Phase map

| Phase | Work | Gate |
| --- | --- | --- |
| 0 (unblocked) | `VIK-<taskID>` convention (skill + AGENTS.md + Forgejo external tracker) · Vikunja webhooks enabled · `agent-ready` DoR gate + claim protocol | — |
| 1 | n8n enforcement loop + nightly reconciler | Phase 0 |
| cutover | Forgejo CI parity → Forgejo-leading cutover (existing tickets) | — |
| 2 | Dispatcher pilot: attended runs, then unattended via Forgejo PRs | cutover + phase 0 |
| 3 | In-cluster dispatcher · agent-run reporting hardening | pilot verdict |

The full work breakdown lives on the board: `theme/dark-factory` label, Homelab Roadmap project,
with `precedes`/`blocked` relations encoding this table.

## Open questions the pilot must answer

* **Concurrency/claim** — one ticket per dispatcher run to start; is the claim comment + label
  enough to prevent double-pickup once more than one dispatcher exists?
* **Failure reporting** — a failed run must comment on the ticket and notify (ntfy); is that
  enough, or does the board need a `blocked/agent-failed` state?
* **Budget & cadence** — timer frequency, per-run token budget, and a kill-switch convention.
* **Permission mode** — the pilot runs `--dangerously-skip-permissions` like digest.sh, relying on
  the repo's PreToolUse guard hooks; confirm the hook set is sufficient for write-capable
  unattended runs *before* removing attendance.
* **Worktree hygiene** — unattended worktrees must be cleaned up; PR-per-ticket keeps `main`
  serialization out of scope (the concurrent-writers doctrine stays for attended work).

## Decisions this RFC feeds

| State | ADR | Decision |
| --- | --- | --- |
| candidate | — | Dark-factory dispatcher: trigger, claim protocol, guardrails (after the pilot) |
| candidate | — | In-cluster dispatcher runtime (after the pilot) |

## Links

* [ADR-0040](../adr/adr-0040-vikunja-task-management.md) — Vikunja adoption ·
  [ADR-0043](../adr/adr-0043-vikunja-roadmap-system-of-record.md) — board = roadmap SoT
* [ADR-0013](../adr/adr-0013-forgejo-leading-application-repos.md) (accepted) ·
  [ADR-0011](../adr/adr-0011-flux-source-forgejo.md) (proposed) — the cutover this program rides on
* `scripts/cluster-health/` — the scheduled-agent pattern the dispatcher extends
* `scripts/forgejo-sync.sh` — idempotent repo-settings/webhook tool that gains the
  external-tracker and n8n-webhook legs
