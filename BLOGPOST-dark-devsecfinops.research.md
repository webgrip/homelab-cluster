# Evidence — Dark DevSecFinOps post

*Gathered 2026-07-31 early morning, from live state. Every claim in the post must trace to a
row here. Commands are reproducible; re-run them on publish day, because half of this is
younger than a week.*

*Two redaction notes: per-run LiteLLM key hashes are not reproduced here (referenced as
"key A/B/C/D"; the grouping query is given so anyone with cluster access can re-derive them),
and trace ids in log lines containing the word "key" are truncated — the repo's `guard-secrets`
hook reads `…per-run key trace=<hex>` as a leaked credential and hard-blocks the write. A false
positive worth knowing about, and arguably worth a post of its own.*

---

## 1. The milestone run — ticket → PR → review

**Shift 4, work item 29, VIK-628, team bronze, 2026-07-30 20:46–21:00 UTC.** This is the run
the plan of 2026-07-30 said had *not happened yet*. It happened twenty minutes after that plan
was written, on chart `0.2.0-rc.14`.

### Timeline (from `ploegd` logs, pod `ploeg-5475944cf8-9nstk`)

```
20:45:17  ploegd listening  version=0.2.0-rc.14
20:45:17  resolved tracker project name=Erfbeeld id=4 repo=webgrip/erfbeeld
20:45:17  target map loaded rules=7
20:46:13  target resolved external_id=628 scope=4 team=bronze repo=webgrip/erfbeeld branch=main rule=4
20:46:13  work item queued id=29 team=bronze
20:46:13  shift opened work_item=29 team=bronze pool=3 rounds=2
20:46:13  round opened shift=4 round=1 roles=1
20:47:05  run claimed team=bronze role=builder round=1 writes=true authorized=2 deadline=21:02:05
20:53:45  outcome reported outcome=pr_opened
20:53:45  round opened shift=4 round=2 roles=1
20:54:15  run claimed team=bronze role=reviewer round=2 writes=false authorized=0.4 deadline=21:09:15
21:00:09  outcome reported outcome=no_change_needed
21:00:09  WARN findings not published: no provider for forge  forge="" shift=4
21:00:09  shift closed shift=4 reason=plan_exhausted item_state=needs_human
```

### The builder (pod `ploeg-worker-bronze-builder-jhklq-q9hkp`)

```
20:47:05  ploeg-worker starting version=0.2.0-rc.14 team=bronze harness=openhands node=fringe-workstation
20:47:05  claimed work item id=29 external_id=628 trace=ploeg-58aaeefccd95 role=builder round=1 writes=true
20:47:05  using the shared forge credential supplied by ploegd
20:47:05  resolved work target repo=webgrip/erfbeeld base=main route_rule=4
20:47:16  starting headless harness run harness=openhands role=builder budget_usd=2
20:47:16  minted per-run key   trace=ploeg-58aaeefc…
          openhands-runner: model=litellm_proxy/deepseek-chat trace-id=ploeg-58aaeefccd95
          openhands-runner: OpenHands CLI 1.16.0
          openhands-runner: waiting for docker daemon at tcp://localhost:2376… ready (29.6.2)
20:53:44  revoked per-run key  trace=ploeg-58aaeefc…
20:53:45  run finished outcome=pr_opened links=[https://forgejo.webgrip.dev/webgrip/erfbeeld/pulls/9]
```

Agent's own closing summary (33 agent messages): branch `agent/vik-628` from `main`; two
sentences added to the README's "Working on this repo" section; ran the repo's own quality gate
(`scripts/audit_terminology.py`) — clean; single commit with `VIK-628` and
`Agent-Trace-Id: ploeg-58aaeefccd95` trailers; PR #9 opened via the Forgejo API as
`agent-builder`. Its last line: *"PR is **open**, **not merged** — a human merges."*

### The reviewer (pod `ploeg-worker-bronze-reviewer-dgj8l-t6pdj`)

