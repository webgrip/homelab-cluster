---
status: accepted
date: 2026-10-04
---

# Agent harnesses are plural behind ACP; OpenHands stays the default

Technical Story: [RFC: Dark factory](../rfc/rfc-dark-factory.md), Decision 4 — reconsidered a
second time. Supersedes [ADR-0047](adr-0047-openhands-agent-runtime.md).

## Context and Problem Statement

[ADR-0047](adr-0047-openhands-agent-runtime.md) (proposed 2026-07-17, never ratified) chose
OpenHands as *the* agent runtime and ruled opencode out. Two of the three facts it rested on have
since changed, and one of them is simply no longer true.

1. **"opencode's only viable build is a pinned beta."** ADR-0047's decisive objection was that
   `0.0.0-next-15495` self-updates and churns daily, and that running an *unattended* factory on a
   self-updating beta is an operational risk. Verified 2026-07-29: **opencode `v1.0.0` shipped
   2025-10-31 and the current release is `v1.18.9` (2026-07-28), MIT.** The canonical repository
   moved to `anomalyco/opencode` (`sst/opencode` redirects). There has been a stable line for nine
   months. The objection is void — not weakened, void.

2. **"Run both doubles the runtime and skill-compat surface, for no gain."** That cost has
   collapsed, for two independent reasons:
   - **One protocol covers both.** ACP wire version 1 is stable (the spec now lives in its own
     `agentclientprotocol` GitHub org, co-driven by Zed and JetBrains). `opencode acp` and
     `openhands acp` are both **native**, as are Gemini CLI, Goose, Copilot CLI and Cursor. A single
     client adapter reaches all of them, so "a second harness" is no longer a second integration.
   - **One values entry selects it.** `webgrip/ploeg` — the dispatcher this factory now runs on —
     carries a `harness.Adapter` seam with per-team `harness` overrides (adapter name, agent image,
     entrypoint, DinD) in its Helm values. Swapping harness *and* image per team is one block, not a
     parallel stack.

   The skill-compat half of the objection is also smaller than it looked. Ploeg composes the
   delivery-contract prompt itself (`pkg/worker/task.go`, `ComposePrompt`) for every dispatched run
   on every harness, so the discipline is harness-neutral by construction. Duplication between
   `.openhands/skills/` and `.opencode/agents/` bites only the **interactive** path, where a human
   runs the tool locally.

3. **Unchanged and still load-bearing:** OpenHands is released, versioned, MIT-cored, natively
   LiteLLM- and MCP-integrated, and is what the `agent-runner` image, the `team-bronze` discipline
   skill and [ADR-0048](adr-0048-dark-factory-execution-layer.md)'s execution layer are all built
   around. Nothing about it got worse.

The question is therefore no longer "which one", but "must it be exactly one".

## Decision Drivers

* **Operational stability for unattended runs** — ADR-0047's top driver, retained verbatim. It no
  longer selects *against* opencode, because opencode now has a stable line to pin.
* **`builder ≠ judge` must survive** — the load-bearing safety property (ADR-0047, RFC HAZ-05).
* **Do not pay for plurality twice.** Plurality is worth having only if one adapter buys all of it.
* **Dogfood the dispatcher's own thesis.** Ploeg's README promises "no lock-in on tracker, forge, or
  agent harness". A factory that can run exactly one harness is not evidence for that claim.
* **No decision should rest on a fact that has expired.** A ledger entry whose premise is false is
  worse than no entry, because it is quoted with confidence.

## Considered Options

* **Harness plurality behind ACP, with OpenHands as the default** (chosen)
* Keep ADR-0047 as written — OpenHands exclusively
* Switch the runtime to opencode, reverting toward [ADR-0045](adr-0045-opencode-runtime-server-side-guards.md)

## Decision Outcome

Chosen option: **harness plurality behind ACP, with OpenHands as the default**, because the only
argument that ever excluded a second harness was cost, and ACP plus Ploeg's adapter seam have
removed it — while every reason to keep OpenHands as the *default* is untouched.

