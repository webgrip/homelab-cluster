---
title: "Tokens are cheap. Review isn't."
published: false
description: "Agent tokenomics, review debt and comprehension debt, and where Glide draws the line on responsibility: budgets reserved before a run, spend settled from the gateway, per-run keys that expire, and a human merge."
tags: ai, kubernetes, devops, opensource
canonical_url: CANONICAL_URL_TBD
---

*Originally published at [CANONICAL_URL_TBD](CANONICAL_URL_TBD). This is the engineering cut:
more mechanism, less preamble.*

On 8 August I checked the run records for my coding agents. There were 45 of them from late July,
and they held zero usage figures. The agents' own books were empty. The LiteLLM gateway in front
of the models had every token.

Glide, the tool I build to turn tickets into pull requests that AI agents write and a person
reviews, takes the bill from the gateway for exactly that reason, never from the agent's own
report. In September a capacity plan answered a bigger question. I had asked how many agents my homelab could
run at once, and the limits came back in this order:

1. my own review capacity;
2. the model providers' daily caps;
3. Glide's own setting of one worker pod per agent team;
4. CPU and memory, where the three worker machines had room for seven writing agents in parallel.

Per run, the electricity costs between a tenth of a euro cent and one cent, and a cheap model
costs one to five euro cents. In July a two-sentence README fix, written by one agent and reviewed
by a second, cost **$0.019872** in total according to the gateway's ledger.

Tokens are cheap. The scarce resource in an agent pipeline is the person at the end of it.

**Scope, up front:** Glide is Apache-2.0, self-hosted on Kubernetes, pre-1.0, and I'm the only
maintainer. It works with Forgejo or GitLab and Vikunja or ClickUp. No GitHub, Jira or Linear yet.
The checklist near the end applies to any agent tool.

## Three costs, and only one shows up on an invoice

The token bill is visible and small per run. It can still surprise you, because an agent in a loop
doesn't get tired.

**Review debt** is the queue. Glide's planning docs reduce it to one line:

```text
accepted results per week <= min(ready tickets, candidate changes produced, review capacity)
```

With 20 good tickets a week, 50 candidate changes from the agents, and 8 you can properly review,
you ship 8. Double the agents to 100 candidate changes and you still ship 8, with 92 pull requests
waiting. Better tests and clearer evidence might lift review to 16 a week. More agents won't.

**Comprehension debt** is code that got merged, works, and nobody on the team understands. It has
no queue. It surfaces when something breaks and the person on call reads the module for the first
time.

Behind all three sits the question a lead eventually asks: *who is responsible for this change?*
"The agent" means nobody.

## The shape of Glide

A **Work Item** is a ticket you've decided to do. You assign it to an agent **team**. Glide runs the
team's roles (typically a writer, a reviewer and fix rounds) as short-lived Kubernetes jobs, each
with its own budget and model key. The output is one pull request. You merge it or you don't.

- **Ploeg** ("crew") is the Go controller that authorizes, budgets and runs every agent run.
- **Vloer** ("floor") is the front end, in the browser or in VS Code.
- The harness is pluggable: OpenHands by default, Claude Code, any ACP agent such as opencode, or a
  plain command.

Glide doesn't merge, deploy or host models. Models come through a LiteLLM gateway you run.

## Reserve, spend, settle from the gateway

Think of a card payment: a hold for the estimated amount, replaced later by the real charge.

Before a run starts, Ploeg claims the work, locks the Work Item's budget pool (a **Shift**) and
reserves the run's share, in one database transaction. With less than five cents left, nothing
happens: no pod starts work, no key is minted, no attempt is used up. A test covers the race you'd
worry about: five concurrent requests against a pool that can fund two, and exactly two succeed.

The worst case is written down before anything runs. For my cheapest team, bronze:

| | |
| --- | --- |
| Writer cap | $2.00 |
| Reviewer cap | $0.40 |
| Runs (writer, reviewer, two fix rounds) | 6 |
| Worst case, per the config comment | $7.20 |
| Pool per Work Item | $8.00 |

When a run ends, Ploeg reads the gateway's spend log for that run's key. That is the lesson from
the 45 empty run records.

{% details How the hold and settlement work %}

- Claim, row lock and reservation run in one transaction with `SELECT … FOR UPDATE SKIP LOCKED`;
  the minimum reservation is $0.05 (`apps/ploeg/pkg/store/shift.go`). With the pool exhausted, the
  claim API answers `204 No Content`.
- Tests: `TestAuthorizeIsAtomicUnderConcurrency` (the five-request race),
  `TestSettlementReleasesTheHoldAndRecordsSpend`, `TestSweptRunCannotReport`.
- Settlement calls `GET /spend/logs` per run key (`apps/ploeg/pkg/litellm`, called from
  `pkg/httpapi/llm_control.go`). A sweeper settles runs whose worker died.
- Two budget levels: a pool per Work Item and a cap per role.
- Limit: the gateway budget and key lifetime bound spend from requests already in flight when a key
  is blocked; they can't make it exactly zero.

{% enddetails %}

**"LiteLLM already has budgets."** It does: capped, expiring keys, and Glide uses exactly those.
What Glide adds is one pool per Work Item shared by all its runs, the reservation taken before a key
exists, and a settlement that returns the unused hold. An org-wide monthly cap tells you afterwards
that you spent too much. It can't tell you, before a run starts, whether this ticket may still cost
another $2.40.

## Per-run keys, and what they don't cover

Each run gets a LiteLLM virtual key named after the run, capped at the run's budget, valid for four
hours by default. Ploeg refuses to mint a key without a cap. The worker refuses to start if it can
see the gateway master key, the database URL or the forge admin token; those stay in the
controller.

