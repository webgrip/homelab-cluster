# Ticket template — webgrip default team

The fill-in skeleton behind the [Definition of Ready](definition-of-ready.md). Filled in =
DoR-compliant; what "filled in" looks like is in [golden-tickets.md](golden-tickets.md).

Four rules up front:

- **Everything in English.** A Dutch request still yields an English ticket. Quotes stay
  in their original language, in a quote block (`>`); log lines in a code block.
- **Two readers, two halves.** On top the **functional half** for the product owner, the
  requester and whoever accepts: what changes, for whom, and how you see it. Below a rule
  the **technical write-up** for the developer and the agent: how and where. A reader who
  stops at the rule can discuss, plan and accept the ticket.
- **Headings that stay empty: delete them.** An empty heading is noise; a deleted one is a
  choice. The TL;DR is always there. No code research done? Then no rule and no technical
  write-up either.
- **The title is the summary**: `<area>: <what changes>`, ≤ 70 characters, usable as a
  commit subject. No product name on its own, no complaint, no class name.

Labels at grooming: one `theme/*`, one `repo/*`, one `kind/*`, one `value/*`, `impact/*`.
The estimation trio (`effort/` `time/` `uncertainty/`) is set at refinement; `do-next` and
the pick-up queue are planning ([board.md](../board.md)).

---

## Base (change / bug / chore)

```markdown
**Source:** <occasion> of <date>, <link>: "<the requester's or alert's words, literally>"

## TL;DR
<Two to four sentences in the reader's language: who runs into what, where,
and what it costs.>
- **Who notices:** <which people or systems>
- **Where:** <service, page or flow as people call it>
- **What happens now:** <current behaviour>
- **What we want:** <behaviour afterwards>

## Reproduction
1. <Step, as the reporter took it>
2. <Step> → expected <X>, got <Y>

## Environment
<Where (cluster, namespace, site), since when, how often.>

## Outcome
<One sentence: the end state, not the activity.>

## Acceptance criteria
- [ ] <What someone observes: which screen, alert, run or endpoint, which action,
      what appears. Binary: two readers, one conclusion.>
- [ ] <If <failure case>, then <what is observed>.>
- [ ] <The criterion that closes the cheap way out. Ask: "how do I finish this
      ticket without solving the problem?" The answer is this criterion.>

## Verification
<Who proves what, in which environment, with which concrete case and expected
result. GitOps work names the reconciled revision and the running digest, not
the merge. Technical steps → "(see technical write-up)".>

## Not in scope
- <What someone would reasonably also expect, and where it goes instead.>

## Open questions
- <Question nobody can answer now> — owner: <name>

---

# Technical write-up

> For the developer and the agent that picks this up. You do not need to read this to
> understand or discuss the ticket.

## Technical context
<The mechanism, with evidence another person can check: `path/file.ext:line`,
manifests, commits, earlier tickets, the PR. A stale assumption is a finding.>

## Approach
1. <Direction with real paths and the decisions taken. Not a recipe.>

## Technical verification
<Commands that prove the criteria: `flux get kustomization <name>`, a query, a test.>

## Protected areas
<Agent-bound only: what stays untouched — always tests and CI config.>

## Rollback
<Above the lowest risk tier: revert commit, feature flag, or migration down-path.>

> Researched against `<branch>` @ `<short sha>`.
```

Always leave a **blank line above and below the rule** (`---`). Text directly above it turns
that line into a heading and the rule disappears. Put file names in backticks.

Drop **Reproduction** and **Environment** on anything that is not a bug.

## The functional half

The half everybody reads. The product owner decides on it, the requester recognises their
problem in it, whoever accepts tests against it. It is complete without the technical
write-up.

**The test per sentence: would it change if the implementation changed?** Yes → it belongs
below the rule. That removes class names, file paths, Helm keys, endpoints, flags and
disguised solutions ("raise the retention to 30d").

- **Sentences of at most 15 to 20 words.** Two thoughts are two sentences.
- **Active, with verbs**: "the job reports success", not "success reporting takes place".
- **The names people see**: the service, dashboard or page as it is labelled.
- **Most important first**, in the TL;DR and in every bullet.

**Acceptance criteria are behaviour, not code.** If a criterion must secure something
technical, write its observable effect ("the alert fires within five minutes"). The
Verification says where to read it off; the Technical verification says how.

**Not in scope** is what someone would reasonably expect. "Must not break" is not out of
scope but a criterion.

## Variant: spike / choice

A spike is done when it is **decided**, not when it is researched. The **Question** is the
TL;DR here: one sentence in domain language, no separate heading above it.

```markdown
**Source:** <occasion> of <date>, <link>

## Question
<The one question. Two questions is two tickets.>

## Timebox
<E.g. 1 day. Running over means it is implementation, not research.>

## What we decide on
<The 3–5 criteria the options are compared on: operating cost, risk, lock-in,
fits GitOps, …>

## Who decides
<Name>, by <moment>.

## Acceptance criteria
- [ ] Every option is scored on the criteria above
- [ ] It is decided, and the decision is recorded with its trade-off in <ADR / comment>
```

## When splitting

Title per child: `<area>: <subject> - Part n/m - <part outcome>`. Each child gets its own
Outcome (the base skeleton), a criterion that protects what already works, and the order as
a `precedes`/`blocked` relation on the previous part. The parent is an epic
(`Epic: <subject>`, label `meta`, `subtask` relations) and holds the overall outcome without
criteria of its own.

---

**The test that sums it up:** write the ticket for the colleague — or the agent — that picks
it up in three months while you are away. If they can start without calling you, it is
right.
