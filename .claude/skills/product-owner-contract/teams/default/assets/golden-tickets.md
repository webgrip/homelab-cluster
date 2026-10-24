# Golden tickets — the standard grooming writes towards

Four examples, one per common kind. **Form is the norm; content is illustrative**: services,
numbers, dates and paths below are invented to show the form. When grooming a real ticket,
every claim comes from research (the current state of the project's development branch and
the live cluster) or from the requester, never from this file.

Every ticket has **two halves**: on top the functional half the product owner and the
acceptor read, below the rule the technical write-up for the developer and the agent. The
skeleton, the language rules and the per-sentence test are in
[ticket-template.md](ticket-template.md).

---

## 1 · Change — a visible improvement

```text
Title:  Status page: show when each service was last checked
Labels: theme/observability · repo/status-page · kind/change · value/reduces-risk · impact/M
```

```markdown
**Source:** incident review of 2026-09-14, <link>: "The status page said green for an hour
while the probe itself was down."

## TL;DR
Visitors of the status page cannot tell a healthy service from a probe that stopped
running. During the last incident the page stayed green for an hour after its probe died.
- **Who notices:** everyone who checks the status page before reporting an outage
- **What we want:** next to every service, the time of its last successful check

## Outcome
Every service on the status page shows when it was last checked, and a stale check is
visibly marked.

## Acceptance criteria
- [ ] Each service row shows the time of its last completed check, in the visitor's timezone
- [ ] A service whose last check is older than three check intervals shows "stale" instead
      of green
- [ ] The time shown is the check's completion time, not the time the page was rendered
- [ ] With the probe stopped for 10 minutes, the row turns "stale" without a page redeploy

## Verification
On the staging status page: stop the probe for one service for 10 minutes. Expected: that
row shows "stale" with the time of the last completed check; every other row stays green.

## Not in scope
- Alerting on stale probes: already covered by the probe-down alert
- History graphs per service: separate ticket

## Open questions
- Should "stale" also page someone, or only show? — owner: Ryan

---

# Technical write-up

> For the developer and the agent that picks this up. You do not need to read this to
> understand or discuss the ticket.

## Technical context
- The page reads only the up/down result (`src/status/fetch.ts:41`); the probe's
  completion timestamp is exported but unused.

## Approach
1. Read the completion timestamp next to the result in `src/status/fetch.ts`.
2. Derive "stale" from the probe's own interval, not a fixed constant.

## Technical verification
`kubectl -n status scale deploy/probe-api --replicas=0`, wait 10 minutes, reload the page.

> Researched against `main` @ `<short sha>`.
```

**Why golden:** criterion 3 closes the cheap way out (the render time looks like a check
time and costs nothing to show), and criterion 4 tests the exact failure from the incident.
Above the rule no file name appears: the requester recognises their own words in the Source.

---

## 2 · Bug — a false success

```text
Title:  Nightly backup: job reports success when the upload failed
Labels: theme/backup-dr · repo/homelab-cluster · kind/bug · value/reduces-risk · impact/H
```

```markdown
**Source:** restore drill of 2026-09-02, <link>: the newest archive in the bucket was four
days old while every nightly run was green.

## TL;DR
The nightly backup reports success even when its upload to object storage fails. We only
found out during a restore drill, four days after the last good archive.
- **Who notices:** whoever restores; until then nobody
- **What happens now:** the run is green, the archive never arrives
- **What we want:** a failed upload turns the run red and pages

## Reproduction
1. Make the storage bucket read-only for the backup user
2. Run the nightly backup by hand → expected a failed run, got a green run

## Environment
Production cluster, every nightly run since the storage credentials were rotated on
2026-08-29; every run with a failed upload.

## Outcome
A nightly backup run is only green when its archive is complete in object storage.

## Acceptance criteria
- [ ] A run whose upload fails ends failed, and the backup-failed alert fires within 15
      minutes
- [ ] A run that uploads only part of the archive ends failed, not green
- [ ] A normal run still ends green and the newest archive in the bucket is from that run

## Verification
On the staging cluster, with the bucket read-only for the backup user: run the backup by
hand. Expected: failed run, alert in the alerts channel within 15 minutes, no new archive.
Then restore write access, rerun: green, newest archive from this run.

## Not in scope
- Restore automation: tracked separately
- Rotating the storage credentials again

---

# Technical write-up

> For the developer and the agent that picks this up. You do not need to read this to
> understand or discuss the ticket.

## Technical context
- The upload step pipes into `tee` without `pipefail`
  (`kubernetes/apps/backup/job.yaml:58`), so its exit code is the last command's.

## Approach
1. Set `pipefail` in the job script and fail on a non-zero upload.
2. Compare the uploaded object size with the local archive before reporting success.

## Technical verification
`kubectl -n backup create job --from=cronjob/nightly manual-$(date +%s)` and read its status.

## Rollback
Revert the commit; Flux reconciles the previous job spec.

> Researched against `main` @ `<short sha>`.
```

