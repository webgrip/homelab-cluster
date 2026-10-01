# Tokens are cheap. Review isn't.

*Agent tokenomics, review debt and comprehension debt, and where Glide draws the line on
responsibility.*

*Draft v2, 2026-09-27. Not published. Needs Ryan's ownership pass. Every claim traces to
BLOGPOST-glide.research.md or to the Glide and homelab repositories; v2 incorporates a cold-reader
test and a source-level fact-check.*

> **TL;DR.** Glide turns a ticket into a pull request that AI agents write and a person reviews.
> It reserves the money before an agent gets a key, takes the bill from the model gateway instead
> of the agent's own report, gives every run a capped key that expires, and never merges.
> It is open source (Apache-2.0), self-hosted on Kubernetes, pre-1.0, and maintained by one
> person: me. **Who can use it today:** teams on Forgejo or GitLab with Vikunja or ClickUp. No
> GitHub, Jira or Linear yet. If that rules you out, the checklist near the end still applies to
> whatever agent tool you pick.

---

In September I planned how many coding agents my homelab could run at once. I expected a hardware
answer. The plan came back with the limits in a different order.

First: **my own review capacity**. Second: the model providers' daily caps. Third: Glide's own
setting of one worker pod per agent team. CPU and memory came last; the three worker machines had
room for seven writing agents in parallel. The electricity for one agent run costs between a
tenth of a euro cent and one cent. The model spend for a run on a cheap model is one to five euro
cents. In July a two-sentence README fix, written by one agent and reviewed by a second, cost
**$0.019872** in total, according to the gateway's ledger.

Tokens are cheap. The scarce resource in an agent pipeline is the person at the end of it.

## A coding agent costs you three things

The token bill is the visible one. Per run it is small, and it can still surprise you, because an
agent in a loop doesn't get tired.

**Review debt** is the second. Glide's planning docs reduce it to one line:

```text
accepted results per week <= min(ready tickets, candidate changes produced, review capacity)
```

Say you can write 20 good tickets a week, your agents produce 50 candidate changes, and you can
properly review 8. You ship 8. Double the agents to 100 candidate changes and you still ship 8,
with 92 pull requests waiting. Better tests and clearer evidence might lift review to 16 a week.
More agents won't.

**Comprehension debt** is the third: code that got merged, works, and that nobody on the team
understands. Review debt at least shows up as a queue. Comprehension debt shows up later, when
something breaks and the person on call reads the module for the first time.

Behind all three is the question an engineering lead eventually gets: *who is responsible for this
change?* If the answer is "the agent", nobody is.

## What Glide is

A **Work Item** is a ticket you've decided to do, in Vikunja or ClickUp. You assign it to an agent
**team**. Glide runs the team's roles, typically a writer, a reviewer and fix rounds, as
short-lived Kubernetes jobs. Each run gets its own budget and its own model key. The result is one
pull request on Forgejo or GitLab. You review it, and you merge it or you don't.

Glide has two parts, with Dutch names: **Ploeg** ("crew") is the Go controller that authorizes,
budgets and runs every agent run; **Vloer** ("floor") is the front end, in the browser or in VS
Code. The harness that edits the code is pluggable: OpenHands by default, Claude Code, any ACP
agent such as opencode, or a plain command.

Glide does not merge, does not deploy, and does not host models. It reaches models through a
LiteLLM gateway you run yourself.

## Tokenomics: reserve first, spend second, settle from the gateway

Glide handles model spend the way a card payment works: a hold for the estimated amount, replaced
later by the real one.

Before a run starts, Ploeg claims the work, locks the Work Item's budget pool (its **Shift**, in
Glide's terms) and reserves the run's share of the money, all in one database transaction. If less
than five cents is left, nothing happens: no pod starts work, no key is minted, no attempt is used
up. A test covers the race you'd worry about: five concurrent requests draw on a pool that can
fund two, and exactly two succeed.

The worst case is written down before anything runs. My cheapest team, bronze, caps the writer at
$2.00 and the reviewer at $0.40. A comment in its config does the sum for one writer, one reviewer
and two fix rounds: six runs, *"a hard worst case of $7.20 against the $8 pool"*, which leaves 80
cents of headroom.

When a run ends, Ploeg doesn't ask the agent what it spent. It reads the gateway's spend log for
that run's key. I found out why that matters when I checked on 8 August: the 45 run records from
late July held zero usage figures. The agents' own books were empty. The gateway had every token.

