# RFC: Omnigraph 0.14 — the upgrade, what we take from the cookbooks, and how knowledge is tiered

> Status: **Proposed** · Date: 2026-10-24 · Epic: VIK-1259 (second brain) and VIK-1858 (agents learn
> from a knowledge base) · Replaces the open ticket VIK-2054 with the plan below · Builds on the
> [knowledge system](../general/knowledge-system.md), the [Omnigraph runbook](../runbooks/omnigraph.md),
> the [branch workflow RFC](rfc-omnigraph-branch-workflow.md), the
> [brain retrieval RFC](rfc-brain-retrieval.md) and Ploeg ADR-0087/0088/0089.

> **TL;DR.** The homelab runs Omnigraph **0.11.0**; upstream released **0.12.0** (2026-10-05),
> **0.13.0** (2026-10-07) and **0.14.0** (2026-10-22). The release notes were read in full
> (about 140 items) and every item that touches this estate has a verdict in
> [section 3](#3-release-notes-012--014-verdicts). Three things decide the shape of the work:
>
> 1. **The upgrade is a rebuild, not a bump.** Measured locally ([section 4](#4-the-upgrade-path-measured)):
>    a 0.11 *cluster-managed* graph cannot be converted in place by any 0.14 command, and an
>    upgraded standalone copy cannot be put back into a cluster. Every graph is exported with 0.11
>    and loaded into a fresh 0.14 cluster root. Rows, vectors and blobs survive; commit history and
>    branches do not. The 0.11 export bug on brain's `Artifact` table (VIK-2054) has a measured
>    workaround: copy the graph root out, run the 0.14 offline upgrade on the copy, export with 0.14.
> 2. **The HTTP contract, the CLI and the MCP bridge all change at once**, so the cutover touches
>    three repositories (this one, `omnigraph-explorer`, `ploeg`) and lands as one rehearsed change
>    set behind a parallel deployment, with the brain eval gate measured before and after.
> 3. **Tiering is by graph, never by property.** Omnigraph's policy is graph- and branch-scoped and
>    upstream states that per-entity and per-property authorization is not supported. The estate
>    already has the right shape (seven graphs, eighteen actors, a scope gate in ploegd and
>    brain-tools); [section 6](#6-knowledge-tiers-who-may-know-what) names the tiers, the rules, and
>    the one structural change: the company graph takes the `company-brain` cookbook's claim layer.
>
> Also today: **Omnigraph was down for 20 hours** because its 5Gi volume filled up
> ([section 1](#1-the-incident-of-2026-10-23)). Fixed by growing the volume to 20Gi
> (commit 3044d1c8); the cleanup that stops it recurring is P0 below.

## 1. The incident of 2026-10-23

| Fact | Evidence |
|---|---|
| The pod sat in `Init:CrashLoopBackOff` from the 03:15 maintenance restart until 00:05 on 2026-10-24 (243 restarts) | `kubectl -n ai get pod -l app=omnigraph`, 2026-10-23 21:50Z |
| Cause: the 5Gi Longhorn volume `omnigraph-state` was full (actualSize 5,355,282,432 of 5,368,709,120 bytes) and the init container could not write `__cluster/lock.json` | init container log: `storage write_if_absent failed … No space left on device (os error 28)` |
| Growth: 2.16 GB on 2026-10-08 → 5.27 GB on 2026-10-23, about 200 MB a day. 0.11 retains every old table version until an explicit `cleanup`, and the importers rewrite rows every 15 minutes and every hour | `kubelet_volume_stats_used_bytes{persistentvolumeclaim="omnigraph-state"}` over 30 days |
| The alerts fired: `OmnigraphUnreachable`, `PVCVolumeAlmostFull`, `PVCVolumeFillingFast`, `AppPersistentVolumeCriticallyLowFree`, plus every importer's `*Stale`. Nobody acted on them for 20 hours | `max_over_time(ALERTS{alertstate="firing"}[24h])` |
| Fix: PVC 5Gi → 20Gi (Longhorn expanded the attached volume online; the node has 60Gi free). Pod Ready at 00:05, vault import reading again at 00:05 | commit 3044d1c8; `kubectl -n ai get pvc omnigraph-state` shows capacity 20Gi |

What the incident teaches, beyond the fix:

- **Nothing reclaims space.** The nightly `optimize` compacts but never deletes; `cleanup --keep N`
  exists in 0.11 and in 0.14 but is not run anywhere. At 200 MB a day the 20Gi volume lasts about
  70 days. P0 adds a bounded cleanup to the nightly init container (the server is stopped then, so
  there is no concurrency question), with the 0.12 note in mind that the first cleanup after the
  upgrade must be `cleanup --keep 1 --confirm` alone.
- **Firing is not delivery.** The alert rules were right; the [alert delivery RFC](rfc-alert-delivery.md)
  owns why a critical on the second brain reached nobody. This RFC does not re-open that.
- **The volume carries every graph.** One full disk took down the second brain, agent memory, the
  company graph and both Ploeg tenant graphs, plus every front door. Tiering by graph
  ([section 6](#6-knowledge-tiers-who-may-know-what)) does not change that; one server, one volume is
  the accepted blast radius for now, and the cleanup plus the volume alerts are the controls.

## 2. Where we stand

| Piece | State on 2026-10-24 |
|---|---|
| Server and CLI | `modernrelay/omnigraph-server:v0.11.0`, mise pin 0.11.0, storage format v9, HTTP contract pre-0.12 (no `Omnigraph-Http-Api` header) |
| Graphs | `brain` (second brain, the `second-brain` cookbook plus `Passage`, `Topic`, `Distillation`), `memory` (agent memory), `webgrip` (company meetings: `Meeting`, `Source`, `Chunk`, `Decision`, `ActionItem`, `Person`, `Topic`), `webgrip-knowledge` and `webgrip-notes` (Ploeg's tenant graphs, ADR-0087/0088). `client-<name>` graphs on demand from `meetings.pg` |
| Actors | 18 tokens, one per writer or door: `act-ryan`, `act-admin`, `act-brain-agent`, `act-brain-reader`, `act-brain-scribe`, `act-brain-eval`, `act-vault-import`, `act-forge-import`, `act-distill`, `act-glide`, `act-review`, `act-explorer`, `act-ingest`, `act-agent`, `act-reader`, `act-ploeg-run`, `act-ploeg-review`, `act-gitops` |
| Writers | Obsidian importer (every 15 min), Forgejo importer (hourly :40), distiller (hourly :55), embed-step (writer-side vectors), meeting ingest (`just omnigraph-ingest-meeting`), ploegd (notes graph `main`, knowledge graph by promotion), chat and Claude Code (`brain` `main` directly), Glide/Ploeg runs (`glide/<run>` branches) |
| Doors | Open WebUI and Claude Code through LiteLLM's MCP gateway (`@modernrelay/omnigraph-mcp` 0.10.0 behind supergateway, seven containers, one per actor×graph), brain-tools (MCP + REST, `rt_*` stored queries, profiles `p0`/`p1`), explorer and review UI (`omnigraph-explorer`, first-party), the `omnigraph` CLI on the laptop (`just omnigraph-login`) |
| Gates | pre-commit rehearsal (`scripts/rehearse-omnigraph-bundle.sh`, 10 s, mutation-tested), brain eval (nightly retrieval, weekly answers), policy validator, writer tests |
| Known open tickets | VIK-2054 (upgrade from 0.11), VIK-1404 (export limit), VIK-1348 (backfill out of the startup path, in review), VIK-1347 (schema-ready check), VIK-1406/1573 (03:15 restart quirks), VIK-1872 (tenant graphs, done in fact), VIK-1300 (Glide tools) |

## 3. Release notes 0.12 → 0.14: verdicts

Read in full from the GitHub releases. Verdicts use the dependency-intake scale: **breaks us**,
**shifts a default we rely on**, **retires a workaround**, **worth adopting**, **reaches agents or
users**, **noise**. Items not listed are noise for this estate (managed-service CLI, Azure, GQT,
benchmarks, Rust API changes).

### 3.1 Breaks us (must change before or at the cutover)

| Release | Change | What it hits here | Action |
|---|---|---|---|
| 0.12 | Storage format 14 (0.14: 16); ordinary open refuses v8/v9; `omnigraph upgrade` converts only *standalone* graphs; cluster-managed graphs are rebuilt by export and load | Every graph is cluster-managed | Export with 0.11 (or the copy-out route), fresh 0.14 cluster, load. History and branches are lost; the plan accepts that ([section 4](#4-the-upgrade-path-measured)) |
| 0.12 | Ledger v2 only: `cluster import`, `approve` and the apply fallback are removed; `cluster upgrade-ledger --writers-stopped` converts a ledger but refuses one whose graphs are v9 (measured) | `bootstrap.sh` steps 2–4 (`import`, gated `approve`, `apply`), `approved-deletions` | Rewrite the bootstrap around fresh `cluster apply --target ROOT --config DIR` plus `force-unlock` of its own lock before serving; the deletion gate becomes a plan check for graph removals |
| 0.12 | One HTTP contract header, `Omnigraph-Http-Api: 0.12`, then `0.14`; missing or wrong value is `400 api_contract_mismatch` before any effect | brain-tools (`upstream.ts`), explorer (review server and read path), ploegd (`pkg/omnigraph/client.go`), brain-eval, forge-import's direct HTTP calls, the blackbox probe bodies | Add the header in every client and pin the value next to the image pin; three repositories, one coordinated release |
| 0.14 | CLI redesign: `--server`/`--store`/`--cluster`/`--profile` are gone; destinations are `--target NAME|PATH`, sources `--config DIR`; the operator file format changed (`servers:` is refused, measured) | every `apply.sh` and `snapshot.sh` in vault-import, forge-import, distill; `bootstrap.sh`; the justfile recipes; `just omnigraph-login` writes the old format; the rehearsal script | Rewrite; `omnigraph-login` writes a 0.14 operator file (`targets.homelab`, `auth: {provider: token, source: {store: {}}}`) |
| 0.14 | A server target's endpoint must be HTTPS; HTTP only for an anonymous loopback server | The importers run the CLI against `http://omnigraph.ai.svc.cluster.local:8080` with a bearer token | Decision D2: the importers call the HTTP API directly (they are Python already; the `disposition` body gives them exact outcomes), or the pod terminates TLS from the cluster CA. Recommendation: direct HTTP |
| 0.12 | `@modernrelay/omnigraph-mcp` must match the server; 0.14 ships the MCP endpoint in the server and says the npm package is replaced | The omnigraph-mcp bridge deployment (seven supergateway containers, pinned 0.10.0) | Retire the bridge: LiteLLM points at `http://omnigraph…:8080/mcp` with one entry per actor; the server runs with `--mcp-allow-writes` and `--mcp-allowed-host omnigraph.ai.svc.cluster.local:8080` |
| 0.12 | `DateTime` strings with more than three fractional digits are refused on load, query and parameters; a stored query holding such a literal fails its graph's startup | Importers write timestamps from Forgejo and Obsidian (second precision); brain-eval metadata is not graph data | Add a check to the export-to-load step: no value with a fourth non-zero fractional digit; `cluster validate` with 0.14 already accepts every stored query (225 resources, measured) |
| 0.14 | `omnigraph embed` embeds the `@embed` source text **exactly as stored**, no templated line; "regenerate older offline embeddings with `--reembed-all`" | The embedding contract (`scripts/test_omnigraph_embedding_contract.py`) pins the template `type: {type}\n{field}: {value}` that the 0.11 backfill used; the writers copy it so row vectors match the backfill | Decision D3: one text format for every vector, which is the raw source text (what a text `nearest` query embeds). Re-embed every `Note`, `Passage`, `Topic`, `Decision`, `Concept` through the in-cluster TEI model after the load. Gate with the retrieval eval |
| 0.14 | String full-text calls require `@index` on the property | All searched properties already carry `@index`; validated by the 0.14 CLI | None, keep the validator |
| 0.12 | `--allow-data-loss` removed; drops no longer reclaim at apply; `cleanup --keep N` counts graph commits | `bootstrap.sh` never passed it | None |
| 0.12 | Multi-hop bounds such as `{1,2}` on an edge between two node types are refused with `T5` | `brain.gq`, `brain.topics.gq`: checked by `cluster validate` on 0.14 (passes) | None |

### 3.2 Shifts a default we rely on

| Release | Change | Here |
|---|---|---|
| 0.12 | `optimize` and `cleanup` run beside live writers; the recovery sidecars and the "optimize next to a live server leaves a barrier" failure are gone | The 03:15 restart exists only because of that 0.11 limit. After the upgrade it becomes a maintenance Job on the same node (RWO volume) and the server stops restarting nightly; VIK-1406 and VIK-1573 close with it |
| 0.12 | Admitted writes outlive their HTTP caller; a lost response is `outcome_unknown` with an exact disposition | The `omnigraph_write` helper classifies failures by grepping stderr; replace with `code` and `disposition.effects` |
| 0.12 | Exact merge receipts: a merge returns the commit it published; up-to-date is `commit: null` | The review UI's merge path reads the receipt; align |
| 0.14 | MCP write tools wait 30 s and never retry; requests are 64 KiB; results 1 MiB | Open WebUI tools and Claude Code: `load` over MCP stays small, bulk goes through `/load/ndjson` as today |
| 0.14 | Full-text lowercases and stems at write time; a `search` for "deep" no longer misses "Deep Learning" until the next optimize | Retires the "found by keyword only after 03:15" row in the knowledge-system table for case |
| 0.14 | `branch merge` bases on the newest common ancestor; a nearest-by-hops base could drop a delete or report a false conflict | The branch workflow RFC's conflict recipes stay; fewer false conflicts |
| 0.14 | Merges hold the source branch only while capturing it; merges into different targets run concurrently | Review UI no longer blocks a writing run while merging |
| 0.12 | Readiness during startup: `/readyz` reports `loading_graph_count`; `--require-all-graphs` keeps admission closed until every graph is up | The startup probe stays on `/healthz`; readiness semantics unchanged for us |
| 0.14 | Dropping a property no longer rewrites the table; `optimize` does | Schema drops get cheap; `cleanup` after optimize reclaims |

### 3.3 Retires a workaround

| Workaround here | Retired by |
|---|---|
| Explorer skips the `Artifact` table because 0.11's export dies at `ordered_scan_input_batch_bytes` (homelab #746, VIK-2054, VIK-1404) | 0.12 fix: "export … no longer fail with … `ordered_scan_input_batch_bytes`"; export and change baselines retain transport capacity and resume after backpressure |
| The review UI previews a merge on a throwaway branch (branch workflow RFC §7) | 0.14 `GET /branches/diff`, `GET /branches/merge-base`, `POST /branches/merge` with `dry_run: true` |
| Agent proposals live on `glide/<run>` branches, which block every schema change (runbook, VIK-1347) | 0.14 **unpublished commits**: `mutate … as commit` records the result off-branch; a person runs `commit publish` or `commit drop`; publishing is its own policy action (`commit_publish`); the proposal expires if `main` moves past its parent. No branch, no schema block |
| `omnigraph_write` guesses the outcome class from stderr text | Typed `disposition` (`effects: none|partial|unknown`, `action`) on every error |
| Hand-written policy probes (the 403 curls in VIK-1872's acceptance) | `GET /graphs/{id}/access` and `omnigraph access`: the server reports what a credential may do |
| The vendored MCP best-practice texts in the bridge | `/mcp` serves `omnigraph://best-practices/*` from the server's own version; `omnigraph skill export` writes the matching agent skill |

### 3.4 Worth adopting (after the cutover, each its own ticket)

| Feature | Why here |
|---|---|
| Unpublished commits as the agent proposal mechanism (`as commit`, `commit_publish`) | Replaces branches for Glide/Ploeg proposals and meeting ingests; removes the schema-change blocker class; the review UI shows a diff per proposal |
| Unattached branches (`as unattached branch`, `on "<id>"`) | A run's scratch snapshots that never publish: what-if writes for agents, dropped as a chain |
| `branch create --from-commit` | Revert or fix where a change was made, then merge |
| `return distinct`, `count(distinct …)`, Boolean projections over aggregates, list membership `in` | The `rt_*` and distiller queries get shorter and exact; `recall_*` dedupe moves into the graph |
| Correlated blocks (`exists {}`, `count {} > n`) and streaming traversal | The explorer's neighbourhood queries and `open_items` without whole-table scans |
| `query_memory_bytes`, `write_max_bytes`, `load_source_max_bytes` as settings | The export and backfill limits that broke VIK-1404 become tunable per request |
| `load csv` through `mutate` | Bulk imports of structured exports (FreshRSS, calendar) without JSONL conversion |
| Edge container images (`omnigraph-server:edge-<date>-<commit>`) | Test a fix before the release, never pin one in production (the Renovate hold rule stays) |
| Engine catalogue (`@Operator`, `@Setting`) | The rehearsal can assert server settings instead of parsing `--help` |
| `commit list --limit/--page-token` | The review UI and the branch monitor stop reading whole histories |

### 3.5 Reaches agents or users

- Every Open WebUI chat and Claude Code session loses its tools for the cutover window and gets a
  **different tool set** back (the server's own MCP: `graphs`, `schema`, `queries`, `query`, `read`
  (opt-in), `snapshot`, `access`, `branches_*`, `commits_*`, `changes_poll`, and with writes
  `mutate`, `load`, `branches_merge`). Tool names and schemas change; the Brain preset and the
  `second-brain` skill are re-cut.
- Error bodies change shape; brain-eval's tool-error classes (`gq_parse`, `policy_denied`, …) are
  re-derived from `code` instead of text.
- The laptop CLI needs a new operator file; `just omnigraph-login` rewrites it.

## 4. The upgrade path, measured

Run on 2026-10-24 with the pinned 0.11.0 CLI and the 0.14.0 CLI from mise against a throwaway copy
of the bundle (`scratchpad/mig/experiment.sh`). No homelab graph was touched.

| Test | Result |
|---|---|
| `omnigraph cluster validate --config bundle` with 0.14 on our unchanged bundle | **valid: 225 resources, 431 dependency edges**; five warnings that external Blob ingress is deny by default (intended) |
| 0.14 `omnigraph upgrade --target state/graphs/brain.omni --check` on a graph inside the 0.11 cluster root | **refused**: "upgrade refuses graph … inside cluster …; a qualified cluster upgrade operation is required" |
| 0.14 `cluster upgrade-ledger --writers-stopped` on the 0.11 root | **refused**: "`__manifest` is stamped at internal schema v9 … A cluster-managed graph has no in-place route yet: export with 0.11.x, `init`, `load --mode overwrite` … commit history and branches are not preserved" |
| Copy `brain.omni` out of the root, then 0.14 `upgrade --check` and `upgrade` on the copy | **completed**, history kept (route `history-lance-files-v9-to-v14`, 64 table opens); 0.14 `export` and `commit list` work on the copy |
| Put that upgraded copy into a fresh 0.14 cluster root under the same graph id | **refused**: `applied_schema_drift: opened graph schema differs from the cluster's achieved contract` |
| Fresh 0.14 `cluster apply --target ROOT --config bundle14` (bundle without the `storage:` line) | **converged**, five graphs created, lock id printed; `force-unlock <id>` then serving works |
| 0.14 CLI with the laptop's existing `~/.omnigraph/config.yaml` | **refused**: `unknown field 'server', expected one of 'profile', 'target', 'output'` |

So: the only route for our data is **export → fresh cluster → load**. The history loss is real
and bounded: commit history is the audit trail of the last four weeks of imports and a handful of
hand writes; the importers rebuild `brain` from source anyway, and the two tenant graphs are days
old. The upgraded standalone copy is the **export route for `brain`**, because 0.11's own export
cannot read `Artifact` (VIK-2054) and the copy-out upgrade is cheap (85 KB of legacy history on
the test graph; brain's is larger but bounded by the limits in the upgrade guide).

### 4.1 Cutover design: parallel root, same deployment

1. **Prepare (git, no cluster effect).** A new bundle directory `app/bundle` keeps the same
   `cluster.yaml`, schemas, queries and policies (they validate on 0.14 as they are). `storage:`
   is dropped and the state root is selected by `--target`. `bootstrap.sh` becomes:
   `cluster validate` → if no ledger: `cluster apply --target ROOT --config DIR --as act-gitops`,
   read its lock id, `force-unlock` it → else `cluster plan` (refuse on any graph removal unless
   named in `approved-deletions`) → `cluster apply` → `optimize` and bounded `cleanup` per graph
   → `rebuild-full-text-indexes` when optimize asks. The vector backfill stays capped exactly as
   today (VIK-1348's structural fix is separate).
2. **Rehearsal first.** `rehearse-omnigraph-bundle.sh` and `omnigraph_rehearsal.py` are ported to
   the 0.14 CLI (targets, operator file in a temp `OMNIGRAPH_HOME`, the `Omnigraph-Http-Api`
   header, `access` instead of probe curls). Its mutation test must still fail every case it fails
   today and pass the unchanged bundle. The CI job runs the same.
3. **Clients in step.** brain-tools, explorer, ploegd, brain-eval, forge-import's HTTP path and
   the blackbox probes send `Omnigraph-Http-Api: 0.14`. Explorer and ploegd release first with the
   header behind the image pin of their next release; LiteLLM's `mcp_servers` get the native
   `/mcp` entries (one per actor: `omnigraph_brain` as `act-brain-agent`, `omnigraph_memory` as
   `act-agent`, `omnigraph_glide` as `act-glide`, `omnigraph_brain_eval`) with the bridge entries
   removed; the omnigraph-mcp deployment is deleted in the same change.
4. **Data migration Job (hands-on, hook-blocked for agents).** With the deployment scaled to 0 and
   a Longhorn backup taken: a Job with the 0.11 image exports `memory`, `webgrip`,
   `webgrip-knowledge`, `webgrip-notes` as JSONL to a scratch PVC; for `brain` it copies
   `graphs/brain.omni` to the scratch PVC, and a second container with the 0.14 image runs
   `omnigraph upgrade` on the copy and exports it. The exports are checked: entity counts per
   type against the 0.11 `snapshot`, no sub-millisecond `DateTime`, every `@embed` row keeps its
   vector.
5. **New root.** The PVC is replaced by `omnigraph-state-v16` (20Gi). The 0.14 pod boots, the
   init container creates the cluster, the same Job loads each export with `load --mode overwrite`
   (one request per type batch under 32 MiB, through `/load/ndjson`), then re-embeds every
   `@embed` row with the raw-text format (D3). The old PVC stays until the eval gate passes.
6. **Gate.** The brain retrieval eval runs on the new root pinned to its first commit and is
   compared with the last 0.11 run; the smoke eval on answers runs once. Only then does the
   maintenance Job replace the 03:15 restart.
7. **Rollback** is scaling to 0, pointing the deployment back at the old PVC and the 0.11 image,
   and restoring the explorer and ploegd pins. Nothing written on 0.14 survives a rollback; the
   importers refill `brain` within an hour.

### 4.2 What stays hook-blocked and is handed over

Scaling the deployment, running the migration Job and deleting the old PVC are imperative cluster
actions that the agent hooks block. They come as one ordered command set in the P1 ticket, each
step with its read-only check, and are run by Ryan with an agent watching the output.

## 5. The cookbooks: what we have, what we lack, what we make

The cookbook repository (`ModernRelay/omnigraph-cookbooks`, 2026-10-19, written for 0.13) ships
seven bundles. Three were asked about.

### 5.1 `second-brain` — we have it

`brain.pg` **is** the cookbook's schema, extended: the same thirteen node types and forty-odd
edges, plus `Passage` (the cookbook's `Chunk`, with our 384-dimension vectors), `Topic` and
`Distillation` (the distiller's layer), `@index` on every searched text, and 103 stored reads and
58 stored mutations against 10 and a handful in the cookbook. The seed is replaced by 750 notes,
2,615 documents and 2,544 topics of real data. Nothing to build; two things to take:

- the cookbook's **slug prefixes** (`per-`, `org-`, `proj-`, `nt-`, `tk-`, …) are already our
  convention; keep enforcing them in `capture_*` mutations with `@check` on the slug once we are on
  0.14 (adding a `@check` is a rebuild, so it goes into the schema of the new root, D5);
- its `policies/` are the three-role sample; ours are richer. No change.

### 5.2 `company-brain` — we have half of it, and the other half is the valuable half

What the cookbook models that `meetings.pg` (the `webgrip` graph) does not:

| Cookbook idea | `meetings.pg` today | Gap |
|---|---|---|
| **Claims before facts.** `Claim` is what someone said, verbatim, with status `unverified → verified / rejected`; `Decision` and `ActionItem` are *promoted* from claims by a person | Decisions and action items are extracted directly from a source; `quote` is a property, not a node; nothing records "said but not accepted" | The claim layer: `Claim`, `ClaimFrom`, `ClaimedBy`, `Contradicts`, `BasedOn`, `ActionFrom` |
| **Decisions are never edited**; a change is a new `Decision` the old one points to with `SupersededBy @card(0..1)`, so two competing successors collide at merge | `Supersedes: Decision -> Decision` exists, unbounded | Flip the direction and cap it; store `rationale`; derive "current" in queries |
| **Actor ≠ Person**: `Actor` is the token identity (`act-…`), linked to the person accountable (`ActsFor`), so commit history joins to a node | Only `Person`; actors live in policy files | `Actor` node and `add_actor`/`deactivate_actor` |
| **Create is not overwrite**: each create also writes one unkeyed `@card(0..1)` edge, so re-creating an existing slug fails the whole write instead of resetting reviewed state | Keyed edges everywhere; a replayed ingest can overwrite a reviewed decision | The four guard edges (`ClaimFrom`, `DecisionAbout`, `AssignedTo`, `ActsFor`) and the stored mutations that write node and guard edge in one commit |
| **Two clocks**: `occurred_at`/`decided_at` (world) and `recorded_at` (the brain learned it) | `held_on`, `ingested_at` on `Meeting` only | `recorded_at` on every fact |
| **Hygiene reads that must return zero rows** (`unsupported_decisions`, `claims_without_source`, `accepted_on_unverified`, `claims_without_speaker`) | None | Add; the rehearsal invokes them |
| Org history as stints (`MemberOf` keyed by `since`, closed by `LeftTeam`) | `Attended` only | Add `Team`, `MemberOf`, `LeftTeam`, `PartOf` |
| Quote search (`search_quotes`) over `Claim.quote` | `Chunk` full-text | Keep both: chunks for recall, claims for provenance |

What our `webgrip` graph has that the cookbook lacks, and keeps: `Source.raw` as a Blob, `Chunk`
with vectors (semantic recall over transcripts), opaque HMAC person slugs (no personal data in
ids), `Topic` edges, `Meeting.kind`, and per-client sealed graphs. The cookbook says explicitly
"access is per graph and branch, not per row, so ingest only what every reader may see"; our
`client-<name>` split is that rule applied.

**Proposal (D4):** a new schema `company.pg` = cookbook `company-brain` + our `Source.raw`,
`Chunk`, `Topic` and HMAC slugs, replacing `meetings.pg` for the `webgrip` graph and for every
client graph (the same file serves both, as `tenant-*.pg` already does). The meeting extractor
(`scripts/omnigraph_meeting_to_ndjson.py`) emits `Claim` rows with status `unverified` and
proposes decisions; acceptance happens in the review UI on `main`. The cookbook's `mutations.gq`,
`hygiene.gq`, `claims.gq`, `decisions.gq`, `people.gq`, `actions.gq` are taken as they are and
renamed into our `rt_`/`capture_` conventions where brain-tools reads them. This is a schema
change with a key and cardinality change, so it lands in the new 0.14 root (section 4, step 1),
never as an in-place apply.

### 5.3 `beads` — do not build it; take three patterns

`beads` is a dependency-aware issue tracker for coding agents (issues, `BlockedBy`/`ChildOf`,
derived readiness, atomic claims with leases, a `Memory` type that `ob prime` loads into every
session, a Python client `ob`). The estate already has the two things it would duplicate:

- **Vikunja is the system of record for work** (ADR-0043), with the pick-up queue, labels and the
  Vellum board, and ploegd routes by label (ADR-0038).
- **Ploeg is the dispatch plane**: Work Items, Leases, Runs, approval limits, notes and
  promotions live in ploegd's Postgres (ADR-0031, 0087, 0088). A second queue in a graph would
  split the truth that ADR-0043 just unified.

What is worth taking, into what already exists:

| Beads pattern | Where it lands here |
|---|---|
| Readiness is **derived on every read**, never stored (`ready()` over `BlockedBy` and `childOf{1,8}`); no `blocked` status | Vellum's derived stages already follow this for labels; the same rule applies to any "status" column ploegd might be tempted to cache from Omnigraph |
| **Atomic claim as one conditional update** (`where status = "open"`), lease renew/reclaim instead of heartbeats | ploegd's Lease is already a row-level claim in Postgres; nothing to add. For agent writes to Omnigraph the equivalent is `if_graph_commit` on every read-modify-write ([section 7](#7-writing-to-omnigraph-the-design-rules)) |
| **`Memory` per project, primed into each session** | This is exactly Ploeg's knowledge pack (ADR-0065) plus Work Item Notes (ADR-0088). The `Memory → MemoryAbout → Issue` link maps to `Note.work_item`/`root_work_item` in `tenant-notes.pg`, which already exists |
| Unknown-outcome discipline: exit 3 `"outcome": "unknown"`, never replay blindly | Becomes the `disposition` rule in the shared write helper |

Re-evaluate only if Ploeg needs sub-Work-Item task graphs inside a Run (an agent decomposing its
own work with dependencies); then `beads` is the schema to copy into a per-tenant `work` graph,
read and written through ploegd like the notes graph.

## 6. Knowledge tiers: who may know what

### 6.1 What the engine can and cannot enforce

Omnigraph's policy (Cedar bundles, [policy.md](https://github.com/ModernRelay/omnigraph/blob/v0.14.0/docs/user/operations/policy.md))
decides per **actor × graph × action × branch class** (`any`, `protected`, `unprotected`).
Upstream: "Per-entity and per-property authorization is not currently supported; authorization
is graph/branch scoped." Branch names are a convention, not a scope (an actor allowed on
unprotected branches may write any of them). `invoke_query` covers the whole stored-query
catalogue of a graph. Nothing in 0.12–0.14 changes this.

Consequences, and they are the whole design:

1. **A tier is a graph.** If two readers must not see the same rows, the rows live in two graphs.
   A `scope`, `client` or `tier` property is a hint for a gateway, never a boundary.
2. **A row-level boundary is a gateway.** ploegd (ADR-0087/0089) and brain-tools are the only two
   places that filter rows before an agent sees them; they hold the graph tokens and the agent
   holds a session. That is the pattern upstream's own `company-brain` README assumes ("ingest
   only what every reader may see") and the one the Ploeg ADRs chose on 2026-10-11.
3. **Writes are tiered by actor.** One token per writer, with the narrowest action set; agents
   never hold `branch_merge` or `commit_publish`.

### 6.2 The tiers

Classification follows the usual four-level scheme (public, internal, confidential, restricted)
with one extra rule from mandatory-access-control thinking: **no read-up, no write-down** — a
reader sees its tier and below; a derived row lands at the tier of its most restricted source.

| Tier | Holds | Graph(s) | Readers | Writers of `main` |
|---|---|---|---|---|
| **T0 shared** | Reusable know-how with no personal, client or company-internal content: reviewed concepts scoped `tenant` | `webgrip-knowledge` (scope `tenant`) | every Ploeg run, every tenant member, interactive sessions via unfold-mcp | ploegd as `act-ploeg-review` by accepted promotion |
| **T1 personal** | Ryan's second brain: notes, people, tasks, projects, Obsidian, Forgejo documents | `brain` | Ryan, his chat and Claude Code (`act-brain-agent`), brain-tools (`act-brain-reader`), the eval; **never** a Ploeg run, never a client user | the importers, the distiller, `act-brain-agent`, `act-brain-scribe` |
| **T2 agent memory** | What agents learned across sessions, proposed and reviewed | `memory` | agents (read), Ryan | Ryan; agents propose (`as commit` after the upgrade) |
| **T3 company** | Webgrip's own meetings, claims, decisions, action items, org | `webgrip` → `company.pg` (D4) | staff, internal agents; **no** client user, no Ploeg run of a client Work Item | meeting ingest proposes; Ryan accepts; later `act-company-agent` proposes |
| **T4 client** | One client's meetings, claims, decisions; the concepts and notes of that client's work | `client-<name>` (company.pg), `webgrip-knowledge` rows scoped `client`/`repository`, `webgrip-notes` by root Work Item | that client's people (via ploegd operator routes, ADR-0089), runs of that client's Work Items, Webgrip staff | ingest proposes; Ryan accepts; ploegd writes notes within scope |
| **T5 restricted** | Credentials, tokens, keys, anything the secrets model owns (ADR-0055) | **no graph, ever** | — | — |

Rules that make the table hold:

- **No cross-graph edges.** Omnigraph has none; references across tiers are strings (`work_item`,
  `client`, slugs), as `tenant-notes.pg` does. A distiller that reads T4 to enrich T3 is a
  write-down and is refused by design: it runs per graph.
- **Taint on derivation.** A distilled `Topic` or summary inherits the tier of its sources; the
  distiller writes only to the graph it read from.
- **Ploeg runs reach knowledge only through ploegd's Run API**, never with a graph token
  (ADR-0087). `act-glide` (reads `brain`, `memory`, `webgrip`) stays for Glide-era agents and must
  not be handed to a client Work Item's run; VIK-1300 scopes which runs get it.
- **The chat key and the Claude Code key see `brain` and `memory` only** (LiteLLM
  `mcp_access_groups`); a separate `company` MCP group fronts T3, held by staff keys only.
- **Secrets never enter a graph.** The vault importer's client-term tagging and ploegd's
  credential-withholding on notes (ADR-0088) are the filters; the honeytoken detectors watch.
- **Review is the write-up gate.** Anything that moves from a lower-trust writer to a higher-tier
  `main` (agent → `memory`, ingest → `company`, note → concept) passes a person: branches today,
  unpublished commits after the upgrade, promotions in ploegd.

### 6.3 Other solutions, weighed

| Option | Row-level control | What it would cost here | Verdict |
|---|---|---|---|
| **Keep Omnigraph, tier by graph, gate rows in ploegd/brain-tools** (this RFC) | At the gateway | Nothing new; sharpen policies and names | **Yes** |
| Postgres + pgvector with row-level security | Native RLS per row | A second store with no branches, merges, history or typed graph queries; the archive RFC already reserves Postgres for raw items, not knowledge | No for knowledge; stays the archive's index |
| Neo4j / Memgraph enterprise fine-grained access (label and property level) | Native | Licence cost, a JVM or C++ database on a 4Gi budget, migration of 170 stored queries, no git-style review | No |
| Hosted memory layers (Mem0, Zep/Graphiti, Letta) | App-side scoping by user/session id | SaaS in the ops path, rejected before (healthchecks.io, 2026-07-11); self-hosted variants add a store without branching | No |
| OpenFGA/Cedar in front of the HTTP API | Any granularity the gateway can express | A policy service per request; duplicates what ploegd and brain-tools already do with far fewer moving parts | Not now; re-evaluate if a third gateway appears |
| Omnigraph OIDC resource identities (0.12+) | Per person, graph-scoped | Replaces static tokens for *people* with Authentik-issued identities; still graph-scoped | Later, for the laptop CLI and the review UI (ties into the access-plane RFC) |

## 7. Writing to Omnigraph: the design rules

How every writer, human or agent, should put knowledge in. Most of these are already practised by
one writer here; this makes them the rule for all of them.

1. **One identity per writer, minted in the cluster.** Token in OpenBao, delivered by External
   Secrets, named in exactly one policy group. New actor: token in one push, policy in the next
   (runbook). After the upgrade, `omnigraph access` is the probe.
2. **Agents write through stored mutations, never raw inserts.** A stored mutation encodes the
   invariant (node plus guard edge in one commit, status `unverified` on creation, `recorded_at`
   set by `now()`); `invoke_query` + `change` is the agent's write surface. Raw `mutate` with
   hand-written GQ stays for Ryan and for the importers.
3. **Create is not overwrite.** Keyed node inserts upsert the whole row; protect reviewed rows
   with an unkeyed `@card(0..1)` guard edge (company-brain) or write on a fresh slug. Edges that
   may be replayed are keyed `@key(@src, @dst[, prop])`.
4. **Facts are appended, never edited.** A changed decision is a new one; `SupersededBy`
   `@card(0..1)`; a wrong claim is rejected and re-recorded. Current state is derived by queries.
5. **Provenance is structural.** `ClaimFrom`/`ClaimedBy`, `DerivedFromArtifact {activity, model,
   confidence}`, `source_refs`, `trust: trusted|untrusted`, two clocks (`observed_at`,
   `recorded_at`). An agent's text is `untrusted` until a person says otherwise, and untrusted
   text is shown to agents as quoted data (tenant-notes already does this).
6. **Namespaces by writer.** `obsidian/`, `forge/`, `derived/`, `glide/<run>`: a writer edits only
   its own slugs, so importer rewrites and agent proposals cannot conflict (branch workflow RFC §6).
7. **Read-modify-write is conditional.** Read with `graph_commit_id`, write with
   `if_graph_commit`; `412` means re-read, never replay unconditionally.
8. **Propose, then publish.** Low-trust writers never touch a protected `main`: branches now,
   `as commit` after the upgrade; a person (or the review service acting on a click) publishes.
   The policy action is `commit_publish`, held by `act-ryan` and `act-review` only.
9. **Vectors travel with the row.** Every writer supplies the embedding of the exact source text
   (D3); nothing waits for a nightly backfill; the eval counts vectorless rows.
10. **Outcomes are typed.** Success is a `commit` receipt (or `null` for no-op); an error is read
    by `code` and `disposition.effects`; `unknown` means read before replay; MCP writes are
    ≤ 64 KiB, bulk goes to `/load/ndjson` in batches under 32 MiB.
11. **Schemas evolve by rebuild when identity changes.** Nullable additions, enum widening,
    `@index`, renames and drops apply in place; keys, cardinalities and `@check` need a new root.
    Decide identity first (upstream's schema-design guide, which the server now serves at
    `omnigraph://best-practices/schema`).

## 8. Phased plan and tickets

On the board since 2026-10-24: epic VIK-2323 (P1) with VIK-2326 (T1.1), VIK-2327 (T1.2),
VIK-2328 (T1.3), VIK-2336 (T1.4, Omnigraph Explorer), VIK-2337 (T1.5, Unfold), VIK-2329 (T1.6),
VIK-2330 (T1.7), VIK-2331 (T1.8), VIK-2332 (T1.9); VIK-2324 (T0.1), VIK-2333 (T2.1), VIK-2334
(P3), VIK-2335 (P4). T1.2, T1.7, T1.8, T2.1, P3 and P4 wait on decisions D1–D4 as
`needs-refinement`. VIK-2054 is closed as superseded. T2.2–T2.5 fold into those tickets or wait
until after the cutover. The gateway failure found while writing them is VIK-2325.

### P0 — stop the recurrence (this week, 0.11)

**T0.1 omnigraph: bounded cleanup in the nightly init container.** Why: 200 MB/day of retained
versions filled 5Gi in 28 days and took every graph down for 20 h. Scope: `bootstrap.sh` runs
`omnigraph cleanup --keep 30 --confirm` per graph after `optimize` (0.11 syntax; server stopped);
the rehearsal gains a case that seeds 50 versions and asserts the reclaimed count; a runbook line
records that the first post-upgrade cleanup must be `--keep 1 --confirm`. Acceptance: the volume's
used bytes stop growing monotonically over 7 days; `kubelet_volume_stats_used_bytes` is on the
omnigraph dashboard. Verification: live `kubectl -n ai logs deploy/omnigraph -c apply-and-optimize`
shows `cleanup` rows; the 7-day series. Monitoring: `PVCVolumeFillingFast` on `omnigraph-state`
(exists). Labels: theme/ingest, impact/H, effort/S, time/days, uncertainty/low, ready.

**T0.2 alerting: a critical on the second brain reaches a person.** Owned by the alert delivery
RFC; this ticket only records the 20-hour gap as its test case.

### P1 — the 0.14 cutover (one change set, three repositories)

**T1.1 omnigraph: port the bundle, bootstrap and rehearsal to 0.14.** Scope: section 4.1 steps 1–2;
`bootstrap.sh` on ledger v2; `omnigraph_rehearsal.py` and the mutation test on the 0.14 CLI;
`.mise.toml` pin 0.14.0; `just omnigraph-login` writes the 0.14 operator file. Acceptance: the
rehearsal passes on the unchanged bundle with 0.14 binaries and still fails every case the mutation
test lists. Verification: `scripts/test-rehearse-omnigraph-bundle.sh` output; CI job green.
Labels: theme/ingest, impact/H, effort/L, time/days, uncertainty/med, ready.

**T1.2 omnigraph: importers and helpers speak the 0.14 HTTP contract directly.** Scope: the
`apply.sh`/`snapshot.sh` CLI calls in vault-import, forge-import, distill and embed-step become
Python HTTP calls with `Omnigraph-Http-Api: 0.14`, typed `disposition` handling in
`omnigraph_write`, `if_graph_commit` where they read-modify-write; the writer tests and the
real-server tests run against a 0.14 server. Decision D2 first. Labels: theme/ingest, impact/H,
effort/L, time/days, uncertainty/med, needs-refinement until D2.

**T1.3 brain-tools, brain-eval, probes: send the contract header and read typed errors.** Scope:
`upstream.ts`, `brain_eval.py`, `probe-omnigraph.yaml`; tool-error classes from `code`.
Labels: theme/ingest, impact/H, effort/M, time/days, uncertainty/low, ready, agent-ready.

**T1.4 omnigraph-explorer: 0.14 contract, native diff and merge preview.** Repo
`omnigraph-explorer`. Scope: header; review mode uses `GET /branches/diff`, `merge-base` and
`dry_run`; `commit list` paging; "publish/drop" for unpublished commits. Labels: repo/omnigraph-explorer,
impact/H, effort/M, time/days, uncertainty/med, ready.

**T1.5 ploeg: omnigraph client on the 0.14 contract.** Repo `ploeg`, `pkg/omnigraph/client.go`
and the knowledgegraph packages; conformance tests against a 0.14 server. Labels: repo/ploeg,
impact/H, effort/S, time/hours, uncertainty/low, ready, agent-ready.

**T1.6 litellm: native Omnigraph MCP, bridge retired.** Scope: `mcp_servers` entries pointing at
`/mcp` with per-actor bearer tokens and the existing access groups; server flags
`--mcp-allow-writes`, `--mcp-allowed-host`; the `omnigraph-mcp` app deleted; the Brain preset and
the `second-brain` skill re-cut to the new tool names; `validate-mcp-gateway-only` still passes.
Labels: theme/ingest, impact/H, effort/M, time/days, uncertainty/med, ready.

**T1.7 omnigraph: the data migration and cutover (hands-on).** Scope: section 4.1 steps 4–7 as an
ordered command set with checks; the Longhorn backup; the brain eval before and after; old PVC
retained 7 days. Blocked by T1.1–T1.6. Labels: theme/ingest, impact/H, effort/M, time/days,
uncertainty/med, needs-refinement until the others merge.

**T1.8 omnigraph: re-embed everything in one text format (D3).** Scope: a one-off Job after the
load; the embedding contract test updated; retrieval eval gate. Labels: theme/ingest, impact/M,
effort/S, time/hours, uncertainty/low, ready.

**T1.9 omnigraph: nightly maintenance Job replaces the 03:15 restart.** After T1.7: `optimize`
and bounded `cleanup` from a Job on the volume's node while the server serves; closes VIK-1406 and
VIK-1573 and the restart half of VIK-1348. Labels: theme/ingest, impact/M, effort/S, time/days,
uncertainty/med, ready.

### P2 — adopt (each after P1)

T2.1 proposals as unpublished commits for Glide/Ploeg runs and meeting ingest (policy
`commit_publish` for `act-ryan` and `act-review`; review UI lists `listing=unpublished`); closes
VIK-1347's reason to exist. T2.2 `return distinct`, correlated blocks and settings in the `rt_*`
queries, measured by the eval. T2.3 `omnigraph access` in the rehearsal's actor checks and in the
runbook. T2.4 `load csv` for FreshRSS/calendar imports (VIK-1257). T2.5 OIDC resource identities
for the laptop CLI and the review UI.

### P3 — company brain (D4)

T3.1 `company.pg` = company-brain + `Source.raw`/`Chunk`/`Topic`/HMAC slugs, the cookbook's
queries ported, the meeting extractor emitting claims; T3.2 the review UI's claim verification and
decision acceptance; T3.3 migrate the `webgrip` graph's existing decisions as `verified` claims
with promoted decisions, and the client graphs the same way. Lands in the 0.14 root.

### P4 — tiers made explicit

T4.1 a `tiers` section in the knowledge-system guide (this RFC's table) and a validator that every
policy group maps to exactly one tier; T4.2 the `company` MCP access group and key; T4.3 remove
`act-glide` from `brain` once VIK-1300 scopes runs; T4.4 the distiller refuses to run across
graphs (a test).

## 9. Decisions for Ryan

| # | Question | Recommendation |
|---|---|---|
| D1 | Accept the history loss of the rebuild (four weeks of commit history and open branches; rows, vectors and blobs kept) | Yes. The alternative is to wait for an upstream in-place cluster route that 0.14 says has "no in-place route yet" |
| D2 | Importers on 0.14: call the HTTP API directly, or terminate TLS in the pod so the CLI's HTTPS rule is met | Direct HTTP. The importers are Python; the typed `disposition` is better than parsing CLI output; no in-cluster CA to manage |
| D3 | One embedding text format for all rows: raw source text (what 0.14 `embed` and a text `nearest` use), re-embedding ~20k rows once | Yes, gated by the retrieval eval |
| D4 | Reshape `webgrip` and the client graphs on the `company-brain` cookbook (claims before facts, actors, supersede-once) | Yes, in the 0.14 root; the meeting extractor already produces quotes, it will produce claims |
| D5 | Add `@check` slug prefixes and the guard-edge cardinalities in the new root's schemas (a rebuild is the only time this is cheap) | Yes |
| D6 | `beads`: not adopted; patterns folded into Ploeg and the write rules | Agree, with the re-evaluation trigger named in 5.3 |
| D7 | Keep one server and one volume as the blast radius (tiers by graph, not by process) | Yes for now; a second server per tier is the escape hatch if a client contract demands it |

## 10. Monitoring that catches regression

- `PVCVolumeFillingFast` and `AppPersistentVolumeCriticallyLowFree` on `omnigraph-state` (exist;
  fired correctly on 2026-10-23); after P0 the used-bytes series must flatten.
- `OmnigraphUnreachable` (exists); the eval's `brain_eval_missing_vectors_ratio` and
  `OmnigraphVectorsBacklog` for D3; the rehearsal's CI job for the bundle; `OmnigraphBranchesPileUp`
  until T2.1 removes the branch class.
- After T1.6: LiteLLM's MCP tool-call error rate per server (`litellm_*` spend logs, VIK-1403) and
  brain-eval's `tool_error_classes`.

## 11. Sources

- Releases: [v0.12.0](https://github.com/ModernRelay/omnigraph/releases/tag/v0.12.0),
  [v0.13.0](https://github.com/ModernRelay/omnigraph/releases/tag/v0.13.0),
  [v0.14.0](https://github.com/ModernRelay/omnigraph/releases/tag/v0.14.0); docs at tag v0.14.0:
  `docs/user/operations/upgrade.md`, `policy.md`, `mcp.md`, `server.md`, `maintenance.md`,
  `docs/user/clusters/config.md`, `docs/user/cli/targets.md`, `docs/user/branching/index.md`,
  `skills/omnigraph/references/schema-design.md`.
- Cookbooks: [ModernRelay/omnigraph-cookbooks](https://github.com/ModernRelay/omnigraph-cookbooks)
  at 379879ec (2026-10-19): `second-brain/`, `company-brain/`, `beads/`.
- Local measurements of 2026-10-24: the experiment script in the session scratchpad
  (`mig/experiment.sh`), reproducible with `mise x github:ModernRelay/omnigraph@0.11.0` and
  `@0.14.0`.
- Ploeg ADR-0087, 0088, 0089 (`ploeg/docs/adrs/`), VIK-2004, VIK-1858, VIK-1861, VIK-1872.