```
20:54:15  ploeg-worker starting version=0.2.0-rc.14 harness=openhands
20:54:15  claimed work item id=29 trace=ploeg-602c12547be6 role=reviewer shift=4 round=2 writes=false
20:54:16  reading run prepared on_review_branch=true branch=agent/vik-628 base=main
20:54:17  branch already has an open PR pr=https://forgejo.webgrip.dev/webgrip/erfbeeld/pulls/9
20:54:17  starting headless harness run role=reviewer budget_usd=0.4
20:54:17  minted per-run key   trace=ploeg-602c1254…
21:00:09  revoked per-run key  trace=ploeg-602c1254…
21:00:09  run finished outcome=no_change_needed
```

Note what the reviewer log does *not* contain: no `using the shared forge credential` line. The
builder has it, the reviewer does not. That is the rc.14 credential fix, visible as an absence.

### The review itself (`agent_runs.findings`, run id 41, `verdict=approve`)

Stored verbatim in the dispatch DB. Excerpt:

> **Accuracy:** The text correctly states that changes are dispatched from the Erfbeeld board by
> the Ploeg factory, and that agents open PRs but never merge them. This matches the workflow
> described in `AGENTS.md` […]
>
> **Minor observation (not a change request):** Neither "Erfbeeld board" nor "Ploeg factory" is
> linked. The board's MCP server is LAN-only per the repo conventions, so a URL would not be
> useful to external readers. This is the right call — linking to something unreachable would be
> worse than not linking at all.
>
> **Verdict: Approve.**

The reviewer read the repo's conventions and defended a *non-change* on the grounds of those
conventions. It is a real review, not a rubber stamp — and it is also a review of a two-sentence
README edit, which is the honest size of the thing.

### The database rows

`kubectl exec -n ploeg ploeg-db-1 -c postgres -- psql -U postgres -d app`

| run | shift | role | round | writes | outcome | authorized | links | verdict |
|---|---|---|---|---|---|---|---|---|
| 41 | 4 | reviewer | 2 | false | `no_change_needed` | 0.4000 | `{}` | `approve` |
| 40 | 4 | builder | 1 | true | `pr_opened` | 2.0000 | erfbeeld/pulls/9 | — |
| 39 | 3 | devops | 2 | false | `failed` | 0.3000 | `{}` | — |
| 38 | 3 | reviewer | 2 | false | `failed` | 0.3000 | `{}` | — |
| 37 | 3 | builder | 1 | true | `pr_opened` | 2.0000 | erfbeeld/pulls/8 | — |
| 36 | 2 | (none) | 1 | true | `no_change_needed` | 0.0000 | `{}` | — |
| 35 | 1 | (none) | 1 | true | `pr_opened` | 0.0000 | ploeg/pulls/30 | — |

Runs 38 and 39 are the previous evening's fan-out: both readers dead in **1.2 seconds**
(19:30:49.52 → 19:30:50.71), the `exec: "opencode": executable file not found in $PATH` failure.
Runs 40/41 are the same team, same board, one chart version later.

`agent_runs.usage` is NULL on every row. Token/cost accounting does not flow back into the
dispatch DB; it lives only in the LiteLLM ledger. `shifts.spent` is `0.0000` for all four
shifts — the budget column is written by nothing. **Not built. Do not imply otherwise.**

---

## 2. The money

`kubectl exec -n ai litellm-db-1 -c postgres -- psql -U postgres -d litellm`, grouping
`LiteLLM_SpendLogs` by the per-run key over the day:

```sql
select left(api_key,12), count(*), round(sum(spend)::numeric,6), sum(total_tokens),
       min("startTime"), max("startTime")
from "LiteLLM_SpendLogs" where "startTime" > '2026-07-30 12:00:00' group by 1 order by 5;
```

| run key | calls | USD | tokens | window (UTC) | what it was |
|---|---|---|---|---|---|
| A | 37 | **0.010315** | 1,153,540 | 12:22:52 → 12:30:18 | silver, shift 1, ploeg PR #30 |
| B | 35 | **0.015096** | 1,211,793 | 19:23:48 → 19:29:51 | bronze builder, shift 3, erfbeeld PR #8 |
| C | 32 | **0.013573** | 1,153,764 | 20:49:36 → 20:53:38 | bronze builder, shift 4, erfbeeld PR #9 |
| D | 16 | **0.006299** | 454,392 | 20:56:37 → 21:00:02 | bronze reviewer, shift 4 |

