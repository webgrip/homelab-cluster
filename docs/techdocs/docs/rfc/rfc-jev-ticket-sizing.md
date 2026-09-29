# RFC: Ticket sizing with Jev

> Status: **Proposed** · Date: 2026-09-29 · Epic: [VIK-1410](https://vikunja.webgrip.dev/tasks/1410)
> (Dark Factory) · Extends the board contract's 3D estimation (`CLAUDE.md` "Board contract";
> product-owner skill `refine.md`, `flow.md`)

> **TL;DR.** Jev is a classifier-style model: it returns a level with a probability for every
> option instead of text. We use it as a **second estimator** for the three sizing axes
> (`effort/*`, `time/*`, `uncertainty/*`), never as the one who decides. The research is sober:
> automated estimators rarely beat a median guess, and people anchor on the number they are
> shown. So Jev has to earn its place on our own data. An offline backtest checks it against the
> closed tickets we already labelled **and** against what those tickets actually took (cycle time,
> Glide attempts and spend), and the "always M" guess has to lose first. If Jev passes, a blind
> shadow job sizes tickets after a human has labelled them. Only after that does it comment on
> tickets in refinement, where its most useful output is disagreement: a prompt to look at a
> ticket again. It never sets a sizing label and never grants `agent-ready`. Slice 0 is worth
> doing even if Jev fails: a written rubric with reference tickets, and a measurement of whether
> our own labels predict anything.

| Term | Meaning |
| --- | --- |
| **Axis** | One of the three sizing dimensions: effort (`S/M/L`), time (`hours/days/weeks`), uncertainty (`low/med/high`) |
| **Rubric** | The written definition of each level on each axis, with two reference tickets per level. Humans and Jev use the same text |
| **Proposal** | Jev's answer for one ticket: per axis the most likely level, the probability of every level, and Jev's confidence |
| **Actual** | What a closed ticket really took: lead time, Glide attempts, rounds and settled spend, commits carrying its `VIK-` trailer |
| **Shadow** | Jev sizes a ticket only after a human labelled it, so neither side can copy the other |
| **Sizer** | The scheduled job that builds a ticket's state, calls Jev through LiteLLM and writes the proposal |

## 1. Why

The three labels are not decoration. They gate agent work: `agent-ready` requires effort ≤ M
and uncertainty ≤ med (product-owner skill `agents.md`), and `uncertainty/high` forces a spike
first. Today whichever person or agent refines a ticket sets them. There is no written level
definition beyond the axis names, and nothing checks later whether an M really behaved like an M.
We do not know whether the labels are consistent, or whether they predict cost or lead time.

The owner wants a cheap, consistent second opinion. Jev fits the shape of the problem: it
answers typed questions with a probability per option, costs almost nothing, and LiteLLM
already carries it. The open questions are whether it sizes *our* tickets well, and how to use
it without teaching humans to copy it. This RFC answers the first with measurements before
anything is built, and the second with shadow mode and an anchoring check.

The skill's position still holds: **right-sizing replaces estimating** (`flow.md`). This is
not a return to story points or velocity. The axes exist to answer "does this fit, or must it be
split or spiked first?", and Jev is judged on that question.

## 2. Jev, as of 2026-09-29

Jev launched this month. Everything below is from the vendor docs and independent write-ups,
read on 2026-09-29. Verified in this repo where marked.

