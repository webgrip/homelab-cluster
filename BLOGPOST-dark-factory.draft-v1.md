# Building a Dark Factory: Kanban tickets in, reviewed pull requests out

*Draft — 2026-07-19*

At 07:39 UTC this morning, a bot account called `agent-builder` opened pull request #1 on one
of my repositories: 205 lines of unit tests, a small refactor to make them possible, correct
commit trailers linking back to the ticket that asked for them. Twenty minutes earlier that
ticket had been nothing but a card on my Kanban board with a label that says `team/bronze`.

Eleven minutes after the PR opened, a *different* bot — `agent-reviewer`, which cannot push,
cannot merge, and cannot rewrite anything — left a review: the tests pass, but the author
skipped the TypeScript gate (three strict-mode errors) and slightly exceeded the ticket's
scope. Requesting changes.

No human touched any of it. The merge button is still mine, and that's the point.

This post is the story of the **dark factory** — the term borrowed from lights-out
manufacturing: a factory that runs with the lights off because nobody is inside — and a fairly
complete tour of the infrastructure it took to make one run on a homelab Kubernetes cluster.
It is also, unavoidably, a museum of everything that went wrong on the way, because roughly
half of the engineering here consists of failures that got promoted into design decisions.

A note on method: large parts of this build were pair-programmed with an AI agent, which is
pleasingly recursive — an agent helping to build the factory that runs agents. The division of
labour that emerged is the same one the factory itself enforces: the machine proposes and
builds, verification gates everything, and the irreversible decisions stay human.

---

## What I actually wanted

The feeling I was chasing is simple to state:

> Drag a ticket on the board, assign it to `team/bronze`, and some time later a reviewed pull
> request exists — written by an agent, judged by a different agent, merged by me.

The constraints made it interesting:

- **Self-hosted everything.** The forge, the board, the CI, the registry, the inference proxy
  and the observability stack all run on my own cluster. No SaaS control plane gets to be a
  dependency of the factory.
- **Metered by construction.** Every agent run must carry its own spend budget, minted for
  that run and revoked after it. An unattended system that can spend money must not be able
  to spend *unbounded* money.
- **`builder ≠ judge`.** The actor that writes code must never be the actor that approves it.
  This came out of painful experience (more below), and it is the single load-bearing safety
  property of the whole design.
- **Everything in git.** The dispatch path, the runner, the policies, the credentials plumbing
  — all declarative, all reconciled by GitOps. No workflow-in-a-database products on the
  critical path.

## The platform it landed on

None of this started from zero. The factory is maybe the fifteenth tenant of a cluster that
already existed, and almost every piece of it leans on machinery that was already there:

| Piece | Role in the factory |
|---|---|
| **Kubernetes (Talos), 5 nodes** | 3 × `soyo` control-planes (small, run etcd, deliberately kept free) + 2 workers |
| **FluxCD** | GitOps reconciler — every manifest in this post ships by pushing to `main` |
| **Forgejo** | The forge: repos, PRs, and — crucially — **Forgejo Actions** as the execution substrate |
| **KEDA** | Autoscales Actions runners from queue depth; the factory adds a second runner pool |
| **Harbor** | Registry + pull-through proxy; the agent image lives here, cosign-signed |
| **Vikunja** | The Kanban board — the factory's only input |
| **LiteLLM** | The metered inference plane: one proxy in front of every model, virtual keys with budgets |
| **ESO + OpenBao** | Secrets: everything credential-shaped is an `ExternalSecret` backed by a self-hosted vault |
| **Kyverno** | Admission policy — the factory's privileged parts run under explicit, documented exceptions |
| **Cilium** | CNI with identity-based network policy — the source of two excellent traps described below |
| **VictoriaMetrics / Logs / Traces** | Observability; the factory's per-run trace ids are designed to land here |

If there is one meta-lesson in this post it's that **the factory is mostly not new
infrastructure**. It is a new *tenant* wired into existing primitives: a runner pool, two bot
accounts, three secrets, one policy exception, one workflow file. The RFC that scoped the
project ratified this explicitly: reuse the KEDA-scaled runners, don't build a bespoke agent
controller. A purpose-built operator with an `AgentTask` CRD is the v2 graduation, not the
v1 foundation.

