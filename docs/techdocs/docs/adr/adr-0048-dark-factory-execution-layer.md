---
status: proposed
date: 2026-07-18
---

# Dark-factory agents run on a dedicated Forgejo Actions pool, poll-dispatched, as two role bots

Technical Story: [RFC: Dark factory](../rfc/rfc-dark-factory.md), Decision 5 — the execution
substrate — and its HAZ-02 (per-task budget) and HAZ-05 (independent reviewer) hazards.

## Context and Problem Statement

The agent-runner image is built and published ([ADR-0047](adr-0047-openhands-agent-runtime.md)):
headless OpenHands, a per-run LiteLLM key minted and revoked by its entrypoint (ADR-0044), a docker
CLI for its sandbox, and a baked skills loadout. **Nothing runs it.** There is no execution
substrate, no forge identity for it to push as, and no trigger. This ADR settles those three so one
Vikunja `agent-ready` ticket can become a reviewed PR.

Three questions had real alternatives:

1. **Substrate** — a bespoke Kubernetes `Job`/CronJob controller, or the existing KEDA-scaled
   Forgejo Actions runners? The runners already carry privileged Docker-in-Docker, a Kyverno
   PolicyException, autoscaling, ESO-delivered secrets, logs, retries and a UI. A bespoke controller
   re-earns every one of those plus new RBAC to create Jobs.
2. **Trigger** — a Vikunja webhook (via n8n, which is deployed), or a scheduled poll? Vikunja's
   outgoing webhooks are not even enabled yet, agent runs cost real money, and n8n's flows live in
   its database rather than git — unversioned config on a money-spending critical path.
