# Dark DevSecFinOps: the loop, and how far round it I actually got

*Draft v1 — 2026-07-31. Not published. Needs Ryan's ownership pass.*

Last night at 20:46 UTC I assigned a ticket on my Kanban board to a user called `bronze`.

At 20:47 a pod started on a repurposed desktop in my apartment, claimed the ticket, and read it.
At 20:53 it pushed a branch and opened a pull request. At 20:54 a **second** pod started, one
that holds no push credential, cloned the branch under review, read the diff, and at 21:00 wrote
this:

> **Minor observation (not a change request):** Neither "Erfbeeld board" nor "Ploeg factory" is
> linked. The board's MCP server is LAN-only per the repo conventions, so a URL would not be
> useful to external readers. This is the right call. Linking to something unreachable would be
> worse than not linking at all.
>
> **Verdict: Approve.**

Fourteen minutes, two pods, one pull request, one independent review of it. Total inference cost,
from the ledger, not an estimate: **$0.019872**.

Then the next line in the log:

```
21:00:09 WARN findings not published: no provider for forge  forge="" shift=4
```

The review is real. It is sitting in a Postgres row with `verdict=approve`. The pull request has
never heard of it, and never will, because the publisher looks its forge up by an id that the
routing rule leaves empty. The factory did the work and told nobody. Again.

That gap, between what ran and what landed, is the entire subject of this post.

---

## What this is

I have been building what I call a **dark factory**: the term comes from lights-out
manufacturing, a plant that runs with the lights off because there is nobody inside to see. Mine
runs on five Talos Kubernetes nodes at home, on hardware I already owned, and every piece of it
except the model API is open source and self-hosted.

The ambition is a loop, and the loop is why I keep saying **DevSecFinOps** instead of something
snappier. Each of those syllables is a separate thing the machine has to do without me:

| Arc | State today |
|---|---|
| Ticket refined to a Definition of Ready → assigned | **Human.** I write the tickets. |
| Assignment → agent picks it up, in the right repo | **Runs.** |
| Agent → branch, commit, pull request | **Runs.** |
| PR → independent agent review | **Runs.** The verdict does not reach the PR yet. |
| Review → merge | **Human, deliberately.** No agent merges anything. |
| Merge → production | **Runs**, for the cluster repo. Flux does it. |
| Production → telemetry | **Runs.** Dashboards, ledger, traces. |
| Telemetry → new tickets, refined to DoR | **Not built.** Designed only. |

Five of eight arcs move on their own. Two are human on purpose. One does not exist. This post
walks the two that changed last night and is honest about the rest, because a post about an
autonomous system that reports only its successes is an advertisement.

The register throughout is: **truth, then good, then beautiful.** Every capability claim below
carries a run id, a log line, or a ledger row. Anything unbuilt is labelled unbuilt.

---

## What existed before

Twelve days ago I wrote a long draft about this project and never published it. It was accurate
then and it is wrong now, which is the correct fate for writing about a system you are still
building. The useful parts, compressed:

**Agents are ordinary workloads.** The single most load-bearing realisation of the whole build is
that "schedule an AI agent" means "add one more KEDA `ScaledJob`". KEDA sees a queue, scales a pod
from zero, the pod runs one job and exits. That is what it does for my CI. An agent run is a CI
job that happens to think. There is no agent platform, no orchestration SaaS, no bespoke operator
on the critical path, and scale-from-zero means an idle factory costs exactly nothing.

**Every run mints and destroys its own money.** Inference goes through a self-hosted LiteLLM
proxy. Each run mints a virtual key scoped to its tier's models, capped with a hard budget, and
revokes it on exit, success or failure. A run that dies before minting has spent $0.00 by
construction. On top sit per-provider daily ceilings, so even a pathological day has a known worst
case.

