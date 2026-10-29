---
status: accepted
date: 2026-10-29
decision-makers: Ryan Grippeling
---

# The cluster holds no personal Claude login: team pewter and its self-hosted runner are retired

## Context and Problem Statement

Team pewter ran Ploeg Runs as Claude Code sessions on a self-hosted runner (`claude-runner`, Ploeg
ADR-0084). Its worker used harness `claude-environment` and dispatched each Run signed in as a WebGrip
Team member, from a Claude configuration kept on the `pewter-claude-login` volume in namespace
`ploeg`. Since the standalone Ploeg release folded into the Unfold release (Unfold ADR-0043), the
Ploeg chart inside the Unfold chart renders the runner, the volume and pewter's network policies from
`ploeg.claudeRunner` and `ploeg.executor.teams[pewter]`.

On 2026-10-18 Ploeg ADR-0112's spike showed that a copied Claude login keeps working without a
browser. Anthropic's terms forbid a service storing or intermediating a person's Claude credentials,
so the stored-login part of ADR-0112 is not to be built. The agent-plane hardening review of the same
day listed the volume as an open gap, and retiring it waited on the owner while pewter was still being
built on. On 2026-10-29 the owner decided to retire it.

Should the cluster keep pewter, its runner and the volume?

## Decision Drivers

* No credential a service may not hold should live in the cluster, signed in or not.
* A team with its own egress to Anthropic, its own Secret and its own policy exceptions is attack
  surface.
* The way back must stay open if Anthropic offers a sanctioned delegated login.

## Considered Options

* Retire pewter, the runner and the login volume
* Remove the team and the runner, keep the volume
* Keep everything until Anthropic answers

## Decision Outcome

Chosen option: **retire pewter, the runner and the login volume**, because it is the only option
that leaves no stored login and no path to Anthropic in the cluster.

1. Team pewter leaves the Unfold release's `ploeg:` values: its executor team, its tracker routing,
   and its place in the `unfold`, `mcp-reader` and `mcp-operator` consumers. Unfold's own
   `config.ploeg.teams` drops it. Copper gets its own tracker user back.
2. `ploeg.claudeRunner` is removed, so the chart's default `enabled: false` applies: no
   `claude-runner` Deployment, no `ploeg-claude-runner` and `ploeg-worker-pewter-anthropic` network
   policies, no `ploeg-worker-pewter` ScaledJob.
3. ploegd no longer serves the Claude environment routes: the post-render patch stops setting
   `PLOEG_CLAUDE_ENVIRONMENTS`.
4. The `claude-runner-environment` ExternalSecret and the `claude-runner-egress` and
   `pewter-worker-anthropic-egress` Cilium policies in `ploeg/app/` are deleted, and
   `ploeg-allow-egress` stops naming `claude-runner`.
5. The daily `glide-cve-rescan` stops reading the `claude-runner` Deployment, which no longer exists.
6. The `pewter-claude-login` PersistentVolumeClaim is deleted, and its data with it. The chart
   annotates it `helm.sh/resource-policy: keep`, so Helm leaves it in place when the values go: a
   person deletes it once after the release reconciles. Its storage class `longhorn-general` reclaims
   with `Delete`, so the Longhorn volume goes too.
7. The `pewter--default` key stays in the worker bootstrap registry. Changing that ExternalSecret
   rotates every team's bootstrap token, and an unused key grants nothing without a pewter worker.
8. The `anthropic/claude-runner` environment secret stays in OpenBao, untouched, so a sanctioned
   return does not need a new self-hosted environment.

### Consequences

* Good, because no Claude login, stored or signed out, remains in the cluster.
* Good, because the only egress to Anthropic from `ploeg` is gone.
* Bad, because plan-paid Claude Runs need new work to come back, through a person's own client
  (the client-carried direction of Ploeg ADR-0112) or a sanctioned delegated login.
* Bad, because deleting the volume is a one-time manual step outside Git.
* Neutral, because the Ploeg chart keeps the Claude environment harness; only this deployment stops
  using it.

### Confirmation

After Flux reconciles the Unfold release and the person has run
`kubectl -n ploeg delete pvc pewter-claude-login`: `kubectl -n ploeg get deploy claude-runner`,
`pvc pewter-claude-login`, `ciliumnetworkpolicy pewter-worker-anthropic-egress` and
`networkpolicy ploeg-worker-pewter-anthropic` all return NotFound; `kubectl -n ploeg get scaledjob
ploeg-worker-pewter` returns NotFound; the ploegd container has no `PLOEG_CLAUDE_ENVIRONMENTS`; and
`git grep -n pewter -- kubernetes` finds only the worker bootstrap registry.

## Pros and Cons of the Options

### Remove the team and the runner, keep the volume

* Good, because a return would not need a new sign-in.
* Bad, because the signed-out login data stays on disk, which is what the terms question is about.

### Keep everything until Anthropic answers

* Good, because nothing changes.
* Bad, because the runner, its egress and the volume stay in the cluster for an unknown time.

## More Information

* Ploeg ADR-0084 (self-hosted Claude environments) and ADR-0112 (whose login a Claude environment
  Run uses) record the harness and the terms question.
* [ADR-0071](adr-0071-agent-egress-reaches-only-what-it-needs.md) named the runner's gateway egress
  as its residual risk; this removes it.
* Re-evaluate when Anthropic answers the terms question or offers delegated, session-only
  authorization.
* 2026-10-29 — accepted by Ryan Grippeling; first proposed 2026-10-19 as PR #824 and rebuilt on the
  Unfold release.
