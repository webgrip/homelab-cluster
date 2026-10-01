# LinkedIn variant

*Native post. Delivers the review-debt arithmetic and the eight-question checklist with no click.
No link in the body; the link goes in the first comment (text below). About 2,300 characters.
Every claim is in draft-v2.*

---

I planned how many AI coding agents my homelab could run at once. I expected a hardware answer.

CPU and memory came last. First on the list was my own review capacity.

A two-sentence README fix, written by one agent and reviewed by a second, cost $0.019872 in model spend. Tokens are cheap. The scarce resource is the person reading what the agents produce.

The arithmetic fits in one line. Accepted results per week can't exceed the smallest of three numbers: ready tickets, candidate changes produced, and review capacity.

Say you write 20 good tickets a week, your agents produce 50 candidate changes, and you can properly review 8.

You ship 8.

Double the agents to 100 candidate changes and you still ship 8, with 92 pull requests waiting. Better tests and clearer evidence might lift review to 16 a week. More agents won't.

That queue is review debt. There is a quieter cost too, comprehension debt: code that got merged, works, and that nobody on the team understands. It shows up when something breaks and the person on call reads the module for the first time.

Before I'd let any coding-agent tool open pull requests, I'd ask it these eight questions:

1. Is a budget reserved before a run starts, per ticket, or is spend only capped per month?
2. Where does the cost figure come from: the provider or gateway, or the agent's own report?
3. Does each run get its own credential, and when does it expire?
4. What can a prompt-injected agent push to, and with which token?
5. Does one ticket end in one pull request, however many attempts it took?
6. Is there a second reviewer that cannot push?
7. Can agents create new work, and who approves it before it runs?
8. Who merges?

Behind all eight sits the question an engineering lead eventually gets: who is responsible for this change? If the answer is "the agent", nobody is.

I've been building an open-source tool around these questions, called Glide. It never merges. Whoever presses merge owns the change.

Who can use it today: teams on Forgejo or GitLab with Vikunja or ClickUp, running their own Kubernetes. No GitHub, Jira or Linear yet. It is pre-1.0 and I'm the only maintainer. The checklist works for whatever tool you pick.

Which of the eight is hardest to get a straight answer to in your setup?

#AIAgents #PlatformEngineering #CodeReview

---

## First comment (post it yourself right after publishing)

The full write-up, including Glide's own answer to each of the eight questions (some of them are "not yet"): CANONICAL_URL_TBD

Code: forgejo.webgrip.dev/webgrip/glide
Docs: docs.webgrip.dev/glide

---

## Notes

- Hook = the first two lines (about 170 characters together). The fold on mobile falls around
  140, so line 1 alone has to carry it: it promises a capacity answer, and line 2 turns it.
- The hook inherits owner-judgment point (a) from the publish checklist: "I planned" versus the
  plan having been produced by an agent for you. If you change the opening of the canonical post,
  change line 1 here to match.
- The $0.019872 figure is a July run, not a typical cost; the post frames it the same way. Don't
  round it into a "2 cents per PR" claim in replies.
- Deliberately left out: kagent, Kata/gVisor, the card-payment reservation mechanics. They belong
  to the technical audience on dev.to; here they would bury the checklist.
- De-AI sweep: 0 em-dashes, 0 hits on the buzz-verb list, no "not X, it's Y" construction.