**`builder ≠ judge`.** This came from a failure I still wince at. An early agent team built a D3
chart, ran its own checks, declared all gates green, and shipped a chart whose axis was in
entirely the wrong place. It had verified itself and was satisfied. The rule that came out of it
is that the actor which writes must never be the actor which approves, and the separation must be
structural rather than a promise, because a promise is exactly the thing a confident model
overrides.

**It runs on my hardware for cents.** Five nodes, 24 vCPU and 72 GiB total, three of which are
tiny control planes that exist mostly to keep etcd company.

And the sentence I want to quote from that draft, because it is the thing that got falsified:

> Today the dispatch is a curl.

It was. Assignment was me, running a command. Everything downstream of it was real, and the very
first thing in the queue was to make the dispatch real too. That is what this post is about.

---

## Ploeg, and three words you need

The dispatcher is now a service called **Ploeg** — Dutch for a crew, or a team, or (this is the
sense I like) the gang of people who work a field together. It is a small Go program, it is open
source, and it introduces three nouns that do not appear in anything I have published before.

- A **Shift** is one ticket's worth of work, opened when a ticket is assigned and closed when its
  plan is exhausted. It has a budget and a branch.
- A **Round** is one sequential step inside a Shift. Round 1 finishes before Round 2 begins.
- A **Role** is a job to be done inside a Round: `builder`, `reviewer`, `devops`. Crucially, a
  Role is **not** a persona inside a prompt. A Role is a **separate Kubernetes workload**, with
  its own pod, its own resource requests, its own budget cap, its own harness configuration, and
  its own credentials.

Last night's run was one Shift, two Rounds, one Role each:

```
20:46:13  shift opened  work_item=29 team=bronze rounds=2
20:46:13  round opened  shift=4 round=1 roles=1
20:47:05  run claimed   role=builder  round=1 writes=true  authorized=2
20:53:45  outcome reported  outcome=pr_opened
20:53:45  round opened  shift=4 round=2 roles=1
20:54:15  run claimed   role=reviewer round=2 writes=false authorized=0.4
21:00:09  outcome reported  outcome=no_change_needed
21:00:09  shift closed  reason=plan_exhausted item_state=needs_human
```

`writes=true` and `writes=false` are the interesting columns, and I will come back to how much
work it took to make the second one mean anything.

The reason a Role is a workload rather than a prompt persona is that all the controls I care
about are pod-shaped. A budget is a minted key. A privilege is a Kyverno decision at admission. A
credential is an environment variable that is either present or absent. None of those can be
expressed as a paragraph telling a model what it is. If the reviewer is a section of a prompt, its
"read-only" is a suggestion. If the reviewer is a pod, its read-only is the absence of a token.

---

## Boards decide the repository

Here is a failure I enjoy, because the machine did nothing wrong.

A ticket said "add a note to the erfbeeld README". I assigned it to a team whose routing rule
pointed at a different repository. The agent cloned that repository, found its README, added the
note exactly as instructed, committed with the right trailers, and opened a tidy pull request
against **the wrong project**. It was obedient, competent, and completely useless. (That PR is
`webgrip/ploeg#30`, closed.)

Nothing in the agent layer can fix this, because the agent layer was not the layer that lied. The
routing did. So routing moved: **the board decides the repository, the team decides the
capability.** Seven boards now map by name to a repo and a base branch, resolved against the
tracker's API at boot, and Ploeg refuses to start if a name matches nothing:

```
20:45:17  resolved tracker project name=Erfbeeld id=4 repo=webgrip/erfbeeld
20:45:17  target map loaded rules=7
20:46:13  target resolved external_id=628 scope=4 team=bronze repo=webgrip/erfbeeld rule=4
```

Three boards are deliberately **unrouted**: one covers a migration that touches every repository,
one is for a product whose repo does not exist yet, and one is an inbox for triage. An unrouted
board cannot dispatch. I would rather a ticket sit still than move confidently in the wrong
direction, which is the same lesson as the D3 axis wearing different clothes.

### Teams are capabilities