The weak spot: the harness does see its per-run model key, and on my cluster it pushes with a
shared forge token for the agent account. A prompt-injected agent could spend up to its run's cap
within four hours and push to whatever that account can reach. Glide has a design (ADR-0034, with
tests) that gives the harness only placeholders behind a local proxy, and one that mints a forge
token per run. Both are opt-in and I haven't switched them on. Today the protection is the cap,
the expiry, and the repository access of that one agent account.

## Six runs, one pull request

On bronze a Work Item can take six model-spending runs and still end in **one** pull request. The
reviewer is a separate agent with a read-only forge token. The Helm chart refuses to render a team
that has a reviewer role but no read-only token, and a reviewer never falls back to the write
token. Failing CI checks on Forgejo or GitLab go back to the writer as a fix round.

Agent-proposed follow-up work lands as **proposed** and waits for a person to approve it. One run
may create at most 5 items, one team may have at most 20 open, and anything over a limit is
rejected and logged. A team can switch approval off (`autoDispatch`); the design record behind this
is itself still marked proposed.

Not built yet: holding back new work while your review queue is full. That admission rule is a
written proposal.

## Comprehension debt stays yours

Glide keeps the reasons next to the change: the Work Item says why and what, and the reviewer's
verdict says what a second reader found. Vloer's stated goal is to put the ticket, the diff, the
checks that ran and the open questions together, and to make weak evidence easy to spot. That
lowers the cost of understanding. It doesn't create it.

The success measures are defined (clean-merge rate, and the minutes I actively spend per pull
request), and Glide's KPI page says *nothing on this page is measured yet*. So there is no success
rate in this post.

Glide never merges. Whoever presses merge owns the change, as with a colleague's pull request they
approved. This week I decided the ledger should also record *who* started a run.

## Eight questions for any coding-agent tool

1. Is a budget reserved **before** a run starts, per ticket, or is spend only capped per month?
2. Where does the cost figure come from: the provider or gateway, or the agent's own report?
3. Does each run get its own credential, and when does it expire?
4. What can a prompt-injected agent push to, and with which token?
5. Does one ticket end in one pull request, however many attempts it took?
6. Is there a second reviewer that cannot push?
7. Can agents create new work, and who approves it before it runs?
8. Who merges?

Glide today: yes; the gateway; yes, after four hours; a shared account (per-run tokens designed but
off); yes; yes; yes, with limits and a switch; you.

## Why not kagent?

kagent is a CNCF sandbox project for AI agents on Kubernetes. Its 1.0 (still alpha) runs agents on
a new layer, Agent Substrate, which injects one credential per hostname, so it can't carry a
separate model key per run. On my cluster it would also need a privileged daemon on every node,
Kubernetes 1.37 and a beta API.

So I split the layers three ways. Glide is the engine: admission, budget, keys, reviewer, one pull
request, human merge. The sandbox under each run is its own layer: Kata Containers or gVisor via
the Kubernetes SIG project agent-sandbox. Tools come in over MCP, possibly including kagent's own
tool server. Neither the sandbox nor MCP is wired into Glide today.

{% details Sandboxes, Talos and what's live %}

- A normal container shares the node's kernel. **gVisor** puts a user-space kernel (`runsc`)
  between the container and the node; light, but some workloads run slower or not at all. **Kata**
  gives each pod a small VM with its own kernel, at roughly 160 MiB and 0.25 CPU extra per pod on
  my workers.
- Talos is immutable, so runtimes arrive as system extensions in the node image. My three workers
  run the `kata-containers` 3.32.0 extension, a `kata` RuntimeClass is live, and a standing smoke
  job boots a real guest kernel.
- agent-sandbox (v1.0 since August) lets a template choose the RuntimeClass. Glide has had an
  experimental executor for it since 26 September; production workers still use the node's default
  runtime.
- Glide's harnesses pass no MCP servers today. The plan is a read-only role that reaches Grafana,
  logs and a read-only Kubernetes view through my existing MCP gateway, with its per-run key.
- kagent's Substrate runs a privileged node agent, runs agent pods as root with 13 added Linux
  capabilities, and downloads its own `runsc` instead of using a pre-installed one.

{% enddetails %}

In Glide's own survey of the larger open-source agent orchestration projects (26 September),
per-run keys at a proxy with a budget reserved before the run and settled afterwards turned up in
none of them. The same survey made me drop two claims I used to make: leases that survive a dead
pod, and event-driven dispatch, are no longer unusual.

## What isn't true yet

| You might expect | Today |
| --- | --- |
| GitHub, Jira or Linear | No. Vikunja and ClickUp; Forgejo and GitLab. |
| Agents run in a Kata or gVisor sandbox | No. Default runtime; the agent-sandbox executor is experimental. |
| The harness never sees a credential | No. Proxy isolation is designed and tested, opt-in, off here. |
| Per-run forge tokens | Designed, off here; a shared agent account pushes. |
| Measured merge rate, time to PR, cost per PR | Not measured. |
| New work waits while review is full | Proposed, not built. |
| More than one maintainer | No. One owner, pre-1.0. |

## Try it without spending anything

Agents already commit to Glide under the worker's git identity, `agent-builder`. One July change is
titled *"ploeg-worker owns the per-run LiteLLM key lifecycle (mint + always-revoke)"*: the agents
changing how Glide hands out the keys that pay for them.

The repository has a deterministic demo that runs Ploeg, Vloer and PostgreSQL with no model calls:

```bash
mise run demo-unified
```

Code: [forgejo.webgrip.dev/webgrip/glide](https://forgejo.webgrip.dev/webgrip/glide) · Docs:
[docs.webgrip.dev/glide](https://docs.webgrip.dev/glide)

The model spend was never the hard part of letting agents write code. Glide is my attempt at the
rest of it.