**A ticket, a pull request and an independent review of it: $0.013573 + $0.006299 = $0.019872.**
Two cents. The reviewer costs 46% of what the builder costs, on the same model.

Model actually served: `deepseek/deepseek-v4-flash` (the worker asks for `deepseek-chat`; the
proxy routes it). Prompt caching is doing heavy lifting — a typical row shows
`prompt_tokens: 33128` of which `cached_tokens: 33024`, i.e. 99.7% cache hit, `input_cost`
$0.000107.

**Attribution gap, found while gathering this.** Joining spend rows to `LiteLLM_VerificationToken`
to recover the run alias returns NULL for every row, and
`select … where key_alias like 'ploeg%'` returns **0 rows**. Per-run keys are revoked at run end,
revocation deletes the token record, and the human-readable alias → trace-id mapping dies with
it. The ledger keeps the money and the key *hash*; it no longer knows whose key it was. The July
draft claimed the correlation id was "revocation-proof" via an exporter reading the alias out of
request metadata — that path needs re-checking before the new post repeats the claim.

> **CORRECTION, 2026-07-31 (later the same morning).** The paragraph above is **wrong**, and the
> post's "The ledger forgets whose key it was" line is wrong with it. Attribution survives
> revocation perfectly well; I looked in the wrong table.
>
> LiteLLM denormalises the alias into the immutable spend log rather than referencing the token
> row, so `LiteLLM_SpendLogs.metadata->>'user_api_key_alias'` is populated on **83 of 83** rows
> from 2026-07-30 after 19:00, carrying values like `ploeg-58aaeefccd95`. That is
> `"ploeg-" + run_token[:12]`, and `agent_runs.run_token` is intact, so
> `left(run_token,12)` joins spend to run directly — for every run ever dispatched, ~$0.74 total
> across 20 aliases. The Grafana spend-attribution dashboard already does exactly this join.
>
> Deleting the token row loses the *foreign key*, not the *label*. What is genuinely broken is
> the enforcement ledger (`shifts.spent`, §5), which is a different problem with a different fix.
> `request_tags` really is useless — it only ever contains the User-Agent.
>
> The draft must be corrected before publishing: the honest version is "the money and the name
> both survive; the dispatcher just never reads them back."

---

## 3. The board, told properly for the first time

`kubectl exec -n vikunja vikunja-db-1 -c postgres -- psql -U postgres -d app`, `task_comments`:

**VIK-628, 21:00:09** (after rc.14):
> Ploeg **finished** this item and opened a pull request.
> **Outcome:** plan complete; a person is asked to review and merge
> **Pull request:** https://forgejo.webgrip.dev/webgrip/erfbeeld/pulls/9
> Please review and merge — the agents never merge their own work. This task stays open until it
> is in production and its first telemetry has been seen.
> *2 agent run(s) across 2 round(s).*

**VIK-624, 19:30:59** (ninety minutes earlier, rc.13):
> Ploeg **stopped working** this item.
> […] *3 agent run(s) across 2 round(s).*

Same board, same team, same day. A successful shift described itself as a stoppage until rc.14;
the fix is legible as a one-word diff between two comments a reader can see side by side.

**Task states.** `select id, done, done_at from tasks where id in (580,586,624,628)` → all four
`done = f`, `done_at` empty. Ploeg has never closed a ticket. Work item 29 settled internally as
`needs_human`; the board stayed open. Definition of Done is production plus telemetry, and Ploeg
can observe neither.

---

## 4. Failure museum — what last night added

### 4.1 The review that reached nobody

```
21:00:09 WARN findings not published: no provider for forge  forge="" shift=4
```

