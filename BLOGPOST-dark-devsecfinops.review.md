# Review — Dark DevSecFinOps post (v2, 2026-07-31)

## Files

| File | What it is |
|---|---|
| `BLOGPOST-dark-devsecfinops.md` | The post. v2, ~3,550 words. |
| `.research.md` | Evidence. Every claim traces here. 10 sections. |
| `.draft-v1.md` | Frozen v1, kept because two review passes rewrote it substantially. |
| `.hn.md` / `.linkedin.md` / `.devto.md` / `.reddit.md` | Platform variants, regenerated for this post. |
| `.plan.md` | The 2026-07-30 planning doc that scoped it. |

## What changed between v1 and v2, and why

v1 was drafted, then put through a fresh-reader pass (a skeptical platform engineer given only the
draft) and an adversarial fact-check pass (given the draft and the evidence file). Both found
things that changed the post rather than its wording.

**The error that mattered most.** v1's closing table said the two `agent-builder` commits were
"README edits in another repository". They are not. `git log --author=agent-builder --name-only`
shows `ccb09d42` and `a5372aa4`, 18 and 6 files under `kubernetes/apps/erfbeeld/{dev,staging,
production}/app/`, promoting a CI-published image across three environments, both merged to `main`
on 22–23 July. Better than described, and also *not Ploeg's work* — they predate the dispatch
plane by a week. The evidence file carried the same error and now carries the correction.

**The contradiction that would have sunk it.** v1 opened with "from the ledger, not an estimate:
$0.019872" and then explained, 60 lines later, that per-run key revocation deletes the alias so the
ledger cannot say whose key was whose. The headline number was attributed by a mechanism the post
called broken. v2 discloses the matching method (spend windows on the clock) in the same paragraph
as the number.

**Three things v1 claimed that it should not have.** "One *independent* review" in the lede, which
the post retracts 300 lines later on the same-model-family grounds. "No bespoke operator on the
critical path", inherited from the July draft and flatly contradicted by Ploeg. "An idle factory
costs exactly nothing", contradicted by the post's own 73 W. All three are gone or explicitly
retired.

**Two things v1 omitted that a hostile reader would have supplied.** The reviewer has returned
exactly one verdict in its life and has never been given a planted bug, so `builder ≠ judge` is
undemonstrated — now stated. And prompt injection is nowhere in the design: the builder ingests
ticket text as instructions while holding a push token and a privileged daemon, and the only
control is that the board has one human user. Now stated as an open hazard.

**Structure.** The throughput table moved from 90% depth to the second section, on the argument
that it is the most credible thing in the piece and the best defence against the "another agent
post" reflex. The July backstory dropped from 34 lines to three paragraphs. Jargon that v1 used
before defining (forge, ledger, harness, Shift, `authorized=`) is now defined on first use.

**Title.** v1's "Dark DevSecFinOps: the loop, and how far round it I actually got" was retired.
Stacked `-Ops` coinages get mocked before the first line is read, and "how far round it I actually
got" parses badly. v2 leads with the specific failure instead.

Alternatives, if you want a different lean:
1. **"My AI agents wrote 2 of my last 594 commits"** — leads with the honesty deposit, disarms the
   top comment before it is written, does well on HN's taste for self-deprecation.
2. **"Reading a Kyverno policy doesn't tell you what it enforces"** — narrower, and arguably the
   better *first* post: self-contained, checkable, no AI framing to get past.

**De-AI-ify.** The fresh reader counted roughly twelve "not X, it's Y" antithesis constructions,
seven one-word punch sentences, and a portable maxim closing nearly every subsection, and called
the combination a recognisable generated-longform skeleton. v2 cuts the antitheses to five, drops
the maxim-per-section pattern, and thins the bolded-lead-in bullet stacks.

## Quantified checks

| Check | v1 | v2 |
|---|---|---|
| Words | 3,835 | ~3,550 |
| Em-dashes | 2 | 0 |
| Antithesis constructions | ~12 | 5 |
| Buzz-phrase hits | 0 | 0 |
| Carried-over private quotes | 0 | 0 |

The consent question from the July bundle is moot: neither anonymised Discord quote (the
$150-overnight figure, the small-model objection) survives into this post.

Zero em-dashes is slightly over-corrected. If the read-aloud pass wants a few back, that is fine;
the tell is overuse, not use.

## Still Ryan's hands, not an agent's

1. **The read-aloud ownership pass.** HN and Lobsters treat AI-generated prose as a flag reason.
   The sweeps above are cosmetic hygiene; they are not authorship. Read it aloud, rewrite anything
   that is not your sentence. No agent can do this step, including the one that drafted it.

2. **The manifests decision**, verified this morning:

   | repo | Forgejo | GitHub mirror |
   |---|---|---|
   | `webgrip/ploeg` | public, Go, LICENSE present | public, last pushed 2026-07-23 |
   | `webgrip/homelab-cluster` | public, YAML | public, last pushed 2026-07-25 |
   | `webgrip/erfbeeld` | **private** (404 unauthenticated) | — |

   Both GitHub mirrors are stale since the Forgejo cutover. Link Forgejo if
   `forgejo.webgrip.dev` is genuinely reachable from outside the LAN (only confirmable from
   outside it), otherwise link GitHub with one sentence saying the mirror lags. The post does not
   invite anyone to open erfbeeld, which is correct since it is private.

3. **Decide whether to merge PR #9 before publishing.** The post's present tense is "the review is
   in a database, waiting". Merging first changes three sentences and weakens the ending.

4. **Consider running the planted-bug test before publishing.** It is the one experiment that
   would convert the post's weakest claim into its strongest, and the HN thread will ask for it
   within the hour. If it comes back "approved anyway", that is a better post than this one.

## Before publishing, re-verify

Re-run the queries in `research.md` §2, §7 and §9. The throughput table moves daily, and the $1.40
lifetime spend only holds while the ledger is young (it started recording 2026-07-15).

## Publish order

1. Ownership pass, manifests decision, figures re-derived.
2. Substack canonical. Put the final URL into `.devto.md` frontmatter (`canonical_url`).
3. Wait 2–3 days for indexing.
4. **HN** per `.hn.md`: Tue–Thu 09:00–12:00 ET, original title, canonical URL, be in the thread
   24–48 hours. Never solicit votes.
5. **r/kubernetes** per `.reddit.md` (Kyverno angle), context comment immediately.
6. **LinkedIn** native post the same week, not the same morning as HN. Link via comment after
   initial distribution.
7. **r/selfhosted** a few days after r/kubernetes. Never simultaneous.
8. **dev.to** with `canonical_url` set and `published: true`.
9. Lobsters only if invited, "authored by" ticked.

## Housekeeping

The July bundle (`BLOGPOST-dark-factory.*`, 8 tracked files, never published, swept into an
unrelated CI commit by accident) still sits in the repo root. It contains an unfinished sentence
and a placeholder figure. Decide: move both bundles under a `drafts/` path, or delete the July one
now that its reusable content has been harvested into this post's plan and evidence.
