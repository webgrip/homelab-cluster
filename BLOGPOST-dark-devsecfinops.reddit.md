# Reddit variants

One subreddit at a time, never simultaneous. Context comment goes up immediately after posting,
and it discloses authorship. No vote solicitation anywhere.

---

## r/kubernetes — post first

**Title:** Narrowing a Kyverno exception took down my whole agent pool, and taught me that
`.spec.rules` doesn't tell you what a policy enforces

**Why this angle:** r/kubernetes does not care about my agents. It cares about the admission-policy
finding, which is self-contained, checkable, and true for anyone running Kyverno. Lead with that
and let the AI part be background.

**Context comment (post immediately):**

> Author here. Short version, for people who don't want the click:
>
> I had a broad Kyverno exception matched by workload name, waiving privileged DinD for a pool of
> CI-ish pods. I narrowed it to match a hazard label instead (`…/privileged-dind`), which is the
> better pattern — waive the hazard, not the workload.
>
> It took the pool down. KEDA looped on `KEDAJobCreateFailed`.
>
> Two things I hadn't internalised:
>
> 1. **A Job selector matches the Job's own labels.** My hazard label was on the pod template, so
>    the Job never carried it, so the exception could never admit the Job. Baseline enforcement
>    rejects at Job admission, before any pod exists.
> 2. **`.spec.rules` lists only the rules you authored.** Kyverno generates the Job/Deployment/
>    CronJob autogen variants at admission time. I had checked `.spec.rules` for an `autogen-`
>    sibling, found none, and concluded it didn't exist. Reading the policy object doesn't tell
>    you what the policy enforces.
>
> The upside: with the waiver keyed to the hazard, the non-privileged pods in the same pool get no
> waiver at all and are held to the full baseline. The broad exception had been silently covering
> them for privileges they never take.
>
> Happy to answer anything about the setup.

---

## r/selfhosted — a few days later, not the same day

**Title:** My self-hosted "dark factory" turns Kanban tickets into reviewed pull requests for two
cents a run. It has also produced 2 of my last 594 commits.

**Why this angle:** r/selfhosted rewards the full-stack-on-my-own-hardware story and punishes
overclaiming. The self-deprecating half of the title is the whole defence.

**Context comment (post immediately):**

> Author here. The stack, all self-hosted on 5 Talos nodes (24 cores / 72 GiB total): Forgejo as
> the git host, Vikunja as the board, KEDA scaling agent pods from zero, LiteLLM as a metered
> inference proxy, Harbor, Kyverno, Flux for GitOps, VictoriaMetrics for observability. The only
> rented thing is the model API.
>
> Numbers, since they're the thing people ask: a ticket → pull request → review round cost
> **$0.019872** last night. Total inference spend for the project's entire life is **$1.40**.
> Idle costs nothing in inference because the pods scale from zero, though the nodes still draw
> about 73 W continuously, which at Dutch electricity prices is the real floor.
>
> The honest part: nothing merges automatically, nothing deploys through this loop yet, and the
> reviewing agent has returned exactly one verdict in its life. It's further along as
> infrastructure than as output, and the post says so early rather than in a footnote.
>
> Ask me anything about the self-hosting side.

---

## Not r/programming, not r/devops

r/programming will read the AI framing as spam regardless of content. r/devops overlaps heavily
with r/kubernetes and the Kyverno angle is the stronger one there. One post per venue per piece.
