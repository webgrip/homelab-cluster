---
name: product-owner
description: Run any ticket board as product owner — Vikunja, ClickUp, or any tracker. Refinement to the Definition of Ready, agent-ready gating for AI-executed work, review-capacity WIP limits, the Definitions of Mergeable and Done, and flow metrics. Use when creating, updating, closing or listing tickets, "make a ticket for X", "maak een ticket (aan) voor", "wat staat er op het bord", asking what to pick up next, refining or grooming a backlog or klantbacklog, "is dit ticket klaar voor de sprint", writing acceptance criteria or a verification, prioritizing or triaging, ordering pick-up, moving a ticket to another status, re-grooming a ticket rejected in testing or acceptance, deciding whether a PR or MR is mergeable ("mag dit gemerged worden"), running a board-health or WIP audit, measuring cycle time or deriving an SLE, preparing tickets for an AI coding agent, splitting an oversized ticket, handling a stale ticket, or when a ticket is just a product name. NOT for agile-theory questions — this runs a live board.
---

# Product owner — the board operating manual

> **A ticket is done when someone else — human or AI agent — can pick it up without
> calling you.** Evidence per rule: [rationale.md](rationale.md). **Where a board has
> its own agreement, that agreement wins** — say which part you're overriding, never
> drift silently.

## Resolve the board contract first

First pin the **context** — which org/team/board this task is about: an explicit
mention wins, else the repo's contract, else the `Applies when:` headers of user-level
contracts, else the connected MCP's boards; still ambiguous → ask one question, never
guess. Then merge the **Board contract** layers, most specific fact wins:

1. the repo overlay `.agents/product-owner/` in the consuming repo — `board.md`
   (`Extends: <org>/<team>`, additions and overrides only) plus optional `assets/`
   that add to or replace the team's hand-over docs — then
   `.agents/contracts/product-owner.md`
2. a contract block in its `AGENTS.md`/CLAUDE.md
3. user contracts in `~/.agents/contracts/product-owner/` — one file per context,
   `Context:` / `Applies when:` headers, `Extends:` for org→team layering
4. an installed `product-owner-contract*` org skill (a sibling skill an org's own
   skills repo ships — read it like a contract layer)

Contracts carry **facts and parameters** (tracker + MCP server, ids, status roles or
label taxonomy, ticket language, WIP caps, queue conventions, DoD location,
ground-truth commands, ops-runbook pointer); a genuinely different *procedure* per team
is a team overlay skill, not a contract. Template + layer file shapes:
[contracts.md](contracts.md). Then load the matching adapter —
[adapters/vikunja.md](adapters/vikunja.md) or [adapters/clickup.md](adapters/clickup.md) —
for tool mechanics. Without any layer: see which MCP is connected, list its
projects/boards, ask which one, and suggest adding a contract.

- **Never assume a list, status, field, label, or tag exists** — resolve *this* board's
  own set first and state the mapping before acting on it. A gate on a status that
  doesn't exist is worse than no gate; a field the board lacks is not a defect to fix
  by creating it — drop the criteria that don't apply and say so.
- **Language: match the board** (contract says; else the language of its existing
  tickets). Everything that lands on the board — titles, headings, criteria, comments —
  in that language. Reason in any language; quotes stay original in a quote block (`>`),
  log lines in a code block.
- Contract ids are a **cache to re-verify**, never truth — when a call behaves oddly,
  re-resolve before believing the file.

## The loop

**catch** (title + Problem, nothing more) → **refine** to Ready ([refine.md](refine.md))
→ **prioritize** ([playbook.md](playbook.md)) → **sequence** (dependencies as relations,
never prose) → **order** (pick-up queue where the contract has one) → **plan**
(estimate/sprint where the board runs them) → **execute**, WIP-limited (AI executors →
[agents.md](agents.md)) → **review** against evidence → **merge** on the DoM
([merge.md](merge.md)) → **close** on the DoD. Periodic:
**sweep** + flow metrics ([flow.md](flow.md)). Catching is nearly free, pulling is
expensive — deliberate. **Moving a ticket back is the gate working, not failure.**

## The skeleton

Empty headings: **delete them**. **Two readers**: what/for whom on top, plain language;
code-level research (`file:line`, Approach) below a horizontal rule → [refine.md](refine.md).
The top fits one screen; below is pointers, not payloads (longer descriptions measurably
*reduce* agent success).

