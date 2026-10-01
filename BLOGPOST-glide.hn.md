# Hacker News and Lobsters submission plan

> **Write every word that appears on HN or Lobsters yourself.** Both sites ban AI-generated and
> AI-edited text, in submissions and in comments, and "AI-generated" is an HN flag reason. This file
> is notes for you, not text to paste: a title, a URL, facts to check against, and the objections
> to expect. The first-comment skeleton below is bullet points on purpose. Do not ask an assistant
> to turn it into prose.

## Title

Submit the post's own title:

> **Tokens are cheap. Review isn't.**

HN keeps original titles and strips editorializing; this one has no number, no superlative and no
product name, so it should survive as is. Drop the subtitle. Do not add "Glide" or "Show HN" to it.

Fallback, only if the original gets retitled or you prefer something more literal (it must still be
defensible as the post's own framing):

> Agent tokenomics, review debt and comprehension debt

**Show HN?** Possible but not for this submission. Show HN is for something readers can try now,
and the post's URL is an essay. A later `Show HN: Glide – turns tickets into agent-written pull
requests you review` would point at the repository and lean on `mise run demo-unified`. Treat that
as a separate piece at a later date, and only after someone other than you has run the demo on a
clean machine.

**Lobsters:** same title, same URL. Tick **"authored by"**. Tags from the fixed taxonomy; likely
candidates are `ai`, `devops` and `practices`, but check the current tag list on the day. Your
self-promotion there must stay under roughly 25% of your activity; if the account is quiet, skip
Lobsters for this one.

## URL

The canonical URL (CANONICAL_URL_TBD). Never the dev.to copy, never the Forgejo repository, never
the docs site.

## Optional first comment: skeleton only

Facts to draw on, in no required order. Write it in your own words, short, no marketing.

- You maintain Glide alone; it is pre-1.0, Apache-2.0, self-hosted on Kubernetes.
- Works with Forgejo or GitLab, and Vikunja or ClickUp. No GitHub, Jira or Linear.
- The starting point: a capacity plan for your homelab put review capacity first and CPU/memory
  last (point (a) of the publish checklist applies to how you describe who produced that plan).
- One concrete number: a July README fix, one writing agent plus one reviewing agent, $0.019872 in
  total per the gateway ledger.
- The mechanism in one line: budget reserved per Work Item before a key exists, spend settled from
  the gateway's log, per-run capped keys that expire after four hours, one pull request, human merge.
- What is not done: sandboxing (Kata/gVisor executor experimental), per-run forge tokens (designed,
  off), review-queue admission (proposed), no measured merge rate.
- A code pointer for the curious: forgejo.webgrip.dev/webgrip/glide, and the no-spend demo.

## Likely objections, and the facts to answer them with

**1. "LiteLLM already does budgets and expiring keys."**
True, and Glide uses those keys. The addition: one pool per Work Item shared by all its runs, the
reservation inside one database transaction before a key exists, and settlement that returns the
unused hold. A monthly cap reports overspend afterwards; it can't say before a run whether this
ticket may still cost another $2.40. Test: `TestAuthorizeIsAtomicUnderConcurrency` (five requests,
pool funds two, exactly two succeed).

**2. "Prompt injection. The agent holds a push token."**
Conceded in the post. The harness sees its per-run model key and pushes with a shared forge token
for the agent account. Worst case: spend up to the run's cap within four hours, and push to what
that account can reach. ADR-0034 (placeholders behind a local proxy) and per-run forge tokens are
designed and tested, opt-in, and off on your cluster. Don't argue past this; agree and say what's
next.

**3. "An agent reviewing an agent is theater."**
Facts available: the reviewer is a separate agent with a read-only forge token; the Helm chart
won't render a team with a reviewer but no read-only token; the reviewer never falls back to the
write token. The post makes no claim about review quality and quotes no success rate, because the
KPI page says nothing is measured yet. Your previous post also conceded the reviewer's thin track
record; check whether what you said there still holds before repeating it.

**4. "The review-debt formula is just a min(). Theory of constraints, nothing new."**
Agree. The post attributes it to Glide's planning docs and uses it as arithmetic, not a discovery.
The point is the consequence: 20 tickets, 50 changes, 8 reviewed gives 8 shipped; 100 changes still
gives 8 and 92 waiting.

**5. "$0.02 a PR is cherry-picked."**
It is one README fix, and the post says so. The other numbers in the post: one to five euro cents
per run on a cheap model; bronze worst case $7.20 against an $8 pool; the writer cap is $2.00.

**6. "No GitHub? Then it's irrelevant."**
Correct for GitHub shops today; the post says so in the TL;DR. The eight-question checklist is the
part meant to apply regardless.

**7. "One maintainer, pre-1.0, homelab."**
All stated in the TL;DR. Don't soften it.

**8. "Why not kagent / build on kagent?"**
Agent Substrate injects one credential per hostname, so no separate model key per run; on your
cluster it would need a privileged daemon on every node, Kubernetes 1.37 and a beta API. Substrate
also runs agent pods as root with 13 added capabilities. The post positions kagent's tool server as
something Glide could consume over MCP, not a competitor to beat.

**9. "Did an AI write this post?"**
Answer honestly, in your own words, with whatever disclosure you're comfortable with. The post
itself says agents commit to Glide under `agent-builder`, so the topic will come up.

## Timing

- Tuesday to Thursday, 09:00–12:00 US Eastern. That is 15:00–18:00 in NL, except between 25 October
  and 1 November, when the clocks have changed in Europe but not yet in the US (14:00–17:00).
- Not the same day as the LinkedIn post if you can help it; you want to be free to answer HN.
- Be in the thread for the next 24–48 hours. Answering objections 1–3 well is most of the value.

## Never

- No vote solicitation, anywhere: not on LinkedIn, not in a chat group, not "it's on HN, have a
  look". Ring detection is automated and costs the account.
- No resubmission if it doesn't take. One submission per venue per piece.
