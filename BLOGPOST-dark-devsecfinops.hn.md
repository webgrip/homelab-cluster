# Hacker News submission plan

## Title

Submit the post's own title:

> **I told my AI code reviewer it couldn't push. It could.**

Sentence case, no numbers, no superlatives, no coinage. It names a specific technical failure
rather than a framework, which is what survives the guidelines and the mods. Note the old working
title ("Dark DevSecFinOps: the loop, and how far round it I actually got") should **not** be used
here: stacked `-Ops` portmanteaus get mocked before anyone reads the first line.

Not a Show HN. Nothing for a reader to run; the factory is on private infrastructure.

## URL

The canonical Substack URL. Never a rehost, never a summary.

## Preconditions

- [ ] **Ryan's read-aloud ownership pass.** HN treats AI-generated text as a flag reason. The draft
      went through a de-AI sweep (0 em-dashes, antithesis constructions cut from ~12 to 5,
      section-closing aphorisms removed), but a sweep is not authorship. Read it aloud and rewrite
      anything that is not your sentence.
- [ ] **Decide the manifests answer before submitting.** It will be the first or second comment.
      `webgrip/ploeg` and `webgrip/homelab-cluster` are both public on Forgejo; the GitHub mirrors
      are public but stale since the Forgejo cutover (last pushed 23 and 25 July). `erfbeeld` is
      private. Pick one and put it in the footer.
- [ ] Confirm the figures still hold on the day. The throughput table moves daily.

## Timing

Tuesday to Thursday, 09:00–12:00 US Eastern (15:00–18:00 in NL). Be in the thread for the next
24–48 hours; author presence is half the value of the submission.

## Never

No vote solicitation, anywhere, in any form. Detection is automated and costs the account, not the
post. No resubmission if it does not take.

## The thread, and prepared answers

The first two are the ones that will decide how this goes. Both attack the strongest claim, and
the post already concedes both, which means the job in the thread is to point at the concession
and go further, not to defend.

**1. "Has that reviewer ever actually caught anything? You showed it approving a two-sentence
README edit."**

Correct, and the post says so: one verdict in its life, approve, on a trivial diff, with no
adversarial test ever run. `builder ≠ judge` is currently an architecture diagram, not a
demonstrated control. What I can defend is the *mechanism* rather than the judgement: separate
pods, separate credentials, separate budgets, and the credential scrub is mutation-tested both
ways. What I cannot defend yet is that the judgement is worth anything, and the planted-bug test
is the next thing I run. One thing in its favour: the broken reviewer never emitted a verdict
either, it died at startup, so there is no backlog of untrustworthy approvals in that table.

**2. "Prompt injection. The builder ingests ticket text as instructions while holding a push token
and a privileged Docker daemon."**

Named in the post as an unaddressed hazard, and I would rather be the one who says it. The only
thing standing there today is that the board has exactly one human user, so ticket text is trusted
by assumption rather than by any control. That is adequate for a single-user homelab and it is not
a design. If you want the concrete shape of the exposure: `automountServiceAccountToken: false`
buys nothing against it, because the interesting capability is the forge token and the daemon, not
the Kubernetes API.

**3. "You claimed no bespoke orchestration on the critical path and then wrote a bespoke
orchestrator."**

Yes. The post retires that claim explicitly. Ploeg is a Go service with its own object model,
routing table, config validator and database, sitting directly on the critical path, and I wrote
it. It may still be the right call; it is no longer a virtue I get to claim.

**4. "So it's just a CI job. What's new?"**

Exactly, and that is the thesis. Scheduling agents is solved: KEDA, a ScaledJob, scale-from-zero,
the same machinery that runs my CI. The unsolved problems are spend, identity and trust. Lean into
this comment rather than fighting it; the boring-scheduler framing is the most HN-compatible thing
in the piece.

**5. "Two commits out of 594. Why is this a post?"**

Because that table is in the second section rather than hidden, and because the engineering
findings do not depend on the output volume. The Kyverno autogen finding cost me an outage and is
true for everyone running Kyverno. The false-constraint failure is true for anyone putting a model
behind a credential.

**6. "Privileged DinD on your cluster, seriously?"**

Under a Kyverno exception keyed to a hazard label rather than a workload name, which is what
surfaced that non-privileged reader Roles had been silently waived for privileges they never take.
The reviewer now runs `dind: false` and is held to the full Pod Security baseline. And the pods
carry no ServiceAccount token.

**7. "Your cost numbers are precise to six decimals but you say attribution is broken."**

Both true, and the post discloses it in the same paragraph as the number: the two figures are
matched to the two pods by their spend windows on the clock, because revocation deletes the key
record and takes the alias with it. The ledger keeps the money and loses the name.

**8. Kyverno autogen (expect this to be the top *technical* comment).**

Be ready to expand: `.spec.rules` lists only human-authored rules; Kyverno generates the Job,
Deployment and CronJob variants at admission; a Job selector matches the Job's own labels, so a
hazard label living on the pod template can never admit the Job. If this thread takes off on its
own, that is a signal it should have been its own post, and it still can be.