**What this adds to LiteLLM on its own.** LiteLLM already gives you capped, expiring keys, and
Glide uses exactly those. What Glide adds is the part around them: one budget pool per Work Item
shared by all its runs, the reservation taken before a key exists, and a settlement that returns
the unused hold to the pool. An org-wide monthly cap tells you afterwards that you spent too much.
It can't tell you, before a run starts, whether this ticket may still cost another $2.40.

<details>
<summary>For self-hosters: how the hold and settlement work</summary>

- Claim, row lock and reservation run in one transaction with `SELECT … FOR UPDATE SKIP LOCKED`;
  the minimum reservation is $0.05 (`apps/ploeg/pkg/store/shift.go`). With the pool exhausted, the
  claim API answers `204 No Content`.
- Tests: `TestAuthorizeIsAtomicUnderConcurrency` (the five-request race),
  `TestSettlementReleasesTheHoldAndRecordsSpend`, `TestSweptRunCannotReport`.
- Settlement calls `GET /spend/logs` per run key (`apps/ploeg/pkg/litellm`, called from
  `pkg/httpapi/llm_control.go`). A sweeper settles runs whose worker died.
- Two budget levels: a pool per Work Item and a cap per role.
- Limit: the gateway budget and key lifetime bound spend from requests already in flight when a
  key is blocked; they can't make it exactly zero.

</details>

## Every run gets its own key, and it expires

Each run gets a LiteLLM virtual key named after the run, capped at the run's budget and valid for
four hours by default. Ploeg refuses to mint a key without a cap. The worker refuses to start if
it can see the gateway's master key, the database URL or the forge admin token; those stay in the
controller.

The harness does see the per-run model key, and on my cluster it pushes with a shared forge token
for the agent account. A prompt-injected agent could therefore spend up to its run's cap within
four hours, and push to whatever that account can reach. Glide has a proposed design (ADR-0034, with tests)
that gives the harness only placeholders behind a local proxy, and one that mints a forge token per
run on Forgejo. Both are opt-in, and I haven't switched them on yet. Today the protection is the cap, the
expiry, and whatever repository access I give that one agent account.

## Review debt: many runs, one pull request

More agents can't fix a review bottleneck. A tool can avoid making it worse.

On bronze, a Work Item can take up to six model-spending runs: the writer, the reviewer and two
fix rounds. It still ends in **one** pull request. The reviewer is a separate agent with a
read-only forge token; the Helm chart refuses to render a team that has a reviewer role but no
read-only token, and a reviewer never falls back to the write token. Failing CI checks on Forgejo
or GitLab go back to the writer as a fix round. By the time the pull request reaches you, a second
agent that couldn't push has already argued with the first.

Agents can also propose follow-up work, which is where review debt usually explodes. By default a
Work Item created by an agent lands as **proposed**, and no agent can claim it until a person
approves it. One run may create at most 5 and one team may have at most 20 open. Anything over a
limit is rejected and logged. A team can switch the approval off (`autoDispatch`), and the design
record behind this is itself still marked proposed.

What Glide doesn't do yet: hold back new work while your review queue is full. That admission rule
is written down as a proposal.

## Comprehension debt: no tool solves this for you

Glide doesn't make anyone understand the code. It keeps the reasons next to the change: the Work
Item says why and what, and the reviewer's verdict says what a second reader found. Vloer's stated
goal is to put the ticket, the diff, the checks that ran and the open questions together, and to
make weak evidence easy to spot. That lowers the cost of understanding. It doesn't create it.

Glide defines how I'll know whether this works: a clean-merge rate (pull requests merged without a
change request) and the minutes I actively spend per pull request. Its KPI page says *nothing on
this page is measured yet*, so this post quotes no success rate.

## Responsibility stays with whoever presses merge

Glide never merges. Whoever presses merge owns the change, the same as with a colleague's pull
request they approved.

What Glide can do is make that responsibility bearable: a written worst case per Work Item, a spend
record per run from the gateway, keys that expire, and one reviewed pull request instead of a pile.
This week I decided the ledger should also show *who* started a run, not only which run spent what.

## Questions to ask any coding-agent tool

Whether you use Glide, a hosted coding agent or a CI job that runs one, these are the questions I'd
put to it:

