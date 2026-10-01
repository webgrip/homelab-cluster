# Glide post: outline

Type: product introduction. Reader: an engineering or platform lead deciding how to let AI agents
write code in their organization, who wants the technical depth available but folded away
(`<details>` boxes for self-hosters). Canonical: own blog; then LinkedIn, dev.to, HN/Lobsters
(owner rewrites those two in their own words; both ban AI-written text).

One lesson: letting agents write code is not a model problem, it is a money, keys and merge-button
problem. Glide is the control plane for those three, and it deliberately does not try to be the
sandbox or the toolbox.

Every claim traces to BLOGPOST-glide.research.md (section numbers in brackets).

## Title candidates

1. Glide: agents write the pull request, you keep the budget and the merge button
2. The expensive part of AI coding agents isn't the model
3. Glide: a control plane for coding agents that spend money

## Sections (headers assert claims)

0. **TL;DR box** (3 lines): what Glide is, the three guarantees, pre-1.0 and self-hosted.
1. **Hook** (see hook options below).
2. **"An agent that writes code is an employee with a company card and push rights"**. The problem
   for a lead: spend you can't bound, credentials you can't scope, output nobody reviews. [3, 7]
3. **"A Work Item goes in, a pull request comes out, and a human merges"**. The flow in five steps;
   what Glide refuses to do (merge, deploy, host models). [2] Diagram: Work Item → Team → Shift →
   Runs → PR → you.
4. **"The money is authorized before the agent gets a key"**. Card-payment hold, then settle
   [8.7]; below $0.05 left, no key is minted [3]; the five-goroutines test [3]; worst case written
   in the manifest, $7.20 against an $8 pool [8.3]. `<details>`: the transaction (claim, row lock,
   authorize, SKIP LOCKED), file:line.
5. **"The bill comes from the proxy, not from the agent's word"**. Settlement from LiteLLM
   `/spend/logs` [4]; 45 run rows with 0 usage while the gateway had it all [8.6]. `<details>`:
   llmbroker path.
6. **"Every Run gets its own key, and it expires"**. `/key/generate` with alias, cap, 4h expiry;
   uncapped keys refused; the worker refuses to start if it can see the master key, the DB URL or
   the forge admin token [5]. Honest box: the per-Run key and forge token do enter the harness
   today; placeholder proxies are proposed, off here [claims-not-supported 1].
7. **"Where Glide sits: the engine, not the wall and not the toolbox"**. Layer picture: tools
   (MCP gateway, kagent-tools), engine (Glide), wall (agent-sandbox with Kata or gVisor), cluster.
   Why not build it on kagent 1.0: Substrate needs a privileged node agent and 13 capabilities,
   downloads its own runsc, needs Kubernetes 1.37 (which our CNI doesn't yet support), and injects
   one credential per hostname, so it cannot carry a key per Run; embedding it gives two
   run-trackers [6, RFC c60616fe]. What kagent is good for: its tools over MCP, and A2A later.
   `<details>`: gVisor vs Kata vs runc, Talos system extensions, kata 3.32.0 already on the workers,
   160Mi/250m overhead, ~2 s pod start. Honest box: Glide workers run on runc today; the
   agent-sandbox executor exists since 26 Sep and is experimental [claims-not-supported 3].
8. **"Why a team would want this"**, the business case: bounded worst-case spend per Work Item,
   attributable spend per Run (and soon per person), least-privilege credentials that expire,
   review stays human, self-hosted with your own model gateway, tracker-neutral (Vikunja, ClickUp;
   GitHub and Linear missing). The survey's finding that authorize-then-settle per-Run spend exists
   nowhere else; the lease is no longer unique and the post says so [6].
9. **"What isn't true yet"**: pre-1.0, one owner, no measured success rate or cost per PR, runs
   on runc, credentials in the harness, no GitHub/Linear tracker, retries not fenced [7].
10. **"Agents already work on Glide itself"**: 7 commits by `agent-builder`, including the fix
    for the per-run key leak [8.1]. Close: what's next (sandbox executor on Kata, measured KPIs),
    and how to try the deterministic demo without spending money.

## Hook options

A. **In media res (dogfood):** "Seven commits in Glide's history weren't written by me. They're
   signed `agent-builder`, and one of them fixes how Glide hands out the keys that pay for the
   agents that wrote it." Curiosity 5 · value 3 · specificity 5.
B. **Surprising number:** "$7.20 against an $8 pool. That is the worst case for one piece of work,
   and it's written in the config before any agent gets a key." Curiosity 4 · value 5 ·
   specificity 5.
C. **Bold claim:** "The hard part of letting AI agents write your code isn't the model. It's who
   pays, who holds the keys, and who presses merge." Curiosity 3 · value 4 · specificity 2.

Recommendation: B for the canonical post and LinkedIn (it states the value to a lead in the first
line), A as the dev.to/HN opening where builders read.