## Decision 1 — the harness, and the lesson that shaped everything

The first serious attempt didn't use OpenHands at all. It used opencode, and it used it
ambitiously: a six-agent team — lead, scout, architect, builder, reviewer, render-checker —
each with its own model, its own permissions, its own LiteLLM key. I called it Team Bronze.

Team Bronze taught me the most important lesson of the project by failing. I had it build a
D3 chart, and it shipped — confidently, "all gates green" — a chart whose axis was rendered
in the wrong place entirely. The builder had run its own checks, declared victory, and no
independent actor ever *looked at the result*. My board still has the scar tissue: an ADR that
now mandates a render-verification channel for every visual change, because **a builder
cannot self-verify its own render**, and by extension a builder cannot be trusted to judge
its own anything.

So why is the factory not running Team Bronze? Because opencode's only viable build at the
time was a pinned, self-updating beta that churned daily. Running an *unattended* factory on
a runtime that changes under you overnight is an operational risk I wasn't willing to take,
and a written ADR reconsidered the choice: **OpenHands** — released, versioned, MIT-core,
with native LiteLLM support and a headless mode — became the runtime.

That trade cost something real: OpenHands is a one-strong-agent harness, not a team. The
resolution is the design idea I'm proudest of in this whole build:

> **`builder ≠ judge` moved up a level.** Instead of six agents inside one harness, the
> separation lives in the *pipeline*: a build run (as one bot) opens the PR, and a separate
> review lane (as a different bot, with read-only credentials, ideally a different model
> family) judges it. The forge itself enforces the property — no account can approve its own
> pull request.

The harness became swappable. The safety property became structural.

## Decision 2 — the agent image

Agents need a body. Ours is a container image called `agent-runner` — deliberately *not*
`openhands-runner`, because the previous paragraph happened once already and image names
outlive runtimes. A harness swap should be a content change, not a rename of every manifest
and pull-ref in the cluster.

The image went through five build slices, and one big correction:

1. **The runtime**: OpenHands pinned to a released version, installed with `uv`. Never a
   `@next` tag — the factory does not run on self-updating anything.
2. **Agent tooling**: node, the task-graph tool, the spec-workflow CLI, python — the things
   the *agent itself* uses to navigate a repo.
3. **A docker CLI** — because the agent's pod carries a Docker-in-Docker sidecar (below), and
   that daemon is how the agent runs anything heavier than itself.
4. **Per-run key minting**: the entrypoint mints a budget-capped LiteLLM key at start and
   revokes it on exit — success *or* failure — with the key's TTL as the backstop for hard
   kills.
5. **Skills**: a baked core of agent skills, plus per-ticket extras cloned at start when a
   profile is requested.

The correction: the first version also baked the full Rust toolchain, because the target
repository has a Rust core. That made the image **2.1 GB**, which made every CI publish crawl
and would have made every per-ticket pull expensive. The fix was a design line I now apply
everywhere:

> **Agent tooling is baked; language toolchains are not.** The agent drives the DinD daemon,
> so language gates run in *the same container images CI uses* — the Rust job runs in the CI
> Rust image, the PHP job in `php:8.5-cli`, the web job in `node:24-alpine`. The gates match
> CI exactly instead of approximating it, and the image dropped to 1.12 GB.

Two smaller findings from this phase that cost me an evening each:

- **Skills discovery is subtler than it looks.** In the OpenHands SDK, an AgentSkills-format
  `SKILL.md` is *always* progressive-disclosure — advertised to the model, loaded only if the
  agent chooses to invoke it. If you want a skill (say, your delivery discipline) to be
  *guaranteed* in context, it must be a plain `.md` repo skill with no trigger, or live in
  `AGENTS.md`. I proved this with the SDK's own loader after discovering my "always-active"
  discipline file was silently optional. The delivery discipline now lives in the repo it
  governs, which has the lovely property of being harness-neutral: any tool that reads
  `AGENTS.md` gets the same contract.
