# Tokens are cheap. Review isn't.

*Agent tokenomics, review debt and comprehension debt, and where Glide draws the line on
responsibility.*

*Draft v1, 2026-09-27. Not published. Needs Ryan's ownership pass. Every claim traces to
BLOGPOST-glide.research.md or to the Glide and homelab repositories.*

> **TL;DR.** Glide turns a ticket into a pull request that AI agents write and a person reviews.
> It authorizes the money before an agent gets a key, settles the bill from the model gateway
> rather than from the agent's own report, gives every run a key that expires, and never merges
> anything. It is open source (Apache-2.0), self-hosted on Kubernetes, and pre-1.0 with one
> owner: me. The interesting part is not the token bill. It is everything the token bill hides.

---

In September I sat down to plan how many agents my homelab could run at once. I expected the
answer to be a hardware number. It wasn't.

The capacity plan came back with the limits in this order: **my own review capacity**, then the
model providers' daily caps, then a Kubernetes setting. CPU and memory came last. After
everything else on the cluster, the three worker machines had room for seven agents writing code
in parallel. The electricity for one agent run costs somewhere between a tenth of a cent and a
cent. The model spend for a run on a cheap model is one to five cents. A pull request plus an
independent agent review of it once cost me **$0.019872** in total, from the gateway's ledger.

Tokens are cheap. The expensive resource in an agent pipeline is the person at the end of it.

That changes what a tool for coding agents should be good at. This post introduces Glide, the
tool I have been building for exactly that, and it is specific about what Glide does today and
what it doesn't do yet.

## A coding agent spends three kinds of money

The first kind is the token bill. It is visible, it is small per run, and it can still surprise
you, because an agent in a loop does not get tired.

The second is **review debt**. Glide's own planning docs put it as a formula:

```text
accepted results per week <= min(ready tickets, candidate changes produced, review capacity)
```

If you can write 20 good tickets a week, your agents produce 50 candidate changes, and you can
properly review 8, you ship at most 8. Doubling the agents to 100 candidate changes ships the same
8, plus 92 pull requests that sit there. Better tests and better evidence might get you to 16
reviews a week. More agents won't.

The third is **comprehension debt**: code that was merged, works, and that nobody on the team
understands. Review debt is at least visible, as a queue. Comprehension debt shows up later, the
first time something breaks and the person on call reads a module for the first time.

Behind all three sits one question an engineering lead eventually gets asked: *who is
responsible for this change?* If the answer is "the agent", nobody is.

## What Glide is

Glide turns a unit of work into a pull request that AI agents write and you review.

A **Work Item** is a ticket you have decided to do, from Vikunja or ClickUp. You assign it to an
agent **team**. Glide runs the team's roles (a writer, a reviewer, fix rounds) as short-lived
Kubernetes jobs, each with its own budget and its own model key, until there is one pull request
for you on Forgejo or GitLab. You review it. You merge it, or you don't.

Glide has two parts. **Ploeg** is the Go controller that authorizes, budgets and runs every agent
run. **Vloer** is the front end, in the browser or in VS Code, where you follow and steer the
work. The harness that actually edits code is pluggable: OpenHands by default, Claude Code, any
ACP agent such as opencode, or a plain command.

Just as important is what Glide refuses to do. It does not merge. It does not deploy. It does not
host models; it reaches them through a LiteLLM gateway you run yourself.

It is also honest about its size. The docs say it plainly: *internal tool, pre-1.0, one owner,
self-hosted on Kubernetes. Not a hosted service.*

## Tokenomics: the money is authorized before the agent gets a key

Glide treats model spend the way a card payment works, and the design record uses that analogy
itself: a hold for the estimated amount, replaced later by the real one.

When a run is about to start, Ploeg claims the work, locks the budget row and authorizes the
run's share of the money in **one database transaction**. If less than five cents is left, the
claim returns nothing: no pod does any work, no key is minted, no attempt is used up. There is a
test for the race you'd worry about: five goroutines ask for money from a pool that can fund two,
and exactly two get it.

The worst case is written down before anything runs. My main team's config caps the writer at
$2.00 and the reviewer at $0.40. One writer, one reviewer and two fix rounds is six runs, which
the config itself adds up to *"a hard worst case of $7.20 against the $8 pool. 80 cents"* of
headroom.

