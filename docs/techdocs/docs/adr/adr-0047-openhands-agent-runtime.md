---
status: proposed
date: 2026-07-17
---

# OpenHands is the agent runtime, superseding opencode

Technical Story: [RFC: Dark factory](../rfc/rfc-dark-factory.md), Decision 4 — reconsidered.
Supersedes [ADR-0045](adr-0045-opencode-runtime-server-side-guards.md).

## Context and Problem Statement

ADR-0045 (proposed, never ratified) chose **opencode** as the agent runtime for human/agent
parity, moving the `.claude/` safety guards server-side. Two facts surfaced since that make the
choice worth reconsidering before the guard-parity build (board `#269`) and the author pilot
(`#270`) are spent against it:

1. **opencode's only viable build is a pinned beta** (`0.0.0-next-15495`, binary `opencode2`) that
   self-updates and churns daily; the exact pin exists precisely to fight that. Running an
   *unattended* factory on a self-updating beta is an operational risk the RFC did not weigh.
2. An evaluation of **OpenHands** (Software Agent SDK **v1.21.0**, MIT core, ~74k★, VC-backed)
   found a **released, versioned, self-hostable** harness with native **LiteLLM** (ADR-0044) and
   **MCP**, a Docker-sandboxed headless runtime, and an issue→PR resolver.

The question: keep opencode (agent-native multi-agent + per-agent keys, on a churning beta) or
adopt OpenHands (a mature released runtime with a one-strong-agent worldview)?

## Decision Drivers

* **Operational stability for unattended runs** — a released, versioned harness over a
  self-updating beta.
* **Maturity / low bus-factor** — a backed project with a large community beats a self-maintained
  beta pin.
* **Native LiteLLM (ADR-0044) + MCP** — the metered plane and the MCP gateway must plug in unchanged.
* **`builder ≠ judge` independence** — the load-bearing safety property; must survive the change.
* **Human/agent parity** — devs and agents run one toolchain (the original ADR-0045 driver).
* **Minimise reinvention** — prefer the beaten path unless a road offers serious gains.

## Considered Options

* **OpenHands** — mature released runtime; one strong agent + a discipline skill; independence via a
  separate review pod.
* **opencode (ADR-0045)** — agent-native six-role team + per-agent LiteLLM keys, but a pinned
  churning beta.
* **Run both** — an operator picks; doubles the surface to keep in parity.

## Decision Outcome

Chosen option: **OpenHands**, because it trades opencode's in-harness multi-agent split — which
opencode does natively but only on a churning beta — for a **released runtime**, while the
load-bearing property (`builder ≠ judge`) is **preserved at the pipeline level rather than inside
the harness**: a build pod runs OpenHands headless and opens a Forgejo PR; a **separate** review pod
(independent key/model/context — the Forgejo PR-review lane, board `#276`, the RFC's independent
AI pre-review) judges it. That separation is arguably cleaner than in-harness roles, and it is
where the safety value actually lives.

Load-bearing specifics:

* **Install** `openhands` via `uv tool install openhands` (SDK v1.21.0); pin the pod image to a
  released SDK version — no `@next`/beta.
* **Run** `openhands --headless --override-with-envs` with `LLM_MODEL=litellm_proxy/<model>`,
  `LLM_BASE_URL` at the metered proxy, `LLM_API_KEY` = a per-run budgeted key (ADR-0044). Docker
  sandbox runs in-pod.
* **Discipline** ports as an always-active OpenHands **repo skill**
  (`.openhands/skills/team-bronze/team-bronze.md`). The mechanism is load-bearing and was verified
  against the installed SDK (v1.21.0, `openhands.sdk.skills`): a legacy-format `.md` with no trigger
  partitions into `repo_skills` → injected into REPO_CONTEXT on **every** run. An AgentSkills
  `SKILL.md` would instead land in `<available_skills>` (progressive disclosure) and reach the model
  only if the agent chose to invoke it — i.e. the discipline would be optional, so the filename is
  deliberately **not** `SKILL.md`. `AGENTS.md` (also loaded as an always-active repo skill) carries
  the architecture rules and now the delivery-discipline mandate — the same file opencode read, so
  the repo contract is harness-neutral.