- **Installed skills are just directories.** The SDK's registry is self-healing — anything
  copied under `~/.openhands/skills/installed/` gets discovered and registered. So "give the
  agent skills" is a `cp -r`, which means the *bake* is trivial and the per-ticket loadout is
  a shallow git clone. No install API on the critical path.

## Decision 3 — the execution layer (the homelab-cluster part)

This is the infrastructure the title promised. Everything in this section lives in the
cluster repo and ships via Flux.

### The agent runner pool

Forgejo Actions runners in this cluster are KEDA `ScaledJob`s: ephemeral one-job pods that
register with the forge, block waiting for a task, run exactly one job, and exit; KEDA
watches the pending-job queue and spawns more. The factory adds a **second pool** next to the
CI one, different in four deliberate ways:

```yaml
# kubernetes/apps/forgejo/forgejo-agent-runner/app/scaledjob.yaml (abridged)
spec:
  minReplicaCount: 0          # scale-from-zero: agent runs are bursty, a warm pool
  maxReplicaCount: 2          #   would pin ~1Gi 24/7 for nothing; max 2 doubles as
                              #   a spend ceiling — N concurrent runs = N budgets
  triggers:
    - type: forgejo-runner
      metadata:
        labels: "agent"       # its own runner label — only agent-run.yml targets it,
                              #   so agent runs never queue behind CI image builds
```

- **Its own registration.** A runner's advertised labels are recorded server-side at
  registration, so the pool registers as its own named runner via an idempotent provisioner
  Job — the same "do-once, self-healing" bootstrap pattern the CI pool uses.
- **Host-mode execution with the agent image as the main container.** Workflow steps run
  *inside* `agent-runner` itself. A tiny init container copies the static `forgejo-runner`
  binary out of the official runner image into a shared volume — so the agent image doesn't
  need to know it's also a runner.
- **A privileged DinD native sidecar.** Same shape as the CI pool: `docker:dind` as an init
  container with `restartPolicy: Always`, TLS certs on an emptyDir, and the main container
  pointing at `DOCKER_HOST=tcp://localhost:2376`. This is how the agent runs language gates
  in CI's images.
- **A 6-hour runner timeout** instead of CI's 1 hour, because an agent legitimately thinks
  for a while.

### The policy exception

Privileged DinD does not fly under a Kyverno baseline policy, and it shouldn't. The cluster's
convention is that exceptions are *narrow, matched by label, and documented in the exception
itself* — wildcard names are forbidden by a governance policy, and KEDA generates
random-suffixed Jobs, so the exception matches the label KEDA stamps
(`scaledjob.keda.sh/name: forgejo-agent-runner`) on both the Job and the Pod. The Job match
is load-bearing: baseline enforcement rejects at Job admission, before any pod exists.

The exception's description carries a sentence I want to quote because it captures the
security posture better than any diagram:

> The pod deliberately sets `automountServiceAccountToken: false` and binds a no-authority
> ServiceAccount, so the LLM-driven process in it has zero Kubernetes API access despite the
> privileged sidecar.

The agent gets a shell, a docker daemon, and a git remote. It does not get a cluster.

### Identity: two bots, not one, not many

Who does the agent push as? The cluster already had the answer in the form of precedent: the
Renovate bot — an autonomous account that opens PRs all day with **one identity**, not one
per run. Per-run attribution doesn't need per-run accounts; it needs a correlation id (next
section).

But the factory needs **two** bots, for a structural reason:

- **`agent-builder`** — `write:repository` + `write:issue`. Can push branches, open PRs,
  comment. Deliberately *narrower* than the CI bot: no package scope (it publishes nothing),
  no release scope (it cuts none).
- **`agent-reviewer`** — `read:repository` + `write:issue`. Can read and comment. **Cannot
  push, cannot merge, cannot rewrite the work it judges.**

A forge will not let an account approve its own pull request — so with the author and the
reviewer as *different accounts*, `builder ≠ judge` stops being a convention and becomes a
property the forge enforces.