Load-bearing specifics:

* **Default is unchanged.** `executor.harness.name` stays `openhands` for every team that does not
  explicitly override it. This ADR adds an option; it does not migrate anything.
* **ACP wire version 1 only.** v2 was announced 2026-07-20 as a draft, exists only as alpha
  pre-releases, and its own announcement says the wire protocol "can, and will, change before
  stabilization". It is not adopted, and support would be gated behind version negotiation.
* **One adapter, in Ploeg** (`pkg/harness/adapters/acp`), not one integration per agent. Agents are
  selected per team by a named launch profile.
* **Pin the agent, whichever it is.** No `@next`, no floating tags, digest-pinned images in
  `webgrip/infrastructure`. ADR-0047's stability driver applies to opencode exactly as it applies to
  OpenHands — it simply no longer disqualifies it.
* **`builder ≠ judge` stays a pipeline property**, exactly as ADR-0047 and ADR-0048 specify: a build
  pod and a separate review pod, with distinct forge identities so a forge refuses self-approval.
  Running the reviewer on a different harness *strengthens* that independence; it does not replace
  it. In-harness role splitting is not reintroduced as the safety mechanism.
* **Where a second harness earns its keep:** opencode's native subagent roster with per-agent
  permission ACLs (an `edit: deny` reviewer is expressible directly) suits judge-shaped roles, which
  is precisely where independence matters. OpenHands' one-strong-agent model remains the right fit
  for the builder.

### Consequences

* Good, because the estate's ledger stops resting on a claim that is nine months out of date.
* Good, because a persona can be matched to the harness that suits it without standing up a second
  stack — a values entry, not a parallel pipeline.
* Good, because the reviewer can run on a different harness *and* a different model family, which is
  stronger independence than a second pod alone.
* Good, because Ploeg's harness conformance suite gains a second real consumer, which is the only
  honest evidence for its "bring your own harness" claim.
* Bad, because a second agent image must be built and digest-pinned in `webgrip/infrastructure`
  (`opencode-runner` alongside `agent-runner`), and kept current.
* Bad, because interactive-path skill duplication (`.openhands/skills/` vs `.opencode/agents/`)
  remains real. Ploeg's prompt composition removes it for dispatched runs only, and no one should
  claim otherwise.
* Bad, because ACP is a new protocol dependency and its Go client (`coder/acp-go-sdk`) trails the
  upstream schema — notably its usage type has no field for cost. Mitigated by Ploeg owning its own
  tolerant decoding rather than the SDK's generated semantics.
* Neutral, because OpenHands' Polyform-licensed enterprise governance stays out of scope, unchanged
  from ADR-0047: governance is LiteLLM ([ADR-0044](adr-0044-metered-inference-plane-litellm.md))
  plus our own controls.

### Confirmation

* `executor.harness.name` in this repo's Ploeg HelmRelease is the observable default and must read
  `openhands` unless a team block overrides it — visible in `kubernetes/apps/ploeg/`.
* Every adapter, ACP included, must pass Ploeg's harness conformance suite
  (`pkg/harness/harnesstest`) in Ploeg's CI. An adapter that fabricates outcomes, drops a stuck
  reason, or invents a failure-reason value fails the gate.
* The ACP adapter validates its launch profile at worker startup, **before** it claims work, so a
  misconfigured team fails fast instead of burning a lease and an attempt.
* Agent images are digest-pinned; a floating tag in `webgrip/infrastructure` is a review failure.
* `builder ≠ judge` remains server-enforced by the Forgejo merge whitelist per
  [ADR-0050](adr-0050-per-repo-delivery-contract.md) — `agent-builder` cannot merge its own PR,
  whatever harness produced it.

## Pros and Cons of the Options

### Keep ADR-0047 as written (OpenHands exclusively)