With routing out of the way, a team is now purely an answer to "how expensive and how careful
should this be?":

| Team | Model | Plan | Notes |
|---|---|---|---|
| `bronze` | deepseek-chat | builder (cap $2.00) → reviewer (cap $0.40) | The cheap tier. Two Rounds. |
| `silver` | claude-sonnet-5 | single writer | Works on Ploeg itself. Real Go surgery. |
| `copper` | none, ever | none | The seam test. |

`copper` is my favourite thing in the system. Its harness is not an agent at all: it runs
`/bin/cat` on the generated task specification inside the same runner image and exits zero. A
copper run proves per-team harness selection, task composition, key mint and revoke, and the
`no_change_needed` outcome path, **without spending a single token**. The cheapest possible
integration test for an expensive system is one that deliberately does not think.

### Two ways I broke it on the way

**Naming the default switched it off.** I set `serviceAccountName: ploeg-worker` in the chart
values, which is the chart's own default. Every worker Job then died with
`serviceaccount "ploeg-worker" not found`, because the template's guard reads *a name is present*
as *something external owns this, do not create it*. Naming the default and saying nothing were
opposites. I have written that guard pattern myself, in other charts, and I still walked into it.

**The same config routed differently run to run.** An assignee listed under two teams resolved by
Go map iteration order. Measured inside one process: 168 out of 200 one way, 32 the other. The
configuration was valid, every validator passed, and the behaviour was a coin flip. Ploeg now
refuses to start on that config, which is the only honest response to a nondeterministic route.

---

## Security is the interesting part

Now the one I actually want to talk about.

For a while, the reviewer was told this, in its prompt:

> You hold no write credential, so a push will be rejected by the forge.

Every clause of that sentence was false. The builder's token was mandatory on **every** worker
pod, it reached the agent process through `os.Environ()`, and it was baked into the clone's
`origin` remote. The only thing standing between a "read-only" reviewer and a force-push was a
model believing a sentence it could disprove in one command.

I want to be precise about why this is worse than merely ineffective. A false constraint is not a
weak control, it is a **negative** one. The moment a model tests that claim and finds it untrue,
every other line in the contract becomes a hypothesis. "Never merge your own work" is sitting in
the same prompt.

The fix was not better wording. It was to make the reviewer's pod not have the credential. Here is
how that looks in the logs, and it is an absence rather than a line:

```
builder:   20:47:05 using the shared forge credential supplied by ploegd
reviewer:  (no such line)
```

While I was in there, three more defects fell out, and they are all the same shape: **the reader
could not actually read**.

- The clone was `--depth 50 --branch <base>`, and `--depth` implies `--single-branch`. The branch
  under review was **not in the repository at all**, while the prompt cheerfully asserted the
  checkout was standing on it.
- The reviewer was never told the pull request existed.
- A clean reader that touched nothing was recorded as having pushed.

Fixed, it works. Note in the timeline above what the reviewer does before it starts thinking:

```
20:54:16  reading run prepared  on_review_branch=true branch=agent/vik-628 base=main
20:54:17  branch already has an open PR  pr=…/erfbeeld/pulls/9
```

### The diagnosis that was wrong in a useful direction

The night before, two reader Roles died 1.2 seconds after starting:

```
exec: "opencode": executable file not found in $PATH
```

Which reads as: ship the binary. That would have been a disaster, and quietly. The runner image's
opencode adapter sets no outcome file and populates no findings, so shipping it would have turned
*failed to start* into *started, reviewed, and threw the review away*. A visible failure would
have become an invisible one. The real blockers were four layers deeper, in the dispatcher, and
the reviewer now runs on the image that was already installed.

I have started treating "the error message names the fix" as a smell rather than a relief.

### Narrowing a waiver, and what it was hiding

The privileged Docker-in-Docker sidecar that lets a builder run gates in CI's own images does not
pass a Kubernetes baseline policy, and should not. It runs under a Kyverno exception. That
exception used to match by workload name, which is a blunt instrument: it waived *everything*
about those pods, including things they never needed.

