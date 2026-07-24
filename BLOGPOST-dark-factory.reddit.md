# Reddit submissions — dark factory post

Read each sub's rules + wiki the day of posting (self-promo rules change). One sub first,
the second a few days later; never simultaneous. Link post → canonical Substack URL. Always
disclose authorship. Post the context comment immediately after submitting.

## r/selfhosted (first choice — build-log culture, self-promo tolerated when disclosed)

**Title** (plain, no clickbait):
> I built a "dark factory" on my homelab: Kanban tickets in, agent-written + agent-reviewed
> PRs out, fully self-hosted

**Context comment** (post immediately as author):
> Author here. This is the write-up of getting autonomous coding agents running on my own
> cluster with no SaaS in the loop: Forgejo + KEDA-scaled runners + OpenHands + LiteLLM as a
> metered inference proxy. The parts I think this sub will care about: every agent run mints
> its own budget-capped LLM key (failed runs literally cost $0.00), the reviewer bot
> physically can't push or merge, and the whole thing ships as Flux-reconciled manifests.
> First real PR cost $0.046 in inference. Happy to answer anything about the setup — the
> post is also honest about the three runs that failed and why.

## r/kubernetes (second — technical depth expected)

**Title**:
> Scheduling AI coding agents turned out to be a solved problem: they're KEDA ScaledJobs.
> The real work was spend, identity, and trust

**Context comment**:
> Author here. The k8s-specific meat: a second Forgejo Actions runner pool as a KEDA
> ScaledJob (scale-from-zero, max 2 as a spend ceiling), privileged DinD sidecar under a
> label-matched Kyverno PolicyException with `automountServiceAccountToken: false` and no
> API-server egress for the agent pods, and two Cilium traps that bit me (API server is an
> identity not an ipBlock; service VIPs resolve to pod IPs before policy applies, so
> in-cluster URLs timed out while the public gateway worked). Questions welcome.

## Not for this post

- r/programming: low self-promo tolerance and the post is infra-heavy; skip unless it
  organically travels.
- r/homelab: prefers hardware/build posts; could work with a photo of the nodes + a
  different, hardware-first framing. Optional later.

## Lobsters (if an invite exists)

Tags: `devops`, `ai`, `practices`. Tick "authored by". The post must pass the
human-authored bar (same as HN: do the read-aloud ownership pass first).
