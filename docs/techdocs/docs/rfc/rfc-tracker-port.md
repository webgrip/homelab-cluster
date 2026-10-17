# RFC: Trackers are a port

> Status: **Accepted in part** 2026-10-17 · Owner: Ryan · Accepted: the four boundaries below.
> Open: where Report a problem lives (decision 2). Board: see [Plan](#plan).

## Why

The owner tried to give Ploeg and Unfold their own Vikunja user (VIK-1643) and rejected the result:
Vikunja only lets a signed-in person mint a token, and the only sign-in is Google. The obvious
escape, moving to Forgejo Issues, would drop the roadmap and stop the work on the Vikunja
connector. Both are wrong. The real problem is that three components each talk to trackers on
their own, so every identity, permission and behaviour question has to be answered three times.

## What exists on 2026-10-17

| Component | Job | Talks to trackers through | What it does there |
| --- | --- | --- | --- |
| **Ploeg** (`ploeg-hq/ploeg`, Go) | authorizes, budgets and runs agent work | `pkg/provider`: Vikunja, ClickUp, GitHub Issues (`TrackerProvider`, `BoardReader`) | webhook ingest, fetch, comment, set status, read board status |
| **Unfold** (`webgrip/unfold`, TypeScript) | where people define, follow and review work | `apps/unfold/src/tasks.ts`, 650 lines: Vikunja, ClickUp, Forgejo, GitHub, GitLab | browse tasks; **hand-off** (find the team's tracker user, assign it, comment); **Report a problem** (create issue, attach files, follow its state, reply) |
| **Homelab** | wires the estate together | `tracker-wiring` CronJob, mcp-vikunja gateway | registers webhooks, shares boards, gives agents board tools |

All of Ploeg's and Unfold's Vikunja writes, and the wiring job's, use the owner's personal token
(`agent-vikunja-token`, OpenBao `vikunja/mcp`). Report a problem files into Forgejo Issues with its
own token (`forgejo/unfold-reports`).

Two tracker adapter sets with different provider lists is the finding. Unfold's hand-off writes to
the tracker to start Ploeg work, although Ploeg already accepts work directly through
`POST /api/v1/operator/work-items` (Ploeg `pkg/httpapi/operator_work_admission.go`).

## The boundaries (accepted 2026-10-17)

1. **Ploeg owns tracker I/O for work.** Ingest, routing, write-backs and status all go through
   Ploeg's provider contract. Ploeg names no consumer (Ploeg ADR-0069).
2. **Unfold talks to Ploeg, never to a tracker, to start or follow work.** Hand-off becomes a call
   to Ploeg's admission API. Browsing tasks reads what Ploeg sees.
3. **A tracker is a plug-in.** Vikunja is the first fully worked provider; Forgejo Issues, ClickUp,
   GitHub Issues, GitLab and Linear meet the same contract and the same conformance tests. Adding
   one never changes Ploeg's core or Unfold.
4. **Only the homelab knows every name.** Which boards, which repositories, which identities: that
   is configuration here, not knowledge inside a product.

What follows: only Ploeg needs a tracker identity to do work, so the bot-account problem shrinks to
one account, and solving it once solves it for every tracker.

## The port

The contract is the provider SPI Ploeg already has, made explicit:

| Capability | Today | Needed by |
| --- | --- | --- |
| Receive assignment / update events | `ParseWebhook` | ingest |
| Read an item | `FetchItem` | ingest, Unfold browsing via Ploeg |
| Comment | `Comment` | write-backs |
| Move status | `SetStatus`, `BoardStatus` | write-backs, delivery gates |
| List items in a scope | missing | Unfold's task browser |
| Create an item with attachments, follow its state | missing (Unfold only) | Report a problem |

Each capability gets a conformance suite every provider runs (VIK-533 compatibility policy,
VIK-577 authoring guide). A provider declares the capabilities it supports, and a consumer asks
for one instead of a provider name.

## Decisions

1. **Bot identity: a Vikunja bot user.** Spiked 2026-10-17 against the deployed v2.6.0 source.
   Vikunja has had bot users since 2.4.0: no email, no password, refused for password, OIDC and
   CalDAV sign-in, and their owner mints scoped, expiring API tokens for them
   (`pkg/models/api_tokens.go` checks `IsBotOwnedBy`; usernames must start with `bot-`,
   `pkg/user/user_create.go`). The owner signs in as himself, creates `bot-ploeg` under Settings →
   Bot users, mints its token and writes it to OpenBao. No login window opens. Rejected: an
   Authentik service login (Vikunja's OIDC callback only exchanges an authorization code), LDAP
   (it registers `/login` and falls back to local passwords), and writing the token row into
   Postgres (works, but the hash format is not a public contract). The local user `unfold` (id 38)
   has a password and is disabled once the bot is live.
2. **Report a problem.** It is a feedback product, not agent work, and nothing in it needs
   Unfold's domain. Options:
   - **A.** Pull it out as its own small component (widget plus filing server) that any app
     embeds, Unfold and Erfbeeld first. It files through the tracker contract. Recommended: it is
     the first consumer of the port that is not Ploeg, which proves the port is a port.
   - **B.** Keep it in Unfold on its own adapters. No work, but two adapter sets stay.
   - **C.** File reports through Ploeg. Ploeg would gain a job that is not agent work.
3. **Forgejo Issues** becomes a planned provider after the Vikunja provider's hardening epics
   (VIK-1523, VIK-1293) and the conformance suite, not a swap for Vikunja.

## Plan

In order; each step is a board ticket and none starts before it is ordered.

| Step | What | Where |
| --- | --- | --- |
| 1 | Ploeg writes to Vikunja as `bot-ploeg` | Homelab Roadmap VIK-1643, which absorbs VIK-1331 and VIK-1605 |
| 2 | Conformance suite and capability declaration for tracker providers | Unfold board, repo `ploeg` (VIK-533, VIK-577) |
| 3 | Finish the Vikunja provider: strict, loss-free ingest; cards follow work | VIK-1523, VIK-1293 |
| 4 | Unfold hands work off through Ploeg's admission API, not the tracker | Unfold board |
| 5 | Unfold browses tasks through Ploeg; delete Unfold's work adapters | Unfold board |
| 6 | Report a problem placement (decision 2) | Unfold board |
| 7 | Forgejo Issues provider against the suite | Unfold board, repo `ploeg` |

## Not changing

- The roadmap stays in Vikunja (ADR-0043).
- mcp-vikunja, theme suggestion and the Forgejo agent pool keep acting as the owner on purpose.
