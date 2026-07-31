# I told my AI code reviewer it couldn't push. It could.

*Building a lights-out software factory on a homelab, and counting how far round the loop it
actually got.*

Last night at 20:46 UTC I assigned a ticket on my Kanban board to a user called `bronze`.

A minute later a pod started on a repurposed desktop in my apartment, claimed the ticket, and read
it. Six minutes after that it pushed a branch and opened a pull request. Then a second pod
started, cloned the branch under review, read the diff, and wrote a review of it. Fourteen minutes
end to end, two pods, one pull request, one review. Cost, from my inference proxy's spend table:
about two cents.

Then the next line in the log:

```
21:00:09 WARN findings not published: no provider for forge  forge="" shift=4
```

The review is real. It is sitting in a Postgres row with `verdict=approve`. The pull request has
never heard of it and never will, because the code that posts a review looks up which git host to
post it to by an id that the routing rule leaves empty.

That is the good version of the failure. Here is the one in the title.

For most of this project, the reviewing agent was told, in its prompt:

> Do NOT modify, commit or push anything: you hold no lease on this branch and no write
> credential, so a push will be rejected by the forge.

The second half was false. The builder's push token was required on every worker pod, it reached
the agent process through `os.Environ()`, and it was baked into the git remote of the clone the
reviewer was working in. The only thing standing between a "read-only" reviewer and a force-push
was a language model believing a sentence it could have disproved with one command.

---

## Before I tell you it works, here is what it has done

Commits to this repository in the last 30 days, by author:

| Author | Commits |
|---|---|
| Me | 493 |
| Renovate (a dependency bot) | 99 |
| `agent-builder` | **2** |

Two, out of 594. To be fair to them, they are real: both are Flux manifest changes under
`kubernetes/apps/erfbeeld/`, promoting a CI-published image across dev, staging and production,
and both are merged. They are also from 22 and 23 July, a week before the dispatch plane this post
is about existed. Its own two pull requests are still open.

Meanwhile Renovate, a dependency bot that nobody would dignify with the word agent, accounted for
82 of the 102 merges in that window.

I want that table near the top rather than buried at the end, because everything below is
infrastructure I am pleased with attached to an output I am not.

---

## What the thing is

I have been building what lights-out manufacturing calls a **dark factory**: a plant that runs
with the lights off because there is nobody inside to see. Mine is five Talos Kubernetes nodes at
home, 24 cores and 72 GiB between them, running a self-hosted git host (Forgejo, which I will call
the forge), a self-hosted Kanban board, and a self-hosted LLM proxy that keeps a spend table I
will call the ledger. The only rented thing in the loop is the model API.

The ambition is a loop, and every arc of it is a separate thing the machine has to do without me:

| Arc | State today |
|---|---|
| Ticket refined to a Definition of Ready, then assigned | Human. I write every ticket. |
| Assignment → an agent picks it up, in the right repo | **Runs.** |
| Agent → branch, commit, pull request | **Runs.** |
| Pull request → a second agent reviews it | **Runs.** The verdict does not reach the PR. |
| Review → merge | Human, deliberately. |
| Merge → production | Runs for my commits. Flux does it. No agent change has been through it. |
| Production → telemetry | Runs for the cluster. Nothing feeds it back to a run. |
| Telemetry → new tickets, refined and assigned | Not built. |

Five of eight arcs move on their own. Two are human, one of those on purpose. One does not exist.

---

## What was already there

Three things carried over from the version of this that existed a fortnight ago, and they are the
only backstory that matters.

**An agent run is an ordinary Kubernetes workload.** KEDA watches a queue, scales a pod from zero,
the pod runs one job and exits. That is exactly what it does for my CI. Scheduling agents turned
out to be a solved problem that boring software solved years ago for other reasons, and I got it
for free.

**Every run mints and revokes its own budget.** Inference goes through a LiteLLM proxy. Each run
mints a virtual key scoped to its tier's models, capped in dollars, and revokes it when the run
ends. A run that dies before minting has spent nothing.

**The thing that writes must not be the thing that approves.** This came out of an early agent
team that built a chart, ran its own checks, declared every gate green, and shipped a chart whose
axis was in the wrong place. It had verified itself and was satisfied. What I took from it is that
the separation has to be structural, because a promise is exactly what a confident model
overrides.

The old version's honest admission was that assignment itself was still me running a command:
*today the dispatch is a curl*. That is what changed.

---

