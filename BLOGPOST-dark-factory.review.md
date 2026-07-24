# Review — BLOGPOST-dark-factory.md (blog-writer skill, 2026-07-19 evening)

## v3 reframe (later the same evening, on Ryan's direction)

The point is the platform, not the work item. v3 restructures around three claims stated in
the intro and re-landed through the post:

1. **A stock scheduler now schedules AI agents** — "schedule agents" = "one more KEDA runner
   pool"; the scheduling is boring and solved; spend/identity/trust are the real problems
   (new paragraph after the platform table).
2. **Fully open-source, self-hosted platform** — only the model API is rented, one config
   line (intro bullet + closing).
3. **Costs next to nothing, provably, with total observability** — $0.046/PR against peers'
   $150 overnight hosted sessions; idle=$0, failures=$0.00, three-layer caps; "I'm not
   trusting the factory, I'm auditing it" (intro bullet, closing paragraph, observability
   section).

Also added: the "small model can't stack instructions" objection with its answer ("you don't
buy reliability from the model; you build it around the model") — sourced from a peer
conversation. **Consent check for Ryan**: the post now references, anonymized, (a) a friend's
$150-overnight figure and (b) a friend's harness objection, both from a private Discord
thread. No names, no identifying details, but confirm you're comfortable before publishing,
or soften to fully generic phrasing.

All variants updated to lead with the thesis (LinkedIn hook, HN answers #7/#8, dev.to intro,
r/kubernetes title). Quantified checks still green: 5,813 words, 14 em-dashes (1.2/500).

**Title options** (current title kept; pick at publish):
1. *Building a Dark Factory: Kanban tickets in, reviewed pull requests out* — current;
   concept-handle-led, curiosity-strong.
2. *Scheduling AI agents is solved. Spend, identity, and trust aren't* — assertion-led,
   most aligned with the v3 thesis, very HN-compatible.
3. *A dark factory for cents: AI agents as ordinary Kubernetes workloads* — value-promise-led.

---

# Earlier review — v2

v2 rewrote the canonical from fresh evidence (see `BLOGPOST-dark-factory.research.md`:
live ledger metrics, the ticket-454 comment trail, the ADR registry, the board, and a
manifest-level verification sweep). v1 is preserved as `BLOGPOST-dark-factory.draft-v1.md`.

## What changed in v2 (the judgment calls)

1. **Real money in the text.** Run 32: $0.046 / 103 requests / 4.63M tokens / 16 min
   inference (2.3% of budget). Run 35 revision: $0.018. Ticket total $0.064; all three
   failures $0.00. These came from the live litellm-exporter metrics, not estimates.
2. **The story now ends a day later.** New sections: the revision loop (runs 33–35, with the
   honest "33/34 not yet root-caused" caveat) and "Watching the factory" (the six-dashboard
   observability suite and the preview host, both shipped after v1 was written). The closing
   line now lands on "the factory is starting to build the factory".
3. **Factual correction from the manifest sweep**: v1 said all three pod credentials were
   "ESO-delivered from the vault"; the builder token is actually minted by a provisioner Job,
   never stored in the vault, never seen by anyone. v2 states it correctly (and it's a better
   story). Also added: OpenHands local-workspace detail (DinD is for gates only), pinned
   image digest, resource ceilings, provider day-caps.
4. **ADR numbers cited** (0044/0045/0047/0048) instead of "an ADR".
5. **De-AI-ify sweep**: 79 em-dashes → **14** (1.3 per 500 words, human range). Zero
   buzz-phrase hits. Voice lines kept intact.
6. **Reader-test preempts baked in**: cost (answered with ledger numbers), why-self-hosted
   (one clause on vendor pricing/API/outage), why deepseek on bronze (one clause: escalation
   is a label), what runs 33/34 were (honest paragraph).

## Still open before publishing (Ryan's hands, not an agent's)

1. **Read-aloud ownership pass.** HN/Lobsters ban AI-generated/edited text. The prose must be
   yours: read it aloud, rewrite anything that doesn't sound like you. This is the one step
   the skill cannot do for you.
2. **Verify the run-35 revision actually addressed the review** (fetch the branch, run the
   TS gate) before the post ships the revision-loop section as a success story. The ledger
   proves the run happened; it doesn't prove the errors are gone. If the gate still fails,
   the honest edit is one sentence.
3. **Decide the manifests answer**: if the cluster repo is public, add the link to the post
   footer; if not, add one sentence saying paths are from a private repo.
4. Substack: set the title, check tables/code blocks render in the editor, subject-line =
   title (payoff is already in the first clause).

## Publish checklist (order + timing)

1. Ryan's ownership pass + run-35 verification (above).
2. Publish canonical on Substack. Final URL into `.devto.md` frontmatter (`canonical_url`).
3. Wait 2–3 days for indexing.
4. **HN**: per `.hn.md` — Tue–Thu 9:00–12:00 ET, original title, canonical URL, be in the
   thread 24–48 h. Never solicit votes.
5. **LinkedIn**: `.linkedin.md` native post the same week (not the same morning as HN);
   Substack link via comment after initial distribution.
6. **r/selfhosted**: per `.reddit.md`, context comment immediately. r/kubernetes a few days
   later. Never simultaneous.
7. **dev.to**: `.devto.md` with canonical set, `published: true`.
8. **Lobsters**: only if invited; "authored by" ticked.
9. One post per venue per piece; no resubmissions.

## Variant inventory

| File | Audience | State |
| --- | --- | --- |
| `BLOGPOST-dark-factory.md` | Substack canonical | v2, swept, awaiting ownership pass |
| `.linkedin.md` | LinkedIn native | v2 (cost-led hook, ~1.9k chars) |
| `.hn.md` | Hacker News | v2 (submission plan + 6 prepared answers) |
| `.devto.md` | dev.to | new (condensed architecture cut, frontmatter ready) |
| `.reddit.md` | r/selfhosted, r/kubernetes | new (titles + context comments) |
| `.draft-v1.md` | archive | frozen v1 |
| `.research.md` | evidence | every claim traces here |
