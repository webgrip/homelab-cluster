---
status: superseded by [ADR-0047](adr-0047-openhands-agent-runtime.md)
date: 2026-07-17
---

# opencode is the agent runtime; safety guards move server-side

Technical Story: [RFC: Dark factory](../rfc/rfc-dark-factory.md), Decision 4 (ratified 2026-07-14) —
the runtime choice and its load-bearing consequence.

## Context and Problem Statement

The dark-factory pilot ran headless **claude** with `--dangerously-skip-permissions`, relying on the
repo's `.claude/` **PreToolUse guard hooks** as the safety net — the hooks that block editing a
`*.sops.yaml`, committing a plaintext secret, or running a destructive cluster command. The RFC left
this open as its "permission mode" question: *is the hook set sufficient for unattended runs?*

The SOTA extension wants developers and agents to run the **same** toolchain so the pipeline has one
shape (human/agent parity). Developers use **opencode** + **openspec** + the `webgrip/ai-skills`
skills repo. Adopting that toolchain for agents forces the permission question to a head, because:

> **opencode does not execute the `.claude/` PreToolUse hooks.** They are a Claude Code mechanism.

So the moment agents move to opencode, the *only* thing standing between an unattended run and a
committed plaintext secret disappears. The runtime decision and the guard decision are therefore one
decision, not two.

## Considered Options

* **opencode all-in; re-implement the guards server-side** (chosen)
* **Keep headless claude** so the `.claude/` hooks keep protecting unattended runs
* **Run both runtimes** behind the same skills + keys, guards server-side regardless

## Decision Outcome

Chosen option: **"opencode all-in; re-implement the guards server-side"**, because parity is worth
more than the client-side hooks, and — decisively — **client-side hooks were never a real security
boundary for unattended work anyway**. A guard that lives in the operator's workstation config does
not protect a Job running in-cluster or a second developer using a different client. The correct home
for the block-list is the forge and CI, where it applies to every push regardless of who or what
produced it.

Load-bearing specifics:

* **Runtime.** `opencode` (headless for unattended runs) is the agent and developer runtime, driving
  `openspec` for spec-first changes and `npx skills add <profile>` for per-ticket skill loadout from
  the `webgrip/ai-skills` skills repo.
* **Guards move to the forge and CI — the block-list is re-implemented in two independent places:**
  * a **Forgejo `pre-receive` hook** that rejects a push introducing a `*.sops.yaml` edit, a
    plaintext secret pattern, or other block-listed content — server-side, un-bypassable by the client;
  * **CI checks** (the existing Forgejo Actions pipeline) that re-run the same block-list plus
    `./scripts/run-flux-local-test.sh`, so a PR cannot go green with a violation.
* **Ordering constraint.** These server-side guards are a **phase-3 prerequisite**: attendance is not
  removed from an opencode run until both the `pre-receive` hook and the CI check are live and a
  mutation test proves each fires (break what it checks each way it claims to catch, watch it block).
* **Attended interim.** Until then, opencode runs stay attended, exactly as the RFC's Decision 1
  keeps interactive work on `main` unchanged.

### Consequences

* Good, because devs and agents share one runtime, one change protocol, and one skill source — the
  pipeline has a single shape, and a skill or fix written for one operator serves the other.
* Good, because the safety boundary moves from a per-client convention to a server-side control that
  covers *every* push — a stronger guarantee than the pilot had, not a weaker one.
* Good, because it converts the RFC's open "permission mode" question into a concrete, testable gate.
* Bad, because the block-list now lives in three dialects (the legacy `.claude/` hooks for attended
  Claude Code work, the Forgejo `pre-receive` hook, and CI) that must be kept in sync or they drift.
* Bad, because opencode + openspec + the marketplace skills are a newer, less-exercised toolchain
  in this repo than headless claude — skill portability (HAZ-06) is unproven until a profile runs
  identically under both.

### Confirmation

* A test branch that edits a `*.sops.yaml` or plants a plaintext secret is **rejected by the Forgejo
  `pre-receive` hook** on push, and — if it somehow lands — **fails the CI check** on the PR. Both
  legs are proven by a deliberate mutation test, not assumed.
* An opencode run with no `.claude/` hooks present still cannot land a block-listed change, because
  the guard no longer depends on the client.
* One `webgrip/ai-skills` profile is shown to drive the same task under both opencode and Claude Code
  (closes HAZ-06) before the two runtimes are declared interchangeable.

## Pros and Cons of the Options

### opencode all-in; guards server-side

* Good, because full human/agent parity on one toolchain.
* Good, because the safety boundary becomes server-side and universal.
* Bad, because the block-list is maintained in more than one place.

### Keep headless claude

* Good, because the `.claude/` PreToolUse hooks keep working with zero new guard infrastructure.
* Bad, because it breaks parity — devs run opencode, agents run claude, so the pipeline is two
  systems and skills/fixes fork.
* Bad, because it leaves the RFC's real finding unaddressed: a client-side hook is not a boundary for
  in-cluster unattended work regardless of runtime.

### Run both runtimes

* Good, because maximum flexibility — an operator picks the runtime they prefer.
* Neutral, because it still requires the server-side guards (opencode is in the mix), so it does not
  save the guard work.
* Bad, because it doubles the surface to keep in parity (two runtimes, two skill-compat matrices).

## More Information

* Technical story: [RFC: Dark factory](../rfc/rfc-dark-factory.md) — Decision 4, gap HAZ-01, phase 3.
* 2026-07-14 — proposed; ratified in principle in the RFC's SOTA extension, pending the phase-3
  server-side guard build + mutation test.
* Supported by [ADR-0044](adr-0044-metered-inference-plane-litellm.md) — the metered keys this
  runtime consumes.
* Relates to the `.claude/` guard hooks and `./scripts/run-flux-local-test.sh` — the controls whose
  intent this decision relocates to the forge and CI.
* 2026-07-17 — **superseded by [ADR-0047](adr-0047-openhands-agent-runtime.md)** (OpenHands is the
  agent runtime) after evaluating OpenHands against opencode's beta-churn risk; body preserved
  unchanged per the append-only ADR convention. The server-side guard finding (HAZ-01) stands and
  carries forward — it is runtime-independent — but is reworked for OpenHands, not opencode.