So I narrowed it to match the hazard itself, a label saying "this pod takes privileged DinD". The
right instinct. It took the entire factory down: KEDA looped on `KEDAJobCreateFailed`, nothing
dispatched at all.

**A Job selector matches the Job's own labels.** The hazard label lives on the pod template, so
the Job never carries it, so the match can never admit the Job. The comment I had written above
that match confidently explained otherwise.

The second half is better. Before narrowing, I had checked the policy's `.spec.rules` for the
autogenerated Job-level sibling rule, found none, and concluded it did not exist. It does.
`.spec.rules` lists only the rules a human **authored**; Kyverno generates the autogen variants at
admission time. Reading the policy object cannot tell you what the policy enforces.

What made all this worth it: with the waiver keyed to the hazard rather than the workload, the
reviewer, which sets `dind: false` and takes no privilege, gets **no waiver at all** and is held
to the full baseline. The broad exception had been silently covering readers for a privilege they
never take, and every other team too.

### What the agent still cannot reach

The controls that do hold: workers run with `automountServiceAccountToken: false` and a
no-authority identity. The LLM-driven process gets a shell, a docker daemon, and a git remote. It
does not get a cluster.

And one that does not hold, which the boot log announces every single time:

```
per-run forge credentials disabled (PLOEG_FORGEJO_ADMIN_TOKEN unset); workers use the shared token
```

The design says each run should get its own short-lived forge credential. The broker calls
`/api/v1/admin/users/{bot}/tokens`, which returns 404 on the Forgejo version I run. It has never
worked here, not once, and every run to date has used the shared token. It said "disabled" in the
logs for weeks and nobody, including me, read it.

---

## The money

This is the part where a homelab post usually gets vague. I would rather give you the numbers and
the reasons they are less impressive than they look.

**One ticket, one pull request, one independent review: $0.019872.** Builder $0.013573 across 32
calls, reviewer $0.006299 across 16. Two cents, and the reviewer costs 46% of the builder on the
same model.

**Everything, ever: $1.40.** That is the ledger's lifetime total: every experiment, drill, failed
run and shipped pull request since it started recording on 15 July. 2,379 calls, and effectively
100% of it DeepSeek. Prompt caching is doing the heavy lifting: a representative request shows
33,128 prompt tokens of which 33,024 were cache hits, for an input cost of $0.000107.

Now the caveats, because the cheapness is real but it is not free lunch.

**Cheap because small.** Two cents buys a review of a two-sentence README edit. This is a
correctly-working system doing genuinely trivial work. I have no data on what a real feature
costs, because the factory has not done one.

**The euro figure is nearly circular.** OpenCost says €94.76/month. It says that because I hand
set the rates, and the comment next to them says they were calibrated to hit a ~€1,000/year
target. Cross-checking it two ways gives the same answer, which proves the arithmetic and nothing
else. There is no bill behind it.

**Power is not measured.** Kepler reports 72.84 W cluster-wide averaged over a week, of which
worker-1 is 36.2 W and each control-plane node is under 4 W. But Kepler reads Intel RAPL, so that
is CPU package plus DRAM: no power supply losses, no disks, no fans, no NICs. Nothing in this
cluster measures wall draw. At Dutch rates, where a continuous watt costs roughly €3/year, 73 W of
silicon is about €220/year, and that is a floor rather than a bill.

One more, for anyone who copies my query: `sum(kepler_node_cpu_watts)` gives 104.7 W and is
**wrong**. RAPL zones nest, and `package` already contains `core` and `uncore`. You have to filter
`zone=~"package|dram"`. A 44% overstatement, one obvious PromQL expression away, in a metric whose
entire job is to be quoted in posts like this one.

---

## What is not built

Plainly, so that nothing above can be read as more than it is.

