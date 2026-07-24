# research.md — dark-factory post v2 evidence (2026-07-19)

Every claim in the rewrite traces here. Sources: repo sweep (files cited), live VictoriaMetrics
ledger metrics, Vikunja ticket 454 comment trail, dark-factory board (project 5).

## Run ledger (live, litellm-exporter → VictoriaMetrics, queried 18:27 UTC)

| Run | What | Outcome | Spend | Requests | Tokens | LLM wall-clock |
|---|---|---|---|---|---|---|
| 31 | build | failed 16s (key_alias 400) | no ledger row (key never minted... actually run31 died AT mint) | — | — | — |
| 32 | build | PR opened 07:39 | **$0.046** of $2.00 | 103 | 4,634,132 | 977 s (07:22:53→07:39:10 UTC) |
| 33 | revision | failed, "needs human triage" | no ledger row (died pre-key-mint) | — | — | — |
| 34 | revision | failed, "needs human triage" | no ledger row (died pre-key-mint) | — | — | — |
| 35 | revision | finished 09:47 | **$0.018** | 43 | 1,862,275 | 449 s (09:39:33→09:47:02 UTC) |

Ticket total so far: **$0.064**. Zero LLM request failures on runs 32/35
(`litellm_run_failures` = 0). Source: `litellm_run_*{key_alias=~"agent-vik454-.*"}`.
Ticket comment trail (task 454): run 31 started+failed, 32 started+finished("check the PR"),
33/34 "revision started"+"failed — needs human triage", 35 "revision started"+finished.
Caveat: WHY 33/34 died pre-mint is not established here — check Forgejo runs 33/34 before
claiming a cause in print.

## Corrections to draft v1

1. **Secrets provenance** (v1 said "three credentials, all ESO-delivered from the vault"):
   two are ESO (`agent-litellm-master` ← OpenBao litellm, `agent-vikunja-token` ← OpenBao
   vikunja); the third, `AGENT_BUILDER_TOKEN`, is minted by the `agent-builder-provisioner`
   Job into Secret `agent-builder-token` (scaledjob.yaml:178-184, commit 35513598).
2. **Sharper runtime detail**: OpenHands runs LocalWorkspace — the agent edits and gits inside
   the runner container itself; the DinD daemon is only for language gates in CI's images.
3. Stale comments exist in scaledjob.yaml:5-8 and the Kyverno exception (still say "soyo pool")
   — do not quote those headers; the actual nodeSelector is pool: worker.

## New since draft v1 (same day)

**Observability suite shipped** (commit 77e91c49, 18:07 UTC) — v1's "what's next: telemetry":
- Six GrafanaDashboard CRs, folder `ai`, tag `dark-factory`: command-center, run-explorer,
  spend-attribution, runner-fleet, llm-traffic, forge-board. Cross-linked; run ids deep-link
  into the run explorer.
- litellm-exporter run-grain metrics from the immutable spend log
  (`metadata->>'user_api_key_alias'`, 30-day window) — **per-run spend survives key
  revocation**; the run explorer reconstructs a revoked key's history.
- Two read-only Grafana Postgres datasources: LiteLLM Ledger + Vikunja Board
  (grafana_ro role, pg_read_all_data, sslmode require).
- Provider day-caps $5/$2 (VIK-325) — separate layer from per-run tier budgets.

**Preview-host shipped** (commit 7a2a0090, 09:43 UTC): per-branch SPA previews.
CI publishes each branch's static build into a previews repo; git-sync sidecar
(pulls every 30 s **as agent-builder**, reusing the same provisioner-minted token) + nginx
serves at preview.<domain>/<branch-slug>/, LAN-only. This is serving infrastructure for the
render-verification lesson (Team Bronze's D3 axis failure → ADR-mandated render channel).
Gotcha recorded: git-sync + readOnlyRootFilesystem needs HOME=/tmp as a mount (crash-looped 11×).

**Pool hardening** (91096/9109…: commit 91087996): agent-runner image pinned 1.0.0 by digest;
gateway URLs (in-cluster svc URLs curl 000/timeout from the pool, gateway 200 — empirically
verified pre-dispatch); FORGEJO_URL stays in-cluster (intra-namespace). Resources: main 2Gi
limit (no CPU limit, 250m/512Mi requests), dind 3Gi limit, ci-shared emptyDir 8Gi disk.

**ADR numbers** (registry docs/techdocs/docs/adr/index.md):
- ADR-0044 (proposed 2026-07-14): all inference metered through self-hosted LiteLLM; virtual
  keys w/ max_budget+tpm/rpm+model allow-list; kill-switch = revoke key; amended: OSS LiteLLM
  has no Prom /metrics (Enterprise-gated) → CNPG ledger exporter.
- ADR-0045 (superseded by 0047): opencode runtime + server-side guards (pre-receive block-list
  carries forward runtime-independent, board #269).
- ADR-0047 (proposed 2026-07-17): OpenHands SDK v1.21.0 supersedes opencode (pinned beta
  churn `0.0.0-next-15495`); builder≠judge preserved at pipeline level; discipline as repo
  skill + AGENTS.md; OpenHands Enterprise governance is Polyform → stay MIT core, govern via
  LiteLLM.
- ADR-0048 (proposed 2026-07-18): dedicated agent pool, poll-dispatched, two role bots
  (builder write:repository+write:issue; reviewer read:repository+write:issue); claim-as-lock
  dispatch; dated correction 2026-07-18: pool first specified on soyo, corrected to worker
  before any pod ran ("No agent pod ever ran on a soyo"). Webhook accelerator: Argo Events
  later, never n8n.

**Board (project 5, 33 open)** — what's-next candidates, verbatim ticket themes: poll
dispatcher pilot then in-cluster (272/273), factory-gate event receiver (456), independent
review-bot lane (276), skills-profile loadout by ticket label (268), server-side pre-receive
guard parity (269), LiteLLM JWT auth via Authentik client-credentials (281), identity
provisioner from git spec (264), agent-run.yml 10x with 20 improvements (452), per-run keys
stamped with repo+workflow identity (457).

**Capacity/nodes** (HANDOFF-storage-and-node-strategy.md): soyo-1/2/3 = N150 4-core, 12 GiB;
fringe-workstation = i7-4770 16 GiB; worker-1 = i5-4670K 24 GiB. Two workers carry everything
the recovery set doesn't need — explains FailedScheduling bounces.

**Target-project texture**: ticket 454 = "NP-1007 · Chart layer structural tests (ChartBar +
ErfbelastingChart)", a Dutch inheritance-tax calculator; merge 2fb8dee recorded the zero-test
gap; hard rule "clients never calculate" (fixture-driven). Keep repo/user URL out of print;
"an inheritance-tax calculator" is fine texture.

**CI-pool cousin facts** (context, not agent pool): syft OOM at 1280Mi cataloging the ~5GB
ci-runner image → CI ceiling 3Gi (43d9a3a8); two egress fixes each with the ~135s timeout
signature; both scoped to CI runner only, agent pool stays excluded from secrets-backend reach.