3. **Identity** — one bot, one bot per run, or one bot per role? A forge will not let a user approve
   its own pull request, so `builder ≠ judge` (ADR-0047's load-bearing safety property) is a fiction
   unless the builder and the reviewer are *different* forge accounts.

## Decision Drivers

* **Reuse over reinvention** — RFC Decision 5 already ratified "reuse the runners, not a bespoke
  controller"; the v2 graduation is an `AgentTask` operator.
* **Self-healing dispatch** — a dropped or duplicated trigger must never strand a ticket or
  double-spend.
* **`builder ≠ judge` survives to the forge** (ADR-0047, RFC HAZ-05).
* **Bounded blast radius** — an LLM-driven process in a privileged DinD container is the threat; the
  spend key, the push scope and the merge gate must all be bounded.
* **Capacity isolation** — agent runs must not queue behind CI image builds (or vice versa).

## Considered Options

* **Forgejo Actions on a dedicated runner pool, poll-dispatched, two role bots** (chosen)
* **A bespoke k8s Job/CronJob controller** issuing agent pods directly
* **Webhook-primary dispatch** (Vikunja → n8n → workflow dispatch) as the only trigger

## Decision Outcome

Chosen option: **"Forgejo Actions on a dedicated runner pool, poll-dispatched, two role bots"**,
because it reuses a proven privileged-DinD execution plane, keeps the entire dispatch path in git,
and makes the independent-reviewer property real at the forge — while a scheduled poll makes the
whole thing self-healing.

Load-bearing specifics:

* **Substrate.** A second KEDA `ScaledJob`, `forgejo-agent-runner`, mirroring `forgejo-runner` but
  advertising runner label **`agent`** and scheduled on the **`soyo`** pool (measured headroom
  ~49% CPU / 38% memory, versus the CI pool's oversubscribed node). Its own registration
  (`keda-global-agent`), its own Kyverno PolicyException matching the new ScaledJob + pod labels, and
  a raised runner `timeout` (agent runs exceed the CI pool's `1h`). The reused
  `TriggerAuthentication` is only a read-pending-jobs token.
* **Execution mode.** Host execution (`agent:host`) with the pool's main container being the
  agent-runner image, so the entrypoint's `DOCKER_HOST=tcp://localhost:2376` + TLS certs resolve
  exactly as they do for the CI pool. Language gates run in **CI's own images** (`rust-ci-runner`,
  `php:8.5-cli`, `node:24-alpine`) via that daemon, so the agent's gates match CI rather than
  approximating it. (Confirmed by a DinD-reachability spike before the workflow is finalised.)
* **Trigger.** Poll-primary: a hardened k8s CronJob lists Vikunja `agent-ready` tickets, skips any
  already carrying an `agent/*` claim, **claims one** (label + comment + bucket move), then dispatches
  `POST /api/v1/repos/{owner}/{repo}/actions/workflows/agent-run.yml/dispatches` with
  `Authorization: token …` (Forgejo style). The **claim is the lock** — check-then-claim makes the
  poll (and a future webhook) idempotent. A Vikunja webhook is a *later* accelerator, added via a
  git-declarative receiver (Argo Events), never n8n, and never the only path.
* **Identity.** Two role bots on the `renovate-forgejo-bot` pattern (generated password, provisioner
  Job, one identity — not per run): **`agent-builder`** (`write:repository` + `write:issue`, opens
  PRs) and **`agent-reviewer`** (`read:repository` + `write:issue` only — read + comment, per
  HAZ-05). Per-run attribution comes from the LiteLLM `x-litellm-trace-id`, carried in the commit
  trailer beside `VIK-<taskID>`; no per-run forge identity is minted.
* **Spend.** The pool's pod env carries the LiteLLM master key so the entrypoint can mint a per-run
  budgeted key (ADR-0044) — **not** the org-level Forgejo Actions secret store, which would hand
  every workflow unlimited spend (RFC HAZ-02). PR-only, never direct to `main`; the server-side
  pre-receive block-list (the ADR-0045 finding) is the real containment.

### Consequences

* Good, because the privileged-DinD plane, Kyverno waiver, autoscaling, secret delivery, logs and UI
  are inherited, not rebuilt — the agent is "just another runner label".
* Good, because the dispatch path is entirely in git (CronJob + workflow), reviewable and Flux-
  reconciled; no unversioned n8n flow sits on the money path.
* Good, because a scheduled poll is self-healing: a missed trigger is caught next tick, and the
  claim-as-lock prevents double-dispatch/double-spend.
* Good, because two role bots make `builder ≠ judge` enforceable at the forge, and the reviewer's
  read-only scope bounds what a compromised review run can do.
* Good, because agent runs get isolated `soyo` capacity and never queue behind CI image builds.
* Bad, because any workflow that targets `runs-on: agent` can read the pool's master key; mitigated
  by pool-scoping and git-reviewed workflows, and to be tightened later with a budget-capped *minter*
  key rather than the true master key.
* Bad, because host execution couples the pool image to the agent-runner image (a runtime change is a
  pool-image bump), and the runner's node externals must tolerate the image's newer Node — verified
  by the spike.
* Bad, because poll latency (minutes) is worse than a webhook; acceptable — tickets are not urgent,
  and the webhook accelerator can be added without changing the model.

### Confirmation

* `kubectl -n forgejo get scaledjob forgejo-agent-runner` exists; the Forgejo admin runners list
  shows `keda-global-agent` advertising label `agent`; **no** Kyverno `PolicyViolation` on its Jobs.
* A dispatched run's pod lands on a `soyo-*` node (`kubectl get pods -n forgejo -o wide`), and inside
  it `docker info` succeeds and `docker run --rm rust:latest cargo --version` works.
* End-to-end pilot on one `effort/S`, `agent-ready` Erfbeeld ticket: it is claimed and moved, a PR is
  opened with a `VIK-<taskID>` trailer, gates run with output pasted, a per-run LiteLLM key appears in
  spend under the run's trace-id **and is revoked** after, and a **human** merges — never the agent.
* Running the dispatcher CronJob twice back-to-back produces exactly one run for the claimed ticket
  (idempotency).

## Pros and Cons of the Options

### Forgejo Actions on a dedicated pool, poll-dispatched, two role bots

* Good, because it reuses a proven privileged-DinD plane and keeps dispatch in git.
* Good, because poll + claim-as-lock is self-healing and idempotent.
* Bad, because the pool image is coupled to the runtime image, and the master key is visible to
  agent-labelled workflows.

### Bespoke k8s Job/CronJob controller

* Good, because maximal control over the pod spec and no dependency on Forgejo Actions semantics.
* Bad, because it re-implements DinD, the Kyverno waiver, autoscaling, secret delivery, logs and a UI
  the runners already provide, and needs new RBAC to create Jobs — exactly what RFC Decision 5
  rejected for v1.

### Webhook-primary dispatch (Vikunja → n8n → dispatch)

* Good, because low latency.
* Neutral, because it still needs the claim-as-lock to be safe.
* Bad, because Vikunja webhooks are not enabled, and n8n's flows live in its database — unversioned
  config on a money-spending critical path, un-reviewable and non-reproducible.

## More Information

* Technical story: [RFC: Dark factory](../rfc/rfc-dark-factory.md) — Decision 5 (execution
  substrate), HAZ-02 (per-task budget), HAZ-05 (independent reviewer).
* Consumes the per-run keys of [ADR-0044](adr-0044-metered-inference-plane-litellm.md) and runs the
  image of [ADR-0047](adr-0047-openhands-agent-runtime.md).
* Supersedes the premise of board `#273` (the in-cluster dispatcher is a poll CronJob against Forgejo
  Actions, not a bespoke controller carrying an Anthropic credential — spend is per-run LiteLLM keys).
* Narrows board `#281` (Authentik-JWT-to-LiteLLM identities are largely redundant now that per-run
  budgeted keys are minted per Slice D); it may be closed or rescoped.
* Relates to the server-side guard finding of ADR-0045 (`#269`) — the pre-receive block-list is what
  contains an agent that pushes.
* 2026-07-18 — proposed, alongside the `forgejo-agent-runner` pool, the `agent-builder`/
  `agent-reviewer` bots, and the poll dispatcher; pending the end-to-end pilot.