Both bots are provisioned by idempotent bootstrap Jobs that mirror the existing CI-bot
pattern: an in-cluster-generated password (an ESO `ClusterGenerator` — no human ever types or
sees it), user-create-if-missing, token mint into a Kubernetes Secret, org team membership
with per-unit permissions PATCHed on every run. The bots' first provisioning run also
delivered a lesson worth its own paragraph:

**Silent success is the enemy.** The two provisioners ran concurrently, both created org
teams with "all repositories" access, and they raced inside the forge's access-recalculation
— one got an HTTP 500 on team creation. My script logged a warning *and exited 0*. Result: a
bot with a valid token and zero repository access, reported as healthy. The fix was not
retry logic — the Job's backoff already provides that — it was making the failure **fatal**
so the backoff actually fires. The retry then found the team already created by the winner
and converged. If a bootstrap can't prove its post-condition, it must fail loudly; "WARN" +
`exit 0` is how broken states become invisible.

### Secrets: pod-scoped, never org-scoped

The agent pool's pods carry three credentials, all ESO-delivered from the vault:

- the **LiteLLM master key** (to mint per-run keys),
- the **board API token** (to comment on the ticket it's working),
- the **builder bot's forge token** (to clone, push, and open the PR).

The tempting place to put these was the forge's Actions secrets — that's what they're for,
right? Wrong, in an important way: **Forgejo Actions secrets are org-level**. Publishing the
inference master key there would hand *every workflow in every repo* unlimited spend. The
project's hazard analysis had already flagged this (per-task budget or bust), so the
credentials are injected only into the agent pool's pod spec. Any workflow that wants them
must target `runs-on: agent`, and everything that targets `runs-on: agent` is a reviewed file
in git.

### The metered plane: a key per run

Every run mints its own LiteLLM virtual key: scoped to the models its tier allows, capped
with a `max_budget`, tagged with the run's trace id, revoked on exit. The trace id
(`agent-vik454-run32`-shaped) is the factory's correlation currency — it appears in the
LiteLLM spend ledger, in the ticket comments, and as a `Agent-Trace-Id:` commit trailer next
to the ticket reference, so a line of git history can be walked back to the exact tokens that
produced it and what they cost.

The proxy itself is hardened — which produced the factory's first production failure, and I
mean that as a compliment (details in the run log below).

### The network said no — three times

The cluster runs zero-trust NetworkPolicies per namespace, on Cilium. Cilium is excellent and
its policy model has two properties that will absolutely get you:

1. **The API server is an identity, not an IP.** An `ipBlock` rule for `10.43.0.1/32:443`
   *silently never matches* — Cilium classifies API-server traffic by the reserved
   `kube-apiserver` identity, so the allow must be a `CiliumNetworkPolicy` with
   `toEntities: kube-apiserver`. The cluster learned this the hard way before the factory
   (a database operator crash-looped for two days on exactly this); the factory re-learned
   it when the new runner-registration provisioner hung trying to write its Secret. The fix
   was one line — adding the new Job's name to the existing identity-based allow — and the
   allow is deliberately scoped to *provisioner Jobs only*: the agent pods themselves are
   excluded, because an LLM-driven process must not gain network reach to the API server
   even accidentally.
2. **Service VIPs resolve to pod IPs before policy applies.** The forge namespace's egress
   policy allows "the internet except the cluster CIDRs" — so a cross-namespace call to
   `litellm.ai.svc.cluster.local` gets translated to a pod IP in the excluded range and
   **times out**, while the very same service via its public gateway hostname works fine.
   I verified this empirically from inside a live runner pod before the first dispatch —
   in-cluster URL: timeout; gateway URL: 200 — and switched the pool's environment to
   gateway URLs. Without that pre-flight the first run would have died mysteriously and I'd
   probably have blamed the wrong layer.
3. **A policy can eat your autoscaler's telemetry.** An earlier incident (before the
   factory) had KEDA's queue polls silently dropped by a namespace policy, which was
   misdiagnosed as a scaler timeout under load for days. The durable lesson made it into a
   code comment: *don't re-derive the timeout theory from this comment* — when scaling
   misbehaves, check policy before performance.