- **Shape.** `POST /v1/systemone` with `model`, `state` (text or JSON) and `questions`. A
  **Score** question takes 2–10 ordered level descriptions and returns `probabilities` per level,
  a weighted `score` and a `confidence`. Several questions go in one call and are evaluated
  **in isolation**: one answer is not context for another
  ([API](https://docs.typesafe.ai/api), [Score](https://docs.typesafe.ai/primitives/score.md),
  [primitives](https://docs.typesafe.ai/primitives.md)).
- **Levels describe situations, not degrees.** "Every level is evaluated separately. The model
  doesn't see a level's number or its neighbours." Bare numbers give it nothing to match against.
  A level can be an object with a description (`what`) and `examples`; examples unlike real
  inputs add nothing ([Score](https://docs.typesafe.ai/primitives/score.md),
  [advanced](https://docs.typesafe.ai/primitives/advanced.md)).
- **Confidence measures how spread the distribution is, not proven calibration.** For three
  levels it is `(3·max_p − 1)/2`, and the docs do not call it calibrated. No calibration curves
  have been published. The confidence page says below 0.5 route to a human and above 0.9 act, and
  that "the correct threshold values depend on your domain"; other pages give 0.6 and 0.85
  ([confidence](https://docs.typesafe.ai/confidence.md),
  [routing pattern](https://docs.typesafe.ai/patterns/confidence-routing.md),
  [Turing Post](https://www.turingpost.com/p/what-is-jev-rlcd)).
- **Documented weak spots** include date and duration comparisons, counting, and large
  irrelevant state ([jaggedness, jev-1.13](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)).
  That is the `time/*` axis and the long tail of our ticket descriptions.
- **No published evaluation of effort sizing.** Independent tests cover routing and reranking
  ([Parallel](https://parallel.ai/blog/testing-jev),
  [dev.to](https://dev.to/arifulislamat/typesafes-jev-model-is-it-really-193x-faster-and-444x-cheaper-56oa)).
- **Cost.** $0.042 per million input tokens, output free
  ([models](https://docs.typesafe.ai/models.md)). About $0.0001 per ticket at 2k tokens.
- **Access.** Direct signups are **paused since 2026-09-22**, no resume date; existing keys and
  resellers keep working ([report](https://jevainews.com/news/typesafe-signups-paused/)).
  Resellers: OpenRouter (`typesafe/jev-1.13`) and the Vercel AI Gateway
  ([OpenRouter](https://openrouter.ai/docs/guides/community/jev),
  [Vercel](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe)).
- **LiteLLM.** Supported as a provider **pass-through** at `/typesafe/v1/systemone`, not as a
  chat model. It injects `TYPESAFE_API_KEY` and tracks spend; no streaming
  ([docs](https://docs.litellm.ai/docs/pass_through/typesafe)). **Verified:** our deployed
  `litellm-database:v1.102.1` includes it (release notes: "backport the jev change set to
  stable/1.102.x for v1.102.1", BerriAI/litellm#42595). LiteLLM's egress already allows public
  443 (`kubernetes/apps/ai/litellm/app/networkpolicy.yaml`), so no policy change.
- **Sovereignty.** Closed weights. TypeSafe AI, Inc. hosts in the United States with no EU
  region; the DPA uses SCC Module 2; zero data retention is enterprise-only; the terms allow
  telemetry processing "without restriction"
  ([privacy](https://typesafe.ai/legal/privacy-policy),
  [DPA](https://typesafe.ai/legal/data-processing), [MCA](https://typesafe.ai/legal/mca)).
- **Exit path.** Laya (Apache-2.0, 421M parameters, runs on CPU) ships a Jev-compatible
  `laya-serve`, but its card says it is weak on ordinal scoring until fine-tuned
  ([Laya](https://huggingface.co/convaiinnovations/laya)). Because the API is the same, a
  self-hosted replacement is a base URL change, not a rewrite.

## 3. What the evidence says about automated estimation

Short version: **accuracy is the weakest reason to do this.** Independent replications of
automated story-point estimators find they rarely beat a median guess, and humans anchor on
whatever number they are shown. The value that survives the evidence is consistency, flagging
ambiguous tickets, and the actuals the evaluation forces us to record. The design follows from
that.

- **Estimators rarely beat a trivial baseline.** Deep-SE beat the median guess significantly in
  8 of 42 cases on replication ([Tawosi et al.](https://arxiv.org/abs/2201.05401)). GPT2SP, after
  a bug in its published MAE was fixed, beat the median in 6 of 16 projects within-project, and
  the median had the lowest error in 8 ([replication](https://arxiv.org/pdf/2209.00437)).
  Zero-shot GPT-4 did worse than the mean and median guesses; hand-picked examples helped, but the
  example selection saw the test set ([2403.08430](https://arxiv.org/pdf/2403.08430)). Recent
  LLM preprints reach a rank correlation of about 0.35–0.45 with the team's own labels
  ([2603.06276](https://arxiv.org/html/2603.06276v2)). Retrieval of similar past issues gave no
  significant gain ([2604.03443](https://arxiv.org/html/2604.03443v1)).
- **Our own examples beat none, if they cover the whole range.** Balanced examples covering every
  level beat examples drawn from the most frequent label, and few-shot models drift toward the
  majority label and the last example shown
  ([2603.06276](https://arxiv.org/html/2603.06276v2),
  [Zhao 2021](https://proceedings.mlr.press/v139/zhao21c/zhao21c.pdf)).
- **Human labels may not predict time either.** Across 37 projects, story points correlated
  strongly with development time in only 7 % of projects
  ([Tawosi ESEM'22](https://solar.cs.ucl.ac.uk/pdf/tawosi2022esem.pdf)). This is why §6.1
  measures our labels against actuals before measuring Jev against our labels.
- **Anchoring is robust, including on AI advice.** Anchors move professional estimates even when
  implausible ([Løhre & Jørgensen](https://cms.simula.no/sites/default/files/publications/files/lohre_jorgensen_-_anchors_software_estimation.pdf)),
  and experts overturned 7 % of correct judgments after wrong AI advice
  ([2603.11821](https://arxiv.org/abs/2603.11821)). On average, human and AI together do worse
  than the better of the two alone on decision tasks
  ([Vaccaro 2024](https://www.nature.com/articles/s41562-024-02024-1)). Hence R5.
- **Disagreement is useful.** Estimates reconciled after discussion beat averaged independent
  estimates ([Moløkken-Østvold 2008](https://www.sciencedirect.com/science/article/abs/pii/S0164121208000885)).
  A disagreement between Jev and the refiner is a prompt to look again, which is what slice 3
  delivers.
- **Agent work makes "effort" noisy.** Token use on the same task varies up to 30×, and expert
  difficulty matches token cost only weakly (τ = 0.32)
  ([2604.22750](https://arxiv.org/html/2604.22750v2)). Agents do worse on under-specified,
  "messier" tasks ([METR](https://arxiv.org/pdf/2503.14499)), which is what `uncertainty/*`
  should capture.
- **Goodhart pressure sits on uncertainty.** `uncertainty/low|med` makes a ticket eligible for
  an agent, so optimistic labelling is rewarded. An independent estimator that disagrees is a
  check on exactly that.

The papers are mostly Jira story points on public projects, several are 2026 preprints, and none
studies t-shirt sizing of agent-executed tickets on a one-person board. Treat them as priors
our own backtest can overturn.

## 4. Requirements

| # | Requirement | Why |
| --- | --- | --- |
| R1 | **Advisory only.** The sizer never sets `effort/*`, `time/*`, `uncertainty/*` or `agent-ready`. | The labels decide what an agent may pick up. Automation must not authorise its own work |
| R2 | **One rubric.** Level definitions and reference tickets live in one place. Humans read it, and the sizer generates Jev's criteria from it | Two rubrics drift, and then disagreement means nothing |
| R3 | **Fail loudly, never substitute.** A Jev error, timeout or unexpected `model` in the response means "no proposal" plus a metric. Never another model's guess | The 2026-09-28 Glide incident: a silent LiteLLM fallback looked like an agent that found nothing to do |
| R4 | **Beat a baseline before trust.** Each slice has a numeric gate against the majority-class guess and against the human labels | A number with no baseline is theatre |
| R5 | **Blind before visible.** Jev is measured on tickets a human already labelled before its proposals are shown on tickets in refinement | Visible proposals anchor humans, and agreement then measures copying |
| R6 | **Data scope by allowlist.** Only listed projects are sent. The state holds the title, description and non-sizing labels only, with no comments and no attachments | A US processor with no EU region and a broad telemetry clause |
| R7 | **Stateless and self-healing.** The sizer recomputes everything from the board, proves it ran, and alerts when stale | The board is the system of record, and a silent job looks like a quiet week |
| R8 | **Pinned and replaceable.** Record the served model version on every proposal. A version change re-runs the backtest. The client speaks the Jev API, so a Jev-compatible server can replace the vendor | `jev-latest` moves under us, and vendors retire models silently (Fireworks, VIK-1251) |

## 5. Design

### 5.1 The rubric (slice 0)

Three Score questions, three levels each, written as **situations**, with two real reference
tickets per level from our own board as the level's `examples`. The references cover every level
equally, because few-shot models drift toward the most frequent label (§3), and come only from
the earlier half of the history (§6.2). They carry no sizing labels or numbers, since models
anchor on numbers in the prompt ([FSE'25](https://dl.acm.org/doi/10.1145/3715771)). Draft to
refine against those references:

| Axis | Level 0 | Level 1 | Level 2 |
| --- | --- | --- | --- |
| **effort** | **S**: one manifest or file, one app, a pattern that already exists in the repo; the diff is reviewable in minutes | **M**: several files or one new component; follows an existing skill end to end; one PR | **L**: new app, cross-namespace change, migration, or anything that needs more than one PR; must name its first shippable slice or be split |
| **time** | **hours**: finishes inside one working session; no wait on a rollout, a soak, a person or another ticket | **days**: needs a reconcile-and-observe cycle, a soak of a day or so, or one handoff to the owner | **weeks**: several soaks or waits, a staged rollout, a seasonal or external dependency |
| **uncertainty** | **low**: the approach is written in the ticket and has been done here before | **med**: the approach is known, but one fact must be checked against live state or upstream first | **high**: the approach is unknown or disputed, the root cause is not established, or nothing like it exists in the repo; spike first |

The `time/*` levels deliberately avoid durations and comparisons, because Jev is documented as
weak on those. They describe waits, soaks and handoffs. The rubric lands in the board contract
(instance references) and the product-owner skill (the generic rule that levels are situations
with references). It helps human refinement even if Jev is dropped.

### 5.2 The state sent to Jev

A JSON object: `title`, `project`, `description` (HTML stripped to text, task-list checkboxes
rendered unchecked), `labels` excluding the three sizing axes, `repo` (from `repo/*`), and two
derived counts: acceptance criteria and whether a Verification section exists. Capped at 8k
tokens; a longer description is cut at the end of the Acceptance criteria section and the cut is
recorded. No comments, no attachments, no existing sizing labels. The last rule prevents
leakage in the backtest and anchoring in shadow.

### 5.3 From answers to a proposal

- Per axis, take the **most likely level** from `probabilities`, not the rounded `score`.
- Keep the full distribution. A near-even split between two levels is itself information: it is
  the ticket being ambiguous, which is what `uncertainty/*` should capture.
- The questions are isolated, so cross-axis rules live in code: flag (do not fix) combinations
  the rubric calls unusual, e.g. `effort/L` with `time/hours`.
- Derive **agent-ready eligibility** (effort ≤ M and uncertainty ≤ med) as a display value, never
  as a label.
- Thresholds are **tuned on our backtest**, per axis (§6). The vendor's numbers are a starting
  point only.

### 5.4 Where the sizer runs

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| **A. Offline script** reading the `vikunja-db` and `ploeg-db` datasources, calling Jev through LiteLLM | No cluster change; ideal for the backtest; reruns cheaply on a new Jev version | Nobody runs it on a schedule; no board output | **Slice 1** (backtest) |
| **B. CronJob sizer** in the cluster, same shape as the outcome-observation evaluator ([§7.2](rfc-outcome-observation-loop.md#72-shape-option-b)) | Deterministic, scheduled, stateless, metrics and a dead-man; the pattern is already designed | A Vikunja bot identity and a small program | **Slices 2–3**. Share the evaluator's image and program if it has shipped by then |
| **C. Glide intake hook**: size on ingestion, route by size | Glide already receives the webhook and knows the team tiers | Sizing is unproven; couples a new signal to agent dispatch | **Later**, only after slice 3 evidence (§8) |
| **D. Vellum "ask Jev" button** | On demand during refinement | UI work; the anchoring risk sits right next to the label picker | Rejected for now |

### 5.5 Plumbing (option B)

- **LiteLLM.** `TYPESAFE_API_KEY` in OpenBao KV, added to the existing `litellm-secret`
  ExternalSecret. The sizer gets its own virtual key with a small `max_budget`. The pass-through
  bypasses the chat router, so the `default_fallbacks: ["deepseek-chat"]` chain should not
  apply. **Slice 0 proves it** by calling with a revoked vendor key and checking that the error
  surfaces and no other model answers. It also proves whether key budgets and model scopes are
  enforced on pass-through routes. If they are not, the sizer enforces its own daily call cap.
- **Identity.** A Vikunja user `jev-sizer`, its token minted by the owner into OpenBao, wired
  by ExternalSecret. Its comments are attributable and revocable on their own, following decision 6 of the
  outcome RFC.
- **Idempotency.** Each proposal comment ends with a machine-readable line
  `jev-sizing: v1 state=<sha256 of the state> model=<served model>`. The sizer re-sizes a ticket
  only when the state hash or the model changes. No database.
- **Placement and network.** Worker pool (not the soyo recovery set); egress to `litellm` and
  `vikunja` only; hardened pod per the `provisioner-job` skill; digest-pinned image.
- **Monitoring.** `jev_sizer_last_success_timestamp`, `jev_sizer_proposals_total{axis,level}`,
  `jev_sizer_errors_total{reason}`, `jev_sizer_served_model_info{model}`. A `JevSizerStale`
  VMRule (last success older than 2 h) and a `JevModelChanged` warning. The run exits non-zero
  when it scans zero tickets in scope, so a revoked Vikunja token cannot pass as a quiet day.

### 5.6 The proposal comment (slice 3)

One comment per state hash, for example:

> **Jev sizing (advisory)** · effort **M** (S 0.12 · M 0.71 · L 0.17) · time **days** (0.55) ·
> uncertainty **med** (0.48, low confidence: consider refining) · agent-ready eligible: **yes** ·
> differs from current labels on: time (hours)

Low confidence on any axis is phrased as a refinement prompt, not a verdict. Disagreement with
existing labels is shown, and the human decides.

## 6. Evaluation

### 6.1 Three questions, three datasets

| Question | Data | Measure |
| --- | --- | --- |
| **Do our own labels predict anything?** | Closed tickets in projects 3, 5, 9, 10 carrying all three axes (the axes exist since 2026-07-18) joined to actuals | Spearman rank correlation and per-level medians of each axis against its actual (below) |
| **Does Jev agree with refined labels?** | The same tickets, state built without sizing labels | Confusion matrix, macro-averaged MAE on the level index, the S↔L (extreme swap) rate, and linear weighted kappa, per axis |
| **Does Jev predict actuals at least as well as we do?** | The same join | The same correlations as question 1, for Jev's levels, side by side with the human labels |

Actuals per axis:

- **effort**: for agent-run tickets, Glide settled spend, attempts and review rounds; for all
  tickets, the number of commits and changed lines carrying the ticket's `VIK-` trailer. Token
  cost is noisy (§3), so compare per-level medians, not single tickets.
- **time**: claimed→done cycle time, with the claim taken from the first `agent/<name>` claim
  comment or Glide's first run `started_at`. Where there is no measured start, created→done
  labelled as a lead-time proxy, as `flow_metrics.py` does.
- **uncertainty**: surprises. A Glide `needs_human` outcome or more than one attempt, a split or
  spike spawned after work started, a cycle time past the board's SLE.

Question 1 comes first. If the human labels predict nothing, agreement with them is a
meaningless target. The fix is then the rubric (§5.1), and Jev is re-measured against actuals
only.

Why these measures: off-by-one accuracy is nearly free on a three-level scale, because only S↔L
counts as a miss. Quadratic weighted kappa can ignore the middle cell with an odd number of
levels, so linear weighting is used instead
([Warrens 2012](https://link.springer.com/article/10.1007/s11336-012-9258-4)). Macro-averaged
MAE resists class imbalance ([Baccianella et al.](https://iris.cnr.it/retrieve/5bcf86c7-cd68-4884-93b5-ff86095082ec/prod_91979-doc_199135.pdf)).
Calibration is the Brier score plus an equal-mass reliability table (terciles by confidence),
because binned ECE is biased at small n ([Roelofs 2022](https://proceedings.mlr.press/v151/roelofs22a.html)).
At n = 60 a 95 % interval on accuracy is about ±13 points, so every comparison is a **paired
bootstrap** on the same tickets, never two point estimates side by side.

### 6.2 Leakage

- **Time order.** Tickets are split by refinement date. The rubric's reference tickets (§5.1) come
  only from the earlier part and are never scored. Test tickets never influence the choice of
  references or thresholds; thresholds are tuned on the earlier part and reported on the later.
- **Post-hoc text.** The sizer cannot see how a description looked at refinement time, so a
  closed ticket's description may contain text added during the work. Evidence normally goes
  into comments (Definition of Done), which the state excludes, and task-list boxes are reset to
  unchecked. The backtest is still labelled **optimistic**, and the blind shadow (slice 2) is the
  honest measure.
- **Versioned inputs.** The rubric text, the reference set and the Jev model version are recorded
  with every result, so a rerun is comparable or visibly not.

### 6.3 Gates

Proposed values (D4). An axis that fails its gate is dropped from proposals; the others continue.

| Gate | After | Pass condition, per axis |
| --- | --- | --- |
| **G0 labels mean something** | Slice 0 export | Human labels show a monotone per-level median against the axis's actual. If not, rewrite the rubric first; Jev is then gated on actuals only (G1b) |
| **G1a beats the baseline** | Slice 1 | Jev's macro-MAE is lower than the majority-level guess ("always M"), with the paired-bootstrap 95 % interval of the difference excluding zero |
| **G1b predicts actuals** | Slice 1 | Jev's rank correlation with the actual is at least the human labels' (interval of the difference includes or exceeds zero) |
| **G1c no extreme swaps** | Slice 1 | S↔L (or hours↔weeks, low↔high) on at most 5 % of tickets |
| **G1d confidence means something** | Slice 1 | Exact agreement in the top confidence tercile is higher than in the bottom tercile. If not, proposals never show confidence and never use it to suggest refinement |
| **G2 holds blind** | Slice 2, ≥ 30 tickets | The G1 measures stay inside the slice 1 intervals |
| **G3 no copying** | Slice 3, ≥ 30 tickets | Human–Jev exact agreement rises no more than 15 points above the slice 2 rate unless agreement with actuals rises too; otherwise the comment moves to after labelling |

If effort **and** uncertainty both fail G1, the Jev part stops. The rubric, the history export
and the actuals stay, because they improve human sizing on their own.

## 7. Slices

**Slice 0: rubric, data, access.** Each item is useful without Jev. Decisions [VIK-1411](https://vikunja.webgrip.dev/tasks/1411),
export [VIK-1412](https://vikunja.webgrip.dev/tasks/1412), rubric [VIK-1413](https://vikunja.webgrip.dev/tasks/1413), LiteLLM wiring [VIK-1414](https://vikunja.webgrip.dev/tasks/1414).

- The rubric (§5.1) with two reference tickets per level, in the board contract and the
  product-owner skill.
- The labelled-history export: closed tickets with their sizing labels joined to actuals from
  `vikunja-db`, `ploeg-db` and git trailers. Answers §6.1 question 1 on its own.
- Access decided (§9 D1) and wired: key in OpenBao, `litellm-secret` updated, sizer virtual key,
  and the fallback and budget proofs from §5.5.

**Slice 1: backtest** ([VIK-1415](https://vikunja.webgrip.dev/tasks/1415)). Script A over the export. The output is a techdocs page with the numbers,
the confusion matrices, a reliability table per confidence band, and the tuned per-axis
thresholds. Go or no-go against §6.3.

**Slice 2: blind shadow** ([VIK-1416](https://vikunja.webgrip.dev/tasks/1416)). Sizer B sizes only tickets whose three axes a human has already set,
then posts the proposal as a comment. At least 30 tickets or four weeks, whichever is later.
Go or no-go against §6.3.

**Slice 3: advisory at refinement** ([VIK-1417](https://vikunja.webgrip.dev/tasks/1417)). The sizer also comments on `needs-refinement` tickets that
have a Problem and Acceptance criteria but no sizing labels. Humans still set the labels. Measure
the **anchoring check**: if human–Jev exact agreement jumps well above the shadow rate while
agreement with actuals does not improve, humans are copying, and the comment moves back behind
the human's labelling.

## 8. What not to build

- **No auto-applied sizing labels and no auto `agent-ready`.** R1 holds at every slice. Revisit
  only with a separate RFC and months of slice 3 data.
- **No story points, velocity or hour estimates.** The axes stay ordinal and exist to right-size.
- **No Jev-driven Glide routing** until slice 3 shows Jev's effort predicts Glide spend. Then it is a
  Glide ADR, not a change here.
- **No fine-tuning or self-hosting now.** Jev has no tuning API, and Laya needs more labelled
  history than we have. Revisit on the triggers in §10.
- **No sizing of product or employer boards** without a decision (§9 D2).

## 9. Decisions for the owner

Tracked in [VIK-1411](https://vikunja.webgrip.dev/tasks/1411).

1. **D1 Access path.** Direct TypeSafe account (signups paused, wait), OpenRouter, or the Vercel
   AI Gateway. All three are US SaaS; the resellers add a second processor. Recommendation: wait
   for direct access and do slice 0's rubric and history export meanwhile, since they need no
   Jev. Use OpenRouter only if the wait blocks the backtest for more than a month.
2. **D2 Data scope.** Recommendation: the infra boards only (Homelab Roadmap 3, Dark Factory 5,
   Vellum 6, CI/CD 9, Ploeg 10). Exclude Internal Delivery Platform (83, employer work) and
   Erfbeeld (4, product) unless decided separately.
3. **D3 SaaS in the loop.** The sizer is advisory. When Jev is unavailable, refinement works as
   it does today and the sizer only goes stale. This is an advisory path, not an ops-path
   dependency, but it is a new US processor for ticket text. Accept, or wait for an EU or
   self-hosted option.
4. **D4 Thresholds in §6.3.** Proposed values; the owner confirms or adjusts before slice 1.

## 10. Re-evaluation triggers

- TypeSafe offers an EU region or zero data retention below enterprise tier.
- An open-weight, Jev-compatible model with published ordinal-scoring results appears, or the
  labelled history passes ~500 tickets (enough to fine-tune a small model).
- LiteLLM adds Jev as a native provider with key scoping.
- The served model version changes: re-run slice 1 automatically.

## 11. Further uses

Epic [VIK-1445](https://vikunja.webgrip.dev/tasks/1445) collects the other places where a stream of
short English text meets a fixed set of answers, and a human or code takes over when Jev is
unsure. Every child follows R1–R8: advisory only, fail loudly, beat a baseline first, and never
route data by model guess (the VIK-1259 guardrail: Omnigraph has no row-level security, so
destinations stay explicit).

| Use | Jev decides | Board | Ticket | Gate |
| --- | --- | --- | --- | --- |
| Self-hosted fallback | Can Laya (`laya-serve`, Jev API) replace Jev per question type? | Dark Factory | VIK-1446 | Spike; decides the private-data rows |
| FreshRSS scoring | must-read / skim / skip per article | Homelab Roadmap | VIK-1454 | Public data; the first live consumer |
| Renovate PR risk | safe / review / breaking; renamed config key; CRD migration | CI/CD | VIK-1458 | Backtest on 100 merged PRs |
| Glide run forensics | Why an `agent_error` or `no_change_needed` run stopped | Ploeg | VIK-1459 | 60 hand-labelled runs |
| Theme and repo labels | `theme/*` and `repo/*` suggestions in the sizing comment | Dark Factory | VIK-1448 | After the sizer (VIK-1416) |
| Ticket linter | The DoR judgement checks `ticket_lint.py` returns as MANUAL | Dark Factory | VIK-1449 | 50 hand-labelled tickets |
| Duplicate tickets | Which of ten embedding neighbours is the same work, or none | Dark Factory | VIK-1450 | Known `duplicateof` pairs |
| Review evidence | Is the evidence live state, a CI result, a diff or prose? | Dark Factory | VIK-1451 | 40 closed tickets |
| Commit trailers | Does each commit belong to the `VIK-` ticket it names? | Dark Factory | VIK-1452 | Includes the VIK-364 case |
| Alert runbooks | Does the linked runbook section cover its alert? | Homelab Roadmap | VIK-1455 | One-off audit, outside the alert path |
| Shared consumer kit | Client, key, metrics and evaluation harness, once two consumers exist | Dark Factory | VIK-1447 | Needs refinement |
| Brain review queue | Keep-or-reject order for graph-review | Homelab Roadmap | VIK-1456 | Private: VIK-1411 or VIK-1446 |
| Archive keep-or-skip | Is a mail or chat item worth distilling? A filter, never a router | Homelab Roadmap | VIK-1457 | Private; archive RFC parked |
| Chat model choice | Cheap or premium model per Open WebUI prompt | Dark Factory | VIK-1453 | Private; lowest priority |
| Glide team tier | copper / bronze / silver per work item | Ploeg | VIK-1460 | Only after G3 (VIK-1417) and a Glide ADR |
| Created work items | Duplicate or out-of-scope items held for approval | Ploeg | VIK-1461 | Only after Glide ADR-0031 is accepted |

Considered and rejected, with the reason:

- **Muting Falco or Tetragon events.** Adversarial input is a documented Jev weak spot, so an
  attacker could shape an event to look benign. A classifier never silences a security signal.
- **Live alert enrichment in the delivery path.** 153 of 159 rules already carry a
  `runbook_url`. A relay in the path would make alert delivery depend on Jev. The one-off audit
  (VIK-1455) gets the value without the dependency.
- **Routing brain or archive items to a graph or client.** Forbidden by the VIK-1259 guardrail.
- **Erfbeeld content.** Dutch legal and personal data. Jev is weaker outside English, and the
  data is sensitive.
- **Invoice or transaction categories.** A classic classifier task, but financial data. Revisit
  only if the Laya spike passes.
- **Web-search reranking.** Open WebUI has web search disabled
  (`ENABLE_WEB_SEARCH: "false"`), and brain retrieval already plans a CPU reranker
  ([brain retrieval RFC](rfc-brain-retrieval.md)).
- **Anything that counts, compares dates or does maths**, such as SLE breaches, certificate
  expiry or cost checks. These are documented weak spots, so they stay in code.
- **The outcome-observation evaluator.** Its RFC keeps LLMs out of verdicts, and that stays.

## 12. References

- Board contract: `CLAUDE.md` "Board contract"; [ADR-0043](../adr/adr-0043-vikunja-roadmap-system-of-record.md);
  product-owner skill (`agents.md` agent-ready sizing, `refine.md` estimation at refinement,
  `flow.md` right-sizing and SLE)
- Pattern for the sizer: [outcome observation loop](rfc-outcome-observation-loop.md) §7
- LiteLLM: `kubernetes/apps/ai/litellm/app/litellm-config.configmap.yaml` (fallbacks, provider
  budgets), `helmrelease.yaml` (image `v1.102.1`), `networkpolicy.yaml` (public 443 egress)
- Glide actuals: `apps/ploeg/pkg/store/migrations/` in `webgrip/glide` (`agent_runs.usage`,
  `shifts.spent`, `attempts`, `round`, `outcome`)
- Silent-fallback precedent: 2026-09-28 Glide runs served by `fireworks-gpt-oss-120b` after
  provider caps tripped (VIK-1408, VIK-1365)
- Jev sources: §2 links