The reviewer read the diff, wrote a real review, stored it in the database, and set
`verdict=approve`. Then publication to the pull request failed because the resolved target's
`forge` field is the empty string, and the publisher looks the provider up by forge id rather
than falling through to the single configured provider. `ploegd` logs
`forge provider configured forge_id=forgejo` at boot, four lines into its own startup.

This is the **same class as the bug rc.13 fixed** — the factory doing the work and telling nobody
— one layer further out. The first one was `notifyHuman` gated on `needs_human`, so the success
path was the silent one. This one is a lookup key that is empty because the routing rule never
sets it. Two independent instances of "the last hop is the one nobody tests" in two days.

The honest sentence for the post: **PR #9 has a review, and the pull request does not know it.**

### 4.2 Naming a thing switched it off (`0b49c7ff`, 21:00)

Setting `serviceAccountName: ploeg-worker` — the chart's own default value — suppressed creation
of the ServiceAccount, because the template's guard read a *name* as "something external owns
this". Every worker Job then failed with `serviceaccount "ploeg-worker" not found`. Naming the
default and saying nothing were opposites.

### 4.3 Narrowing a Kyverno waiver blocked the whole factory (`91bc5e17`, 21:17)

bronze could not dispatch at all: KEDA looped on `KEDAJobCreateFailed`, with
`pod-security-baseline-enforce/autogen-privileged-containers` denying the Job.

The waiver had been narrowed from a workload-name match to a hazard-label match
(`ploeg.webgrip.dev/privileged-dind`) — which is the *right* instinct and the wrong mechanism:
**a Job selector matches the Job's own labels**, and the hazard label lives on the pod template,
so the Job never carries it. The comment above the match asserted otherwise.

Compounding it, from the commit message: *"I removed the equivalent entries earlier after
checking `.spec.rules` for an `autogen-` sibling and finding none. That check was wrong:
`.spec.rules` lists only AUTHORED rules; Kyverno generates the autogen variants at admission."*
An inspection of the policy object cannot see the rules the policy will actually enforce.

copper survived only because `dind: false` means no privileged container — which is also why the
reviewer Role needs no waiver at all, and stays held to the full baseline.

### 4.4 Thirty seconds of DNS, thirty minutes of blackout (`6a4c6c15`, 17:32)

k8s-gateway restarted 10 times. It is the sole upstream for the `webgrip.dev` zone, so for a few
seconds `harbor.webgrip.dev` had no record. CoreDNS cached that NXDOMAIN at the **default denial
TTL of 1800s** and kept serving it long after the upstream recovered. Cluster-wide, nothing could
pull a chart or an image from Harbor by hostname; Flux's ploeg OCIRepository sat on
`OCIArtifactPullFailed` and the rc.13 rollout could not proceed.

Verified by querying both resolvers: k8s-gateway answered `10.0.0.27` while CoreDNS still said
NXDOMAIN for the same name, and `grafana.webgrip.dev` resolved fine through the identical path.

Fix: `denial 9984 30`. Positive caching and `serve_stale` untouched — *serving a known address
through an outage is wanted; manufacturing a durable "does not exist" from a restart is not.*
It does not flush the entry already cached; that needs a CoreDNS restart.

### 4.5a The false-constraint prompt, verbatim and sourced

The post's title rests on this, so it is quoted from source rather than memory. In the ploeg repo,
`git show 8045b6d` ("fix(worker): give a reader the work, and take away the credential",
2026-07-30 22:02) removes exactly these two lines from the reading run's contract:

```
Do NOT modify, commit or push anything: you hold no lease on this branch and
no write credential, so a push will be rejected by the forge.
```

The same commit message states the mechanism: *"It held a full push credential. AGENT_BUILDER_TOKEN
is requireEnv on every [worker pod]"*, and `pkg/worker/worker.go:253` carries the surviving comment
*"straight into the agent's process, so 'you hold no write credential'"*. The clone URL is built by
`authURL(…, "agent-builder", cfg.BuilderToken, …)` unconditionally, and the agent inherits
`os.Environ()`.

