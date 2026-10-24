# Playbook — recipes for the common PO operations

Create · Gate check · WIP · Prioritize · Merge check · Close · Queue ops · Audit · Sweep ·
Dedupe · Verify-and-close · Product-name rewrite · Sequencing · Sprint pull · Rework.
Tool-agnostic sequences; the exact calls, payload shapes, and traps are in the adapter
([adapters/vikunja.md](adapters/vikunja.md) / [adapters/clickup.md](adapters/clickup.md)) —
read it before the first write of a session. Board gates and ids: the Board contract.

## Create a ticket end-to-end

1. Title per the convention — `area: what changes`. Given a product name, ask (or
   research) what must be true afterwards; write *that*.
2. Create with description = at minimum the Problem section, at the board's
   caught/intake stage, with the contract's intake taxonomy (theme/area, impact).
3. Report the ticket URL/id and which gate criteria it does not yet meet.

Intake is deliberately cheap — don't refine at intake unless asked. **Search before
create** (open + recently finished titles): duplicates are real, and the dedupe pool is
the whole board, not your memory.

## Gate check before a status move

1. Fetch the ticket with its description; save the body to a file.
2. `python3 scripts/ticket_lint.py body.md --gate ready|agent-ready --title "..."`.
   On a status-ladder board also check the target status's row in the contract's
   per-status table (fields, estimate, sprint membership). Gates are cumulative — a
   later stage includes the earlier ones.
3. Met → move. Moving into a started stage checks WIP first.
4. Unmet, ≤ 10 min → fix, then move (ten-minute rule). More → leave it, comment naming
   exactly what's missing, tell the user.

## Enforce the WIP limit

1. Count items in the started stage(s); compare with the contract cap.
2. At the cap → refuse the move; report current occupants **sorted by Work Item Age**
   and name the oldest as the one to finish first.
3. Already over → that is the finding. Propose a specific set to push back (oldest,
   least progressed first) and **ask before moving them**.
4. Agent work: also check the review column's own cap — review full means "clear the
   review queue", not "start more" ([agents.md](agents.md)).

## Prioritize

- **P0 = live risk or cheap correctness now.** Six simultaneous P0s means no P0.
  Priority is an order, not a feeling.
- Sequence by **cost-of-delay class** (expedite / fixed-date / standard / intangible),
  shortest-job-first within a class. RICE/WSJF structure arguments, never auto-rank —
  summed ordinal scores are fake math; confidence claims need an evidence tier
  (opinion / anecdote / data / experiment).
- A ticket never ranks above one that blocks it. Small unblocked tickets are pick-up bait.
- Bands, not a stack-ranked backlog — that precision is fake and rots. **Queue time is
  the lever**: an item aging past the SLE wants a decision (split, swarm, unblock,
  drop), not another day of ageing.
- Keep the backlog small and honest — hold fewer tickets rather than pad toward a target.

## Merge check (is this PR mergeable?)

1. Fetch the PR head into the up-to-date checkout; run `python3 scripts/merge_check.py
   --base origin/<target> --head pr-<n>` with the ticket's Protected areas and the
   contract's trailer.
2. Read the forge for the MANUAL lines (checks on the landing tree, approval on the
   current head, blocking threads) and name any trap the green badge rests on.
3. Review intent and scope; verdict per [merge.md](merge.md). Not mergeable → one comment
   naming each unmet line, back to the author. Never merge an agent's PR on its say-so.

## Close with evidence

1. Check the DoD line by line against reality, not the ticket's optimism — every change
   for the ticket merged through the DoM, not just "a PR exists".
2. Evidence comment: what shipped (commit/MR/PR), the Verification output, where it
   runs, the rollback path, the regression signal (alert/dashboard/check — or why none).
3. A DoD line missing without a stated reason → not done; say which line and stop.
4. Only then the finished status. Agent-executed work goes through review first —
   agents never complete their own tickets. Incidents follow the board's incident
   procedure (the contract points at it).

## Pick-up queue operations (where the contract keeps one)

The queue is the total order for what gets picked up next: every do-next holder + a
bounded next-up tail (≤ 2× the do-next cap). Emit/insert per the adapter's mechanism
(on Vikunja: a section in the project description — round-trip carefully, see adapter).
Rules: insert where it fits, never blind-append · never above a blocker · every entry
is an open ticket · refresh when membership changes, a queue ticket closes, or a
refined ticket outranks an entry.

**do-next rebalance**: drop now-blocked/stale holders → add highest-leverage unblocked
up to the cap → re-emit the queue → say what changed and why.

