# LinkedIn variant

*Native post. Must deliver full value with no click, because LinkedIn suppresses external links to
roughly a quarter of normal reach. Link goes in a comment after the post has had its first few
hours, or via an edit once distribution has settled. ~1,900 characters.*

---

For months my AI code reviewer ran with this in its prompt:

"Do NOT modify, commit or push anything: you hold no lease on this branch and no write credential,
so a push will be rejected by the forge."

The second half was false. The push token was required on every worker pod, it reached the agent
through the process environment, and it was baked into the git remote of the clone the reviewer
was working in. The only thing between a "read-only" reviewer and a force-push was a language
model believing a sentence it could have disproved with one command.

I think this is the most useful mistake I have made this year, and not because of the missing
control.

A false constraint is worse than no constraint. The moment a model tests that claim and finds it
untrue, every other instruction becomes a hypothesis. "Never merge your own work" was sitting in
the same prompt.

The fix was not better wording. It was removing the credential from the pod, so that the
reviewer's read-only status is a fact about its environment rather than a claim in its context
window. Then I mutation-tested it: with the scrub disabled the tests fail, with it restored they
pass, and the case that must keep working still works. A control you have not tried to break is a
control you are guessing about.

The general version, for anyone putting a model behind a credential:

If a safety property is expressed in the prompt, it is a request. If it is expressed in the
deployment, it is a property. Budgets, privileges and credentials are all things your platform can
enforce and your prompt cannot.

Full writeup, including the part where the review then failed to reach the pull request at all,
and the month where my agents produced 2 of 594 commits: link in the comments.

---

## Notes

- Do not open with the cost figure. On LinkedIn a "$0.02 per PR" hook attracts the wrong audience
  and the comments become vendor pitches.
- The self-deprecating throughput number in the closing line is what keeps this from reading as a
  humblebrag. Keep it.
- If engagement is good, the natural follow-up post is the Kyverno autogen finding, which is
  self-contained and has a wider professional audience than the agent framing.