**The fix is mutation-tested**, which is the only reason it can be claimed as a control. From the
commit message: *"Mutation-tested both ways: with the scrub disabled the reading-run tests fail,
with it restored they pass, and the writer-keeps-its-token case holds throughout."* That covers
both directions plus the must-still-pass case.

### 4.5 The obvious diagnosis was wrong (rc.14 commit message, `d8f9f652`)

Readers died with `exec: "opencode": executable file not found in $PATH`, which reads as "ship
the binary". Shipping opencode would have converted *failed to start* into *started, reviewed,
and threw the review away*: ACP and claude-code set no outcome file and populate no findings, so
only `openhands` and `exec` can return a review at all. The real blockers were four defects
deeper, in ploegd — shallow single-branch clone of the base, no PR reference, a live push
credential, a clean reader recorded as having pushed. The reviewer now runs on the image that was
already there.

---

## 5. Still not true on 2026-07-31 — say so plainly

- **Merge, deploy, telemetry.** Nothing merges. Nothing deploys. No telemetry closes the loop.
  All four recent tickets are still open on the board.
- **The review reaching the PR.** §4.1. Wired, ran, blocked at the last hop.
- **Per-run forge credentials.** `per-run forge credentials disabled (PLOEG_FORGEJO_ADMIN_TOKEN
  unset); workers use the shared token` — logged at every boot. ADR-0013 tier 2 has never worked
  on this Forgejo: the broker calls `/api/v1/admin/users/{bot}/tokens`, which 404s on Forgejo
  15.0.2 (confirmed running: `{"version":"15.0.2+gitea-1.22.0"}`).
- **Spend accounting in the dispatch plane.** `shifts.spent = 0.0000`, `agent_runs.usage = NULL`.
  The caps are enforced at the proxy, not tracked by the dispatcher.
- **Ledger→run attribution.** §2, attribution gap.
- **The refinement/DoR team.** Designed, not built.
- **Branch protection.** Agents not merging is convention plus a prompt, not enforcement.
- **Harness plurality / opencode.** ADR-0051 still `proposed`.

---

## 6. Verification notes / limits

- `webgrip/erfbeeld` is a **private** repo: `GET /api/v1/repos/webgrip/erfbeeld` returns 404
  unauthenticated, so PR #9's state on the forge could not be independently confirmed from
  outside. The PR URL is recorded in `agent_runs.links` (run 40), in the builder's own log line,
  and in the board comment. `webgrip/ploeg` is public and returns 200.
- flux-local could not be run for the rc.14 commit (local Docker daemon down); that commit's
  evidence is a rendered chart plus kubeconform, not a full tree build. Stated in the commit.
- All July draft figures (33 open tickets, six dashboards, agent-runner 1.0.0, `$0.064`) are
  frozen at 2026-07-19 and must be re-derived. See §7–§8.

---

## 7. The board and the decision record, 2026-07-31

### Board (direct SQL; the Vikunja MCP is not connected this session)

| project | done | open | total |
|---|---|---|---|
| Homelab Roadmap | 28 | 154 | 182 |
| Erfbeeld | 0 | 115 | 115 |
| **Dark Factory** | **13** | **46** | **59** |
| Vellum | 0 | 30 | 30 |
| Forgejo Migration | 1 | 10 | 11 |
| CI/CD | 58 | 21 | 79 |
| Ploeg | 4 | 113 | 117 |
| Ploeg Test | 6 | 17 | 23 |
| De Vloer | 0 | 7 | 7 |
| **all projects** | **113** | **513** | **626** |

The July draft's "33 open tickets" in the dark-factory project is now **46**. Building the thing
generated more backlog than it burned.

**The board has four users**: `ryangr0`, and three agent users named `bronze`, `silver`,
`copper`. The team names *are* the users. Assignment is the dispatch mechanism — there is no
`agent-builder` board account; roles live inside a Shift and are never assignable.

**Everything the agents have ever been assigned: 10 tasks.** 6 done, 4 open. Every completed one
is in the *Ploeg Test* project — drills and smoke tests. The only agent work aimed at a real
product repo is bronze's two open Erfbeeld tickets, 624 and 628. That is the honest scale of it
and the post must not round it up.