* **Vikunja / observability tools** reach the agent through the LiteLLM MCP gateway (`#263`),
  unchanged by the runtime choice.

### Consequences

* Good, because a released, versioned runtime replaces a self-updating beta — materially lower
  operational risk for the unattended dispatcher (`#272`/`#273`).
* Good, because LiteLLM + MCP are native: the metered plane and MCP gateway plug in with no adapter.
* Good, because `builder ≠ judge` is preserved as a **pipeline** property (build pod → independent
  review pod), and per-**phase** LiteLLM attribution survives (two pods = two budgeted keys).
* Good, because human/agent parity holds — devs and agents both run OpenHands — and `AGENTS.md`
  makes the repo contract harness-neutral.
* Bad, because opencode's native **six-role, per-agent-key split within a single run** is lost;
  fine-grained per-role attribution would need the OpenHands SDK (Python custom agents) later.
* Bad, because guard parity (ADR-0045 / HAZ-01, board `#269`) and the skills-profile loadout
  (`#268`) were opencode-shaped and must be reworked for OpenHands' skills + `AGENTS.md` mechanism
  and its Docker sandbox; the author pilot (`#270`) becomes an OpenHands pilot; the dispatcher
  (`#272`) swaps `opencode --worktree` for `openhands --headless`.
* Bad, because OpenHands' enterprise governance (SSO/RBAC/audit/budget) is **Polyform-licensed, not
  FOSS**; for this single-team self-hosted use we stay on the MIT core and provide governance via
  LiteLLM (ADR-0044) + our own controls — never the Polyform control plane.
* Bad, because the Docker-sandboxed runtime is a new in-pod requirement (Docker-in-pod) that opencode
  did not need.

## Pros and Cons of the Options

### OpenHands

* Good, because released and versioned (v1.21.0), MIT core, large backing — low bus-factor.
* Good, because native LiteLLM + MCP + headless + sandboxed runtime out of the box.
* Neutral, because one strong agent, not a team — the discipline lives in a skill + `AGENTS.md`, and
  independence lives in a separate review pod.
* Bad, because per-role attribution and in-harness multi-agent regress; enterprise governance is
  non-FOSS.

### opencode (ADR-0045)

* Good, because agent-native primary→subagent teams with per-agent keys and `edit:deny` reviewers.
* Good, because full human/agent parity was its original driver.
* Bad, because the only viable build is a self-updating beta — an unattended-factory operational risk.

### Run both

* Good, because maximum operator flexibility.
* Bad, because it doubles the runtime + skill-compat surface to keep in parity, for no gain.

## More Information

* Supersedes [ADR-0045](adr-0045-opencode-runtime-server-side-guards.md); **[RFC Decision 4](../rfc/rfc-dark-factory.md)
  names opencode and needs an amendment note** pointing here.
* Evidence: the OpenHands evaluation — installed v1.21.0, Team Bronze discipline ported to
  `.openhands/skills/team-bronze/SKILL.md` (SDK-verified to load, always-active), and the
  stack-fit analysis (native LiteLLM/MCP; Forgejo/Vikunja glue identical to opencode; the beta-churn
  risk that tipped it).
* Reshapes board tickets `#268`, `#269`, `#270`, `#272`; `#276` (independent review lane) becomes
  the home of `builder ≠ judge`.
* Consumes the metered keys of [ADR-0044](adr-0044-metered-inference-plane-litellm.md).
* 2026-07-17 — proposed, superseding ADR-0045 after the OpenHands evaluation; pending ratification
  with the OpenHands author-pilot (`#270` reworked).
