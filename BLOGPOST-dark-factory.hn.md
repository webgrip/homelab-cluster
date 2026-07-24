# HN submission plan — dark factory post (v2)

## Title

Submit the post's own title, de-hyped per HN norms (mods retitle editorialized submissions):

> **Building a dark factory: Kanban tickets in, reviewed pull requests out**

"Dark factory" is the post's concept handle, not hype; it survives the guidelines. Sentence
case, no numbers, no superlatives.

Not a Show HN: nothing for readers to try right now (the factory runs on private infra).
If the manifests get published as a browsable repo later, that could be a separate Show HN.

## URL

The canonical Substack URL. Never a rehost, never a summary page.

## Preconditions

- [x] Em-dash density fixed in v2 (79 → 14; 1.3 per 500 words, human range).
- [x] Real cost numbers in ($0.046 build, $0.018 revision, $0.064 ticket total, $0.00 failures).
- [x] Revision-loop story included (runs 33–35), with the honest "not yet root-caused" caveat.
- [ ] **Author read-aloud pass in Ryan's own hands.** HN bans AI-generated/edited text; the
      post discloses AI pair-building of the factory, and the prose must be genuinely owned.
      Read it aloud, rewrite anything that doesn't sound like you, then submit.
- [ ] Decide the answer to "can I see the manifests?" before submitting; it will be the first
      or second comment. (The cluster repo paths are cited throughout; if the repo is public,
      link it in the post footer.)

## Timing

Tue–Thu, 9:00–12:00 US Eastern (15:00–18:00 NL). Be available in the thread for the following
24–48 h; author presence is half the value.

## Never

- No vote solicitation anywhere (no Slack, no newsletter nudge, no "please upvote").
- No resubmission if it doesn't take; one shot per venue per piece.

## Expected thread + prepared answers

1. **"The agents will just game the reviewer"** → builder ≠ judge is forge-enforced (separate
   accounts, reviewer can't push/merge); merging stays human; server-side pre-receive guards
   are named on the roadmap as the control that doesn't depend on agent manners.
2. **"Privileged DinD on a cluster, seriously?"** → narrow label-matched Kyverno exception,
   `automountServiceAccountToken: false`, no-authority ServiceAccount, no API-server egress
   for agent pods. The agent gets a shell and a docker daemon, not a cluster.
3. **"What does it cost?"** → answered in the post with ledger numbers: $0.046/PR,
   $0.064/ticket including a revision; per-run budget caps + provider day-caps; failed runs
   spend $0.00 by construction.
4. **"Cheap model writing tests is just slop"** → pilot evidence: 16 real specs, 83/83 green,
   fixture-driven assertions, and the reviewer still caught 3 strict-mode errors — which is
   the point of the design, not a flaw in it.
5. **"Why self-host instead of GitHub + hosted agents?"** → no SaaS control plane as a factory
   dependency (pricing/API/outage immunity); spend metering by construction; everything
   reconciled from git.
6. **"What were runs 33/34?"** → two revision dispatches that died before minting keys; both
   cost $0.00 and left triage comments; root cause is the top of the dispatcher work queue.
   Honest answer, already in the post.
7. **"So it's just a CI job. What's new here?"** → exactly, and that's the thesis: scheduling
   agents is a solved problem (KEDA, ScaledJobs, scale-from-zero); the new problems are
   spend, identity, and trust, and the post is about those three. Lean into this comment,
   don't fight it — the "boring scheduler" framing is the most HN-compatible part of the post.
8. **"A small model can't follow all those instructions"** → agreed, and the design assumes
   it: thin workflow, repo-carried discipline, gates in CI's images, independent reviewer.
   The pilot showed both halves: good tests written, gate skipped, harness caught it. You
   don't buy reliability from the model; you build it around the model.