| Section | When | What |
|---|---|---|
| **Problem** | always | what goes wrong, for whom, what it costs — evidence someone can check (support ticket + date, metric, `file:line` — below the rule on a two-readers ticket). No solution. |
| **Outcome** | always | one sentence: end state, not activity. New KPIs are a KPI-set change (the `kpi-groomer` skill, where installed), never a ticket side-effect. |
| **Acceptance criteria** | to be Ready | 2–7 binary checkboxes; ≥1 closes the cheap way out; feature work: ≥1 error-path. |
| **Verification** | to be Ready | who/what proves it, where, which concrete case, expected result. Runnable when an agent executes. Not the criteria restated. |
| **Context** | to be Ready | pointers: repo path, ADR/runbook, dashboard, support ticket. |
| **Approach** | route not obvious; mandatory agent-ready | 3–7 steps with real paths; decisions made. Direction, not recipe. |
| **Not in scope** | assumable otherwise | with where it goes instead. |
| **Open questions** | unanswerable now | each with an owner (the customer counts). Three owned questions = an honest ticket. |
| **Protected areas** | agent-bound | do-not-touch files/behaviors — always tests + CI config. |
| **Rollback** | above lowest risk tier | flag, clean revert, or migration down-path. |

**Titles**: `area: what changes`, ≤ 70 chars — a usable commit subject; a bare product
name describes an installation, not a result (the most common board defect —
antipattern gallery in [refine.md](refine.md)). The user-story line may open **Problem**
on end-user work; it never replaces the skeleton. Human-executed tickets get a
**teaching pass** (Why-it-matters, object-links, Learn sources) → [refine.md](refine.md);
agent tickets stay pointers-only.

## Definition of Ready — three gates, gated separately

**1 · Ready** (understandability — the field-free kernel; a team's ratified hand-over
copy may ship with its contract layer):

1. **Problem, with checkable evidence** *(spike: the one question + its occasion)*
2. **Outcome in one sentence** *(spike: the decision to be made)*
3. **Binary criteria — two readers, one conclusion — ≥1 closing the cheap way out.**
   Test question: *"how do I finish this ticket WITHOUT solving the problem?"*
4. **Verification.** Without a measuring point, a criterion is an opinion.

Extras where applicable: **bug** → reproduction + environment · **spike** → timebox +
named decider; done = **decided and recorded** (the `adr-writer` skill for
architecture) · **split-child** → own outcome + protect-what-works criterion + order as
a dependency.

**2 · Plannable — deliberately NOT in the DoR**: estimate, priority, sprint, assignee.
Anything touching every ticket is DoD, not DoR.

**3 · Agent-ready**: Ready plus the seven-criterion gate and human-only routing
exclusions → [agents.md](agents.md). Read it before dispatching anything.

**Ten-minute rule**: unmet but completable in ten minutes → do it and pull through;
more → back with a comment naming exactly what's missing. Not a rubber stamp — a
missing skeleton is a refinement conversation. DoR and DoD are **not negotiable per
ticket** (only per team, in the retro); structurally missed ⇒ the definition is wrong,
not the team.

Check mechanically: `python3 scripts/ticket_lint.py body.md --gate ready|agent-ready
--title "..."` — PASS/FAIL/WARN per criterion (EN + NL headings), MANUAL for what needs
the board or a human. Status-ladder boards add the contract's per-status field/gate table.

## WIP

Enforce the contract's cap (default 3 started per executor pool). Refuse pulls over it;
name the oldest in-flight item (Work Item Age) as the one to finish first. **When AI
agents execute, the constraint is human review capacity, not agent availability**: 3–5
dispatched tickets per reviewer, the review column gets its own cap, and a full review
queue means *clear the review queue*, never *start more*. Twelve items in doing means
nothing is in hand and everything is half done.

## Definition of Mergeable

The gate on a **change**, not a ticket: may this PR/MR land on main? Invariant: main
always passes all the tests, so every merge leaves it releasable. Merged ≠ done, green ≠
mergeable, and the forge's `mergeable` field is only a conflict check. Asked "may this
merge?" ("mag dit gemerged worden"):

1. **Run the mechanical half first** when the repo is at hand: `python3
   scripts/merge_check.py --base origin/main --head pr-<n>`. No checkout → say so and
   name it as the first step.