* Good, because it is the smallest possible change: nothing to build, nothing to pin.
* Good, because one runtime is one thing to keep patched.
* Bad, because its decisive premise — "the only viable build is a self-updating beta" — is factually
  false as of 2025-10-31 and has been for nine months.
* Bad, because it forecloses matching a persona to a harness for a cost that no longer exists.

### Switch the runtime to opencode

* Good, because agent-native primary→subagent teams with per-agent keys and `edit: deny` reviewers,
  which was ADR-0045's original and still-valid attraction.
* Bad, because it discards the OpenHands investment — the `agent-runner` image, the `team-bronze`
  always-active repo skill, and ADR-0048's execution layer — for a gain that plurality delivers
  without the churn.
* Bad, because it would repeat this ADR's own mistake in the opposite direction: making an exclusive
  choice where the seam makes exclusivity unnecessary.

## More Information

* **Supersedes [ADR-0047](adr-0047-openhands-agent-runtime.md)**, which superseded
  [ADR-0045](adr-0045-opencode-runtime-server-side-guards.md). ADR-0047's *outcome* (OpenHands as
  the runtime) survives as the default; its *exclusivity* does not.
* **[RFC Decision 4](../rfc/rfc-dark-factory.md) still names opencode and still needs an amendment
  note.** ADR-0047 flagged this and it was never done; it now needs one note pointing here, not two.
* Evidence, verified 2026-07-29: opencode `v1.0.0` 2025-10-31 → `v1.18.9` 2026-07-28 (MIT, repo
  `anomalyco/opencode`); ACP wire version 1 stable, spec at `agentclientprotocol/agent-client-protocol`,
  schema release `schema-v1.20.0` 2026-07-21, v2 draft announced 2026-07-20 with alpha pre-releases
  only; native `acp` subcommands in opencode, OpenHands SDK 1.38.0, Gemini CLI 0.53.0, Goose 1.44.0,
  Copilot CLI 1.0.75 and Cursor; `coder/acp-go-sdk` v0.13.5 is the only serious Go client and trails
  the schema.
* Corroboration from an adjacent sweep: OpenHands closed its A2A tracking issue as `not_planned`
  (`OpenHands/software-agent-sdk#1060`) and shipped ACP instead — the incumbent harness evaluated
  both protocols and chose this one. Full dossier: `webgrip/ploeg`
  `docs/research/2026-07-28-a2a-fit.md`.
* Consumes the metered keys of [ADR-0044](adr-0044-metered-inference-plane-litellm.md); the
  execution substrate and role bots are [ADR-0048](adr-0048-dark-factory-execution-layer.md);
  delivery enforcement is [ADR-0050](adr-0050-per-repo-delivery-contract.md).
* Implementation lives in `webgrip/ploeg` (`pkg/harness/adapters/acp`, backlog #64, which also
  closes #63). This repo owns only the HelmRelease values that select a harness per team.
* Watch items that would move this decision again: ACP v2 stabilising with a compatibility
  commitment; `coder/acp-go-sdk` falling far enough behind the schema to force a hand-rolled
  transport; or either harness losing its stable release line, which would restore ADR-0047's
  original objection against that harness specifically.
* 2026-07-29 — proposed, superseding ADR-0047 after opencode's stable line and ACP v1 removed the
  cost of a second harness. Pending ratification alongside the ACP adapter landing in Ploeg.
* 2026-09-29 — ACP adapter live in production: bronze runs OpenHands over ACP
  (`harness.name: acp`, `profile: openhands`, 4808ac45); the executor default stays `openhands`
* 2026-10-04 — accepted (status corrected in audit); the Ploeg-side conformance-suite gate was not
  re-checked in this audit
* 2026-10-04 — [ADR-0048](adr-0048-dark-factory-execution-layer.md), cited here as the execution layer, is deprecated; Ploeg's executors are that layer now, with the same role bots and per-run keys (a8a92ef2)
