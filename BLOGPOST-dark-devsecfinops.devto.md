---
title: "I told my AI code reviewer it couldn't push. It could."
published: false
description: "A false constraint in a prompt is worse than no constraint. What it took to make a reviewing agent actually read-only, on a self-hosted Kubernetes homelab."
tags: kubernetes, ai, devops, security
canonical_url: TODO-set-substack-url-before-publishing
---

*Originally published on [Substack](TODO). This is the engineering cut: less narrative, more
manifest.*

For most of this project, the reviewing agent in my homelab's "dark factory" was told this:

> Do NOT modify, commit or push anything: you hold no lease on this branch and no write
> credential, so a push will be rejected by the forge.

The second half was false. The builder's push token was required on every worker pod, it reached
the agent process through `os.Environ()`, and it was baked into the git remote of the clone the
reviewer was working in.

## Why a false constraint is worse than no constraint

The moment a model tests that claim and finds it untrue, every other line in its instructions
becomes a hypothesis. "Never merge your own work" was in the same prompt.

The fix is not wording. It is that **every control I care about is pod-shaped**:

| Control | Where it actually lives |
|---|---|
| Budget | A virtual API key minted per run, capped in dollars, revoked on exit |
| Privilege | An admission-control decision at Job creation |
| Credential | An environment variable that is either present or absent |
| Identity | A separate bot account that the forge will not let approve its own PR |

None of those can be expressed by telling a model what it is.

## A Role is a workload, not a persona

The dispatch plane models work as **Shift → Round → Role**. A Shift is one ticket's worth of work.
A Round is a sequential step. A Role is a job inside a Round, such as `builder` or `reviewer`.

The design decision worth copying: a Role is a **separate Kubernetes workload**, with its own pod,
resource requests, budget cap, harness config and credentials. Not a section in a system prompt.

```yaml
plan:
  - roles:
      - {name: builder, writes: true, cap: "2.00"}
  - roles:
      - name: reviewer
        writes: false
        cap: "0.40"
        harness: {name: openhands, dind: false}
        workerResources:
          requests: {cpu: 500m, memory: 384Mi}
          limits:   {cpu: 500m, memory: 384Mi}
```

`dind: false` is load-bearing twice. It skips the Docker-daemon wait, and it drops the
`privileged-dind` hazard label, so the reader is held to the full Pod Security baseline instead of
being waived for a privilege it never takes.

Verification, in the logs, as an absence:

```
builder:   using the shared forge credential supplied by ploegd
reviewer:  (no such line)
```

Mutation-tested both ways: with the credential scrub disabled the reading-run tests fail, with it
restored they pass, and the writer-keeps-its-token case holds throughout. A control you have not
tried to break is a control you are guessing about.

## Three more defects, all "the reader could not read"

1. The clone was `--depth 50` against the base branch, and **`--depth` implies
   `--single-branch`** — so the branch under review was not in the repository at all, while the
   prompt asserted the checkout was standing on it.
2. The reviewer was never told the pull request existed. The prior-PR reference was interpolated
   only into the writer's contract.
3. A reader that touched nothing was recorded as having pushed.

## The Kyverno finding, which is the transferable one

The builder carries a privileged Docker-in-Docker sidecar so it can run language gates in CI's own
images. It runs under a Kyverno exception. I narrowed that exception from a workload-name match to
a hazard-label match, which is the right instinct, and it took down every team that takes the
sidecar with `KEDAJobCreateFailed`.

**A Job selector matches the Job's own labels.** The hazard label lives on the pod template, so
the Job never carries it, so the match can never admit the Job.

And the part that cost me the outage: before narrowing it, I checked the policy's `.spec.rules`
for the Job-level sibling rule, found none, and concluded it did not exist.

> `.spec.rules` lists only the rules a human **authored**. Kyverno generates the Job, Deployment
> and CronJob variants at admission time.

Reading the policy object does not tell you what the policy enforces. If you run Kyverno and did
not know that, it is the single most useful sentence here.

## What this does not do

Full disclosure, because the post it is drawn from leads with it: nothing merges through this
loop, nothing deploys through it, no telemetry closes it. The reviewer has returned exactly one
verdict in its life (approve, on a two-sentence README edit) and no adversarial test has been run,
so `builder ≠ judge` is currently an architecture diagram rather than a demonstrated control.
Builder and reviewer also share a model family, which my own hazard analysis says invalidates the
independence.

And prompt injection is unaddressed: the builder ingests ticket text as instructions while holding
a push token and a privileged daemon. The only thing standing there is that the board has one
human user.

Stack, all self-hosted: Talos Kubernetes, Flux, Forgejo, KEDA, Harbor, Vikunja, LiteLLM,
OpenHands, External Secrets with OpenBao, Kyverno, Cilium, VictoriaMetrics.