## Ploeg, and three words

The dispatcher is a small Go service called **Ploeg**, Dutch for the crew who work a field
together. Its daemon is `ploegd` and it is open source. It brings three nouns.

A **Shift** is one ticket's worth of work: a budget, a branch, opened on assignment and closed
when its plan runs out. A **Round** is one sequential step inside a Shift; Round 2 does not start
until Round 1 finishes. A **Role** is a job inside a Round, such as `builder` or `reviewer`.

The part I would defend at length: a Role is not a persona in a prompt. It is a separate
Kubernetes workload with its own pod, resource requests, budget cap, harness (the CLI that
actually drives the model, OpenHands in my case) and credentials. Last night's run was one Shift,
two Rounds, one Role each:

```
20:46:13  shift opened   work_item=29 team=bronze rounds=2
20:47:05  run claimed    role=builder  round=1 writes=true  authorized=2      # dollars
20:53:45  outcome reported  outcome=pr_opened
20:54:15  run claimed    role=reviewer round=2 writes=false authorized=0.4
21:00:09  outcome reported  outcome=no_change_needed
21:00:09  shift closed   reason=plan_exhausted item_state=needs_human
```

I went to workloads rather than personas because every control I care about is pod-shaped. A
budget is a minted key. A privilege is an admission-control decision. A credential is an
environment variable that is either present or absent. None of those can be expressed by telling a
model what it is. If the reviewer is a paragraph in a prompt, its read-only status is a
suggestion, which is how I ended up with the sentence in the title.

---

## The board decides the repository

A failure I enjoy, because the machine did nothing wrong.

A ticket said "add a note to the erfbeeld README". I had assigned it to a team whose routing rule
pointed at a different repository. The agent cloned that repository, found its README, added the
note exactly as instructed, wrote correct commit trailers, and opened a tidy pull request against
the wrong project. It was obedient, competent, and useless.

Nothing in the agent layer could have caught that, because the agent layer was not the layer that
lied. So routing moved: the board decides the repository, the team decides the capability. Seven
boards map by name to a repo and a base branch, resolved against the board's API at startup, and
`ploegd` refuses to boot if a name matches nothing:

```
20:45:17  resolved tracker project name=Erfbeeld id=4 repo=webgrip/erfbeeld
20:45:17  target map loaded rules=7
20:46:13  target resolved external_id=628 team=bronze repo=webgrip/erfbeeld rule=4
```

Three boards are deliberately unrouted: a migration that touches every repository, a product whose
repo does not exist yet, and an inbox for triage. An unrouted board cannot dispatch at all. I
would rather a ticket sit still than move confidently in the wrong direction.

With routing settled, a team is now only an answer to "how expensive and how careful":

| Team | Model | Plan |
|---|---|---|
| `bronze` | deepseek-chat | builder (cap $2.00) → reviewer (cap $0.40) |
| `silver` | claude-sonnet-5 | single writer, aimed at Ploeg's own repo. One run on record. |
| `copper` | deepseek-chat, never called | none |

`copper` is my favourite thing here. Its harness runs `/bin/cat` on the generated task
specification inside the same runner image and exits zero. A copper run proves per-team harness
selection, task composition, key minting and revocation, and the "nothing to do" outcome path,
without spending a token. It is an integration test that deliberately does not think.