1. Is a budget reserved **before** a run starts, per ticket, or is spend only capped per month?
2. Where does the cost figure come from: the provider or gateway, or the agent's own report?
3. Does each run get its own credential, and when does it expire?
4. What can a prompt-injected agent push to, and with which token?
5. Does one ticket end in one pull request, however many attempts it took?
6. Is there a second reviewer that cannot push?
7. Can agents create new work, and who approves it before it runs?
8. Who merges?

Glide's answers today: yes; the gateway; yes, four hours; a shared account (per-run tokens
designed but off); yes; yes; yes, with limits and a switch; you.

## Where Glide sits

I compared Glide with kagent this month, because the obvious question is whether Glide should run
on top of it. kagent is a CNCF sandbox project for AI agents on Kubernetes, and its 1.0 (still
alpha) runs agents on a new layer, Agent Substrate. Substrate injects one credential per hostname,
so it can't carry a separate model key per run, which is the core of how Glide bounds spend. On my
cluster it would also need a privileged daemon on every node, Kubernetes 1.37 and a beta API.

So the layers split three ways. Glide is the engine: admission, budget, keys, reviewer, one pull
request, a human merge. The sandbox under each run is a separate layer: Kata Containers or gVisor
through the Kubernetes SIG project agent-sandbox. Tools come in over MCP; that could include
kagent's own tool server. Neither the sandbox nor MCP is wired into Glide today; the section below
says what is.

<details>
<summary>For self-hosters: sandboxes, Talos and what's live</summary>

- A normal container shares the node's kernel. **gVisor** puts a user-space kernel (`runsc`)
  between the container and the node; light, but some workloads run slower or not at all. **Kata**
  gives each pod a small virtual machine with its own kernel, at roughly 160 MiB and 0.25 CPU
  extra per pod on my workers.
- Talos is immutable, so runtimes arrive as system extensions in the node image. My three workers
  run the `kata-containers` 3.32.0 extension, a `kata` RuntimeClass is live, and a standing smoke
  job boots a real guest kernel.
- agent-sandbox (v1.0 since August) lets a template choose the RuntimeClass. Glide has had an
  experimental executor for it since 26 September; its production workers still use the node's
  default runtime.
- Glide's harnesses pass no MCP servers today. The plan is a read-only role that reaches Grafana,
  logs and a read-only Kubernetes view through my existing MCP gateway, with its per-run key.
- kagent's Substrate runs a privileged node agent, runs agent pods as root with 13 added Linux
  capabilities, and downloads its own `runsc` instead of using a pre-installed one.

</details>

## Why a team would want this

- A worst case per Work Item, written down before an agent starts.
- Spend attributed per run and settled from your own gateway.
- Credentials that expire, with the dangerous ones never leaving the controller.
- Review that scales with people: one pull request per Work Item, reviewed by a read-only agent
  first, created work held for approval.
- A human merge, so every change has an owner.
- Your own cluster, gateway, tracker and forge.

In Glide's survey of the larger open-source agent orchestration projects (26 September), per-run
keys at a proxy with a budget reserved before the run and settled afterwards turned up in none of
them. The same survey made me drop two claims I used to make: leases that survive a dead pod, and
event-driven dispatch, are no longer unusual.

## What isn't true yet

| You might expect | Today |
| --- | --- |
| GitHub, Jira or Linear | No. Vikunja and ClickUp; Forgejo and GitLab. |
| Agents run in a Kata or gVisor sandbox | No. Default runtime; the agent-sandbox executor is experimental. |
| The harness never sees a credential | No. Proxy isolation is designed and tested, opt-in, off here. |
| Per-run forge tokens | Forgejo only, off here; a shared agent account pushes. |
| Measured merge rate, time to PR, cost per PR | Not measured. |
| New work waits while review is full | Proposed, not built. |
| More than one maintainer | No. One owner, pre-1.0. |

## Agents already work on Glide

Glide's history holds commits authored under the worker's own git identity, `agent-builder`. One
change, from July, is titled *"ploeg-worker owns the per-run LiteLLM key lifecycle (mint +
always-revoke)"*: a change to how Glide hands out the keys that pay for its agents, made under the
agents' identity.

To look at it without spending anything, the repository has a deterministic demo that runs Ploeg,
Vloer and PostgreSQL without model calls: `mise run demo-unified`. The code is at
forgejo.webgrip.dev/webgrip/glide and the documentation at docs.webgrip.dev/glide.

The model spend was never the hard part of letting agents write code. Glide is my attempt at the
rest of it.