The generalized rule I now follow: **before dispatching anything new in a zero-trust
namespace, `kubectl exec` into a representative pod and curl every endpoint the new thing
will need.** It costs one minute and it converts "mysterious first-run failure" into a
one-line diff.

### Placement humility

One more confession from the infrastructure layer. When choosing where the agent pool should
schedule, I looked at the node stats: the three `soyo` nodes had ~50% CPU and ~60% memory
free while both workers were saturated. Obvious answer, right?

The `soyo` nodes are **control-planes running etcd**, and the cluster's very first placement
ADR forbids app workloads on them — overcommitting them is what caused a historical
OOM-cascade, and CI-style IO next to etcd is the documented recipe for fsync starvation.
Their headroom exists *because* they're kept free. I had specified the pool onto them purely
from the numbers; the correction landed before any pod ever ran there, and the ADR now
carries a dated entry recording the error instead of hiding it.

The honest consequence: the agent pool shares two already-tight worker nodes with CI. The
first dispatch bounced off `FailedScheduling` twice before a slot freed. Placement can't
solve that — only hardware can. On a homelab, capacity is always the binding constraint; the
factory's scale-from-zero design and its hard cap of two concurrent runs are as much about
respecting that as about controlling spend.

## The workflow: a thin shell around a disciplined agent

The last piece is the workflow file in the *target* repository — deliberately thin:

1. Resolve the tier (`bronze` → cheap model, $2 budget; `silver` → mid; `gold` → frontier).
2. Mint the per-run key. Fetch the ticket, post a "run started" comment with the run URL and
   trace id.
3. Clone as `agent-builder`.
4. Compose the task: the ticket, plus a non-negotiable delivery contract — branch naming,
   commit trailers, *open a PR and never merge*, and "if the ticket isn't actually doable,
   say so and exit non-zero rather than inventing scope".
5. Run the agent headless.
6. Comment the outcome on the ticket; revoke the key; clean up.

Everything *disciplinary* — run the gates and paste output, adversarial self-review, the
render check for visual work — is **not in the workflow**. It travels with the repository
(`AGENTS.md` plus an always-on repo skill), which means every harness that ever touches the
repo gets the same contract, and the workflow can stay a dumb shell.

Is the current version good? No — it's v1, it has inline heredocs and hardcoded values, and
there's a ticket on the board titled "agent-run.yml 10x" with twenty concrete improvements
(extract scripts, a `teams.yaml` source of truth, claim semantics, idempotency guards, a
structured result contract, OTEL run events, credential hygiene, a dry-run mode…). Shipping
the thin ugly version first was the right call; run 31 would have found the same bug in a
beautiful one.

## Run 31: sixteen seconds

The first dispatch died 16 seconds after task pickup. The complete delivery chain worked —
KEDA scaled from zero, the runner declared its label, picked the task, posted the start
comment, posted the failure comment — and the run failed at exactly one point:

```
{"error":{"message":"Required param key_alias not in data","code":"400"}}
```