### ADRs 0044–0051 (status = literal frontmatter value)

| ADR | status | subject |
|---|---|---|
| 0044 | `proposed` | Metered inference plane (LiteLLM, CNPG ledger, per-task virtual keys with hard caps) |
| 0045 | `superseded by 0047` | opencode as runtime + server-side guards. Never ratified. |
| 0047 | `superseded by 0051` | OpenHands as runtime; `builder ≠ judge` moves to the pipeline. Never ratified. |
| 0048 | `proposed` | Dark-factory execution layer: a second KEDA-scaled Forgejo Actions pool, two role bots |
| 0049 | `accepted` | Failure states under permanent scarcity: Guaranteed-QoS admission control; infra failures never burn the attempt budget |
| 0050 | `accepted` | Server-enforced per-repo delivery contract (branch protection + janitor + harness guard); discipline-based protocols rejected |
| 0051 | `proposed` | Harnesses are plural behind ACP; OpenHands stays default |

Two of the three runtime ADRs were **superseded before they were ever ratified** (0045 → 0047 →
0051, inside twelve days). Good material, honestly told: the runtime question churned faster than
the decision record could settle it.

**ADR-0048 is stale against reality.** It specifies a second Forgejo Actions runner pool labelled
`agent`. What actually ships is Ploeg: a dispatch plane with a KEDA `ScaledJob` per team. The RFC
is stale in the same direction — its "decisions this RFC feeds" table still lists only 0044/0045
and calls the execution substrate a candidate. If the post cites the ADRs it must say which ones
describe the built thing and which describe the plan.

### RFC `rfc-dark-factory.md` — `Accepted in part`, 2026-07-14

Proposes the loop ticket → scheduled agent → PR → human merge → ticket closes, with the board as
system of record. Its design thesis is **human/agent parity**: one pipeline where a developer and
an agent are interchangeable operators, same skills profile, same toolchain, each spending
metered tokens on their own budgeted key. Names five hazards, of which HAZ-05 is the load-bearing
one for this post: **review independence requires a different model *family*** — citing
same-family review inflating pass rates by 9–17 percentage points, and an LLM failing to fix its
own errors ~64.5% of the time.

*Which means last night's run does not satisfy the project's own review standard: builder and
reviewer both ran `deepseek-chat`. Different Roles, different credentials, different pods, same
model family. The post must say this out loud — it is the single most important caveat on the
milestone.*

---

## 8. Ploeg as deployed — `kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml`

`ploegd` `0.2.0-rc.14`, digest-pinned. Runner image `agent-runner:1.0.3`, dind `docker:29.6.2`.
Neither runner line has a Renovate matcher; both are manual bumps.

### Boards decide the repo (7 rules, resolved by name at boot)

| board | repo | branch |
|---|---|---|
| Ploeg Test / Ploeg | `webgrip/ploeg` | `development` |
| Erfbeeld | `webgrip/erfbeeld` | `main` |
| Homelab Roadmap / CI/CD / Dark Factory / De Vloer | `webgrip/homelab-cluster` | `main` |

Deliberately unrouted: *Forgejo Migration* (irreducibly multi-repo), *Vellum* (no repo exists
yet), *Inbox* (triage). ploegd refuses to start if a project name matches nothing.

### Teams as capabilities

| team | model | team budget | target | harness | plan |
|---|---|---|---|---|---|
| **bronze** | `deepseek-chat` | `"3"` | erfbeeld / main | openhands + dind (builder); openhands, `dind: false` (reviewer) | R1 `builder writes:true cap 2.00` → R2 `reviewer writes:false cap 0.40`, 500m/384Mi |
| **silver** | `claude-sonnet-5` | `"6"` | ploeg / development | openhands | none — single writer |
| **copper** | `deepseek-chat` (key scope only; never calls the LLM) | `"1"` | erfbeeld / main | `exec` running `/bin/cat {taskspec}` | none |

