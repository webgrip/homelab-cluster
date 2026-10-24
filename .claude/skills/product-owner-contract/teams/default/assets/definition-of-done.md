# Definition of Done — webgrip default team

> One list. It applies to **every** ticket that wants to be completed, whatever its kind or
> size. No ticket-specific DoDs — those are acceptance criteria and live in the ticket.

A completion is accepted only with an **evidence comment** on the ticket that walks this
list: each line met, or its way out with a reason.

## The list

**Result**

- Every acceptance criterion in the ticket is met
- The ticket's Verification was executed, not just promised

**Code**

- Every change landed on `main` through the Definition of Mergeable (the product-owner
  skill's merge.md); CI green on the landed commit
- Reviewed by someone other than the author; an agent's own review is an input, never the
  approval
- No new critical/high findings, no secret in any file (the `secrets-levels` skill places it)

**Deployed**

- Running where it is meant to run, **verified against real state, not a proxy**: the
  reconciled Flux revision and the running image digest, not "the rollout succeeded"
  *(or explicitly not deployed, with the reason)*
- The rollback path is known and written down

**Monitored**

- Names the signal that would catch a regression — alert, dashboard or scheduled check —
  *or states why none applies (docs-only, a removed feature)*

**Knowledge**

- Behaviour changed? TechDocs, runbook or ADR updated *(or: "not needed, because …")*
- Commits reference the ticket: trailer `VIK-<id>`

## Three rules that keep the DoD standing

1. **It is not negotiable per ticket.** Per team it is, and only in a retro. One exception
   "because it's urgent" turns a definition into a suggestion.
2. **Every rule has a way out with a reason.** "Not deployed, the chart waits for the next
   maintenance window" is fine. "Not deployed" alone is not done. The way out exists so
   nobody has to lie.
3. **Structurally missed means the DoD is wrong, not the team.** Lower it deliberately
   instead of silently ignoring it; an ignored DoD teaches that agreements are optional.

## Relation to the Definition of Ready

The [Definition of Ready](definition-of-ready.md) decides when work may **start**; the DoD
decides when it is **finished**. The DoR is about understandability, the DoD about done —
per-ticket conditions are acceptance criteria and belong in the ticket.
