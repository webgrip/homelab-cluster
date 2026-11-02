# Glide (Ploeg + Vloer) — evidence base for the product-introduction post

Researched 2026-09-27. Read-only. Every entry: **statement** · source · confidence.
Paths starting `glide/` are under `~/projects/webgrip/glide`; paths starting `hc/` are under
`~/projects/webgrip/homelab-cluster`. Line numbers are from `cat -n` / `grep -n` on 2026-09-27
(glide HEAD `29c0ebd`, homelab-cluster HEAD `49f83016`).

Status labels used: **IMPLEMENTED** (code exists) · **TESTED** (a named test exercises it) ·
**DEPLOYED** (seen in homelab manifests or live cluster) · **PROPOSED** (ADR/research
recommendation, not decided or not built) · **OFF-BY-DEFAULT**.

Rule from Glide itself (task brief): code and executable tests describe the implementation;
proposed behaviour is labelled proposed. Glide's own evidence vocabulary agrees:
"**Intended** means an owner-stated direction. **Implemented** means there is source code for it.
**Observed** means a named test exercised it. **Proposed** means a recommendation that still needs
a decision." — glide/docs/landscape/index.md:30.

---

## 1. What Glide is

1.1 **One-line definition:** "Glide turns units of work into pull requests that AI agents write and
you review." · glide/README.md:3, glide/docs/index.md:11 · high

1.2 **Mechanism in its own words:** "You assign it to an agent team. Glide runs the agents with a
budget and a credential that expires, until a pull request is ready for your review, and you
merge. Work can also create work: splitting a Work Item, or making it ready, is a job for agents
too." · glide/docs/index.md:13 · high

1.3 **Status:** "internal tool, pre-1.0, one owner, self-hosted on Kubernetes. Not a hosted
service." · glide/docs/index.md:15 · high. README: "Glide is an internal, pre-1.0 tool that is
self-hosted on Kubernetes." · glide/README.md:5

1.4 **Two parts:** Ploeg "authorizes, budgets and runs every agent Run. It is a Go controller plus
short-lived worker pods." Vloer "is its front end, where you follow and steer work, in the browser
or in VS Code." · glide/docs/index.md:19-20 · high

1.5 **Names:** "Ploeg" introduced publicly as "Dutch for a crew" (prior post) ·
hc/BLOGPOST-dark-devsecfinops.draft-v1.md:103-137 (per subagent read) · medium. "Vloer" = Dutch
"floor" — NOT sourced in the docs I read; do not assert without a source.

1.6 **Licence:** "Code is [Apache-2.0](LICENSE). Original notices and bundled third-party licenses
remain with each application. The Vloer and Ploeg mark policies apply." · glide/README.md:27;
Ploeg ADR-0003 "Ploeg ships under Apache-2.0" (accepted 2026-07-29) ·
glide/docs/reference/decisions.md (register row) · high. Names/marks are trademarks, not
CC-licensed (Ploeg ADR-0022) · glide/apps/ploeg/docs/adrs/0022-… · high (title only read)

1.7 **Quality goals, in priority order:** 1 Bounded spend ("Every Run has a budget and a model key
that stops working when the Run ends"); 2 "A pull request is the only output"; 3 Recoverable ("A
dead worker loses its Lease… a paid step never repeats silently"); 4 Replaceable parts (tracker,
forge, harness, model behind adapters). · glide/docs/concepts/architecture.md:22-27 · high

1.8 **Constraints stated:** "One owner operates and maintains it. Simplicity outranks
generality." Self-hosted: Kubernetes, PostgreSQL, a LiteLLM gateway, Forgejo, Vikunja or ClickUp.
· glide/docs/concepts/architecture.md:29-33 · high

1.9 **Monorepo decisions:** Glide ADR-0001 (accepted 2026-09-12) — independently deployable apps in
one repo; ADR-0002 (accepted 2026-09-22) — "Ploeg authorizes and executes all agent work; Vloer is
the front end"; ADR-0003 (accepted 2026-09-22) — the unit of work is the Work Item and "work can
create work"; ADR-0004 (accepted 2026-09-27) — one Glide version for both apps, tags `glide-v…`. ·
glide/docs/adr/adr-000{1,2,3,4}-*.md, "Decision Outcome" at L25-31 / L26-32 / L25-31 / L25-31 · high

1.10 **Maturity facts (git):**
- 544 commits on the checked-out branch (`git log --oneline | wc -l`), 615 across all refs. · live
  command 2026-09-27 · high
- First commit `b29e475` 2026-07-21 "feat: bootstrap Ploeg — dispatch plane for ephemeral agent
  crews"; Vloer history imported 2026-09-12 (`5000acb`). · `git log --reverse` · high
- Authors (all refs, `git shortlog -sn --all`): Ryan Grippeling 459, webgrip-ci 87,
  semantic-release-bot 52, agent-builder 7, Renovate Bot 6, Codex 4. · live command · high
- Non-rc tags: ploeg-v0.0.0 (2026-07-22), ploeg-v0.1.0 (07-25), ploeg-v0.2.0 (08-27), vloer-v0.2.0
  (09-09), glide-v0.3.0 (tag 2026-09-27). The glide-v0.3.0 tag message: "Baseline for the single
  Glide release train. **Not a release**: … the first Glide candidate is 0.4.0-rc.1." · `git tag`,
  `git show -s glide-v0.3.0` · high
- Releases are zero-major rc candidates only: "a breaking change raises the minor version, and only
  `0.x.y-rc.N` from `development` is released" · glide/docs/adr/adr-0004-glide-releases-one-version.md:30 · high
- 61 decision records across three ledgers: 35 accepted, 26 proposed (rows under the
  "Proposed" heading). · glide/docs/reference/decisions.md (`grep -c`), sections at L16/L56/L89 ·
  medium (counted rows, not re-verified by hand)

---

## 2. The flow

2.1 **Four steps:** assign a Work Item to an agent team → Ploeg opens a **Shift** (one team's
attempt) → short-lived worker pods run the Shift's agents "each within a budget and with a
credential that expires" → "The Shift ends with a pull request for you to review and merge." ·
glide/docs/concepts/how-work-flows.md:13-16 · high

2.2 **Sequence (as documented, source-read 2026-09-23):** tracker assignment → signed webhook to
Ploeg → store Work Item, open Shift + Round, create pending Runs → KEDA starts a pod per pending Run
→ worker claims Run, gets branch + signed control token (writer also gets a Lease) → worker asks
Ploeg for a model key; Ploeg mints one with the Run's budget → agent works through LiteLLM → push
branch, open/update PR → worker blocks key, reports Outcome → next Round (reviewers) or close →
reviewer findings posted as PR comments → tracker comment/status → human merges → forge webhook →
Work Item `done` (or `needs_human` if closed unmerged). · how-work-flows.md:22-48 (diagram),
52-62 (steps) · high

2.3 **Rounds:** "A Round contains either one writer or several read-only reviewers, never both."
"A team without a plan gets one Round with one writer." · how-work-flows.md:53 · high

2.4 **Intake limitation:** "Ploeg ignores events other than assignment today." · how-work-flows.md:52 · high

2.5 **Outcomes:** `pr_opened`, `stuck`, `failed`; a harness that runs too long or goes silent is
stopped and reported failed with reason `timeout`. · how-work-flows.md:58 · high