**Why golden:** criterion 2 closes the cheap way out (a fix that only checks the exit code
still accepts half an archive), and the verification proves both the red and the green path.

---

## 3 · Spike — a decision

```text
Title:  Logs: decide where logs older than 30 days are kept
Labels: theme/observability · repo/homelab-cluster · kind/spike · value/unblocks · impact/M
```

```markdown
**Source:** storage alert of 2026-09-20, <link>: the log volume passed 85% for the third
time this quarter.

## Question
Where do logs older than 30 days live, so the log store stops filling up without losing
what an incident review needs?

## Timebox
1 day. Running over means it is implementation, not research.

## What we decide on
- Monthly cost at today's volume
- How an incident review reads a 60-day-old log line
- Fits GitOps: declared in the repo, no hand-run jobs
- Restore effort when the cold store is unavailable

## Who decides
Ryan, by the next refinement.

## Acceptance criteria
- [ ] Every option is scored on the criteria above, with today's volume as input
- [ ] It is decided, and the decision is recorded with its trade-off in an ADR

## Not in scope
- Implementing the chosen option: a follow-up ticket per the decision
```

**Why golden:** the second criterion is the cheap way out closed: a spike that presents
options and stops has not delivered. Done = decided and recorded.

---

## 4 · Split child — part of a series

```text
Title:  Agents: identity - Part 2/4 - each agent run gets its own token
Labels: theme/agents · repo/unfold · kind/change · value/reduces-risk · impact/H
Parent: Epic: agent identity · blocked by Part 1/4
```

```markdown
**Source:** epic "Agent identity", <link>, part 1 of 2026-09-10 (one service account per
agent)

## TL;DR
All runs of one agent share a token, so a leaked token gives access until someone rotates
it by hand. Part 1 gave each agent its own account; this part gives each run its own
short-lived token.
- **Who notices:** whoever revokes access after a bad run
- **What we want:** revoking one run's token stops that run only

## Outcome
Every agent run uses its own token that expires when the run ends.

## Acceptance criteria
- [ ] Two runs of the same agent at the same time use two different tokens
- [ ] A token stops working within 5 minutes after its run ends
- [ ] Revoking one run's token stops that run and leaves a parallel run of the same agent
      working
- [ ] Every agent that worked after Part 1/4 still starts and finishes a run

## Verification
On staging: start two runs of the same agent, revoke the first run's token. Expected: run 1
fails with an auth error, run 2 finishes. Five minutes after run 2 ends its token is refused.

## Not in scope
- Per-run budgets: Part 3/4
- Audit trail of token use: Part 4/4

---

# Technical write-up

> For the developer and the agent that picks this up. You do not need to read this to
> understand or discuss the ticket.

## Technical context
- Tokens are minted once per agent at deploy time (`deploy/agents/secret.yaml:12`).

## Approach
1. Mint a token per run from the vault at run start, with the run's lifetime as TTL.

## Protected areas
- Part 1/4's per-agent service accounts; tests and CI config

## Rollback
Feature flag `per_run_tokens`; off restores the shared token.

> Researched against `main` @ `<short sha>`.
```

**Why golden:** criterion 4 protects what already works in the series, the order is a
`blocked` relation on Part 1/4 instead of a sentence, and the parent epic keeps the overall
outcome.
