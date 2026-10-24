# Agent execution — running a board where AI agents do the work

The ticket body is the executing agent's prompt: it reads title, body, and all comments,
decomposes into a checklist, and stops when its check passes. **Agents almost never ask
clarifying questions unprompted — they guess.** As underspecification rises, safe
success drops ~68%→~9% while wrong-target actions rise ~10%→~75% — every ambiguity the
refinement leaves is a probable wrong action, not a question you'll get asked. Burn
ambiguity down *before* dispatch. (Sources: [rationale.md](rationale.md).)

## The agent-ready gate

Grants the contract's dispatch marker (e.g. an `agent-ready` label). Everything in
Ready, plus:

1. **Approach with real repo paths and zero open design choices** — be opinionated
   ("add a composite index", not "improve performance"); the PO resolves *which
   approach* during refinement. File/module hints multiply success.
2. **A verification the agent can run itself** — a command producing pass/fail it can
   iterate against. A human-only check means a human stays in the loop; say so instead.
3. **Protected areas stated** — do-not-touch files and behaviors, *always including
   test files and CI config* (the classic gaming surface).
4. **Escalation point named** — what needs a human: a decision, a credential, a
   production touch.
5. **Sized ≤ roughly one junior-engineer day** (contract terms: effort ≤ M, uncertainty
   ≤ med). Uncertainty high ⇒ spike or de-risk step first, never agent-ready.
6. **Self-contained** — everything needed is in or linked from the ticket. Unresolved
   external dependencies (API access, environment setup, third-party config) measurably
   sink agent PRs: split them out as sequenced prerequisite tickets.
7. **Concise** — the functional half one screen, the technical half pointers
   (`file:line`, not pasted code or logs). Body length is the strongest negative
   predictor of merge; density beats completeness-by-volume.

**Routing — refuse the gate regardless of ticket quality for:** security-critical
paths, auth/billing/data-deletion/migrations (human-review-mandatory risk tier),
cross-repo changes, and anything with an unresolved design question. Good default agent
fare: bug fixes with repro, test coverage, docs, accessibility passes, small
well-bounded debt, migrations with a proven per-item recipe. For recurring classes,
keep a reusable ticket template so one refinement amortizes across the fleet.

Check mechanically: `python3 scripts/ticket_lint.py body.md --gate agent-ready`.

## Dispatch

The WIP rule (capacity anchored on human review, the caps, "clear the review queue") is
in SKILL.md's WIP section — it binds here hardest, since agent availability is never the
constraint (2026 telemetry: task throughput +34% while review time +441%). Dispatch
mechanics:

- Dispatch from the top of the pick-up queue: topmost eligible entry (dispatch marker
  present, unclaimed, unblocked). Skip-and-report dead or claimed entries; don't reorder.
- One ticket = one agent run = one branch/PR.
- Give the review column its own age watch: oldest-awaiting-review is the age metric
  that matters most here ([flow.md](flow.md)).

## Claim, visibility, ownership

- **The human stays the accountable owner** of a delegated ticket — the agent is a
  delegate, never the sole assignee. Every agent-executed ticket keeps a named human
  who answers for the outcome.
- **Claim**: the agent marks the claim per the contract (e.g. `agent/<name>` label) +
  a comment with its session/run id. Skip if a claim comment exists.
- **Visibility**: progress comments at milestones; blocking questions as explicit
  comments (never silent guessing); a silent claimed ticket past a staleness threshold
  is a board-health finding.
- **Attribution**: commits carry the contract's ticket trailer; the PR references the
  ticket. Agent-authored work is identifiable as such.

## Mid-flight scope is frozen

Once an agent PR exists, corrections go as **PR comments** (the agent reacts there);
**new scope becomes a new ticket** — never edit the in-flight ticket's criteria and
never bolt additions onto the run. Mid-task scope change is a documented top cause of
agent failure. Re-refining a ticket means recalling it first.

## Finish → review → accept

**Finish (agent side)**: post the evidence comment — the *full-kit review packet*: what
changed and why (commit/PR links) · the ticket's own Verification output · risk areas ·
known limitations · the regression signal (alert/dashboard/scheduled check, or why none
applies). Then mark for review per the contract. **Agents never complete their own
tickets, and never approve, merge, or mark ready their own PRs.**

**Accept (PO/human side)**:

1. The PR passes the **DoM** with its agent-authored extras ([merge.md](merge.md)):
   approver outside the agent's session, AI review as input only, every test-touching
   hunk read and reasoned. Mechanical half: `python3 scripts/merge_check.py --base
   origin/main --head pr-<n> --protected '<glob>'` — agent authorship is auto-detected
   and tightens the test and gate lines to FAIL.
2. **Fresh-context review against intent and scope**, not just correctness: does the
   diff do what the *Problem* needed, and does it touch **nothing outside the ticket's
   named files**? Then evidence against the **DoD** — verification actually executed
   (not promised, not just green CI), deployed-and-seen or reasoned.
3. Where feasible, run a **held-out check** the agent never saw. Reward hacking is
   measured, not hypothetical (hard-coded expected outputs, edited tests); detectors
   catch only ~63% of hack categories, so green-on-visible-checks is necessary, never
   sufficient.
4. Gaps → return with a comment naming what's missing (back to the executor); met →
   complete, drop the queue line.

## Machine-authored tickets

Tickets created by agents (incident bots, PRD decomposition, sweep agents) enter as
**draft/triage — never directly agent-ready**. Same DoR gate as human tickets, plus a
human prioritization pass. AI-slop economics: every criterion that maps to an automated
check lets red CI bounce work back with zero human minutes — no human review until
automated gates are green.

## Measure the delegation, not the vibes

Perceived agent speed is unreliable (a controlled trial measured experienced devs 19%
*slower* while believing they were 20% faster). Track per ticket-class: merge/acceptance
rate, bounce-backs, reopen count, cycle time vs human baseline. Expand delegation only
in classes with demonstrated success; pull classes with high rejection back to
human-first. Pair every throughput number with its stability guardrail
([flow.md](flow.md)) — rising throughput with rising rework is net-negative, not a win.
**Task type predicts merge more than the agent does** (docs/CI/chores merge far more
often than performance or test work) — compare classes, not vendors. A merge rate is not
an agent-quality score on its own: only about a third of rejected agent PRs are clear
agent failures; the rest are duplicates, superseded work, abandoned reviews — or carry
no reason at all, which is why every PR closed unmerged gets one. Watch **approvals without a single review comment** on agent
PRs: approval rates rising while comments fall is habituation, not earned trust.
