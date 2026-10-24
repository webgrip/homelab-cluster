# Default team — the webgrip Vikunja boards

Stages · Pull criteria · Labels · Epics · Queue · Invariants. Applies to every webgrip
Vikunja project unless a repo overlay or a repo contract says otherwise. The craft itself is
the `product-owner` skill (its refine.md, playbook.md and agents.md); this file holds the
facts and house rules.

**English board.** Titles, headings, criteria, comments, splits. A Dutch request still yields
an English ticket; quotes stay original in a quote block (`>`), log lines in a code block.

**Read [assets/definition-of-ready.md](assets/definition-of-ready.md) before gating a ticket
and [assets/ticket-template.md](assets/ticket-template.md) before writing one** — they are the
ratified text. Worked examples: [assets/golden-tickets.md](assets/golden-tickets.md) — **form
is the norm, content is illustrative**. Closing: [assets/definition-of-done.md](assets/definition-of-done.md).

## Board facts (a cache to re-verify, never truth)

- Tracker: Vikunja · MCP server `vikunja` (LAN/VPN only — off-VPN it fails to connect; say
  so instead of retrying) · instance list cap 250 per page, and `tasks_list` returns one
  page: count before concluding you have them all
- Ticket prefix and commit trailer: `VIK-<id>`; bare task URLs autolink in Forgejo
- Project ids live in each repo's contract, not here. No repo at hand → `projects_list`
  and ask which one; never guess a project
- Labels are **instance-wide**: a new value costs every board

## Stages — derived from labels, never stored separately

| Stage | Derived from | Meaning |
|---|---|---|
| Backlog | `needs-refinement`, or no lifecycle label | caught |
| To Do | `ready` (and optionally `agent-ready`) | pullable |
| Doing | `agent/<name>` claim, or an assignee who started | started — counts against WIP |
| Reviewing | `review` | built; a human accepts against the DoD |
| Done | completed | finished — the only stage completion counts use |

Kanban buckets, where a project uses them, mirror these stages; labels are authoritative,
buckets are display. Moving a ticket back a stage is the gate working, not failure.

## Pull criteria per stage

Gates are cumulative. Check the content half with the product-owner skill's
`ticket_lint.py --gate ready` (or `--gate agent-ready`); check the label half against this
table from the task.

| Into | Must be true | Who |
|---|---|---|
| Backlog | Title per the convention + a Source line or TL;DR. Nothing else. | Anyone |
| Refining (still `needs-refinement`) | Outcome · one `theme/*` · one `repo/*` · one `kind/*` · one `value/*` · `impact/*` | Writer |
| To Do (`ready`) | The DoR's four rules · bug: reproduction + environment · spike: timebox + decider · `effort/` `time/` `uncertainty/` all set | Refinement |
| `agent-ready` | Ready + the agent-ready gate (agents.md) · `uncertainty/high` never qualifies — spike first | Refinement |
| Doing | WIP below the cap · claim placed (`agent/<name>` or assignee) | Executor |
| Reviewing (`review`) | PR link in a comment or under Technical context · executor's evidence comment | Executor |
| Done | The Definition of Done, in full, as an evidence comment | Executor + reviewer |

## Labels — the dimensions are contract, the values are board state

Enumerate with `labels_list` before applying any. If no existing value fits, that is a
taxonomy decision for a human — raise it; **never create a label to unblock a write.**

| Dimension | Values | When |
|---|---|---|
| `theme/<kebab>` | whatever the board defines | exactly one per ticket |
| `repo/<repo>` | the repo the work lands in | exactly one per ticket; routes agents |
| `kind/` | `change` · `bug` · `spike` · `chore` | every ticket at refining — a spike is a kind, never a `SPIKE:` title prefix |
| `value/` | `saves-time` · `reduces-risk` · `unblocks` · `compliance` | every ticket at refining — prioritize on value, not volume |
| `impact/` | `H` · `M` · `L` | every ticket at refining |
| `effort/` · `time/` · `uncertainty/` | `S M L` · `hours days weeks` · `low med high` | at refinement, gate `ready`; effort L names its first slice or is split |
| lifecycle | `needs-refinement` · `ready` · `agent-ready` · `review` | the stage ladder above |
| `do-next` | — | at most 10 per project, all in the pick-up queue |
| `agent/<name>` | — | an agent's claim |
| `meta` | — | epics only |

`kind/*` and `value/*` must exist on the instance before they gate anything. Missing → name
the kind and value in the ticket's TL;DR, flag the gap once, and carry on.

## Epics

`Epic: <subject>` titles, label `meta`, children wired with `subtask` relations (parent →
child, one parent per child). An epic keeps `theme/*` + `impact/*`, holds the overall outcome,
has no criteria of its own, is exempt from estimation and lifecycle labels, is never
agent-workable, and closes only when every child closes.

## Pick-up queue

Each project's **description** carries a `Pick-up queue`: an ordered list
(`VIK-<id> — title`), top = picked up first, covering every `do-next` holder plus a short
next-up tail. Executors take the topmost eligible entry; the PO inserts new tickets where
they fit and drops entries on close. Raw drag order in the stock UI is not the queue.

## WIP

Doing ≤ 3 per executor pool · agent tickets in flight ≤ 3–5 per human reviewer · a full
Reviewing column means clear review first, never start more.

## What NOT to groom

- **Fixture projects** a repo contract names as such (test task sources, benchmark boards)
  — they are inputs to tooling, not backlogs.
- **Epics' criteria** — the outcome lives on the epic, the criteria on the children.
- Anything another session marks as in progress: leave it.

When in doubt, skip and report the doubt.

## House parameters on the generic pass

- **Ground in the project's checkout** on the development branch, else `main`; stamp
  `Researched against <branch> @ <short sha>`. GitOps premises are checked against the
  reconciled cluster state too, not only the repo.
- **Splits** follow `<area>: <subject> - Part n/m - <part outcome>`; the epic keeps the
  outcome, children the criteria, order as relations.
- **Secrets never land on a ticket** — name the vault path or the level, never the value.
- Requester material gets worked in, not parked: files attached, the essence quoted with its
  date as checkable evidence.

## Board invariants (audit recipe: the product-owner playbook)

Doing ≤ 3 · every open ticket exactly one `theme/*` and one `repo/*` · refining+ has
`kind/*` + `value/*` + `impact/*` · `ready`+ has the estimation trio, binary criteria and a
Verification · spike has timebox + decider · bug has reproduction + environment · no
`uncertainty/high` with `agent-ready` · `do-next` ≤ 10 and all in the queue · no product-name
titles · dependencies as relations, not prose · nothing completed without a DoD evidence
comment.