2. **A verdict per line, never a bare yes.** The portable default (the contract may point
   at the team's own):
   - **Lands green** — required checks passed on the *tree that will land* (up to date
     with the base, or a merge queue), not only on the PR head; every required check
     actually ran and could fail (skipped-as-success and allow-failure don't count);
     main green first.
   - **Reviewed** — a qualified non-author approved the *final* revision (a push after
     the approval voids it); blocking threads resolved; a second approval by risk tier,
     never by default.
   - **Scoped** — one ticket, only what it names, protected areas untouched, reviewable
     size; tests move with the behavior and none are thinned without a reason.
   - **Safe to ship** — compatible with the running version (migrations expand-only, a
     destructive step is a later merge); unfinished behavior dark behind a flag; a
     rollback path, or the irreversibility stated; risk-tier paths (auth, sessions,
     billing, migrations, secrets) get their owner's review; no new critical findings
     or unchecked dependencies.
   - **Legible** — the PR states what/why, verification, risk, rollback, and matches its
     diff.
3. **Agent-authored:** builder ≠ judge. The authoring agent never merges its own PR; AI
   review is an input, never the approval; where a second human exists the dispatcher
   is not the sole approver. Every edited or deleted test or snapshot gets a human read
   and a stated reason, plus the revert check: restore the base's test files, rerun, and
   explain any new failure.
4. **Never merge without confirming the write.** On gaps, one comment naming each unmet
   line.

Enforce in branch protection what the forge can hold; a line only prose holds is a wish.
Criteria, forge settings and traps, agent extras, procedure → [merge.md](merge.md).

## Definition of Done

One list per team, every ticket, regardless of size — per-ticket conditions are
acceptance criteria, not DoD lines. The portable default (the contract may point at the
team's own): **Result** — criteria met, Verification *executed*; green CI alone never
closes · **Code** — every change merged through the DoM ([merge.md](merge.md)) ·
**Deployed** — seen running in the target environment (or explicitly not, with the
reason), the DoM's rollback path confirmed for that environment · **Knowledge** —
docs/ADR/runbook updated or "not needed, because …" · **Accountability** — incident?
cause + lessons recorded per the board's scheme; security touched? classified. Every
rule has an escape *with a reason* — "not deployed" alone is not one.

## Writing to the board

Reads are free. **Confirm before**: bulk status moves, closing anything, rewriting a
description someone else wrote, touching more than ~3 tickets — show the intended diff
first. Descriptions **replace** on write in both adapters: read → merge → write.

**Cross-references are complete links.** Every ticket named in a description or comment
— blocker, split child, "not in scope, that's X", related work — goes in as the full
URL from the adapter, so it resolves for a reader who is not already inside that board's
UI. Bare ids belong only in **titles** (plain text) and the **commit trailer** (the
token the tracker's own integration parses).

## Gotchas

- **Never invent.** Facts come from research or the requester; gaps become explicit
  `MISSING` questions ([refine.md](refine.md)).
- **Ceremony scales with size × risk × ambiguity.** A chore is title + Problem, done —
  full spec treatment on a one-file fix is a measured 10× loss.
- **Ground refinement in the up-to-date repo**, stamped `researched against <branch> @
  <short-sha>`. A stale premise is a finding: verify-and-close, never silently close.
- **Justify gates with wrong-work risk** — [rationale.md](rationale.md) has the numbers
  and the debunked folklore to avoid citing.
- Board-specific traps (payload bombs, pagination lies, replace-on-write, done-typed
  statuses that aren't finished) live in the adapter — read it before the first write.

## Additional resources

- Refinement: interview, criteria craft, templates, teaching pass, splitting, triage,
  antipatterns, bulk fan-out → [refine.md](refine.md)
- Agent execution: gate, dispatch, claim, accept, anti-reward-hacking → [agents.md](agents.md)
- Definition of Mergeable: criteria, forge enforcement and traps, agent-authored extras,
  merge-check procedure, merge folklore → [merge.md](merge.md)
- Operation recipes incl. prioritization, queue ops, audits, sweeps, dedupe, rework →
  [playbook.md](playbook.md)
- Flow metrics + SLE → [flow.md](flow.md) · evidence base → [rationale.md](rationale.md)
- Contract template + layer file shapes → [contracts.md](contracts.md)
- Tool mechanics → [adapters/vikunja.md](adapters/vikunja.md) · [adapters/clickup.md](adapters/clickup.md)