**Nothing merges. Nothing deploys through this loop. No telemetry closes it.** All four tickets
the agents have touched this week are still open on the board. Ploeg has never closed a ticket in
its life, by design: its Definition of Done is "in production, first telemetry seen", and Ploeg
can observe neither. It says so on the ticket:

> This task stays open until it is in production and its first telemetry has been seen.

**The review does not reach the pull request.** The failure at the top of this post. It is the
second instance in two days of the factory doing the work and telling nobody. The first was a
notification gated on the failure path, so the *success* path was the silent one, and no error
appeared anywhere because no call was made. The last hop is the one nobody tests.

**The reviewer is not independent enough.** My own RFC names this hazard and cites the research
behind it: same-family review inflates pass rates by 9 to 17 percentage points, and models fail to
fix their own errors around 64.5% of the time. Last night's builder and reviewer ran different
pods, different credentials, different budgets, and **the same model family**. By my own written
standard, that review is worth less than it looks. It is the most important caveat on the whole
milestone and I would rather write it here than have it found.

**The dispatcher does not track its own spending.** The caps are real and enforced at the proxy.
The dispatch database's `spent` column is `0.0000` on every Shift, and the per-run usage field is
null on every run. Nothing writes them.

**The ledger forgets whose key it was.** Per-run keys are revoked at the end of a run, revocation
deletes the token record, and the alias that mapped a key back to its run trace dies with it. The
money survives; the attribution does not. I only found this while gathering numbers for this post,
which is a decent argument for writing things down.

**Agents not merging is a convention.** Branch protection that would make it a rule is written up
and not rolled out. Today it holds because the bot has no merge scope and because the prompt says
so, and I have already told you what I think of prompts as controls.

**Two runtime decisions were superseded before they were ratified.** The agent runtime ADR chain
went opencode → OpenHands → harnesses-are-plural in twelve days, and two of the three never
reached "accepted". The execution-layer ADR describes a second CI runner pool; what actually ships
is a dispatch plane with a scaled job per team. The decision record is behind the code, and saying
so is cheaper than pretending it isn't.

---

## The number that should keep me honest

Commits to this repository over the last 30 days, by author:

| Author | Commits |
|---|---|
| Me | 493 |
| Renovate (dependency bot) | 99 |
| **`agent-builder`** | **2** |

Two. Out of 594. Both of them README edits, in another repository, in pull requests nobody has
merged.

Meanwhile Renovate, a boring dependency bot that nobody would call an agent, accounted for 82 of
the 102 merges in that window. The unglamorous automation is still, by an enormous margin, the
automation that does the work.

I could have opened this post with the two cents and closed it with the loop diagram, and it would
have read as a triumph. The table above is the more useful artifact. What I have built is a
correct, observable, well-metered path from a Kanban card to a reviewed pull request, and I have
driven approximately no work through it.

---

## What is next

One arc, then the next one.

**Make the review land on the pull request.** It is a one-field bug and it is the difference
between a system that reviews and a system that reviews into a void.

**Give the reviewer a different model family.** My own hazard analysis demands it, the budget for
it is $0.006 a run, and the only reason it has not happened is that I was busy making the reviewer
run at all.

**Then merge.** Not automatically. The human merge stays. But the arc from a merged pull request
to a deployment to a metric to a new ticket is the half of DevSecFinOps I have only drawn.

The lights are not off. They are on a dimmer, and last night it moved one notch. A ticket became a
pull request, a different process read it and approved it, and it cost two cents. The review is in
a database, waiting for the one line of code that would let anyone see it.

---

*Stack, all self-hosted: Talos Kubernetes · Flux · Forgejo · KEDA · Harbor · Vikunja · LiteLLM ·
OpenHands · External Secrets + OpenBao · Kyverno · Cilium · VictoriaMetrics, Logs and Traces. The
dispatch plane is `webgrip/ploeg`. The only rented thing is the model API, and it costs about a
euro a fortnight.*