My own proxy hardening requires every minted key to carry a unique alias, and the entrypoint
didn't send one. I love this failure. The security control did its job against the system
that installed it; the per-run trace id was sitting right there being unique, so it became
the alias. One reproduction probe with the pool's own credential confirmed the fix shape
(mint-with-alias ✓, revoke ✓), the image got the durable fix, and the workflow got a bridge
(mint in the workflow, pass the key in — the entrypoint's caller-supplied path) so the pilot
didn't have to wait for an image rebuild.

Also in the sixteen-seconds museum: my first attempt at the entrypoint fix contained an
apostrophe inside a single-quoted shell block — `bash -n` failed and a sloppy `&&` chain let
the commit through anyway. The push after that one verified syntax *before* committing.
Verification isn't a phase, it's a reflex, and the reflex has to fire on the fixes too.

## Run 32: twenty minutes

The second dispatch went end to end:

- **07:19** — dispatched: ticket 454, `team/bronze`, deepseek-chat, $2 budget.
- KEDA spawned the pod; two `FailedScheduling` bounces; a CI slot freed; init containers up;
  the 1.12 GB image pulled from the LAN registry.
- The agent read the ticket (write structural tests for a chart layer that shipped without
  any — a real gap, recorded at merge time), extracted three pure functions into a utils
  module so the components could be tested without mounting D3, and wrote 16 specs: locale
  currency formatting, segment totals, the mapping from tax assessments to chart segments
  with fixtured expected values.
- **07:39** — branch pushed, **PR #1 opened**, correct `VIK-454` + `Agent-Trace-Id` trailers,
  "run finished" comment on the ticket.

Then the part I insisted on doing properly: **verification, not vibes.** I fetched the
agent's branch and ran its work myself. The test suite: 83/83 green, 16 of them new, and the
assertions genuinely use fixtured values rather than re-deriving them (the target repo has a
hard rule that clients never calculate — the agent respected it). The TypeScript gate:
**three strict-mode errors** in the agent's own test file. The discipline file explicitly
lists that gate; the agent either didn't run it or didn't heed it. It also stretched the
ticket's "no production changes" boundary with its (defensible, explained) refactor.

So the review lane got its first real workout: `agent-reviewer` — the account that *cannot*
push — posted the findings on PR #1 and requested changes. Builder wrote, judge judged,
and the judge caught something real on day one.

I could not have scripted a better pilot outcome. A flawless run would have proven much less
than a good run with a caught defect: the factory's value isn't that agents are perfect,
it's that the *system* is honest about where they aren't.

## The safety model, in one table

| Layer | Control |
|---|---|
| **Spend** | Per-run budgeted key, minted at start, revoked at exit, TTL backstop; hard cap of 2 concurrent runs; tier budgets ($2/$5/$15) |
| **Forge** | Two scoped bots; builder can push branches + open PRs, nothing else; reviewer is read+comment; **merging is human-only**; server-side push guards are the next hardening step |
| **Cluster** | No ServiceAccount token, no API-server egress for agent pods, Kyverno baseline everywhere except one narrow documented exception |
| **Network** | Zero-trust namespace policies; the agent reaches exactly: the forge (intra-namespace), the board and the proxy (via the gateway), and whatever its DinD gates pull |
| **Attribution** | One trace id from ticket → run → commits → spend ledger |
| **Review** | An independent, credential-separated review lane, on by design from run #1 |

## What's next

- **The dispatcher.** Today the dispatch is a curl. The target design is event-driven off the
  board's webhooks into a declarative receiver — with a slow reconciling poll as the
  self-healing backstop, and the claim-as-lock protocol so the two paths can never
  double-dispatch (and never double-spend).
- **Telemetry.** The trace ids are flowing; the dashboard that joins run outcomes with the
  spend ledger and PR/ticket flow is specced and next on the build list. I want to *watch*
  the factory before I stop watching it, if you see what I mean.
- **The iterate loop.** The obvious next experiment: re-dispatch the same ticket and let the
  builder fix its own reviewer findings. Then tighten it: reviewer findings as structured
  output, an attempt cap, escalation to a better model (`team/silver`) on repeated failure —
  the bronze/silver/gold tiers becoming an actual escalation ladder.
- **Teams as pipelines.** The original Team Bronze idea returns one level up: scout → builder
  → reviewer as separate runs with separate loadouts, cooperating through the forge instead
  of inside one harness. The two-bot identity layer was built for exactly this.
- **Server-side guards.** The pre-receive block-list (no plaintext secrets, no protected-file
  edits, regardless of which client pushed) — the control that makes the forge, not the
  agent's good manners, the final boundary.

## Closing

Three weeks ago this project was a config file and a question — *"how do I use my inference
proxy with a coding agent to pick up tickets?"* It is now a system where a Kanban label turns
into a reviewed pull request while I make coffee, on hardware in my own house, with every
euro of spend budgeted per run, every action attributable, and every irreversible step still
behind a human.

The lights aren't fully off yet. But this morning, for twenty minutes, nobody was in the
factory — and the factory worked.

---

*Stack: Talos Kubernetes · FluxCD · Forgejo + Forgejo Actions · KEDA · Harbor · Vikunja ·
LiteLLM · OpenHands · ESO + OpenBao · Kyverno · Cilium · VictoriaMetrics. All self-hosted.*