Then the settlement. When the run ends, Ploeg does **not** ask the agent what it spent. It asks
the gateway. The cost comes from LiteLLM's spend log for that run's key. I learned why that
matters the hard way: in early August my own database had 45 run records and zero usage figures
in them, while the gateway had every token. The agent's own books were empty. The proxy's books
were complete.

<details>
<summary>For self-hosters: how the hold and settlement work</summary>

- Claim, row lock and authorization run in one transaction using `SELECT … FOR UPDATE SKIP
  LOCKED`; the minimum viable authorization is $0.05 (`apps/ploeg/pkg/store/shift.go`). On
  exhaustion the claim API answers `204 No Content`.
- `TestAuthorizeIsAtomicUnderConcurrency` is the five-goroutine test; settlement is covered by
  `TestSettlementReleasesTheHoldAndRecordsSpend` and `TestSweptRunCannotReport`.
- Settlement reads `GET /spend/logs` on the gateway per run key (`apps/ploeg/pkg/llmbroker`). A
  sweeper settles runs whose worker died.
- Budgets are two-level: a Shift pool per Work Item and a cap per role (ADR-0012).
- What it can't promise: an exact ceiling for requests already in flight when a key is blocked.
  The gateway budget and the key's lifetime bound that exposure; they don't make it zero.

</details>

## Every run gets its own key, and it expires

Each run gets a LiteLLM virtual key of its own: named after the run, capped at the run's budget,
and valid for four hours by default. Ploeg refuses to mint a key without a cap. The worker
refuses to start at all if it can see the gateway's master key, the database URL or the forge
admin token. Those stay in the controller.

This part needs a caveat, so here it is in full. The per-run key and the forge token *are* handed
to the harness today. The agent can read the key it was given. Glide has a design (ADR-0034) that
keeps both behind a local proxy, so the harness only ever sees a placeholder, with tests for it,
but it is opt-in and I don't have it switched on. What a leaked key can do is bounded by its cap
and its expiry, not prevented.

## Review debt: many runs, one pull request

The review side is where Glide earns its place, because more agents can't fix a review
bottleneck, but a tool can stop making it worse.

A Work Item can take up to six runs: a writer, a reviewer and fix rounds between them. It still
ends in **one** pull request for you. The reviewer is a separate agent with a read-only forge
token; the chart refuses to render a team with a reviewer role and no read-only token, and a
reviewer never falls back to the write token. By the time the pull request reaches you, a second
agent that couldn't push has already argued with the first one.

Agents can also propose new work, and that is where review debt usually explodes. In Glide a
Work Item created by an agent lands as **proposed**, which no agent can claim until you approve
it. One run may create at most 5, and one team may have at most 20 open at a time. Anything over a
limit is rejected and logged, not silently dropped.

What Glide doesn't do yet: hold back new work when your review queue is full. The docs call that
admission rule a proposal, and it is the next thing a tool like this should grow.

## Comprehension debt: the part no tool solves for you

I'll be careful here, because this is where products overclaim.

Glide doesn't make you understand code. What it does is keep the reasons next to the change: the
Work Item says why and what, and the reviewer's verdict says what a second reader found. Vloer's
stated goal is to put the ticket, the diff, the checks that ran and the open questions together,
and to make weak evidence easy to spot. That makes understanding cheaper. It doesn't make it
happen.

Glide defines how I'll know whether it works: a clean-merge rate (pull requests I merged without
asking for changes) and the minutes I actively spend reviewing each pull request. The KPI page
itself says *nothing on this page is measured yet*. I don't have those numbers, so this post
doesn't quote any.

## Responsibility stays with whoever presses merge

This is the design decision everything else rests on. Glide never merges. The person who presses
merge owns the change, the same way they would own a colleague's pull request they approved.

Glide's job is to make that responsibility bearable: a bounded bill per Work Item, a spend record
per run that comes from the gateway rather than from the agent, credentials that expire, and one
reviewed pull request instead of a pile. Next on that list is attribution per person, so the
ledger shows who started a run, not only which run spent what.

## Where Glide sits: the engine, not the wall and not the toolbox

This month I compared Glide with kagent, the CNCF sandbox project for AI agents on Kubernetes,
because the obvious question is whether Glide should simply run inside it. My answer is no, and
the reason is specific.

