# Rationale — the evidence behind each rule

Why the skill's rules are what they are, with sources. Labels: **EVIDENCE** (study/RCT/
large-N dataset), **CONSENSUS** (independent vendors/practitioners converge),
**CONTESTED** (credible published disagreement), **VENDOR** (self-reported, unaudited).

## The ticket is the agent's prompt

- **EVIDENCE** — 3,180 real Copilot-coding-agent PRs (AIDev dataset): well-scoped issues
  +16% merge rate, self-contained +17%, unambiguous +8%, actionable steps +8%; **longer
  descriptions −9%**, external dependencies −7%, environment specs −9%,
  performance-sensitive work −34%.
  [arxiv.org/html/2512.21426v1](https://arxiv.org/html/2512.21426v1)
  → the skeleton, the concision cap, self-containedness, splitting env/setup out, and
  routing performance-sensitive work to humans.
- **EVIDENCE** — UnderSpecBench (2,208 prompt variants, Claude Code/Codex/OpenCode):
  safe success 67.9% → 8.6% as underspecification rises; wrong-target actions 9.6% →
  75.1%. Agents guess instead of asking ([arxiv.org/pdf/2607.02294](https://arxiv.org/pdf/2607.02294));
  Ambig-SWE: interactivity recovers up to 74%, but "models default to non-interactive
  behavior unless explicitly prompted"
  ([arxiv.org/html/2502.13069](https://arxiv.org/html/2502.13069))
  → burn ambiguity down before dispatch; zero open design choices at agent-ready.
- **EVIDENCE** — "What makes a good bug report for an AI agent" (433 SWE-bench issues ×
  87 agents + ablation): fix suggestions 3.6× resolution odds, code snippets 2.8×,
  *executable* repro scripts 2.5×, file/module localization 2.3×; prose repro steps ≈
  nothing; **markdown structure alone worth 10–30 solve-rate points**
  ([arxiv.org/html/2607.07593v1](https://arxiv.org/html/2607.07593v1))
  → bug template with runnable repro + localization hint; headings are load-bearing.
- **CONSENSUS** — GitHub, Anthropic, OpenAI, Cognition converge on the same anatomy:
  problem + complete acceptance criteria + file pointers
  ([GitHub Copilot agent best practices](https://docs.github.com/copilot/how-tos/agents/copilot-coding-agent/best-practices-for-using-copilot-to-work-on-tasks)) ·
  "Give Claude a check it can run … If you can't verify it, don't ship it"
  ([Claude Code best practices](https://code.claude.com/docs/en/best-practices)) ·
  Goal/Context/Constraints/Done-when ([OpenAI Codex guidance](https://learn.chatgpt.com/guides/best-practices)) ·
  "be opinionated", clear requirements + verifiable outcomes at junior-engineer 4–8h size
  ([Devin guidelines](https://docs.devin.ai/essential-guidelines/instructing-devin-effectively),
  [Cognition 18-month review](https://cognition.com/blog/devin-annual-performance-review-2025))
  → the agent-ready gate's seven criteria.
- **CONSENSUS** — pointers beat payloads: context engineering = the "smallest possible
  set of high-signal tokens"; prefer file paths/links over pasted content
  ([Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).

## Two readers — functional on top, technical below

- **EVIDENCE** — what developers need from a bug report (Apache/Eclipse/Mozilla survey,
  156 developers): steps to reproduce rated most important (83%); the worst problems are
  errors in those steps (79%) and incomplete information (74%) — "non-technical
  language" bothered only 19%. Reporters find test cases and code examples hardest to
  supply ([Bettenburg et al., FSE 2008](https://thomas-zimmermann.com/publications/files/bettenburg-fse-2008.pdf))
  → plain language on top costs developers nothing as long as repro and facts are
  right; the code-level half is what the researcher adds, not what the reporter must.
- **EVIDENCE** — issue body length is the top-ranked feature against agent merges
  (AIDev study above); file/module hints and edge cases specified raise them
  → the technical half stays, as pointers.
- **CONSENSUS** — specifications describe behaviour, not implementation: "Will this
  wording need to change if the implementation does?"
  ([Cucumber: Writing better Gherkin](https://cucumber.io/docs/bdd/better-gherkin/));
  the card is a reminder of a conversation, the acceptance test its confirmation
  ([Jeffries, Card/Conversation/Confirmation](https://ronjeffries.com/xprog/articles/expcardconversationconfirmation/));
  rules paired with concrete examples ([Adzic](https://gojko.net/2008/11/04/specifying-with-examples/))
  → the implementation-change test, observable criteria with examples.
- **CONSENSUS** — customer-facing part first, technical questions after: Amazon's PR/FAQ
  (one page, no jargon, then an internal FAQ — [Working Backwards](https://workingbackwards.com/concepts/working-backwards-pr-faq-process/));
  Google design docs keep context factual and non-goals as things "that could
  reasonably be goals" ([Design docs at Google](https://www.industrialempathy.com/posts/design-docs-at-google/))
  → the order of the halves; Not in scope ≠ negated criteria.
- **CONSENSUS** — specialists prefer plain language too ("the more specialist their
  knowledge, the greater their preference for plain English" —
  [GOV.UK](https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/writing-guidelines/clear-language/);
  [NN/g, plain language for experts](https://www.nngroup.com/articles/plain-language-experts/));
  conclusion first ([NN/g, inverted pyramid](https://www.nngroup.com/articles/inverted-pyramid/));
  split sentences over 25 words (GOV.UK), Dutch B1 15–20
  ([Schrijfwijzer IPLO](https://iplo.nl/digitaal-stelsel/toepasbare-regels/maken-testen/schrijfwijzer/schrijftips-taalniveau-b1/))
  → the plain-language rules on the functional half.

## Verification and anti-gaming

- **EVIDENCE** — reward hacking is measured: RL post-training raised exploit rates 0.6%
  → 13.9% ([arxiv.org/html/2605.02964](https://arxiv.org/html/2605.02964)); TRACE
  benchmark (517 trajectories, 54 hack categories): best detector catches only ~63%
  (hard-coded outputs, edited tests)
  ([arxiv.org/html/2601.20103v1](https://arxiv.org/html/2601.20103v1))
  → protected areas always include tests + CI config; held-out checks at review; green
  CI alone never closes a ticket; fresh-context review against intent and scope.
- **EVIDENCE** — LLMs "improving" tickets hallucinate absent Expected/Actual sections
  ~50% of the time even when told not to
  ([arxiv.org/html/2504.18804](https://arxiv.org/html/2504.18804))
  → the MISSING-marker rule: gaps become explicit questions, never synthesized content.
- **EVIDENCE** — testability is the one universally evidenced criterion property: EARS
  measurably reduced ambiguity/vagueness at Rolls-Royce (single industrial case study,
  not a controlled experiment)
  ([Mavin et al., RE'09](https://research.manchester.ac.uk/en/publications/easy-approach-to-requirements-syntax-ears/));
  adopted as AWS Kiro's AC grammar ([kiro.dev/docs/specs](https://kiro.dev/docs/specs/)).
  No controlled evidence that Gherkin beats plain checklists; BDD reviews show real
  maintenance cost ([IEEE](https://ieeexplore.ieee.org/document/10210040/))
  → EARS as default behavior-criterion grammar; Given/When/Then only where it becomes a test.

## The review bottleneck

- **VENDOR** (telemetry; magnitudes unaudited, direction corroborated by LinearB and
  DORA) — Faros AI, 10k+ devs, 1,255 teams: high-AI teams +21% tasks, +98% merged PRs,
  but **review time +91%, PR size +154%, bugs +9%, org-level DORA flat**
  ([faros.ai on DORA 2025](https://www.faros.ai/blog/key-takeaways-from-the-dora-report-2025));
  2026 update (22k devs): task throughput +34%, review time +441%, 31% more PRs merged
  unreviewed, agent PRs wait ~5× longer for pickup
  ([faros.ai 2026 report](https://www.faros.ai/blog/ai-acceleration-whiplash-takeaways),
  [LinearB benchmarks](https://blog.exceeds.ai/linearb-code-review-metrics-2026/))
  → WIP anchored on review capacity (3–5 per reviewer); review column with own cap +
  SLE; "clear the review queue" beats "start more".
- **EVIDENCE** — DORA 2024: +25% AI adoption ↔ −1.5% throughput, −7.2% stability; DORA
  2025: throughput flips positive, instability stays negative — AI is an amplifier;
  small batches are the converting mechanism
  ([dora.dev/dora-report-2025](https://dora.dev/dora-report-2025/),
  [AI capabilities model](https://dora.dev/ai/capabilities-model/report/))
  → split gates are not hygiene, they're the mechanism; every speed metric paired with
  a stability guardrail.
- **CONSENSUS** — "full kit" review packets (what/why/risk/evidence/limitations) exploit
  the constraint ([Yuval Yeret](https://yuvalyeret.com/blog/ai-coding-made-code-review-the-bottleneck/))
  → the evidence-comment format.
- **CONSENSUS** (documented incident, not a study) — curl's bug bounty drowned in AI
  slop (~20% of submissions, ~5% genuine); its test suite was the effective filter
  ([LeadDev](https://leaddev.com/software-quality/open-source-has-a-big-ai-slop-problem))
  → every criterion maps to an automated check; no human review until gates are green;
  machine-authored tickets enter as draft, never agent-ready.

## Ownership and process shape

- **CONSENSUS** — Linear's delegation model: agent = delegate, human stays accountable
  owner; agents disclose, acknowledge, emit progress
  ([linear.app/developers/agents](https://linear.app/developers/agents),
  [AIG](https://linear.app/developers/aig)) → the claim protocol.
- **CONSENSUS** — mid-task scope change is a top agent-failure cause; corrections go as
  PR comments, new scope = new ticket
  ([GitHub agentic workflows](https://github.blog/ai-and-ml/github-copilot/from-idea-to-pr-a-guide-to-github-copilots-agentic-workflows/),
  [Cognition](https://cognition.com/blog/devin-annual-performance-review-2025)).
- **CONSENSUS** — risk tiers decide automation level; human approval mandatory for
  critical code; least-agency identities
  ([Anthropic AI-native SDLC](https://claude.com/blog/how-anthropic-secures-its-ai-native-software-development-lifecycle),
  [Microsoft least privilege for agents](https://www.microsoft.com/en-us/security/blog/2026/07/16/least-privilege-for-ai-agents-identity-access-and-tool-binding/)).
- **CONTESTED** — spec-driven maximalism: Spec Kit produced 2,577 markdown lines for 689
  code lines, ~10× slower than iterative prompting on small work
  ([Scott Logic](https://blog.scottlogic.com/2025/11/26/putting-spec-kit-through-its-paces-radical-idea-or-reinvented-waterfall.html))
  → ceremony scales with size × risk × ambiguity; chores stay title + Problem.
- **VENDOR** — Atlassian's AI-native team: tickets as "executable specs" scored 4.47/5
  vs 2.72, 83% vs 6% agent-ready, widest gap = AC clarity; ~180 small tickets/engineer
  vs ~43 ([Atlassian](https://www.atlassian.com/blog/jira/writing-tickets-for-ai-agents))
  — treat the multipliers as marketing, the ticket-shape recipe as corroboration.

## Merging — the Definition of Mergeable

- **CONSENSUS** — the name is ours; the split is not. "Definition of Mergeable" is not an
  established term, but a pre-merge gate distinct from done is: GitLab runs a pre-merge
  MR checklist plus items "checked after the merge request has been merged"
  ([GitLab DoD](https://docs.gitlab.com/development/definition_of_done/)); CharlieHR's
  "ready to merge" vs "actually done" (2017) is the same two-level cut
  → the DoM/DoD boundary; a change can be mergeable while its ticket is not done.
- **CONSENSUS** — the Not Rocket Science Rule: "automatically maintain a repository of
  code that always passes all the tests"
  ([Graydon Hoare](https://web.archive.org/web/2024/https://graydon2.dreamwidth.org/1597.html));
  "test each change applied to the tip of the branch exactly as it is going to be merged"
  ([Zuul](https://zuul-ci.org/docs/zuul/latest/gating.html)) → the invariant and line 1.
- **EVIDENCE** — a green head is not a green merge: ≈9% of textually clean merges (133 of
  1,428) broke the build or tests, a third of all conflicts
  ([Brun et al., TSE 2013](http://people.cs.umass.edu/brun/pubs/pubs/Brun13tse.pdf));
  replaying merges found build+test conflicts in 20–39% per project
  ([Kasi & Sarma, ICSE 2013](http://web.engr.oregonstate.edu/~sarmaa/wp-content/uploads/2020/08/2486788.2486884.pdf));
  Uber: 5% real-conflict chance with 2 concurrent changes, 40% with 16; changes 1–10 h
  stale had a 10–20% chance of turning main red; iOS main was green 52% of the time
  before a submit queue ([EuroSys 2019](https://www.masoud.io/docs/eurosys19.pdf))
  → up-to-date rule or merge queue; a freshness bound is the fallback.
- **VENDOR** (docs, Forgejo source-verified) — forge "mergeable" is a conflict predicate:
  GitHub's field is "based on the existence of merge conflicts"; required checks pass on
  `success`, `skipped` or `neutral`; a job skipped after a failed dependency "may not
  block merging"; path-filtered required checks hang pending
  ([GitHub](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)).
  Forgejo's `mergeable` ignores protection, Actions PR runs test the head, and no merge
  queue exists ([gitea#36392](https://github.com/go-gitea/gitea/issues/36392)); GitLab
  lets an older passing MR pipeline satisfy the check
  ([GitLab auto-merge](https://docs.gitlab.com/user/project/merge_requests/auto_merge/))
  → the enforcement table and the forge traps.
- **EVIDENCE** — red is mostly real, and flaky is a defect: only 12.8% of CI test
  failures are flaky ([Labuschagne et al., FSE 2017](https://www.cs.ubc.ca/~rtholmes/papers/fse_2017_labuschange.pdf));
  24% of flaky-test fixes changed the code under test, 94% of those fixing a real bug
  ([Luo et al., FSE 2014](http://mir.cs.illinois.edu/marinov/publications/LuoETAL14FlakyTestsAnalysis.pdf));
  35.2% of builds with failing tests still passed overall
  ([Beller et al., MSR 2017](https://gousios.org/pub/tests-broke-build-explorative-analysis-travis-ci-github.pdf));
  failed CI is the strongest pre-merge technical signal against merging (OR 0.65,
  [Zhang et al., TSE 2023](https://arxiv.org/pdf/2105.13970)). Google: ~1.5% of test
  runs flaky and ~84% of pass→fail transitions involve a flaky test (**VENDOR**,
  [testing blog](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html)).
  Auto-retry is **CONTESTED** among experts
  ([Zampetti et al., EMSE 2020](https://digitalcollection.zhaw.ch/bitstreams/b9a428d1-322e-460e-b4fa-4f18fa60b06e/download))
  → one bounded rerun plus a flaky-test ticket; a gate that reports green over failing
  tests is a finding.
- **EVIDENCE** — one reviewer is the norm: Google's median is 1, fewer than 25% of
  changes have more; median change 24 lines
  ([Sadowski et al., ICSE-SEIP 2018](https://sback.it/publications/icse2018seip.pdf));
  DORA: heavy multi-approval review is a pitfall and external approval showed "no
  evidence" of lower change failure
  ([DORA](https://dora.dev/capabilities/streamlining-change-approval/)). **CONTESTED**:
  Rigby & Bird's two-reviewer convergence is descriptive, and no study tests "require 2"
  against "require 1" in async review. What predicts quality is *who* reviews: repeat
  reviewers of a file write 65–71% useful comments vs 32–37% for first-timers
  ([Bosu et al., MSR 2015](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/bosu2015useful.pdf));
  the share of non-expert reviewers tracks post-release defects
  ([Thongtanunam et al., ICSE 2016](https://rebels.cs.uwaterloo.ca/papers/icse2016_thongtanunam.pdf)),
  as do changes merged without discussion
  ([McIntosh et al., EMSE 2016](https://rebels.cs.uwaterloo.ca/papers/emse2016_mcintosh.pdf));
  in a security-review study no single reviewer found all 7 planted vulnerabilities
  (mean 2.33) ([Edmundson et al., ESSoS 2013](https://people.eecs.berkeley.edu/~daw/papers/coderev-essos13.pdf))
  → one qualified non-author; a second by risk tier, security paths first.
- **CONSENSUS** — approval binds to the final revision: GitHub stale-approval dismissal
  and last-push approval, GitLab "authors and people who add commits cannot approve",
  Azure DevOps "prohibit the most recent pusher from approving"
  ([Azure](https://learn.microsoft.com/en-us/azure/devops/repos/git/branch-policies))
  → line 4.
- **CONSENSUS** — nits never block: Google approves "even if the CL isn't perfect" and
  allows LGTM-with-comments ([eng-practices](https://google.github.io/eng-practices/review/));
  Conventional Comments' blocking/non-blocking decorations
  ([conventionalcomments.org](https://conventionalcomments.org/)); GitLab: "enforce code
  style through automation rather than review comments" → line 5.
- **EVIDENCE** for direction, thresholds **CONTESTED** — defect risk rises with files
  touched and churn ([Kamei et al., TSE 2013](https://posl.ait.kyushu-u.ac.jp/~kamei/publications/Kamei_TSE2013.pdf));
  the useful share of review comments falls as files grow, noticeably from ~20 files
  ([Bosu et al., MSR 2015](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/bosu2015useful.pdf),
  [Czerwonka et al., ICSE-SEIP 2015](https://www.microsoft.com/en-us/research/wp-content/uploads/2015/05/PID3556473.pdf));
  small PRs do *not* clearly merge faster (r_s 0.26,
  [Kudrjavets et al., MSR 2022](https://arxiv.org/pdf/2203.05045)). Google: "100 lines is
  usually a reasonable size … 1000 lines is usually too large" (**CONSENSUS**,
  [small CLs](https://google.github.io/eng-practices/review/developer/small-cls.html));
  SmartBear's 200–400 LOC is **VENDOR** with a density artifact
  → a split trigger on lines *and* files with a stated-reason escape, never a cap.
- **CONTESTED** — coverage as a gate: low-to-moderate correlation with suite
  effectiveness once suite size is controlled
  ([Inozemtseva & Holmes, ICSE 2014](https://www.cs.ubc.ca/~rtholmes/papers/icse_2014_inozemtseva.pdf))
  vs R² 0.94 across 1,254 projects ([Gopinath et al., ICSE 2014](https://agroce.github.io/icse14.pdf)).
  Not contested: Google enforces no global threshold
  ([Ivanković et al., FSE 2019](https://storage.googleapis.com/gweb-research2023-media/pubtools/5172.pdf));
  >80% of surveyed Codecov users sometimes ignore failing coverage checks
  ([Sterk et al., AST 2024](https://repository.tudelft.nl/file/File_a7da55d7-f73d-412d-91f0-27a7ea40313f));
  mutants shown during review coupled to 70% of Google's high-priority bugs
  ([Petrović et al., ICSE 2021](https://arxiv.org/pdf/2103.07189))
  → changed lines executed and asserted, mutants in review where available, no % gate.
- **EVIDENCE** — review is not the bug filter: 14% of review comments concern defects
  ([Bacchelli & Bird, ICSE 2013](https://sback.it/publications/icse2013.pdf)); ~75% of
  findings are maintainability, across five settings
  ([Mäntylä & Lassenius, TSE 2009](https://aaltodoc.aalto.fi/bitstreams/cab054e8-0c06-47ab-8754-54bb09a0a6d3/download),
  [Beller et al., MSR 2014](https://sback.it/publications/msr2014.pdf))
  → tests and gates own correctness; review owns intent, scope, design.
- **CONSENSUS** + single-company **EVIDENCE** — blocking gates need near-zero false
  positives; findings shown at review time get fixed, batch reports mostly don't
  (Google FindBugs fixit: 16% fixed; [Sadowski et al., CACM 2018](https://cseweb.ucsd.edu/~dstefan/cse227-spring20/papers/sadowski:lessons.pdf);
  Facebook Infer diff-time fix rate >70%, an experience report,
  [CACM 2019](https://discovery.ucl.ac.uk/id/eprint/10084236/1/O'Hearn%20AAM%20scaling-static-analysis-at-facebook.pdf));
  81% of leaked secrets were never removed and no repo rewrote history
  ([Meli et al., NDSS 2019](https://www.ndss-symposium.org/wp-content/uploads/2019/02/ndss2019_04B-3_Meli_paper.pdf))
  → block on near-zero-FP checks and secrets; everything else advisory, in the PR.
- **EVIDENCE** (RCTs, single company each) — review latency is movable: nudging overdue
  PRs cut their mean lifetime 197 h → 78 h
  ([Maddila et al., TOSEM 2022](https://arxiv.org/pdf/2011.12468)); Meta's NudgeBot cut
  time in review 6.8% ([Shan et al., FSE 2022](https://users.encs.concordia.ca/~pcr/paper/NudgeBot2022FSE-preprint.pdf));
  29–63% of review lifetime is idle after acceptance
  ([Kudrjavets et al., MSR 2022](https://arxiv.org/pdf/2203.05048)); no response is the
  top abandonment reason ([Li et al., TSE 2021](https://yuyue.github.io/res/paper/abPR_TSE2021.pdf)).
  One business day to first response is **CONSENSUS**
  ([Google](https://google.github.io/eng-practices/review/reviewer/speed.html))
  → the review SLE, nudges, auto-merge on approved-and-green.
- **CONSENSUS** — main stays releasable: "all code sent to the mainline is production
  quality" with latent code dark behind toggles
  ([Fowler, CI](https://martinfowler.com/articles/continuousIntegration.html)); test a
  release toggle in both states and ticket its removal
  ([Hodgson](https://martinfowler.com/articles/feature-toggles.html)); expand/contract
  ([parallel change](https://martinfowler.com/bliki/ParallelChange.html)); "updating is
  not atomic" ([GitLab multi-version](https://docs.gitlab.com/development/multi_version_compatibility/))
  → lines 9–11.

### Agent-authored changes

- **EVIDENCE** (MSR'26 short / peer) — self-merge dominates: 77.5% of merged agent PRs
  were merged by their submitter vs 57.6% for human PRs
  ([arxiv 2601.18749](https://arxiv.org/html/2601.18749)); 61.4% of 33,596 agent PRs
  had no recorded review, and of the reviewed, 58.8% were reviewed by AI only
  ([Duma et al., EASE 2026](https://arxiv.org/abs/2605.02273)) → builder ≠ judge.
- **VENDOR** (documented behavior) — GitHub's coding agent cannot approve, merge, or
  mark its PR ready, and the requester cannot approve it
  ([GitHub](https://docs.github.com/en/copilot/concepts/agents/coding-agent/risks-and-mitigations));
  GitLab attributes agent MRs to the triggering human for segregation of duties
  ([GitLab](https://docs.gitlab.com/user/duo_agent_platform/composite_identity/))
  → approver ≠ dispatcher.
- **EVIDENCE** — AI review is an input: best system on 1,000 PRs reaches precision
  16.7%, recall 23.2% ([SWR-Bench, FSE 2026](https://arxiv.org/html/2509.01494)); PRs
  reviewed only by AI merge 45.2% vs 68.4%
  ([arxiv 2604.03196](https://arxiv.org/html/2604.03196v1)); models favor their own
  output ([Panickssery, NeurIPS 2024](https://arxiv.org/abs/2404.13076)); reviewers
  anchor on the lines an LLM flags
  ([Tufano, ICSE 2025](https://arxiv.org/abs/2411.11401)); PR-description framing slipped
  known CVEs past AI review 32/33 times (preprint,
  [arxiv 2603.18740](https://arxiv.org/abs/2603.18740)) → never the approval; the
  agent's description is untrusted input.
- **EVIDENCE** — tests: thin, not deleted. In real PRs agents delete tests *less* than
  humans (0.9% vs 4.8%) ([arxiv 2601.21194](https://arxiv.org/abs/2601.21194)); only
  49.6% of agent PRs changing testable code touch tests and 64.8% of Python ones execute
  no changed line ([ICSME 2026](https://arxiv.org/abs/2607.18057)); 80.2% of agent test
  patches have weak or no oracle ([AITest 2026](https://arxiv.org/abs/2606.18168)). Under
  pressure they do cheat: >79% of Claude-model cheating on impossible tasks is test
  modification, and read-only tests stop edits but not other hacks
  ([ImpossibleBench, ICLR 2026](https://arxiv.org/abs/2510.20270)); cheating =
  passes, and fails once the test changes are reverted
  ([Baker et al.](https://arxiv.org/abs/2503.11926)) → the revert check; test-touching
  hunks reasoned, not banned (legitimate test edits exist); changed lines executed and
  asserted.
- **EVIDENCE** — claims drift from diffs: "phantom changes" are 45.4% of agent
  description/code inconsistencies, and such PRs merge 28.3% vs 80.0%
  ([MSR'26](https://arxiv.org/html/2601.04886)); only 11% of merged agent performance
  fixes carried a benchmark, and 9 of 30 re-run showed no gain or a regression (preprint,
  [arxiv 2609.37985](https://arxiv.org/html/2609.37985)) → claims carry evidence.
- **EVIDENCE** — dependencies: agents pick a known-vulnerable version 2.46% vs 1.64%,
  with a fixed version available 86.6% of the time
  ([arxiv 2601.00205](https://arxiv.org/abs/2601.00205)); 19.7% of suggested packages
  are hallucinated and 43% of those recur, which makes them squattable
  ([USENIX Security 2025](https://www.usenix.org/system/files/usenixsecurity25-spracklen.pdf))
  → line 12.
- **POLICY**, trailer **CONTESTED** — every project that permits AI keeps a human
  accountable: "AI agents MUST NOT add Signed-off-by tags"
  ([Linux](https://docs.kernel.org/process/coding-assistants.html)); LLVM, Fedora and
  NixOS use `Assisted-by:`, NixOS rejects an AI `Co-authored-by:`, Kubernetes forbids AI
  trailers; 83% of accountability-stance policies require disclosure
  ([ASE 2026](https://arxiv.org/abs/2603.26487)) → the trailer is a contract fact.
- **EVIDENCE** (preprints) — the gate habituates: approval of agent PRs rose 30.1% →
  36.8% while inline comments fell 22% ([arxiv 2606.22721](https://arxiv.org/abs/2606.22721));
  substantive human review fell from ~39% to ~21% of PRs at one company
  ([arxiv 2607.01904](https://arxiv.org/html/2607.01904v1)); merged agent PRs draw
  verified follow-up fixes at 1.62× the odds of human ones
  ([arxiv 2609.26847](https://arxiv.org/abs/2609.26847)) → zero-comment approvals as a
  guardrail; the post-merge watch.
- **EVIDENCE** (MSR'26 short) — rejections: reviewer abandonment 38%, duplicates ~23%,
  CI failure ~17% of 600 rejected agent PRs
  ([arxiv 2601.15195](https://arxiv.org/html/2601.15195)); only 35.7% of rejections are
  clear agent failures and 33.1% carry no rationale
  ([arxiv 2605.22534](https://arxiv.org/abs/2605.22534)); task type spreads merge rates
  29 points, more than the agent does ([arxiv 2602.08915](https://arxiv.org/html/2602.08915v2))
  → a reason on every unmerged close; measure per class, not per vendor.

## Flow, forecasting, prioritization

- **CONSENSUS** (normative standard, not a study) — Kanban Guide 2025.5:
  WIP/Throughput/Work Item Age/Cycle Time mandatory;
  SLE = elapsed time + probability; Work Item Age is the only leading indicator;
  right-sizing = "fits the SLE?"
  ([kanbanguides.org](https://kanbanguides.org/the-kanban-guide/2025.5/),
  [Open Guide](https://kanbanguides.org/open-guide-to-kanban/2025.7/)).
- **CONSENSUS** — Monte Carlo over item counts replaces points; "plans based on averages
  fail on average"; forecasts void on regime change (agent adoption is one)
  ([InfoQ/#NoEstimates](https://www.infoq.com/articles/noestimates-monte-carlo/)).
- **CONSENSUS** — Reinertsen holds: queue time dominates cycle time (Maersk: one feature,
  38 weeks in queues, ~$8M delay cost); CD3 sequencing; **summed-ordinal WSJF is
  undefined arithmetic** ([Black Swan Farming](https://blackswanfarming.com/cost-of-delay/),
  [Jason Yip](https://jchyip.medium.com/problems-i-have-with-safe-style-wsjf-772df2beaf02))
  → cost-of-delay classes + shortest-job-first; scores structure arguments, never auto-rank.
- **CONSENSUS** — confidence needs an evidence ladder (opinion → anecdote → data →
  experiment), or every idea scores maximum
  ([Itamar Gilad](https://itamargilad.com/tag/prioritization/)).
- **CONTESTED** — backlog bankruptcy: bulk-close stale *internal ideas* ("really
  important ideas will come back to you", [Shape Up](https://basecamp.com/shapeup/2.1-chapter-07),
  [Mountain Goat](https://www.mountaingoatsoftware.com/blog/product-backlog-bankruptcy));
  but stale-bots on user-reported issues destroy trust
  ([kubernetes#103151](https://github.com/kubernetes/kubernetes/issues/103151))
  → the class-split staleness policy.
- **CONSENSUS** — metrics get gamed as targets (Goodhart); DORA warns against ranking
  teams/individuals ([How to misuse DORA metrics](https://newsletter.getdx.com/p/misuse-dora))
  → system-level only, never per-assignee.

## Debunked — never cite these

- **The 1×/10×/100× defect-cost curve**: traced to untraceable 1981 training notes
  (Bossavit); the largest study (171 projects) found **no delayed-issue effect**
  ([Menzies et al., EMSE 2017](https://arxiv.org/pdf/1609.04886)). The defensible
  justification for refinement gates is wrong-work risk (quantified above).
- **Perceived AI speed**: METR RCT — 16 experienced maintainers, 246 real tasks, **19%
  slower with AI while believing 20% faster**
  ([arxiv.org/abs/2507.09089](https://arxiv.org/abs/2507.09089)) → measure the board's
  own per-class outcomes; never plan on vendor multipliers.
- **INVEST / the user-story template as validated practice**: perception-only evidence
  ([Lucassen et al., REFSQ 2016](https://webspace.science.uu.nl/~dalpi001/papers/luca-dalp-werf-brin-16-refsq.pdf))
  → INVEST is a conversation heuristic; the story line is optional Problem-opener.
- **"Agents delete tests to get green" as a real-world base rate**: the strong evidence
  is from impossible-task benchmarks and training logs; in real PRs agents delete tests
  less than humans do (above). Cite it as a risk under pressure, not as what agent PRs
  typically do — the typical failure is thin tests.
- **SmartBear's "review 200–400 LOC, under 500 LOC/h, max 60–90 min" and "review finds
  70–90% of defects"** as evidence: vendor data with a density artifact; the time cap was
  never measured in that study, and the 70–90% is personal-review data grafted in.
- **"33% of clean merges have semantic conflicts"** (a misread of Brun: 33% is the share
  of all conflicts; ≈9% of clean merges) and **"16% of Google's tests are flaky"**
  unqualified (runs, tests-with-some-flakiness, and transitions are three denominators).
- **"Tests in a PR make it 17% more likely to merge"**: odds per standard deviation, and
  OR 1.02 at 3.35M PRs.
- **Agent merge rates without their denominator**: the same agent reads 52.5% or 83.8%
  depending on star threshold and whether open PRs count, and the AIDev paper's prose
  rates contradict its own table. Quote the table, the sample, and the filter — or don't.

## Deliberately NOT encoded (fashionable-but-wrong)

Story points / velocity / any estimate-theater field · mandatory "As a user…" templates ·
full spec pipelines on every ticket · mandatory Gherkin · summed-ordinal WSJF or precise
RICE as ranking authority · flow-efficiency percentage gates · hierarchies deeper than 3
levels or PI-planning cadence · age-based auto-closure of user-reported bugs ·
per-person/per-agent metric rankings · "the agent will ask when confused" as a safety
mechanism · exhaustive tickets as better tickets · vendor multipliers as planning
assumptions · two approvals on every PR · project-wide coverage-% merge gates · a
change board or manual QA sign-off before merge · merge freezes · hard line-count
limits · an AI review counted as the human approval · an agent merging on its own green.