Two ways I broke this on the way. I set `serviceAccountName: ploeg-worker` in the chart values,
which is the chart's own default, and every worker Job then died with `serviceaccount
"ploeg-worker" not found`, because the template's guard reads the presence of a name as "something
external owns this, do not create it". Naming the default and saying nothing were opposites. And
an assignee listed under two teams resolved by Go map iteration order: valid config, every
validator green, and a route that was genuinely a coin flip between runs. That is a startup error
now.

---

## The security part, which is the interesting part

Back to the sentence in the title. I want to be precise about why a false constraint is worse than
no constraint. The moment a model tests that claim and finds it untrue, every other line in its
instructions becomes a hypothesis, and "never merge your own work" is sitting in the same prompt.

The fix was not to write it more firmly. It was to scrub the credential out of a reading run's
environment and out of its git remote. In the logs that shows up as an absence:

```
builder:   20:47:05 using the shared forge credential supplied by ploegd
reviewer:  (no such line)
```

I mutation-tested that one, because a control you have not tried to break is a control you are
guessing about: with the scrub disabled the reading-run tests fail, with it restored they pass,
and the case that must keep working, a writer keeping its token, holds throughout.

Three more defects fell out while I was in there, all the same shape: the reader could not read.
The clone was `--depth 50` against the base branch, and `--depth` implies `--single-branch`, so
the branch under review was not in the repository at all while the prompt asserted the checkout
was standing on it. The reviewer was never told the pull request existed. And a reader that
touched nothing was recorded as having pushed.

Fixed, the reviewer now orients itself before it thinks:

```
20:54:16  reading run prepared  on_review_branch=true branch=agent/vik-628 base=main
20:54:17  branch already has an open PR  pr=…/erfbeeld/pulls/9
```

### The error message named the wrong fix

The night before, two reader Roles died 1.2 seconds after starting:

```
exec: "opencode": executable file not found in $PATH
```

Which reads as: install the binary. That would have been a quiet disaster. The runner image's ACP
and claude-code adapters set no outcome file and populate no findings, so only two of the four
adapters can return a review at all. Installing opencode would have converted *failed to start*
into *started, reviewed, and threw the review away*. The real blockers were four defects deeper,
in the dispatcher, and the reviewer now runs on the harness that was already installed.

I have started reading "the error message names the fix" as a smell.

### Narrowing a policy waiver, and what it was hiding

The builder pod carries a privileged Docker-in-Docker sidecar so it can run language gates in the
same images CI uses. That does not pass Kubernetes Pod Security baseline, and shouldn't, so it
runs under a Kyverno exception. The exception used to match by workload name, which waived
everything about those pods including things they never needed.

So I narrowed it to match the hazard itself: a label saying "this pod takes privileged DinD". That
took down every team that takes the sidecar. KEDA looped on `KEDAJobCreateFailed` and bronze
dispatched nothing at all.

**A Job selector matches the Job's own labels.** The hazard label lives on the pod template, so
the Job never carries it, so the match can never admit the Job. The comment I had written above
that match explained, confidently, otherwise.

The second half is the part worth stealing. Before narrowing it, I had checked the policy's
`.spec.rules` for the Job-level sibling rule, found none, and concluded it did not exist. It does.
Kyverno auto-generates Job, Deployment and CronJob variants of a Pod rule at admission time, and
`.spec.rules` lists only the rules a human authored. Reading the policy object does not tell you
what the policy enforces. If you run Kyverno and did not know that, it is the most useful sentence
in this post.

What made it worth the outage: with the waiver keyed to the hazard rather than the workload, the
reviewer, which takes no privilege, now gets no waiver at all and is held to the full baseline.
The broad exception had been quietly covering readers for a privilege they never take.

### The hazard I have not addressed at all

Worker pods run with `automountServiceAccountToken: false` and a no-authority identity, so the
model-driven process gets a shell, a docker daemon and a git remote, and does not get a cluster.

That control is irrelevant to the thing that should actually worry me. The builder ingests ticket
text as instructions while holding a forge token with push access and a privileged Docker daemon.
Prompt injection does not appear anywhere in my design documents. The only reason it has not
mattered is that the board has exactly one human user, which makes every ticket trusted by
assumption rather than by control. That is a fine answer for a homelab and not an answer at all
for anything else.

And one control that has never once worked, announced at every single boot:

```
per-run forge credentials disabled (PLOEG_FORGEJO_ADMIN_TOKEN unset); workers use the shared token
```

Each run is supposed to get its own short-lived forge credential. The broker calls
`/api/v1/admin/users/{bot}/tokens`, which returns 404 on the Forgejo version I run. Every run in
the system's life has used the shared token. It has been printing "disabled" since the day it was
written and nobody, me included, read it.

---

## The money

One ticket, one pull request, one review of it: **$0.019872**, split $0.013573 for the builder
across 32 calls and $0.006299 for the reviewer across 16.

An honest footnote on that precision. I matched those two figures to those two pods by their spend
windows on the clock, not by a stored run id, because per-run keys are revoked when a run ends,
revocation deletes the key record, and the alias that mapped a key back to its run trace dies with
it. The ledger keeps the money and loses the name. I found that while gathering numbers for this
post, which is a decent argument for writing things down.

The bigger number: **$1.40 is the total inference spend for this project's entire life.** 2,379
calls since the ledger started recording on 15 July, effectively all of it DeepSeek. Prompt
caching does the heavy lifting; a representative request shows 33,128 prompt tokens of which
33,024 were cache hits.

Three reasons that is less impressive than it sounds.

It is cheap because it is small. Two cents buys a review of a two-sentence README edit. I have no
idea what a real feature costs, because the factory has not done one.

The euro figure is close to circular. OpenCost reports €94.76/month for the cluster. It reports
that because I hand-set the rates, and the comment next to them records that they were calibrated
to hit an assumed thousand-euro-a-year target. Cross-checking it two ways gives the same answer,
which confirms the arithmetic and nothing else.

Power is not measured. Kepler, which reads the CPU's own energy counters, reports 72.84 W
cluster-wide over a week, of which one worker is 36.2 W and each control-plane node is under 4 W.
That is processor package plus memory only: no power supply losses, no disks, no fans. Nothing
here measures what the wall socket sees. At Dutch rates, where a continuous watt runs about €3 a
year, 73 W of silicon is roughly €220/year, and that is a floor. It is also what an idle factory
costs, so scale-from-zero saves me inference and pod scheduling, not electricity.

One more for anyone who copies the query: `sum(kepler_node_cpu_watts)` returns 104.7 W and is
wrong. The energy counters nest, so the package zone already contains core and uncore, and you
have to filter `zone=~"package|dram"`. A 44% overstatement, one obvious PromQL expression away, in
a metric whose main job is to be quoted in blog posts.

---

## What is not built

Nothing merges through this loop. Nothing deploys through it. No telemetry closes it.

Agents have been assigned ten tickets ever. Six are closed and all six are drills and smoke tests
in a scratch project. Of the four still open, two are the only ones ever aimed at a real product
repo. Ploeg has never closed a ticket in its life, by design: its Definition of Done is "in
production, first telemetry seen", and it can observe neither. It says so on the ticket it just
worked, which I find slightly moving:

> This task stays open until it is in production and its first telemetry has been seen.

**The review does not reach the pull request.** The failure at the top. It is the second time in
two days that this system did the work and told nobody: the first was a notification gated on the
failure path, so success was the silent one, and no error appeared anywhere because no call was
made. The last hop is the one nobody tests.

**The reviewer has never requested changes.** One verdict in its life, approve, on a diff of two
sentences. I have never handed it a diff with a planted bug to see whether it approves that too,
and until I do, "builder ≠ judge" is an architecture diagram rather than a demonstrated control.
The one thing in its favour is that the broken version never emitted a verdict either, because
both attempts died at startup, so there is no pile of untrustworthy approvals sitting in that
table.

**The reviewer is not independent enough.** My own hazard analysis says a reviewer must use a
different model *family*, citing same-family review inflating pass rates by 9 to 17 percentage
points and models failing to fix their own errors around 64.5% of the time. Last night's builder
and reviewer ran different pods, different credentials and different budgets, on the same model
family. By my own written standard, that approval is worth less than it looks.

**The dispatcher does not track its own spending.** The caps are real and enforced at the proxy.
The dispatch database's `spent` column reads `0.0000` on every Shift and nothing writes it.

**"Agents never merge" is a convention.** The branch protection that would make it a rule is
written up and not rolled out. Today it holds because the prompt says so and because nothing has
tried, and I have already told you what I think of prompts as controls.

And an admission about the architecture claim I inherited from my own earlier writing: I used to
say there was no bespoke orchestration on the critical path. There is now. It is called Ploeg, it
has its own object model, routing table, config validator and database, and I wrote it. That may
still be the right call, but it is no longer a virtue I get to claim.

---

## What is next

Make the review land on the pull request. It is one empty field, or one fallback line, and it is
the difference between a system that reviews and a system that reviews into a void.

Give the reviewer a different model family. The cap is already $0.40 a run and last night's
reviewer spent $0.0063 of it on a cheap model; a Claude-family reviewer will cost more and I do
not have a figure yet.

Then hand it a diff with a bug in it and find out whether any of this works.

The lights are not off. Humans still write every ticket and perform every merge, on purpose, and
the factory's lifetime output is two commits and two open pull requests. But last night a Kanban
card turned into a branch, a commit, a pull request and a review, without me, for two cents. The
review is in a database, waiting for one line of code that would let anyone see it.

---

*All self-hosted: Talos Kubernetes, Flux, Forgejo, KEDA, Harbor, Vikunja, LiteLLM, OpenHands,
External Secrets with OpenBao, Kyverno, Cilium, and the VictoriaMetrics stack. The dispatch plane
is `webgrip/ploeg`.*
