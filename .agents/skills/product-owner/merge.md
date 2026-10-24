# Definition of Mergeable — may this change land on main?

Three definitions, three questions. **DoR**: may work on this ticket start? **DoM**: may
this *change* land on the shared branch? **DoD**: is the ticket's outcome delivered? The
DoM is the gate between review and merge, and it exists because **merged ≠ done, green ≠
mergeable, and the forge's "mergeable" ≠ mergeable**. Its invariant is the Not Rocket
Science Rule: *main always passes all the tests*, so every merge leaves main releasable.
A change can be mergeable while its ticket is far from done (dark launch, first slice of
a split) — the DoM never requires the ticket's acceptance criteria to be met live; the
DoD does. Evidence per rule: [rationale.md](rationale.md#merging--the-definition-of-mergeable).

## The portable DoM

One list per team, every change; the contract may point at the team's own. Each line is
binary, and each has an escape *with a reason written in the PR* — silence is not one.

### 1 · Lands green

1. **Required checks pass on the tree that will land** — the branch contains the current
   base, or a merge queue/train tested the combination. A green head on a stale base is
   not a green merge: about 9% of textually clean merges still broke the build or the
   tests in the best-known study.
2. **Every required check ran and could have failed** — not skipped-as-success, not
   soft-failed (`continue-on-error`, `|| true`), not a required name no check reports.
   Most red is real (only ~13% of CI failures are flaky), and a quarter of flaky-test
   fixes turned out to fix a real product bug: a flaky failure gets one rerun *and* a
   flaky-test ticket, never rerun-until-green.
3. **Main is green before the merge** — onto a red main, only the fix merges.

### 2 · Reviewed

4. **Approved by a qualified non-author, on the final revision.** A push after approval
   voids it; the last pusher never supplies the only approval. Qualified = has history in
   the touched files, or is their named owner — familiarity roughly doubles the share of
   useful review comments. **A second approval goes by risk tier** (the contract's
   human-review-mandatory paths; security paths above all — single reviewers miss most
   planted vulnerabilities), never by default. Approvals without any discussion on
   non-trivial changes go with more post-release defects — look twice at one.
5. **Every blocking thread resolved.** Nits are labelled non-blocking and never hold a
   merge; style belongs to the formatter, not the reviewer.

### 3 · Scoped

6. **One ticket, one logical change** — it references exactly one ticket (the contract's
   trailer), touches only what that ticket names (Protected areas untouched), keeps
   refactoring out of behavior changes, and is the only open PR for that ticket.
7. **Reviewable** — past ~400 changed lines or ~20 files (lockfiles and generated files
   aside), split, stack, or say why it cannot be smaller. A split trigger, not a cap: risk
   rises with files touched and churn, but no study has estimated a hard threshold.
8. **Tests move with the behavior** — changed behavior has tests in the same change that
   execute the changed lines and assert on them; no existing test deleted, skipped, or
   thinned without the behavior change that retired it named in the PR.

### 4 · Safe to ship at any moment

9. **Nothing unfinished is reachable** — partial behavior sits behind a default-off flag,
   tested in both states, with its removal ticket on the board.
10. **Compatible with the version still running** — schema, API, payload, and config
    changes are expand-only; the contract step is a later merge. A migration does one
    thing and is reversible, or its irreversibility is stated.
11. **Revertable on its own, rollback written** — a clean revert, a flag flip, or a
    forward-fix plan for what cannot be reverted.
12. **No new critical/high findings, no secrets, every new dependency checked** — it
    exists (hallucinated package names are squattable), is pinned, and is not a known-
    vulnerable version. Secrets block *before* the merge: most leaked secrets are never
    removed afterwards, so one that slips through is rotated, not just deleted.

### 5 · Legible

13. **The PR says what and why, how it was verified, the risk, and the rollback** — and
    every claim matches the diff. Verification means the ticket's Verification output or
    where to read it, never "tested locally".
14. **History lands clean** — no `fixup!`/WIP commits under a merge or rebase style; the
    subject follows the repo's convention; docs that change with the code are in the
    change (their *review* never blocks).

Where the DoM stops and the DoD starts: reviewed, trailer, docs, and rollback-*known* are
DoM; deployed-and-seen, rollback-*exercised*, criteria confirmed live, and flag rollout
finished are DoD. The DoD's Code line is simply "merged through the DoM".

## Enforcement — the forge, not the prose

A DoM line the forge can enforce but doesn't is a wish: prose never rejected a push.
Move every line the server can hold into branch protection, and keep the reviewer for
what only a human can judge — intent, scope, claims vs diff. A gate that cannot fail is
not a gate, and a gate that fails correct code gets bypassed: **block only on checks with
near-zero false positives**; show the rest in the PR at review time, where findings get
fixed (batch reports mostly don't).

| DoM line | GitHub | GitLab | Forgejo / Gitea |
|---|---|---|---|
| 1 tested tree = landed tree | merge queue, or "require branches to be up to date" | merge trains, or merged-results pipelines + a freshness bound | `block_on_outdated_branch` — the only way: PR runs test the **head**, and there is no merge queue |
| 2 checks ran | required checks listed by exact name | "pipelines must succeed", with "skipped pipelines are successful" left off | `enable_status_check` + explicit `status_check_contexts` |
| 4 final-revision approval | dismiss stale approvals · require last-push approval · CODEOWNERS | prevent author/committer approval · reset approvals on push | `required_approvals` · `dismiss_stale_approvals` · approvals allow-list |
| 5 blocking threads | require conversation resolution | discussions must be resolved | `block_on_rejected_reviews` |
| 6 protected areas | CODEOWNERS + rulesets on paths | code owners + locked paths | `protected_file_patterns` |
| who may merge | bypass list empty | "allowed to merge" roles | merge allow-list · `apply_to_admins` |

Forge traps that make "mergeable" lie — say so when a PR's green badge rests on one:

- **The API field is a conflict check.** GitHub's `mergeable` and Forgejo's `mergeable`
  mean "merges textually" (Forgejo ignores protection entirely); GitHub's `CLEAN` with no
  required checks configured means nothing ran.
- **Skipped counts as passed** on GitHub (and, by its status ranking, on Forgejo) — a
  job skipped because its dependency failed can let a broken PR through; a
  path-filtered required workflow instead hangs pending forever.
- **What was tested is not what lands.** GitHub's `pull_request` CI tests a merge, but
  only as of the triggering event — a base that moves afterwards makes it stale; Forgejo
  Actions test the PR head itself. GitLab can let an older passing MR pipeline satisfy
  the check despite a newer failing one.
- **Required check names must match reported names exactly** — copy them from a real
  PR's check list, then prove the rule both ways (a red check blocks, a green one merges).
- **Instance admins bypass protection** on Forgejo even with `apply_to_admins`.

**Speed is part of the gate.** A first review response within one business day is the
practitioner norm; nudging overdue PRs cut their lifetime in randomized trials, and no
response is the top reason contributors abandon a PR. Once every forge-enforceable line
is enforced, turn on auto-merge for approved-and-green — a large share of review lifetime
is idle time after approval.

## Agent-authored changes

Everything above, plus — because the author will not ask and does not tire of retrying
(agent evidence: [agents.md](agents.md)):

- **Builder ≠ judge.** The agent never approves, merges, or marks its PR ready. The
  approving human is outside the agent's session, and — where the team has a second
  human — not the person who dispatched it (GitHub and GitLab enforce exactly this
  separation). A solo maintainer records that in the contract and leans harder on the
  held-out check below.
- **AI review is a required input, never the approval.** Measured precision on real
  defects is low, AI-only-reviewed PRs fare worse, a model endorses its own mistakes, and
  a PR description written by the agent is untrusted input to any AI reviewer (framing
  attacks slipped known CVEs past review pipelines 32 of 33 times). Prefer a different
  model than the author, grounded in tests and scanners. The human makes an independent
  pass over scope and intent, not just over the lines the bot flagged.
- **Test-integrity hunks get a human read and a reason.** Tests, snapshots, fixtures,
  `conftest.py`, test-runner and CI config: every hunk there is read, not skimmed. The
  **revert check**: restore the base versions of those files, rerun the suite — a new
  failure means the change needed its test edits to pass, and the PR must say why. The
  real-world failure is thinner tests more than deleted ones: check that the new tests
  execute the changed lines and assert something.
- **Claims carry evidence.** "Faster", "fixes X", "more secure" needs the measurement or
  the reproduction in the PR — of 30 merged agent performance fixes re-run, 9 showed no
  gain or a regression.
- **CI/Docker/IaC edits by an agent** go to their owners, with actions and images pinned;
  keep "approve before workflows run" on agent PRs — skipping it hands unreviewed code the
  repo's secrets.
- **Provenance at merge**: the ticket link, the agent + session/run link, the trailer the
  contract names (`Assisted-by:` is the modal open-source convention; several projects
  reject an AI `Co-authored-by:`), and a human who answers for it.
- **Merged is not correct.** Merged agent PRs draw follow-up fixes at higher odds than
  human ones; the evidence comment's regression signal is the post-merge watch.

## The merge check — procedure

1. **Fetch the PR head** into the up-to-date checkout: `git fetch origin
   pull/<n>/head:pr-<n>` (GitHub, Forgejo, Gitea) or `merge-requests/<n>/head` (GitLab).
2. **Run the mechanical half**:

   ```bash
   python3 scripts/merge_check.py --base origin/main --head pr-<n> \
       --protected 'deploy/*' --trailer 'VIK-\d+' --body pr.md [--author agent]
   ```

   It reads git only: empty diff (zombie PR), conflicts, behind-base, deleted/renamed-
   away/edited tests, net assertions lost, skip/focus/suppression markers, exit-before-
   the-tests tricks, gate-config edits, protected paths, size, dependency and migration
   touches, fixup commits, conventional subjects, ticket trailer, PR-body sections;
   `--max-lines`/`--max-files` set the size trigger.
   Agent-authored (auto-detected from an `Assisted-by:`/`Generated-by:` or agent
   `Co-authored-by:` trailer) tightens the test and gate lines from WARN to FAIL;
   `--allow-test-edits` when the ticket scopes test changes.
3. **Read the forge for the MANUAL lines** — checks on the landing tree, approvals on
   the current head, blocking threads — and name any forge trap the badge rests on.
4. **Review against intent and scope** — does the diff do what the ticket's Problem
   needed and nothing else; does every claim in the description match the diff?
5. **Verdict.** Mergeable → merge by the repo's method, by a human or the forge's
   automation, never by the authoring agent. Not mergeable → one comment naming each
   unmet line, back to the author; **do not fix it inside the review**. A PR closed
   unmerged always gets a reason (duplicate, superseded, wrong approach, abandoned) —
   rejections without one blind the per-class learning in [flow.md](flow.md).

## Escapes and exceptions

The DoM is **not negotiable per PR** — only per team, in the retro, same as DoR and DoD.
**Break-glass** (incident relief, a red main): merge with the fastest available
reviewer, record the reason on the PR, and complete the skipped lines within a working
day as a follow-up the board tracks. A break-glass merge that becomes routine is the
definition being wrong.

## Antipatterns — merge folklore

| Folklore | Why it fails | Instead |
|---|---|---|
| **Two approvals on everything** | Google runs at a median of one reviewer; DORA finds heavy multi-approval hurts without lowering change failure. | One qualified non-author; a second by risk tier. |
| **"CI is green, merge it"** | The head was tested, not the merge; skipped checks count as passed. | Line 1 + line 2, enforced by the forge. |
| **Project-wide coverage % gate** | The coverage–effectiveness link is contested, Google enforces no global threshold, and most teams bypass failing coverage checks. | Changed lines executed and asserted on (line 8); mutants shown in review where available. |
| **Review as the bug filter** | ~14% of review comments concern defects; ~75% of findings are maintainability. | Tests and gates own correctness; review owns intent, scope, design. |
| **Every comment must be resolved** | Nits become blockers; review stalls. | Blocking vs non-blocking labels (line 5). |
| **Change board / manual QA sign-off before merge** | No evidence it lowers change failure; it slows delivery. | Peer review + automated gates + flags. |
| **Hard line limits** | No threshold has been estimated from data; the popular 200–400 LOC comes from a vendor study with a density artifact. | A split trigger with a stated-reason escape (line 7). |
| **Rubber-stamped agent PRs** | Approval rates on agent PRs rise while review comments fall — habituation, not trust. | Track zero-comment approvals on agent PRs ([flow.md](flow.md)). |