kagent 1.0 (still an alpha) runs its agents on a new layer called Agent Substrate. On my cluster
that would mean a privileged agent on every node with 13 extra Linux capabilities, a sandbox
runtime it downloads by itself, Kubernetes 1.37, and a beta API switched on. More to the point
for Glide: Substrate injects one credential per hostname, so it can't carry a separate model key
per run, which is the core of how Glide bounds spend. Embedding kagent's agents would also give me
two systems that each think they own the run.

So the layers split like this:

- **The toolbox** is MCP. Glide's harness adapters can hand an agent MCP servers; on my cluster
  the plan is Grafana, logs and a read-only Kubernetes view through the MCP gateway I already run,
  and kagent's own tool server can sit there too.
- **The engine** is Glide: admission, budget, keys, reviewer, one pull request, a human merge.
- **The wall** is a sandbox runtime under the pod: Kata Containers or gVisor, through the
  Kubernetes SIG project agent-sandbox. Glide's own landscape research calls it the best runtime
  to put under Ploeg.

The wall part is not done. Glide's workers run on the node's default container runtime today.
An agent-sandbox executor exists since 26 September and is marked experimental.

<details>
<summary>For self-hosters: gVisor, Kata and Talos</summary>

- A normal container shares the node's kernel. **gVisor** puts a user-space kernel (`runsc`) in
  between; it is light, and some workloads run slower or not at all. **Kata** gives every pod a
  small virtual machine with its own kernel; stronger, at roughly 160 MiB of memory and 0.25 CPU
  per pod on my workers.
- Talos is immutable, so runtimes arrive as system extensions baked into the node image. My three
  workers already run the `kata-containers` 3.32.0 extension, a `kata` RuntimeClass is live, and a
  smoke job boots a real guest kernel in about two seconds.
- agent-sandbox (v1.0 since August) lets a template pick the RuntimeClass, so the same Glide run
  can land on Kata or gVisor without Glide knowing the difference.
- kagent's Substrate does not use a pre-installed `runsc`; it fetches its own and needs a
  privileged installer. That, not taste, is why it doesn't fit under Glide.

</details>

## Why a team would want this

Strip out my homelab and the case is the same for any team letting agents write code:

- **A worst case per Work Item that is written down before an agent starts**, not discovered on
  the invoice.
- **Spend you can attribute** per run, settled from your own gateway.
- **Credentials that expire**, with the dangerous ones never leaving the controller.
- **Review that scales with people, not with agents**: one pull request per Work Item, reviewed
  by a second agent first, created work held until someone approves it.
- **A human merge**, so responsibility has an owner.
- **Your infrastructure**: your cluster, your gateway, your tracker (Vikunja or ClickUp today) and
  your forge (Forgejo or GitLab today).

In Glide's landscape survey from 26 September, the combination of a budget authorized before the
run, settled afterwards, with a key per run at a proxy, showed up nowhere else. The same survey
also made me drop two claims: leases that survive a dead pod, and event-driven dispatch, are no
longer unique. Other projects have them now.

## What isn't true yet

| Claim you might expect | Status today |
| --- | --- |
| Agents run in a Kata or gVisor sandbox | No. Default runtime; the agent-sandbox executor is experimental. |
| The harness never sees a credential | No. Proxy isolation is designed and tested, opt-in, off here. |
| Measured success rate, time to PR, cost per PR | Not measured. Single data points only. |
| GitHub, Linear or Jira support | No. Vikunja and ClickUp; Forgejo and GitLab. |
| New work waits when review is full | Proposed, not built. |
| Maturity | Pre-1.0, one owner. |

## Agents already work on Glide

Seven commits in Glide's history are signed by `agent-builder`, the worker's git identity. One of
them, from July, is titled *"ploeg-worker owns the per-run LiteLLM key lifecycle (mint +
always-revoke)"*: the agents fixing how Glide hands out the keys that pay for the agents.

If you want to see how it works without spending anything, the repository has a deterministic
demo that runs Ploeg, Vloer and PostgreSQL with no model calls: `mise run demo-unified`. The code
is at forgejo.webgrip.dev/webgrip/glide and the documentation at docs.webgrip.dev/glide.

The tokens were never the hard part. Glide is my attempt at the rest.