copper is the seam test: it runs `/bin/cat` on the generated taskspec inside the same runner
image and exits 0, proving per-team harness selection, taskspec composition, key mint/revoke and
the `no_change_needed` path **without spending a single LLM token**. Worth a paragraph: the
cheapest possible integration test for an expensive system is one that deliberately doesn't
think.

Sizing, per ADR-0049 P1 (Guaranteed QoS, requests == limits): worker `1 CPU / 768Mi`, peak
measured 438Mi. The full core is there because *the OpenHands CLI's single-threaded Python cold
import took 2m20s at 500m before the agent did anything* — and docker/dind was a red herring, its
daemon came up in 13 seconds.

### Inconsistencies found in the manifest — do not repeat these as fact

- bronze's comment says "$2/run budget", `budget: "3"`. silver's says "$4/run", `budget: "6"`.
  The Role caps sum to 2.40 for bronze, so `budget` looks like a headroom envelope above the
  per-Role caps, but ploegd's exact semantics were not verified from this repo.
- A comment still warns "do not assign copper tickets until the rc.5 chart bump lands" — obsolete
  at rc.14.
- The `jake`/`jane` assignees were removed: invented human colleagues who were never Vikunja
  users, so the mapping could never have fired.

---

## 9. Fresh infrastructure and cost figures, 2026-07-31

### The cluster

5 Talos nodes, v1.13.4 / Kubernetes v1.36.1, **24 vCPU and 72 GiB total**. Three `soyo`
control-planes (4c/11Gi each, 234 days old), two workers: `fringe-workstation` (8c/15Gi, 158d)
and `worker-1` (4c/23Gi, 41d). 99 Flux Kustomizations, all Ready. 60 HelmReleases, 58 Ready —
`harbor` sits on a rollback and `n8n` on a failed upgrade as of this morning, which is a fair
picture of a homelab at rest. 36 namespaces, 217 running pods, 142 unique images.

The July draft said "5 nodes, 2 workers, both a decade old". `worker-1` is now 41 days in the
cluster; the i5-4670K / i7-4770 description needs re-checking against what is actually in the
machines before it is repeated.

### What it costs to run — with the caveat that makes the number nearly worthless

OpenCost says **€94.76/month (≈ €1,138/year)**: €84.65 nodes, €10.11 storage. Cross-checked two
ways (`sum(node_total_hourly_cost) * 730` and the asset API) and they agree exactly.

**They agree because they share an assumption.** The OpenCost provider is `custom`, with rates
hand-set in `kubernetes/apps/observability/opencost/app/helmrelease.yaml` (€2.19/core-month,
€0.44/GB-month, €0.0146/GB-month storage) and a comment saying they were calibrated to hit a
~€1,000/year TCO target. The €1,138 figure largely reproduces its own input. There is no bill
behind it. **If the post quotes a euro figure it must say this in the same breath.**

### Power — not measured, and the obvious query is wrong

Kepler reports **72.84 W** cluster-wide, 7-day average (worker-1 36.2, fringe 26.9, and the three
soyos 2.6–3.6 W each — control planes really are nearly free). Two caveats:

1. **That is CPU package + DRAM only.** Kepler reads Intel RAPL. No PSU losses, disks, fans,
   NICs, chipset. Real wall draw is materially higher and **nobody is measuring it**: a search
   for any metric matching watt/power/energy/joule returns only Kepler and one static NVDIMM
   budget constant from cadvisor. No smart plug, no UPS, no PDU is scraped.
2. **The naive query is wrong and gives 104.7 W.** RAPL zones nest — `package` already contains
   `core` and `uncore` — so `sum(kepler_node_cpu_watts)` double-counts. The correct filter is
   `zone=~"package|dram"`. A 44% overstatement available to anyone who writes the obvious PromQL.
   Small, self-contained, and exactly the kind of thing this post is about.

At NL rates (~€0.30–0.40/kWh, roughly €3/year per continuous watt), 72.84 W of silicon is about
€220/year — a floor, not the bill.

### LLM spend, all of it

| window | spend | calls |
|---|---|---|
| last 7 days | **$1.0243** | 2,060 |
| last 30 days | **$1.4039** | 2,379 |
| **ledger lifetime** (2026-07-15 → 2026-07-30) | **$1.4039** | 2,379 |