## Board-health audit

1. Fetch the whole board — **page until exhausted; one call is not the board** (both
   adapters lie differently about pagination).
2. `python3 scripts/flow_metrics.py --tasks *.json --wip-limit 3` (raw ClickUp
   payloads) or `--items board.json` (normalized, any tracker) for metrics + the
   mechanical checks ([flow.md](flow.md)).
3. Check the board invariants the script can't see. The full set:
   - started ≤ WIP cap · review column ≤ its cap
   - every open ticket carries the contract's taxonomy, and exactly **one** theme/area
     tag — two usually means two tickets
   - Ready tickets meet the DoR kernel · agent-ready tickets meet the full agent gate
   - each Problem evidenced · criteria binary · spikes have decider + timebox
   - no title that is only a product name · P0 count small and defensible
   - waiting items name what they wait on · dependencies exist as relations, not prose
   - queue entries are open, in order, none above its blocker
   - nothing finished without its DoD evidence · completion counts use the
     *agreement's* finished status only
   - every open PR references one ticket · no ticket with two open PRs · no PR in
     review past the review SLE (abandoned review and duplicates are the two biggest
     killers of agent PRs) · every PR closed unmerged carries a reason
4. Report: **counts → violations → the three things worth doing about it.** Propose;
   don't mass-mutate. Ask before any bulk write.

## Backlog sweep / top-up (periodic inventory)

1. **Ground truth first** — the contract's commands (`git log` since last sweep, the
   repo's own verification scripts, live read-only checks). Don't trust ticket text.
2. **Read the whole board**, open + recently finished — that's the dedupe pool.
3. Optionally fan out read-only audit agents per dimension, each briefed with the
   ALREADY-DONE list so they only return open gaps; they over-report — verify before
   creating anything.
4. **Reconcile**: shipped → close with evidence · stale premise → verify-and-close ·
   genuinely new → create at intake, deduped against ALL open+recent titles · re-tag
   honestly · rebalance do-next.
5. **Staleness policy — distinguish ticket classes.** Speculative internal ideas
   untouched ~12 months: propose bulk close with "closed in backlog sweep — reopen if
   still valuable" (important ideas come back). **User-/customer-reported bugs are
   never closed for age alone** — triage to an explicit terminal state (won't-fix /
   cannot-reproduce / duplicate) with a human-readable reason, or leave them.
6. **Report** counts, the new priorities/do-next set, and findings that belong in docs
   rather than tickets. A sweep *plans*; implementing is separate work.

## Dedupe

Near-duplicates (same outcome, different words): keep the better-refined one, comment
on the loser pointing at the survivor **by exact title**, then close/reject it with the
reason. Ask before closing anything.

## Stale-premise verify-and-close

Rewrite: Problem becomes "Premise stale — shipped in <commit/date>; remaining work =
verify"; criteria become the verification checks. Cheap to run now → run and close with
evidence; else leave it Ready as a quick win.

## Rewrite a product-name ticket

New title `area: what changes`; keep the product name in the Problem so search still
finds it. Rename **and** leave a comment saying it was renamed and why — colleagues
reference tickets by title. Three things in there → split ([refine.md](refine.md)).

## Sequencing and code linkage

Dependencies as first-class relations (adapter call), never prose; a readable echo
under Context is fine. A ticket never ranks above its blocker. Commits carry the
contract's ticket trailer; the MR/PR references the ticket; the MR link lands under
Context — that is where the review gate looks for it.

## Sprint/iteration pull (separate from refinement)

Sprint-list membership, ordering numbers, and sprint-only estimate fields are
**planning**, set at the pull on tickets that already meet the DoR — never DoR gates
themselves. (Estimation labels that gate agent-ready — `effort/` `time/`
`uncertainty/` — are the exception: those are set at refinement, [refine.md](refine.md).)
Not every board runs sprints: where none exists, note the gap instead of blocking the
ticket, and flag that the team should decide. Iteration boundaries are rhythm, not
commitment — roll unfinished work forward without ceremony.

## Rework (bounced from test/review/acceptance)

Read the rejection feedback and any bounce counters first → classify *unclear ticket*
(DoR-repairable: feed feedback back in as reproduction/criteria) vs *defect in the work*
(not a refinement problem; a PR bounced at the merge gate names the DoM lines it
missed) → **never reset the counters** (they are the DoR-effectiveness measurement) →
report the two classes separately; that split is the DoR metric.
