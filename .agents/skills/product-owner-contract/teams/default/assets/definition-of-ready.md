# Definition of Ready — webgrip default team

> **A ticket is ready to pick up when someone else — a person or an agent — can start on it
> without calling the writer.**

Derived from the [golden tickets](golden-tickets.md); the fill-in skeleton is
[ticket-template.md](ticket-template.md).

A ticket has **two halves**: on top the functional half for the product owner, the
requester and whoever accepts it; below a rule the technical write-up for the developer and
the agent. The four rules gate the functional half: a reader who stops at the rule can judge
the ticket. The **TL;DR** belongs to rule 1 and is not a fifth rule: it decides *how* the
problem is stated.

## The four rules

A ticket is ready when:

1. **The problem is stated, in domain language, with checkable evidence.**
   On top the **Source**: where it comes from, with date and link, and the requester's words
   literally. An alert, an incident, a failed run or a measured value counts too. Below it a
   **TL;DR** of two to four sentences: who runs into what, where, and what it costs. The
   test per sentence: **would it change if the implementation changed?** Then it belongs
   below the rule. Code-level evidence (`file:line`, commits, manifests) sits in the
   **technical write-up**, not on top. No solution. *Spike: the question is the TL;DR, plus
   its occasion.*

2. **The outcome is stated, in one sentence.**
   The end state, not the activity. *"A restore drill that proves last night's backup"* is
   an outcome; *"look into backups"* is not. *Spike: the outcome is the decision taken.*

3. **The acceptance criteria are binary — and at least one closes the cheap way out.**
   Binary: two readers reach the same conclusion. They describe behaviour someone can
   observe, not code. *"Works well"* or *"sufficiently secure"* is not a criterion but a
   discussion moved to review. The test question while writing: **"how do I finish this
   ticket without solving the problem?"** — the answer is your missing criterion.

4. **The verification is stated.**
   How we prove the criteria hold: who shows what, in which environment, with which
   concrete case and which expected result. On a GitOps estate that names the reconciled
   state, not the merge. Without a measuring point a criterion is an opinion. *Spike: where
   the decision and its trade-off are recorded.*

## Extras, only where they apply

- **Bug** → reproduction steps as the reporter took them (expected vs. got) + environment
  (where, since when, how often), in the functional half.
- **Code research done** → findings below the rule (`# Technical write-up`) with
  `file:line` and the stamp `Researched against <branch> @ <short sha>`, so the functional
  half stays readable.
- **Spike / ticket with a choice** → the one question (two questions is two tickets) ·
  timebox · what we choose on · who decides. Done = **decided and recorded**, not
  researched; an architecture choice lands as an ADR.
- **Split child** (`<area>: <subject> - Part n/m - <part outcome>`) → its own outcome per
  child, a criterion that protects what already works, and the order as a dependency —
  never as prose.
- **Agent-bound** → the product-owner skill's agent-ready gate on top of this one:
  protected areas, rollback, runnable verification.
- **Open questions** → allowed, but every question has an owner. Three owned questions is
  not a badly written ticket but an honest one.

## Where this comes from

Every rule can be read off the [golden tickets](golden-tickets.md) — rule 3 most clearly:

| Golden ticket | The cheap way out a criterion closes |
| --- | --- |
| Status page: last check per service | a timestamp that shows the page render time, not the check time |
| Nightly backup: false success | a job that turns red on upload failure but still uploads half an archive |
| Log retention (spike) | researched and presented, never decided |
| Agent identity Part 2/4 | the child built at the cost of what already works in the series |

A groomed ticket with no criterion answering that test question is not ready yet — that is
not a style point but the core of the checklist.

## Deliberately not in it

Estimate, priority, `do-next`, assignee and the three estimation labels. That is about
**plannability**, not **understandability** — planning decisions made after this checklist.
Everything that touches every ticket is in the [Definition of Done](definition-of-done.md),
not here.

## The ten-minute rule

A ticket falls short but you can complete it within ten minutes? **Do that and pick it up.**
More than that, it goes back with a comment naming what is missing. That way the checklist
forces a conversation while it is still cheap — and never becomes a queue.

## Ground rules

- **Not negotiable per ticket.** Per team it is, and only in a retro. One exception
  "because it's urgent" turns a definition into a suggestion.
- **Structurally missed means the DoR is wrong, not the team.** Lower it deliberately
  instead of silently ignoring it.
- **Evaluate after three months**, on one number: how often work came back because the
  ticket was unclear. If the DoR does not move that, it goes.