The 30-day and lifetime figures are the same number because the ledger is only 16 days old. By
model over 7 days: `deepseek-v4-flash` $0.8742 (1,711 calls, 74.2M tokens), `deepseek-chat`
$0.1471, all Anthropic models combined ~$0.0029 across 15 calls of 13–40 tokens each — probes,
not work. Effectively 100% of real spend is DeepSeek.

**The entire inference bill for every experiment, drill, failed run and shipped pull request in
the project's life is $1.40.** That is the FinOps headline, and it is honest.

### Throughput — the humbling table

| window | commits on `main` | merges | Renovate merges |
|---|---|---|---|
| last 7 days | 159 | 37 | 19 (51%) |
| last 30 days | 594 | 102 | 82 (80%) |

Commit authors over 30 days: **Ryan Grippeling 493, Renovate Bot 79, renovate 20,
`agent-builder` 2.**

**Correction, verified 2026-07-31.** An earlier version of this file said the two `agent-builder`
commits were README edits in another repo's PRs. That was wrong. `git log origin/main
--author=agent-builder --name-only` gives:

| commit | date | subject | files |
|---|---|---|---|
| `ccb09d42` | 07-22 22:18 | `feat(erfbeeld): deploy CI-published 1.0.3 to dev/staging/production` | 18 files under `kubernetes/apps/erfbeeld/{dev,staging,production}/app/` — HelmRelease, OCIRepository, ExternalSecret, kustomization, sops secret |
| `a5372aa4` | 07-23 05:26 | `feat(erfbeeld): track split release trains — chart 0.1.0, images 0.1.0` | 6 files, HelmRelease + OCIRepository across the three environments |

So they are **real deployment changes to this repository, merged to `main`**, promoting a
CI-published image across three environments. They are better than I described. They are also
**not** Ploeg's work: both predate the dispatch plane's first Shift by a week and came out of the
older Forgejo-Actions-based factory. Last night's two Ploeg pull requests are in erfbeeld and are
still open.

Two commits out of 594 is 0.34% of the month. Renovate accounted for 82 of the window's 102
merges.

**This table goes in the post.** It is the strongest available answer to "is this hype?", it is
funnier than anything I could write, and any post that omits it is selling something. The
correction above must travel with it.

---

## 10. Gaps the pre-publication review opened, and what closed them

A fresh-reader pass and an adversarial fact-check pass were run against draft v1. Findings that
changed the post rather than just its wording:

1. **The headline cost number was attributed by wall-clock window, not by stored run id** — which
   the post itself explains is impossible, since revocation deletes the alias. v1 said "from the
   ledger, not an estimate" and quoted six decimal places. v2 discloses the matching method in the
   same sentence as the number.
2. **The reviewer has never requested changes.** It has returned exactly one verdict in its life:
   approve, on a two-sentence README edit. No adversarial test (planted bug, watch it approve) has
   ever been run. v1 did not say this; v2 does. Mitigating detail worth stating: the *broken*
   reviewer never emitted a verdict either, because runs 38 and 39 died at startup, so there is no
   backlog of untrustworthy approvals sitting in the database.
3. **Prompt injection is not addressed anywhere in the design.** The builder pod ingests board
   ticket text as instructions while holding a shared forge token with push access and a
   privileged Docker daemon. `automountServiceAccountToken: false` is irrelevant to that. The only
   control today is that the board has exactly **one** human user (§7: `ryangr0`, plus the three
   agent users), so the input is trusted by assumption. v2 states this as an open hazard.
4. **"No bespoke operator on the critical path" contradicts Ploeg**, which is a bespoke Go
   dispatch plane with its own object model, routing table, validator and database, sitting
   directly on the critical path. v1 kept the old draft's claim; v2 retires it.
5. **"An idle factory costs exactly nothing" contradicts the power section** (73 W continuous,
   ~€220/year floor). Scale-from-zero removes marginal inference and pod cost, not the cluster.