2.6 **Review loop:** reviewer asks for changes → fix Round "up to the plan's limit"; stuck or
exhausted fix loop → `needs_human`. · how-work-flows.md:59-60 · high. NB: the governing ADR-0017 is
still **PROPOSED** (2026-07-29) although the code is deployed. · glide/apps/ploeg/docs/adrs/README.md:93 · high.
Homelab: `maxFixRounds: 2` on team bronze; before that it "was simply never switched on, because
MaxFixRounds defaults to 0". · hc/kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml:349-381 · high

2.7 **Background loops:** sweep every 15 s ("expires dead Leases and Runs, blocks their keys,
settles spend and repairs Shifts"); review reconcile every 10 min by default
(`PLOEG_REVIEW_RECONCILE_INTERVAL`) asks the forge directly in case a webhook was missed. ·
how-work-flows.md:62-64 · high

2.8 **Authority table:** what work exists → the tracker, through you; whether a Run may execute and
with which budget → Ploeg; who may push → the Lease holder; which model / how much → Ploeg,
through the key it minted; whether merged → you, on the forge. · how-work-flows.md:116-123 · high

2.9 **Work that creates work:** Runs can return `createdWorkItems`; stored as **proposed**, "where
no agent can claim it", approve/reject via operator API; `createdWork.autoDispatch: true` skips
approval. Limits: 5 per Run, depth 2, 20 open per team, $2.00 per item, $10.00 pool. ·
how-work-flows.md:66-92 · high. Status: "Implemented, proposed in Ploeg ADR-0031" (ADR-0031 is
PROPOSED 2026-09-23). **Doc inconsistency:** the same page's "Limits today" still says "Runs
cannot create Work Items yet" (how-work-flows.md:136). Treat as implemented-but-undecided; do not
feature prominently.

2.10 **Forge follow-ups (OFF-BY-DEFAULT):** `repairFailedChecks` (failed CI check → repair
Follow-Up, `maxRepairs` default 2) and `reworkOnChangesRequested` (human "changes requested" →
back to the same Work Item). "A Team without them acts on no forge event." · how-work-flows.md:74-75,
96-112 · high

### What Glide explicitly does NOT do

2.11 "**Out of scope:** Glide does not merge or deploy the changes agents make. It does not host
models; it reaches providers through your LiteLLM gateway." · glide/docs/index.md:37 · high

2.12 "You review the pull request on the forge and merge it. **Ploeg never merges.**" ·
how-work-flows.md:61 · high

2.13 "Your own tracker, forge, LiteLLM gateway and Kubernetes cluster are required. There is no
hosted service." "Ploeg records the pull request but does not merge or publish anything." ·
how-work-flows.md:133-134 · high

2.14 Candidate delivery "stores approvals, but nothing publishes"; "Delivery ends at the pull
request". · glide/docs/concepts/architecture.md:108 · high

2.15 Ploeg scope: "Ploeg owns dispatch and nothing else." · glide/apps/ploeg/docs/adrs/0032-…:88
(PROPOSED record, restating accepted ADR-0005) · high

---

## 3. Guarantees: implementation and tests

Code paths below are relative to `glide/apps/ploeg/` unless stated (abbreviated `P/`). Verified by a
read-only code sweep on 2026-09-27 (subagent) plus my spot-checks where marked (*).

### 3.1 Admission before spend — IMPLEMENTED, TESTED
- Claim and budget authorization happen in one transaction: pick the oldest pending Run
  (`… WHERE team=$1 AND role=$2 AND state='pending' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1`),
  lock the Shift row (`SELECT budget, spent, branch FROM shifts WHERE id=$1 AND closed_at IS NULL
  FOR UPDATE`), sum holds from `run_budget_holds`, `authorized := budget - spent - reserved`
  clamped to the role cap. · P/pkg/store/shift.go:337-393 · high
- Floor: `if budget > 0 && authorized < minViableAuthorization { return nil, ErrBudgetExhausted }`,
  `minViableAuthorization = 0.05` (USD). · shift.go:22, 27, 391-392 · high
- On exhaustion the claim API returns **204 No Content**: no pod work, no key minted, no attempt
  burned; the Shift closes with "budget exhausted: pool X, spent Y, reserved Z" and the tracker/PR
  are told. · P/pkg/httpapi/server.go:436-442; P/pkg/shiftengine/engine.go:406-411 · high
- Budget `<= 0` means **unmetered**, not exhausted (role cap applies). · shift.go:385-387;
  `TestZeroBudgetMeansUnmetered` · high
- Managed mode: after a claim, `LLMControl.Reserve` inserts a `run_llm_accounts` row (state
  `reserved`, capped at `min(policy budgetUsd, agent_runs.authorized)`), only then signs the Run's
  control token; the key itself is minted later on `POST /api/v1/runs/{token}/llm/credential`, only
  if the Run is still running. · P/pkg/httpapi/worker_auth.go:148-163; llm_control.go:66-81,
  97-123; P/pkg/store/llm_accounts.go:45-131 · high
- Tests: `TestAuthorizeIsAtomicUnderConcurrency` ("five goroutines authorize against a pool that
  funds two; exactly two succeed"), `TestAuthorizationIsCappedByPoolRemaining`,
  `TestExhaustedPoolRefusesToSpawn`, `TestZeroBudgetMeansUnmetered` · P/pkg/store/shift_test.go:144,
  201, 218, 235; description in adrs/0012:137-150 · high.
  `TestManagedReservationIsIdempotentAndBoundedByRunAuthority` · llm_accounts_test.go:129 · high
- Doc framing: "a run that cannot afford to start should never spawn, never mint a key, never burn
  an attempt" (backlog #44, quoted in ADR-0012:35-37). · high

### 3.2 Authorized-then-settled budgets (ADR-0012, ACCEPTED 2026-07-29) — IMPLEMENTED, TESTED
- Design: Shift = pool; each Run takes a hold; key minted for `min(roleCap, poolRemaining)` "so an
  agent can never overrun the ticket ceiling mid-run — LiteLLM cuts it off exactly at the pool
  boundary". Per-Run cap enforced by LiteLLM; Shift pool enforced by Ploeg "**before** spawning". ·
  adrs/0012-two-level-budgets-authorized-and-settled.md:50-61 · high
- Holds are derived, not stored: view `run_budget_holds`; for managed accounts the hold is
  `GREATEST(authorized, observed_spend)` until reconciled, "so the hold survives worker death". ·
  P/pkg/store/migrations/0012_run_llm_accounts.sql:18-25 · high
- Account state machine `reserved → minting → issued|unknown → blocked → reconciled`. ·
  0012_run_llm_accounts.sql:1-16 · high
- Settlement source is the gateway, not the agent: `GET /spend/logs?api_key=<hashed token>` for each
  key; evidence string `litellm:spend-logs alias=… entries=… usd=…`; then `UPDATE shifts SET
  spent=spent+$delta`. Refuses to settle an account that is not blocked/reconciled/zero-spend. ·
  llm_control.go:176-195; P/pkg/llmbroker/litellm.go:146-190; P/pkg/litellm/client.go:179-180;
  llm_accounts.go ~260-274 · high
- Settlement waits `PLOEG_LLM_SETTLE_AFTER` (default **15m**) of quiet after blocking; until then
  the amount shows as Reserved. · P/cmd/ploegd/main.go:52; P/pkg/store/llm_settlement.go:24-33;
  glide/docs/how-to/run-a-pilot-batch.md:76 · high
- Tests (selection): `TestManagedSettlementRequiresTrustedEvidenceAndNeverWorkerCost`,
  `TestManagedBudgetHoldSurvivesWorkerDeathAtEveryMintBoundary`,
  `TestConcurrentCredentialIssuanceHasOneDurableWinner` (llm_accounts_test.go:33, 58, 110);
  `TestControllerSettlesBlockedAccountFromSpendLogsOnce`,
  `…NeverSettlesMintedAccountWithoutDurableSpendSource` (P/pkg/httpapi/llm_settlement_test.go:80,
  138); `TestSettledSpend_ReadsSpendLogsThatOutliveTheKey` (llmbroker/litellm_test.go:243);
  `TestSettlementReleasesTheHoldAndRecordsSpend`, `TestSweptRunCannotReport` (shift_test.go:259,
  314) · high
- Production caveat (dated): through Ploeg rc.14 `shifts.spent` was 0.0000 everywhere so the pool
  bounded concurrency, not total spend (see 7.11). Current live state of `spent` NOT verified. · high

### 3.3 Per-Run LiteLLM virtual keys that expire — IMPLEMENTED, TESTED
- Mint: `POST /key/generate` with `{key_type:"llm_api", key_alias:"ploeg-<first 12 hex of run
  token>", max_budget, models, duration:"<seconds>s"}`. · P/pkg/litellm/client.go:22-31, 53-81;
  P/pkg/llmbroker/litellm.go:39-64 · high
- Fails closed on an uncapped key: "refusing to mint an uncapped key" when budget ≤ 0/NaN/Inf. ·
  llmbroker/litellm.go:50-52; `TestMint_RefusesAnUncappedKey` (litellm_test.go:175) · high
- Expiry default **4h** (`executor.litellm.keyDuration`, worker `LITELLM_KEY_DURATION`); managed
  policy TTL must be 1s–24h. · P/ops/helm/ploeg/values.yaml (litellm block);
  P/cmd/ploeg-worker/main.go:126; llm_control.go:53 · high
- End of Run: key is **blocked** (`POST /key/block`), not deleted, so its accounting survives;
  orphan-key sweep every 15 min and at boot. · client.go:247-252; llmbroker/litellm.go:78-110;
  P/cmd/ploegd/sweep.go:48-57, 243 · high
- Spend logs outlive revoked keys (probe 2026-08-08: 0 live `ploeg-*` keys, 35 aliases still in
  `/spend/logs`). · research/2026-08-08-benchmarking-the-loop.md:629-634 · high
- Worker refuses to start with admin secrets visible: `rejectAdministrativeEnvironment()` rejects
  `LITELLM_MASTER_KEY, LITELLM_ADMIN_URL, PLOEG_WORKER_SIGNING_KEY, PLOEG_WORKER_BOOTSTRAPS,
  PLOEG_FORGEJO_ADMIN_TOKEN, PLOEG_DATABASE_URL, KUBECONFIG`. · P/cmd/ploeg-worker/main.go:80,
  209-216 · high. Test `TestAdministrativeWorkerEnvironmentFailsClosedWithoutSecretDisclosure`
  covers **only** `LITELLM_MASTER_KEY` (main_test.go:24) · high
- Worker credential mode defaults to `managed` (alternative `static-compatibility` = one shared
  `LLM_API_KEY`). · main.go:181-190 · high
- ADR-0008 (ACCEPTED 2026-07-29): alias `ploeg-<12hex>` "is the join key between a ticket, a commit
  and its spend in Grafana"; "a compromised or lying agent cannot skew the books". ·
  adrs/0008-…:13-17, 70-71 · high

### 3.4 Lease that survives a dead pod — IMPLEMENTED, TESTED (with caveats)
- `FOR UPDATE SKIP LOCKED` on the Shift claim (shift.go:358), legacy claim (P/pkg/store/store.go:260)
  and operator-execution expiry (operator_execution.go:376, 422). · high
- Only writers insert into `leases`; one writer per item by unique key; every Run also has its own
  `agent_runs.expires_at`. · shift.go:396-413 · high
- Renewal `POST /runs/{token}/renew` updates both deadlines. Defaults: `PLOEG_LEASE_TTL` **60s**,
  `PLOEG_SWEEP_INTERVAL` **15s**. · store.go:315-339; server.go:524; P/cmd/ploegd/main.go:50-52 · high
- Sweep: `ExpireRuns` marks `failure_reason='lease_lost'`, deletes the lease, then the LLM key is
  blocked, the forge token revoked, block/settle sweeps run. · sweep.go:77-125; shift.go:520-567 · high
- A swept Run cannot report later: `UPDATE agent_runs SET state='finished' … WHERE … state='running'`
  (advance-once CAS); `TestSweptRunCannotReport`. · store.go ~425-440; shift_test.go:314 · high
- **Not implemented: fencing tokens/generations for Runs or Leases** (only `operator_executions.
  generation`). Docs disclaim "repository write fencing" (P/docs/contracts/worker-control.md:46;
  P/docs/ops/managed-workers.md:68); Vloer research: "There are no fencing tokens anywhere in the
  repository" (glide/apps/vloer/docs/research/2026-09-10-ploeg-and-de-vloer-split.md:29). · high
- **"A paid step never repeats silently" is only partly true.** A `lease_lost` Run counts as an
  infra failure and is retried automatically (legacy backoff 1/5/15/60 min, up to
  `MaxInfraFailures = 10`; Shift writers' Rounds reopen while infra attempts < 10). The repeat is
  audited and bounded by the Shift pool, so "not silent" holds; "never automatic" does not. ·
  store.go:52, 700-730; P/pkg/shiftengine/failedwriter.go:71-100 · medium-high
- Dossier: the lease is **no longer unique** (qm, Multica, agent-orchestrator cloud); what is
  distinct is that it "sits under admission and budget". · §5.5 · high

### 3.5 Isolation of Runs — PARTIAL; several protections OFF-BY-DEFAULT
- Pod: one Kubernetes Job pod per Run; `automountServiceAccountToken: false`; dedicated SA; pod
  `securityContext: {fsGroup: 1000}` only. Init container non-root 65532, drop ALL, RuntimeDefault
  seccomp. **Main `worker` container has no container securityContext.** ·
  P/ops/helm/ploeg/templates/_helpers.tpl:179-203, ~224-440 · high
- Chart default `harness.dind: true` renders a **privileged** DinD sidecar (_helpers.tpl:214-215).
  The homelab overrides this: `dind: false` estate-wide since ADR-0053 (2026-08-28), PSA back to
  `baseline`. · hc/docs/techdocs/docs/adr/adr-0053-daemonless-agent-plane.md:59-79;
  hc/kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml:390 · high
- `runtimeClassName` exists only for the **EXPERIMENTAL** `executor.type=sandbox`; default `""`
  (node default runtime, i.e. runc). Values comment*: "set kata or gvisor only after qualifying
  it". · P/ops/helm/ploeg/values.yaml:121-126, 181-184 · high
- **Chart ships no NetworkPolicy** for keda-mode workers. Homelab applies a namespace-wide policy
  (same for controller and workers) allowing egress to the whole `ploeg` namespace (incl. the DB),
  the LAN 10.0.0.0/24, LiteLLM `ai:4000`, Forgejo `:3000`, Vikunja `:3456`. ·
  values.yaml:191-195; hc/kubernetes/apps/ploeg/ploeg/app/networkpolicy.yaml:58-111 · high
- Controller-only secrets: DB URL, webhook secrets, tracker/forge tokens, `LITELLM_MASTER_KEY`,
  `PLOEG_WORKER_SIGNING_KEY`, `PLOEG_WORKER_BOOTSTRAPS` (templates/deployment.yaml:60-187,
  _worker_control.tpl). Worker gets a per-team/role bootstrap token and `AGENT_BUILDER_TOKEN`
  (read-write for writers, read-only for readers; render fails if a reader has no
  `readTokenSecret`). · _helpers.tpl ~326-368 · high
- Per-Run push tokens (ADR-0013 tier 2): `POST /api/v1/admin/users/<bot>/tokens`,
  `scopes:["write:repository"]`, name `ploeg-run-<id>-<owner>-<repo>`, revoked on settle or lease
  loss. **Repository scope is recorded in the token name only, not enforced** — code comment*:
  "Per-repository token scoping is not expressible in Forgejo's token API … an honest limitation".
  **Enabled only if `PLOEG_FORGEJO_ADMIN_TOKEN` is set; chart default unset, homelab does not set
  it**, so production uses the shared agent-builder token. Forgejo only (no GitLab/GitHub broker). ·
  P/pkg/forgebroker/forgejo.go:18-27, 93-117; P/cmd/ploegd/main.go:186-204 · high. Prior post: that
  per-run forge credential "has never worked" (admin tokens endpoint 404, 2026-07-31) ·
  hc/BLOGPOST-dark-devsecfinops.draft-v1.md:288-297 · high (dated)
- **"Credentials never in the sandbox" is NOT the default.** ADR-0034 (PROPOSED 2026-09-26):
  worker is non-dumpable (`conceal_linux.go`); harness gets a placeholder + loopback proxy for the
  model key (`PLOEG_LLM_KEY_ISOLATION=proxy`) and forge token (`PLOEG_FORGE_TOKEN_ISOLATION=proxy`,
  403 outside the Run's repo). Both **opt-in**; chart `keyIsolation: ""` / `forgeTokenIsolation:
  ""` hand the raw credential over; homelab sets neither. Tests
  `TestHarnessCannotReadConcealedWorkerEnvironment`, `TestIsolatedRunNeverHandsTheKeyToTheHarness`,
  `TestForgeProxyRefusesEverythingOutsideTheRunsRepository`, `TestGitPushesThroughTheForgeProxy`. ·
  adrs/0034-…:50-67, 77-85; values.yaml:128-131* · high
- What IS true by default: the **controller** secrets (LiteLLM master key, forge admin token, DB URL)
  never reach a worker, and the worker refuses to start if it sees them (3.3). The per-Run model key
  in the harness is budget- and TTL-bounded. · high

### 3.6 Tracker and forge neutrality — IMPLEMENTED for 2 trackers + 2 forges
- Interfaces `TrackerProvider`, `ForgeProvider` · P/pkg/provider/provider.go:49, 109 · high
- TrackerProviders: **Vikunja** (always registered), **ClickUp** (registered if
  `PLOEG_CLICKUP_SECRET`/`PLOEG_CLICKUP_TOKEN` set). · P/pkg/provider/vikunja/vikunja.go:48;
  clickup/clickup.go:70; P/cmd/ploegd/main.go:113-131 · high
- ForgeProviders: **Forgejo**, **GitLab**. · forgejo/forgejo.go:46; gitlab/gitlab.go:53;
  main.go:145-165 · high
- **Do not exist:** GitHub (tracker or forge), Linear, Jira, GitLab Issues as tracker. · grep of
  P/pkg/provider · high. Vloer (not Ploeg) can read GitHub issues (dossier L374-375,
  glide/apps/vloer/src/tasks.ts). · high
- Only Forgejo reviews are classified for rework; failed-check repair parses Forgejo commit-status
  and GitLab pipeline events. · how-work-flows.md:138 · high

### 3.7 Harnesses — IMPLEMENTED
- Adapters: **openhands (default)**, **exec**, **claude-code**, **acp**. ACP profiles: **opencode**
  (default profile, `opencode acp`) and **custom**. · P/pkg/worker/adapters.go:19, 48-67, 105-134;
  P/pkg/harness/adapters/acp/profiles.go:71-104 · high
- Defaults: worker `PLOEG_HARNESS=openhands` (P/cmd/ploeg-worker/main.go:141); chart
  `executor.harness.name: openhands`, `acp.profile: opencode` (values.yaml:138, 151). Homelab:
  openhands with `dind: false`; team copper uses `exec` running `/bin/cat`. ·
  hc/…/ploeg/app/helmrelease.yaml:390, 446-450 · high
- **Doc conflict:** the 2026-09-26 dossier's harness table says "opencode … Current default"
  (L305); code and how-work-flows.md:57 say OpenHands is the default. Use the code. · high
- Reader findings on claude-code/acp: the 2026-08-08 defect C12 ("ADR-0017's review loop is inert"
  on those harnesses, benchmarking-the-loop.md:567-583) is **fixed in current code** — both
  adapters now set the drop-box env and read it (P/pkg/harness/adapters/claudecode/claudecode.go:67-79;
  acp/acp.go:130-158)*. Fix commit not isolated (predates the 2026-09-12 import). · medium-high
- Qwen Code, Goose, Codex profiles: **PROPOSED** (dossier §10.2). · high

### 3.8 Scale-to-zero (KEDA) — IMPLEMENTED, DEPLOYED
- One `ScaledJob` per (team, role), `minReplicaCount: 0`, polling 30 s (homelab: 5 s), strategy
  `accurate`, `backoffLimit: 0`; trigger `type: postgresql`, `targetQueryValue "1"`, read-only
  scaler role `ploeg_scaler`. · P/ops/helm/ploeg/templates/scaledjob.yaml:17-83 · high
- Query: `SELECT COUNT(*) FROM agent_runs WHERE team = '<t>' AND role = '<r>' AND state =
  'pending'`; Go claim predicate mirrors it (`TestClaimRoleAgreesWithPendingRuns`). ·
  scaledjob.yaml:74; shift.go:488-494 · high
- Chart default `executor.enabled: false`; homelab enables it (and `pollingInterval: 5`, "a
  COUNT(*) over agent_runs' partial index `agent_runs_claimable`"). · values.yaml:119;
  hc/…/ploeg/app/helmrelease.yaml:~302-305 · high
- Live 2026-09-27: zero worker pods in namespace `ploeg` (and the bronze ScaledJobs are paused, 7.8).
  · kubernetes MCP · high
- Alternative executors: `cronjob` (polling) and `sandbox` (EXPERIMENTAL, 2026-09-26). · values.yaml:120-126 · high

### 3.9 Code/test size (2026-09-27)
- Ploeg: 584 `func Test` in 110 `_test.go` files; 39,542 Go lines of which 19,542 test. Vloer:
  41 test files, ~230 top-level test cases; 16,050 TS lines. · `grep`/`wc` via subagent · high
- `go test ./...` in this workstation: all packages passed except `pkg/httpapi` and
  `pkg/shiftengine`, which failed to START because stale embedded-postgres processes held ports
  55441/55443 (environment conflict, not a code failure). Do not cite as a green run. · live command
  2026-09-27 via subagent · high

---

## 4. Numbers

4.1 **There is no benchmark result and no pilot-batch record.** The benchmark design (2026-08-08)
is a survey + phased plan; "No decision is ratified here". I found no `ploeg-bench` results, no
scorecard and no pilot record in either repo (`grep -rln 'ploeg-bench\|pass@1\|pilot batch'` hits
only the design doc, an ADR, a Vloer research note, docs/index.md and the how-to). ·
glide/apps/ploeg/docs/research/2026-08-08-benchmarking-the-loop.md:3-7 · high

4.2 **KPIs are unmeasured:** "**Status: proposal.** Nothing on this page is measured yet." ·
glide/docs/reference/kpis.md:11 · high. Architecture risk table: "Agent quality is unmeasured
beyond single fixtures". · glide/docs/concepts/architecture.md:111 · high

4.3 **Dated single data points that do exist:**
- 2026-09-11 deployment inspection (De Vloer 0.3.0-rc.14, Ploeg 0.3.0-rc.6): "A completed coding
  fixture produced one changed file, passed all three unchanged tests in an independent checkout,
  and recorded **$0.017142048** of observed model cost. It does not establish general agent
  quality…" · glide/docs/landscape/index.md:32 · high
- Same inspection: a ticket import "failed on an OpenCode permission-list response. It stopped
  execution and blocked the model key." · glide/docs/landscape/index.md:34 · high
- 2026-07-31 prior post: ticket assigned to `bronze` 20:46 UTC, PR 20:53, reviewer approves 21:00;
  **$0.019872** (builder $0.013573 over 32 calls, reviewer $0.006299 over 16); lifetime **$1.40**
  over 2,379 calls since 15 July, mostly DeepSeek; cache hits 33,024 of 33,128 prompt tokens. ·
  hc/BLOGPOST-dark-devsecfinops.draft-v1.md:5-20, 306-313 · high (already public in the published
  version — link, don't repeat)
- 2026-07-19 dark-factory post (pre-Ploeg, curl-dispatched): run 32 "103 LLM requests, 4.63 million
  tokens, 16 minutes … $0.046"; whole ticket $0.064; failed runs $0.00. ·
  hc/BLOGPOST-dark-factory.md:426-481 · high (already public)
- 2026-08-08 probe: LiteLLM `/spend/logs` still carried **35 distinct `ploeg-*` aliases** after
  every key was revoked; join matched **34 of 40** recent runs ("the six misses are runs that made
  no LLM call at all"). · benchmarking-the-loop.md:629-634 · high
- 2026-08-08 cluster DB: `agent_runs : 45 rows, 0 with usage (2026-07-24 … 2026-07-31)`,
  `shifts : 6 rows, 0 with spend`, while the gateway held spend "down to `$0.1373` for the most
  expensive". Cause: deployed image predated `settleSpend` (`a1bccea`, 2026-07-31). ·
  benchmarking-the-loop.md:657-669 · high
- Cost-per-trial estimate "roughly €0.50–2 per trial" (an estimate, not a measurement). ·
  benchmarking-the-loop.md:752-754 · medium

4.4 **Statistical honesty already written down:** to separate a 15-point pass@1 gap needs **167
trials per configuration**; at n=5 the widest 95% interval is 65 points; "Never publish a winner
from overlapping intervals"; a 15-point comparison would cost €170–670. ·
benchmarking-the-loop.md:696-754 · high

4.5 **Test counts (Vloer, dated):** 210 application tests + 41 editor extension tests at the
prerelease prep; Ploeg "passes the full Go test suite with embedded PostgreSQL", four chart golden
renderings. · glide/apps/vloer/docs/validation.md:5-7 · high. "These results qualify the
implementation for a prerelease pilot. **No provider inference, live tracker mutation, candidate
publication, cluster deployment or scale qualification was performed.**" · validation.md:11 · high

4.6 **Local integration runs spend nothing, by design:** `mise run integration` exercises key
minting/blocking against a fake LiteLLM; "Its output explicitly reports zero inference calls and
zero spend… Its limits state that no real gateway, model or budget enforcement ran." ·
glide/docs/workflows/managed-execution.md:88-90 · high

4.7 **Stress numbers (Vloer demo pause/resume):** defect in 3 of 44 trials, then 1 of 240; final fix
passed 240 of 240 abort-and-resume trials. · validation.md:15 · high

4.8 **Time to PR:** only the anecdotal 7 minutes (20:46→20:53) from the prior post; no measured
distribution exists. K3 "Lead time to ready" is proposed, unmeasured. · 4.3, kpis.md:22 · high

4.9 **Success rates:** none measured. · kpis.md:11 · high

---

## 5. Landscape verdicts (2026-09-26 dossier)

Source for all: glide/apps/ploeg/docs/research/2026-09-26-agent-orchestration-landscape.md
(surveyed 2026-09-26, ~80 projects, seven parallel research agents, "most working from shallow
clones … rather than READMEs", L3-12). The dossier "changes no decision by itself" (L11-12); its
conclusions are carried into **PROPOSED** ADR-0032 (2026-09-26).

5.1 **Top verdict:** "nothing in this landscape removes Ploeg's reason to exist, but two of the four
differentiators in ADR-0009 are no longer exclusive, and the niche has narrowed to a sharper
claim." · L14-17 · high

5.2 **The unserved combination:** no project combines (1) tracker *and* forge neutrality reaching a
self-hosted Vikunja/Forgejo stack, (2) webhook-triggered, scale-to-zero Kubernetes Jobs per Run,
(3) a durable Postgres lease with TTL, (4) per-Run credentials minted at a proxy the agent cannot
bypass, authorized then settled. · L17-21; ADR-0032:53-59 · high

5.3 **Direct rivals (§3 table, L96-104):** openai/symphony 27.4k★ (poll 30 s; in-memory claims; "No
running sessions are assumed recoverable"; token counting only); github/gh-aw 5.2k★ ("Per-run hard
cap at a proxy", GitHub only); yc-software/qm 15.3k★ (Postgres `lease_token` + `SKIP LOCKED` +
reaper); Untrivial-ai/agent-orchestrator 12.4k★ (cloud edition Postgres leases w/ epoch fencing);
langchain-ai/open-swe 10.8k★ (GitHub only); gastown/gascity; cyrus. Plus Multica 51.4k★ (§4,
"architecturally the closest thing to Ploeg", Go + Postgres + `FOR UPDATE SKIP LOCKED` + Forgejo/
Gitea/GitLab provider, source-available licence, no Kubernetes runtime, no spend cap, L157-182) and
Databricks' Omnigent 10.2k★ ("the closest challenger", K8s Job per session + credential proxy +
`cost_budget` which is "a downgrade gate, not a hard stop"; no tracker, no forge abstraction beyond
GitHub App tokens, no durable work lease, L242-271). · high

5.4 **Absences confirmed by grep across direct rivals:** "zero Vikunja, zero Forgejo, zero Gitea
(except a 0★ Symphony port)… nobody mints a per-Run model key, and nobody runs a scale-to-zero
Kubernetes Job per Run." · L106-109 · high (scope: the rivals in the §3 table)

5.5 **NOT unique any more (§9):**
- "Drop 'event-driven' as a headline differentiator against Paperclip… Say 'execution scales to
  zero; the control plane stays small' instead." · L361-363 · high
- "Stop claiming the lease as unique. qm, Multica and the agent-orchestrator cloud edition have
  equivalent semantics. The distinguishing property is that the lease sits under admission and
  budget, not the lease itself." · L364-366 · high

5.6 **What IS (per dossier):** "The strongest single differentiator is spend. Authorized-then-settled
budgets with per-Run virtual keys at a proxy exist nowhere else; gh-aw's cap is the nearest and is
GitHub-only and self-described as not an authentication boundary against code inside the
container." · L367-370 · high. ADR-0032 (PROPOSED): "Primary differentiator: authorized spend." ·
ADR-0032:72-76

5.7 **Structural argument:** "every large project in this survey is built for one operator on one
host or for GitHub. The things Ploeg does are the things that only matter when several people
share a cluster, a budget and a self-hosted forge: admission before spend, a lease that survives a
dead pod, a key the agent cannot exfiltrate beyond its Run, and a tracker the organization already
owns." · L352-357 · high. **Caveat:** "a key the agent cannot exfiltrate" is only true with the
opt-in proxy of PROPOSED ADR-0034; see 3.5.

5.8 **Biggest risk named by the dossier:** "not a competitor but a pattern. Symphony shows the
pattern is small enough to be regenerated by an agent from a spec. Ploeg's defence is the part a
spec does not carry: the recovery, admission and settlement semantics tested in pkg/store and
pkg/shiftengine." · L376-380 · high

5.9 **kagent:** "Beside, partially competing … A2A peer at most … Not a runtime to embed; still no
tracker, forge or spend" (v0.10.2 / v1.0.0-alpha4). · L278 · high. kagent main branch "replaces the
Deployment runtime with Agent Substrate, adds `Harness` CRDs for Claude Code and Codex, and adds
cron `ScheduledRuns` guarded by database execution leases." · L62-65 · high

5.10 **Never list:** "run Ploeg as a Paperclip or Multica adapter…; adopt Symphony's in-memory claim
model; **embed kagent or Agent Substrate as a dependency before v1**; pass per-Run credentials
through `SandboxClaim.spec.env`." · L403-406 · high

5.11 **agent-sandbox:** kubernetes-sigs/agent-sandbox v1.0.4 "**Best runtime under Ploeg**" (executor
creates `SandboxClaim` → `SandboxWarmPool` → `SandboxTemplate` with RuntimeClass Kata or gVisor;
KEDA scales the warm pool). · L277 · high. It shipped v1.0.0 on 2026-08-28, moved to `v1beta1`,
removed `v1alpha1`; "ADR-0005's trigger … has fired." · L57-61 · high

5.12 **Backlog #58 status:** NOT BUILT. Backlog text still says "pin v1beta1/v0.5.x" and points at
Paperclip's `v1alpha1` builder · glide/apps/ploeg/docs/backlog.md:101 · high. Dossier: "#58 still
says 'pin v1beta1/v0.5.x' and points at Paperclip's now-invalid `v1alpha1` builder" (L289-290) and
proposes "re-pin to v1beta1, v1.0.x" (L420). ADR-0032 (PROPOSED) names agent-sandbox v1.0.x as "the
runtime for the second executor" with KEDA driving a `SandboxWarmPool` (ADR-0032:82-86). The
agent-sandbox controller "is not installed on the homelab cluster, so no live claim was made"
(2026-09-10) · glide/apps/vloer/docs/validation.md:34 · high. Vloer has a `SandboxWorkspaces`
provisioner tested against a fake API server only (same line).
**Update after the dossier:** an EXPERIMENTAL `executor.type=sandbox` landed the same day
(`29b13e3` 2026-09-26 "feat(ploeg): add an experimental agent-sandbox executor"; `af06bbc`
"let sandbox Runs carry an egress allowlist"): the ScaledJob pod becomes a launcher that runs each
Run in an `extensions.agents.x-k8s.io/v1beta1` SandboxTemplate/SandboxClaim
(P/ops/helm/ploeg/templates/sandbox.yaml; P/pkg/sandboxlaunch/launcher.go). Not deployed, not
qualified live (controller absent in the homelab); backlog.md #58 text not yet updated. · high

5.13 **Neutrality gap (dossier's own words):** "Tracker neutrality needs a GitHub and Linear story to
be credible. Ploeg has no GitHub or Linear `TrackerProvider` and no GitHub `ForgeProvider`." ·
L371-375 · high. ADR-0032: "the first external adopter on GitHub cannot use Ploeg's unattended
path at all." · ADR-0032:101-102 · high

5.14 **Harness seam:** "ACP v1 in 40+ agents … ACP bet confirmed"; recommended next profiles "Qwen
Code, then Goose, then Codex via codex-acp". · L87, L298-317 · high

5.15 **Earlier dossiers (July):** A2A — "adopt nothing now … fails on fit, not maturity"; one honest
fit is a north-facing facade (watchlist, backlog #102) · research/2026-07-28-a2a-fit.md:9-19 ·
high. Paperclip — "do not integrate, do not depend — mine it for design" (layer collision: it owns
the tracker) · research/2026-07-28-paperclip-fit.md:18-27 · high. Paperclip dossier's method
caveat: three research agents "were killed mid-dig by an org spend limit" · L9-16 · high (nice
irony, citable)

5.16 **Re-evaluation triggers** include "gh-aw targets Forgejo Actions, or any project ships per-Run
virtual model keys" and "Omnigent adds a tracker trigger, a forge abstraction beyond GitHub, or a
hard (refusing) budget." · dossier L424-440 · high

---

## 6. Runtime facts

6.1 **Kata is live in the homelab:** one RuntimeClass `kata`, handler `kata`, age 45 d, no
gVisor/runsc RuntimeClass live or in git. · live `kubectl get runtimeclass` via subagent
2026-09-27 · high. Manifest: `overhead.podFixed: memory 160Mi, cpu 250m`, nodeSelector
`runtime.webgrip.io/kata: "true"`, Cloud Hypervisor via the siderolabs/kata-containers extension ·
hc/kubernetes/apps/kube-system/runtime-classes/app/kata.runtimeclass.yaml:2-41 · high

6.2 **Version and nodes:** "kata 3.32.0 on all three workers, standing smoke Job, real guest kernel
verified" · hc/docs/techdocs/docs/adr/adr-0053-daemonless-agent-plane.md:128-133 · high. Workers =
fringe-workstation (10.0.0.30), worker-1 (.31), worker-2 (.32); Talos patches
hc/talos/patches/fringe-dedicated.yaml:10-15, worker-1.yaml:13-21, worker-2.yaml:29-66 · high.
Guest kernel 6.18.35 inside the VM vs host 6.18.39-talos at the 2026-08-13 check ·
hc/docs/techdocs/docs/rfc/rfc-ci-isolation-talos.md:165-185 · high

6.3 **Overhead figures:** "~160Mi/250m overhead per pod" (ADR-0053:128-133); "measured ~130-160Mi
for Cloud Hypervisor" (VMM + virtiofsd + shim) (kata.runtimeclass.yaml:10-11). **No boot-time or
latency figure exists** in the repo. · high

6.4 **Kata is NOT used for Ploeg workers.** No `runtimeClassName` in hc/kubernetes/apps/ploeg
(`grep -rn runtimeClassName kubernetes/apps/ploeg` → none). ADR-0053 chose "daemonless" (`dind:
false` everywhere, gates run in CI) over "Kata-walled DinD"; Kata stays available "only through a
new ADR". · ADR-0053:49-62, 83-86 · high

6.5 **Why daemonless:** "two node-down incidents"; privileged DinD nested containers land outside
`kubepods`, invisible to kubelet eviction and the Talos OOMController; "Sidero has said outright
that privileged dind on Talos is unsupported." · ADR-0053:22-26 · high

6.6 **Kata incident detail:** worker-2 was once not upgraded and the smoke Job "sat in
ContainerCreating for 12h with `FailedCreatePodSandBox: no runtime for "kata" is configured`". ·
kata.runtimeclass.yaml:14-22 · high

6.7 **gVisor / Agent Substrate facts (ADR-0063, PROPOSED 2026-09-27, "Nothing here has run live
yet" L404-410):**
- Substrate's `ateom-gvisor` "calls `runsc` itself, from a binary atelet downloads", fetched as URL
  + sha256 from `gs://`; it cannot use the Talos gVisor extension (no `runtimeClassName` on a
  WorkerPool; runsc-in-gVisor unsupported). · adr-0063:98-115 · high
- "`atelet` runs `privileged: true`"; "every worker pod runs as root with **thirteen added
  capabilities** (`SYS_ADMIN`, `NET_ADMIN`, `SYS_PTRACE` among them), seccomp and AppArmor
  `Unconfined`, and a hostPath"; needs `user.max_user_namespaces` raised. · adr-0063:116-123 · high
- Summary line: "a privileged DaemonSet, root worker pods with thirteen capabilities and no seccomp
  or AppArmor confinement, a second Postgres, snapshots in Garage, an in-cluster CA provisioner,
  and the `certificates.k8s.io/v1beta1` API. The Talos gVisor extension removes none of it." ·
  adr-0063:337-340 · high
- PodCertificateRequest "GA on Kubernetes 1.37"; Substrate 0.2.0-beta8 "speaks only `v1beta1`", so
  `--runtime-config=certificates.k8s.io/v1beta1=true` stays required. · adr-0063:85-97 · high
- Pilot waits for kagent 1.0 on Kubernetes 1.37; live cluster runs **v1.36.4** (Talos 1.13.10). ·
  adr-0063:15-18; live `kubectl get nodes` 2026-09-27 · high
- kagent upstream controller "has no authentication" (`UnsecureAuthenticator`, defaults to
  `admin@kagent.dev`). · adr-0063:43-50 · high
- Round decisions: R1 kagent never runs unattended, acts only for the person asking; R2 accepts
  Substrate privileges with a sha256-pinned runsc from Garage + two Kyverno exceptions as tracked
  debt; R3 adopts option 1b (`kagent:<email>`, read-only `human-reader`, 15-min tokens). ·
  adr-0063:693-722 · high

6.8 **Connection to Glide:** ADR-0063 is about kagent (an ops assistant), not Glide. The Glide
connection is the dossier verdict "embed kagent or Agent Substrate … never before v1" (5.10) and
ADR-0034's note that kagent/Agent Substrate, Omnigent and OpenShell "converge on the same shape: a
placeholder in the sandbox and the real credential attached at an egress point"
(adrs/0034-…:37-39). · high

---

## 7. Honest limitations and open gaps

7.1 Pre-1.0, one owner, internal, no hosted service, only adopter is the owner ("the owner is
Glide's only adopter"). · docs/index.md:15; glide/docs/adr/adr-0004-glide-releases-one-version.md:11 · high

7.2 **Trackers:** Vikunja and ClickUp only; no GitHub, Linear or Jira TrackerProvider. **Forges:**
Forgejo (leading) and a GitLab adapter; no GitHub ForgeProvider. · dossier L82, L89, L371-375;
architecture.md context diagram "Forgejo (GitLab adapter exists)" · high (see §3 code check)

7.3 **agent-sandbox executor (#58) exists only as EXPERIMENTAL chart/launcher code (2026-09-26)**,
unqualified; the agent-sandbox controller is not installed in the homelab. · 5.12 · high

7.3b **Isolation defaults are weak:** privileged DinD sidecar on by chart default; no container
securityContext on the worker; no chart NetworkPolicy; runc by default; per-Run forge tokens off
and repo scope unenforceable on Forgejo; no fencing tokens. · 3.4, 3.5 · high

7.4 **Credential isolation from the harness is opt-in:** ADR-0034 (PROPOSED 2026-09-26): "both
proxies are opt-in until each harness is qualified, so **a default deployment still hands
credentials over**." Until 2026-09-26 the harness "could read the worker's own environment through
`/proc`, including the long-lived worker bootstrap token and builder forge token." ·
adrs/0034-…:13-19, 56-67, 77-78 · high

7.5 **Two engines still exist:** "Two execution engines until Vloer delegates to `ploeg-worker` —
Accepted in ADR-0002; migration not started". · glide/docs/concepts/architecture.md:107 · high

7.6 **Nothing publishes past the PR**; forge follow-ups off by default; only Forgejo reviews are
classified (a GitLab review never sends work back). · how-work-flows.md:131-140 · high

7.7 **Deployed version lags trunk:** homelab runs Ploeg `0.3.0-rc.6` (digest-pinned) and De Vloer
`0.3.0-rc.14`; latest tags are ploeg-v0.3.0-rc.7 / v0.3.0-rc.16 and glide-v0.3.0 baseline. ·
hc/kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml:58, de-vloer/app/helmrelease.yaml:23; `git
tag` · high

7.8 **Unattended path paused in the homelab right now:** a Kustomize post-renderer adds
`autoscaling.keda.sh/paused: "true"` to ScaledJobs `ploeg-worker-bronze-(builder|reviewer)`. ·
hc/kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml:21-33 · high. The Vloer research note says the
config "explicitly pauses bronze builder/reviewer ScaledJobs for the interactive pilot". ·
glide/apps/vloer/docs/research/2026-09-11-ecosystem-implementation.md:37 · high. Live 2026-09-27:
namespace `ploeg` has ploegd, de-vloer, ploeg-db (2 instances), an exporter, and **zero worker
pods** (kubernetes MCP `pods_list_in_namespace ploeg`) · high

7.9 **Capacity is tiny:** teams run `maxReplicaCount: 1`; "three readers at once do not fit the
worker pool (fringe ~2.3 CPU / 2.3Gi free, worker-1 at 99% CPU requests)". ·
helmrelease.yaml:328, 345-347 · high. "Running 1,000 agents is a capacity ambition, not evidence of
1,000 useful outcomes or a measured capability of this deployment." · glide/docs/landscape/index.md:11 · high

7.10 **Many governing ADRs are PROPOSED** (26 of 61 in the register), including the review loop
(0017), work creation (0031), the strategic restatement (0032) and credential placeholders (0034). ·
glide/docs/reference/decisions.md; adrs/README.md:93-110 · high

7.11 **Money bound was inert in production until rc.16:** "`shifts.spent` … was 0.0000 on every row
ever written … so through rc.14 that first bound was INERT"; "this bound has never once fired in
production". · hc/…/ploeg/app/helmrelease.yaml:361-372 · high. Benchmark doc: "ADR-0012's pool is
not bounding total spend in the deployed cluster; it is bounding concurrency" (2026-08-08). ·
benchmarking-the-loop.md:683-688 · high. NB: the manifest comment says rc.16 settles from the
gateway, but the deployed tag is 0.3.0-rc.6 (a later version line) — whether settlement is live now
was NOT verified against the DB.

7.12 **Agent quality unmeasured; no benchmark run.** · §4 · high

7.13 **Neutrality claim not yet credible by the project's own assessment** (ADR-0032:77-80). · high

7.14 **Vloer browser suite was not re-qualified at one point** (fails at its cancel step), recorded
honestly in the validation matrix. · validation.md:27 · high

---

## 8. Quotable first-hand details

8.1 Agents built part of their own dispatch plane: 7 commits in Glide history are authored by
`agent-builder` (the worker's git identity), including `450ec5f`/`1edb4af` 2026-07-25 "fix:
ploeg-worker owns the per-run LiteLLM key lifecycle (mint + always-revoke)" and `4814851`
2026-07-27 "fix(ploegd): safe Alias() helper, sweeper key revoke, boot orphan sweep". Team `silver`
is "the ploeg-repo team — the factory working on its own dispatch plane (first job: the per-run key
leak, VIK ticket)". · `git log --all --author=agent-builder`; hc/…/ploeg/app/helmrelease.yaml:394-395 ·
high for authorship; medium that each was produced by a Ploeg Run (identity is the worker's
hard-coded git identity per backlog #106, glide/apps/ploeg/docs/backlog.md:177)

8.2 Readers died 2026-07-30 with `exec: "opencode": executable file not found in $PATH`; the
recorded diagnosis "SINGLE WRITER until a reader-capable harness exists" "was wrong about the
cause" — the real blockers were a reader handed "a shallow single-branch clone of the BASE", never
told the PR existed, and holding "a full push credential while being told it did not". ·
hc/…/ploeg/app/helmrelease.yaml:329-344 · high (the push-credential story is already the
published post's headline: "I told my AI code reviewer it couldn't push. It could.")

8.3 Worst-case arithmetic in the manifest: builder cap $2.00 + reviewer $0.40, 1 writer + 1 reader +
2 fix rounds = 6 runs = "a hard worst case of $7.20 against the $8 pool. 80 cents". ·
helmrelease.yaml:373-378 · high

8.4 Copper team: exec harness runs `/bin/cat {taskspec}` — proves harness selection, key
mint/revoke and the `no_change_needed` path "without spending a single LLM token". ·
helmrelease.yaml:429-450 · high

8.5 The self-correcting probe: "I probed for `v0.2.0-rc.15`, got a 404, and concluded too much from
it" — the release pipeline strips the leading `v`. · benchmarking-the-loop.md:671-681 · high

8.6 `agent_runs : 45 rows, 0 with usage` vs gateway holding spend: the metering boundary worked
while the app's own books were empty — which is the case for metering at the proxy. ·
benchmarking-the-loop.md:657-665 · high

8.7 Card-payment analogy is the ADR's own: "the shape of a card payment: a hold for the estimated
amount, replaced by the real one"; "No release statement exists, because none is needed." ·
glide/apps/ploeg/docs/adrs/0012-two-level-budgets-authorized-and-settled.md:50-52, 85-89 · high

8.8 ADR-0013's framing: "the Lease records a right it cannot enforce. Either it earns its keep or it
should not exist." · adrs/0013-push-rights-are-minted-per-run.md:25-26 · high

8.9 ADR-0008 on the alternative gateway (OmniRoute): economics that "depend on ToS-grey free-tier
farming via TLS-fingerprint (JA3/JA4) impersonation. That is arbitraged-and-deniable spend, against
a design whose entire audit value is metered-and-attributable spend." · adrs/0008-…:49-54 · high

8.10 Kata smoke Job stuck 12 h on `no runtime for "kata" is configured` (6.6).

8.11 Paperclip survey agents "killed mid-dig by an org spend limit" (5.15).

8.12 `21:00:09 WARN findings not published: no provider for forge  forge="" shift=4` — already in
the published post (L17). · hc/BLOGPOST-dark-devsecfinops.draft-v1.md:25 · high (link, don't
repeat)

---

## 9. Continuity with prior posts (what is already public)

- **BLOGPOST-dark-factory.md** ("Building a Dark Factory: Kanban tickets in, reviewed pull requests
  out", Draft v2 2026-07-19): pre-Ploeg; dispatch "is a curl" (L532-534); privileged DinD runner
  pool; OpenCode→OpenHands switch; per-run LiteLLM keys; run 31/32 story, $0.046; Cilium traps;
  hardware (i5-4670K / i7-4770 workers). Does not mention Ploeg, Glide, Vloer, Kata or gVisor. ·
  subagent read of hc/BLOGPOST-dark-factory.md · high. NB: L34 has a dangling unfinished sentence.
- **BLOGPOST-dark-devsecfinops.md** (published title "I told my AI code reviewer it couldn't push. It
  could."; draft-v1 2026-07-31): introduces Ploeg, Shift/Round/Role, bronze/silver/copper, the
  reviewer-could-push story, the Kyverno waiver outage, $0.019872 run, $1.40 lifetime, Kepler watts,
  `agent-builder` 2 of 594 commits in 30 days. Published version: "It is called Ploeg"
  (L365-367). Glide and Vloer not mentioned. · high
- **New in this post (not yet public):** Glide as the product name; Vloer; authorize-then-settle
  as the claimed differentiator; the 2026-09-26 landscape verdicts; the daemonless decision + Kata
  facts; ADR-0034 placeholders; work-creates-work.

## 10. Capacity plan and review-debt formula (added for draft-v2's opening)

10.1 Binding limits in order: "owner review capacity, then the model gateway's daily provider caps
(Anthropic $5/day, DeepSeek $2/day, Fireworks $5/day), then `maxReplicaCount`. Cluster CPU and RAM
come after all three." · glide/docs/research/2026-09-23-capacity-plan.md:13-15 (status: proposal,
measured 2026-09-23 against the live cluster) · high

10.2 "the three worker nodes have room for **7 concurrent writer pods**" · capacity-plan.md:9-10 · high

10.3 "Power cost per Run is about €0,001–0,01. A DeepSeek run costs €0,01–0,05 in model spend, and a
frontier-model run costs €1,00–3,00." · capacity-plan.md:19-20 · high

10.4 Ploeg's per-team limit: "at most 4 run at once (4 ScaledJobs × `maxReplicaCount: 1`)" ·
capacity-plan.md:10-12 · high

10.5 Formula `accepted results per week <= min(ready tickets per week, candidate production per
week, review capacity per week)` and the 20 / 50 / 8 → 8, 100 → 8, 16-reviews illustration
("Illustration for ticketed software work, not a measurement") · glide/docs/landscape/bottlenecks.md:26-30 · high

10.6 The capacity plan was produced for the owner by an agent session (owner-judgment point on the
post's "In September I planned…" wording).
