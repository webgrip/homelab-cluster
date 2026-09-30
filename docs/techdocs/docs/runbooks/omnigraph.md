# Omnigraph

Omnigraph v0.11 runs one server in namespace `ai` with three graphs: `memory` (shared agent memory), `brain` (Ryan's second brain) and `webgrip` (internal company meetings). Every graph, schema, stored query and permission rule is declared in the [bundle](../../../../kubernetes/apps/ai/omnigraph/app/bundle/). Push a change to the bundle and the pod applies it on its next start.

## How it runs

- One pod, `strategy: Recreate`, data on the Longhorn PVC `omnigraph-state` with `file://` storage. Garage is deliberately not used: Omnigraph's commits rely on S3 conditional writes (`If-None-Match: *` to create only if absent, `If-Match` to compare-and-swap), and **Garage ignores both**. Tested 2026-09-28 against the same image digest as the cluster (`dxflrs/garage:v2.4.1@sha256:9c96caa2…`) in a throwaway container: a create-if-absent over an existing object returned 200 and overwrote it, a compare-and-swap with a wrong ETag returned 200, and 20 parallel create-if-absent writers on one new key all got 200 where exactly one may. On Garage, two commits could overwrite each other without an error. Revisit only when a Garage release passes that same test.
- The init container runs [bootstrap.sh](../../../../kubernetes/apps/ai/omnigraph/app/bundle/bootstrap.sh):
  1. Copies the bundle out of the ConfigMap, because Omnigraph refuses bundle files reached through symlinks.
  2. Imports state on first boot.
  3. Refuses to start if the plan contains an unapproved deletion.
  4. Applies the bundle.
  5. Fills missing vectors on `main` of every graph, capped so a restart stays under 3 minutes (see [Startup backfill](#startup-backfill)). A failure here is logged and skipped; it never stops the pod.
  6. Optimizes every applied graph and rebuilds full-text indexes when optimize reports stale coverage.
- The `omnigraph-maintenance-restart` CronJob restarts the pod at 03:15. In v0.11, `optimize` next to a live server blocks writes, so it only runs at startup.
- The pod is down for about 3 minutes during that restart (2026-09-30: 01:15:03 to 01:17:51 UTC), and a Reloader restart after a token rotation does the same at any hour. The writers therefore do two things. No writer CronJob starts within 5 minutes of the restart, which is why the vault importer runs at :05, :20, :35 and :50. Every writer's `snapshot` step also polls `/readyz` for up to 5 minutes before its first read and logs `omnigraph ready after Ns`. [test_omnigraph_writer_restart.py](../../../../scripts/test_omnigraph_writer_restart.py) checks both in CI. Before 2026-09-30 the 03:15 vault run failed whenever it met the restart.
- The PVC is enrolled in the `gitops-backup` Longhorn job (daily, 7 kept, offsite).
- Renovate never automerges Omnigraph (image or mise CLI). Minor releases change the storage format.

## Rehearse a bundle change

A bundle change is applied by the init container of the only Omnigraph pod. If the apply fails, every graph stops. Every change under [app/](../../../../kubernetes/apps/ai/omnigraph/app/) (the bundle files, `bootstrap.sh`, `deployment.yaml`, the kustomization) therefore passes a rehearsal before it is committed:

```bash
mise exec -- ./scripts/rehearse-omnigraph-bundle.sh
```

The `rehearse-omnigraph-bundle` lefthook pre-commit hook runs it for you whenever a staged file under `kubernetes/apps/ai/omnigraph/app/`, the embedding contract, `.mise.toml` or the rehearsal itself changes. It takes about 10 seconds and needs no cluster access. What it does, in order:

1. Renders `kustomize build kubernetes/apps/ai/omnigraph/app` for the working tree and for `origin/main` (`--base-ref` picks another ref), and reads the `omnigraph-bundle` ConfigMap out of each render. It rehearses what the pod mounts, not what git holds.
2. Checks that the mise `omnigraph` pin, both server image tags in the Deployment and the CLI on `PATH` are the same version.
3. Checks that every schema, query and policy file `cluster.yaml` names is in the ConfigMap, and that the ConfigMap carries no `.pg`, `.gq` or policy file `cluster.yaml` does not use.
4. Lints every stored query: a variable ranked by `nearest`, `bm25`, `search` or `fuzzy` must be the first binding in `match {}` (bound as `$v: Type`), every `limit` is an integer literal, and no `rrf()` score is projected. v0.11 errors on anchor-first `nearest` and `bm25`, and silently stops ranking an anchor-first `rrf`.
5. Checks that every actor a policy names already has a token in the **deployed** `omnigraph-tokens` aggregator. A new actor's token goes in one push and the policy that names it in a later one (see [Actors and tokens](#actors-and-tokens)).
6. Builds a throwaway cluster from the deployed bundle by running the deployed `bootstrap.sh` with the init container's own environment. Only the storage path, the bundle mount path and the embedding URL are swapped: a local fake embedder stands in for LiteLLM and records what is sent.
7. Seeds every node and edge type of every graph with synthetic rows, vectors included, plus 601 vectorless `brain` `Passage` rows and one vectorless row per other embedding type.
8. Opens a branch `rehearsal-open` on every graph, the way an open `glide/*` branch would be live.
9. Runs the working `bootstrap.sh` over it: a real `cluster apply` (which rejects, for example, `invoke_query` in a rule with `branch_scope`, or a schema change while a branch is open), then the capped backfill, then `optimize`. It checks that the backfill stopped at `OMNIGRAPH_BACKFILL_MAX_ROWS` with a matching `vector backfill capped` line and that every small backlog was filled.
10. Starts `omnigraph-server --require-all-graphs` on the result and invokes every stored query: reads on `main`, each mutation on its own fresh branch, all as an actor the policy lets read, write and invoke.

A failing stage prints `FAIL <stage>: <reason>` and the commit is refused.

**Schema changes.** Step 8 makes every schema change fail, because live `cluster apply` refuses a schema change while the graph has any branch but `main`. Before a schema push, drain the graph (see [Open `glide/*` branches block schema changes](#open-glide-branches-block-schema-changes)), prove it has only `main`, and then name it:

```bash
OMNIGRAPH_REHEARSAL_DRAINED=brain git commit ...
```

The rehearsal then opens no branch on `brain`. The variable is a statement that you checked the live graph; it is not a way around the check.

**CI.** The `e2e / Omnigraph bundle rehearsal` job runs the same script against the previous commit's bundle on every push to `main` and every pull request that touches these paths, with the `omnigraph` binaries copied out of the pinned server image. It runs after the push, so it is a backstop, not the gate. Push runs no longer cancel each other; only pull request runs do.

**Mutation test.** [test-rehearse-omnigraph-bundle.sh](../../../../scripts/test-rehearse-omnigraph-bundle.sh) proves the rehearsal catches what it claims. It must fail on: a query file in `cluster.yaml` but not in the ConfigMap, and the reverse; `invoke_query` in a rule with `branch_scope`; an anchor-first `rrf`; an anchor-first `nearest` with the lint off (caught live); `limit $n`; a schema change while `brain` has a branch; a policy naming an actor without a deployed token; a server image that differs from the mise pin; an init container without a backfill cap; a `bootstrap.sh` that ignores the cap; a `bootstrap.sh` that crashes; a `bootstrap.sh` that ignores the deadline (a short backfill drill runs over its 15-second budget). It must pass on the unchanged bundle, on a new valid query file (a ranked-first two-hop `Passage` query with a `Vector(384)` parameter), on a schema change of a graph declared drained, and on the short drill: 400 vectorless passages, an 8-second deadline, serving within 15 seconds. Each case also checks the reason it failed, so a crashing rehearsal does not count as a catch. It runs in pre-commit when the rehearsal changes, and in CI.

## Actors and tokens

| Actor | Can |
|---|---|
| `act-ryan` | Everything on `brain`, `memory` and `webgrip`, including merging into `main` |
| `act-admin` | Everything on `memory` and `webgrip` |
| `act-agent` | `memory`: read, write on its own branches, never merge |
| `act-reader` | `memory`: read and run stored queries |
| `act-brain-agent` | `brain`: read and write on any branch including `main` (captures from the chat and Claude Code land directly; every write is a revertible commit); create and delete unprotected branches; no merge or export |
| `act-ingest` | `webgrip` (and future client graphs): create unprotected branches and load onto them. It cannot read anything |
| `act-explorer` | `brain`, `memory` and `webgrip`: read and export on any branch, nothing else. Only the explorer's proxy holds it |
| `act-vault-import` | `brain`: read and write on any branch including `main`, and run stored queries. No export, no branch create, merge or delete. Only the [Obsidian vault](#obsidian-vault) importer holds it |
| `act-forge-import` | `brain`: the same rights as `act-vault-import`. Only the [Forgejo projects](#forgejo-projects) importer holds it |
| `act-distill` | `brain`: the same rights as `act-vault-import`. Only the [distiller](#distiller) holds it |
| `act-glide` | `brain`, `memory` and `webgrip`: read on any branch, write only on unprotected branches, create and delete unprotected branches, run stored queries. No merge, no export, never a write to `main`. Only the LiteLLM `omnigraph_glide_*` MCP servers hold it (see [Glide agents](#glide-agents)) |
| `act-review` | `brain`, `memory` and `webgrip`: read and write on any branch including `main`, create, delete and merge any branch, run stored queries. No export. Only the explorer's review container holds it (see [Review mode](#review-mode)); client graphs stay CLI-reviewed as `act-ryan` |
| `act-brain-eval` | `brain`: read and export on any branch, run stored queries. No writes, no branch actions. The [brain eval](#brain-eval) jobs and the `omnigraph_brain_eval` bridge hold it |
| `act-brain-reader` | `brain`: read on any branch, run stored queries. Nothing else. Only [brain-tools](#brain-tools) holds it |
| `act-brain-scribe` | `brain`: read and write on `main` only. No branch actions, no stored queries, no export. For `brain-tools` `remember` (brain retrieval RFC, P6); it can delete any row on `main`, so the scribe audit is its guard |

Each token is generated in-cluster by the `omnigraph-actor-tokens` ExternalSecret, pushed to OpenBao at `secret/omnigraph/<actor>` (field `token`), and assembled into the server's `tokens.json` by the `omnigraph-tokens` ExternalSecret.

Add an actor by creating a new generator ExternalSecret and PushSecret pair, then adding one line to the aggregator. Do not add keys to `omnigraph-actor-tokens`. It is generate-once, so a new key only appears after its Secret is deleted, and deleting it rotates every existing token.

Give an in-cluster consumer its token with an ExternalSecret against the `openbao` store at `omnigraph/<actor>`. Then open the network path on both ends, because namespace `ai` is default-deny and every pod in it carries its own egress allow: add the consumer to `omnigraph-ingress` (a `namespaceSelector` for another namespace, a `podSelector` for a pod in `ai`), and give a pod in `ai` an egress rule to `app: omnigraph` on 8080. Today only LiteLLM (the `omnigraph_memory`, `omnigraph_brain`, `omnigraph_brain_eval` and `omnigraph_glide_*` MCP bridges), the explorer, the vault and Forgejo importers, the distiller, the brain eval jobs, [brain-tools](#brain-tools) and the gateway may connect. The full matrix is in [LiteLLM: network](../general/litellm.md#network-namespace-ai).

## Explorer

`https://graph.<domain>` is a read-only visual explorer ([webgrip/omnigraph-explorer](https://forgejo.webgrip.dev/webgrip/omnigraph-explorer), which documents the app itself). It runs as `omnigraph-explorer` in namespace `ai`.

- **Who gets in.** The route sits behind the gateway's OIDC `SecurityPolicy` with its own Authentik client, `omnigraph-explorer` ([ADR-0060](../adr/adr-0060-gateway-oidc-for-apps-without-a-login.md)). Authentik only issues a token to members of `knowledge-graph-viewers`, the group of the `knowledge-graph-view` capability. That capability is granted to Ryan by name, not through a role, because the explorer shows the brain and client meetings.
- **What it can do.** The pod serves the SPA and proxies `/og/*` to `omnigraph:8080`. The proxy adds `Authorization: Bearer <act-explorer>` itself, strips cookies, and forwards only `GET` on `healthz`, `branches`, `commits` and `schema`, plus `POST` on `export`. The browser never sees the token, and `act-explorer` is refused `change`, `branch_*` and `graph_list` by policy anyway.
- **Token.** `omnigraph-explorer-token` generates it and pushes it to `secret/omnigraph/explorer`. The aggregator adds it to `tokens.json` and the explorer reads it back with `omnigraph-explorer-upstream`. Rotate it by deleting the `omnigraph-explorer-token` Secret; Reloader restarts both pods.
- **Graphs in the picker.** `OMNIGRAPH_EXPLORER_GRAPHS` on the Deployment. A graph also needs an `explorers` group and `explorers-read-and-export` rule in its policy, or every request answers 403. `OMNIGRAPH_EXPLORER_HEAVY_TYPES` (default `Chunk`) lists node types the explorer skips unless asked, together with every edge that touches them. On `brain` the passage type is `Passage`, so add it to the list.
- **Monitoring.** `blackbox-omnigraph-explorer` reads `memory` branches through the pod (nginx, proxy, token and policy in one request). `blackbox-omnigraph-explorer-gate` checks that an anonymous request to the route is sent to Authentik. The alerts are `OmnigraphExplorerBackendDown` and `OmnigraphExplorerGateOpen`.

### Review mode

`https://graph-review.<domain>` is the same app with review mode on: an inbox of open branches, an exact merge preview, conflicts per row, merge, reject and update branch. The design is the [branch workflow RFC](../rfc/rfc-omnigraph-branch-workflow.md); the explorer repo documents the app.

- **Who gets in.** Its own HTTPRoute `omnigraph-review` and SecurityPolicy `omnigraph-review-oidc`, with the Authentik client `omnigraph-review`. Authentik issues that client a token only for `knowledge-graph-reviewers`, the group of the `knowledge-graph-review` capability, granted to Ryan by name. The route points at port 8081 of the explorer Service. The explorer route points at port 8080, which answers 404 under `/review/`, so a viewer who is not a reviewer has no path to the review API.
- **What holds the write token.** A second container, `review` (image `omnigraph-explorer-review`), holds `act-review` from `omnigraph-explorer-review-upstream` (`secret/omnigraph/review`) and listens on `127.0.0.1:8090`. nginx on 8081 proxies `/review/api/` to it and never sees the token. The container never forwards a browser request: it calls a fixed list of Omnigraph endpoints and builds every write from rows it read itself. Every action logs one `review_action` line with the Authentik user, graph, branch and resulting commit, so an `act-review` commit is traced in VictoriaLogs with `review_action AND branch:"glide/..."`.
- **Archive and sweep.** Reject archives the branch's commits and net diff as JSONL to the in-cluster Garage bucket `omnigraph-branch-archive` (key `omnigraph-branches/<graph>/<branch>/<time>.jsonl`), then deletes it. A branch older than 14 days is archived and deleted the same way. Without the archive keys nothing is deleted. The bucket and its key come from the `garage-omnigraph-archive-bootstrap` Job, pushed to `secret/garage/omnigraph-archive`.
- **Monitoring.** The review container exports branch metrics on `:9464` (`omnigraph_branches_open`, `omnigraph_branch_age_seconds`, `omnigraph_branch_empty`, `omnigraph_branch_touches_importer_rows`, `omnigraph_review_refresh_success_timestamp_seconds`, `omnigraph_review_actions_total`), scraped by `VMServiceScrape/omnigraph-review` and shown on the Grafana dashboard *Omnigraph — Branch review*. Alerts: `OmnigraphReviewBacklog` (a branch older than 3 days), `OmnigraphBranchNotSwept` (older than 15 days), `OmnigraphBranchesPileUp` (more than 10 on one graph for an hour), `OmnigraphBranchMonitorStale` (no complete refresh for 30 minutes), `OmnigraphReviewGateOpen` (an anonymous request to the review route is not sent to the `omnigraph-review` client) and `OmnigraphExplorerServesReview` (port 8080 answers anything but 404 under `/review/api/`).
- **Glide.** `act-glide` has no `branch_merge` (decision D3 in the RFC): the policy cannot limit it to a run's own branch. Syncing `main` into a branch is the review UI's **Update branch**.

## Laptop setup

```bash
mise install
just omnigraph-login
```

`omnigraph-login` writes `~/.omnigraph/config.yaml` (server `homelab`, profiles `brain`, `memory`, `webgrip`) if it does not exist. It then pipes the `act-ryan` token from OpenBao into `~/.omnigraph/credentials` (mode 0600) without printing it. The CLI picks its token in this order: `OMNIGRAPH_TOKEN_HOMELAB`, then the credentials file, then `OMNIGRAPH_BEARER_TOKEN`.

For Claude Code, the stdio MCP bridge `@modernrelay/omnigraph-mcp@0.10.0` works against v0.11. It serves one graph per process. It reads `OMNIGRAPH_BASE_URL`, `OMNIGRAPH_GRAPH_ID` and `OMNIGRAPH_TOKEN`, and has no token-file option.

The bridge exposes inline `query`/`mutate`, `load` and branch tools. It does not expose stored queries. Policy is enforced by the server either way.

The server's built-in `/mcp` endpoint does not exist in v0.11.

In-cluster agents reach `memory` through the LiteLLM MCP gateway instead: server `omnigraph_memory`, access group `memory`, running as `act-agent` (read everything, write only on its own unprotected branches, never merge). A LiteLLM key only sees these tools when its `object_permission.mcp_access_groups` contains `memory`. The bridge is installed by the `install-omnigraph-mcp` init container of the LiteLLM pod with `npm ci` from the lockfile in [omnigraph-mcp](../../../../kubernetes/apps/ai/litellm/app/omnigraph-mcp/). LiteLLM refuses to start when `OMNIGRAPH_MEMORY_TOKEN` is missing from its environment, so the `litellm-omnigraph-memory` Secret has to exist before the pod restarts.

`brain` has a second bridge in the same pod: server `omnigraph_brain`, access group `brain`, running as `act-brain-agent` with `OMNIGRAPH_BRAIN_TOKEN` from the `litellm-omnigraph-brain` Secret (`secret/omnigraph/brain-agent`). Its tools carry the prefix `omnigraph_brain-`. `act-brain-agent` reads and writes `main` directly, so a tool call works on `main` without creating a branch.

Two keys see both groups: `open-webui` for [Open WebUI](open-webui.md) and `claude-code` for Claude Code on Ryan's workstation (setup in [Open WebUI: Claude Code](open-webui.md#claude-code)).

## Glide agents

Glide runs read and write `memory`, `brain` and `webgrip` through three MCP servers in the LiteLLM pod, all running as `act-glide`:

| Server | Graph | Tool prefix |
|---|---|---|
| `omnigraph_glide_memory` | `memory` | `omnigraph_glide_memory-` |
| `omnigraph_glide_brain` | `brain` | `omnigraph_glide_brain-` |
| `omnigraph_glide_webgrip` | `webgrip` | `omnigraph_glide_webgrip-` |

The servers sit in access group `glide`. Their token comes from `OMNIGRAPH_GLIDE_TOKEN` in the `litellm-omnigraph-glide` Secret (`secret/omnigraph/glide`).

**How a run gets the tools.** The run holds a LiteLLM virtual key whose `object_permission.mcp_access_groups` contains `glide`. The harness connects to the MCP endpoint `http://litellm.ai.svc.cluster.local:4000/mcp/` over streamable HTTP with `Authorization: Bearer <run key>`. A key without the `glide` group sees none of these tools.

**Branch contract.** A run works on one branch per graph, `glide/<run-id>`:

1. Create it from `main` with `branches_create` before the first write.
2. Read `main` freely, and read and write the run branch.
3. Stop there. A write to `main` answers 403, and so does a merge. Ryan reviews the branch and merges it himself.

The policy cannot pin the `glide/` prefix. `act-glide` may write and delete any unprotected branch, including another run's branch or an `agent/*` proposal. The `glide/` name is a convention that the tool descriptions state.

### Open `glide/*` branches block schema changes

An open run branch counts as a non-`main` branch (see [Known v0.11 limits](#known-v011-limits)). A schema change to `memory`, `brain` or `webgrip` while any `glide/*` branch exists fails `cluster apply`, and the init container then stops every graph. Before you push a schema change, list the branches of the graph and merge or delete every `glide/*` branch:

```bash
omnigraph branch list --profile brain
omnigraph branch delete glide/<run-id> --profile brain --yes
```

Repeat for `memory` and `webgrip`. Over HTTP, `GET /graphs/<graph>/branches` lists them. A delete URL-encodes the `/` (`DELETE /graphs/<graph>/branches/glide%2F<run-id>`).

Review mode's inbox marks every graph that has an open branch as "schema blocked", and `omnigraph_branches_open` shows the same count in Grafana. Drain the graph there before a schema push.

## Second brain (`brain`)

The schema is the ModernRelay `second-brain` cookbook. Two additions: `Note.content` and `Artifact.content` are indexed for full-text search, and [brain.capture.gq](../../../../kubernetes/apps/ai/omnigraph/app/bundle/brain.capture.gq) adds `capture_note`, `capture_task`, `capture_person` and `set_task_status`, which take the optional fields the cookbook's `add_*` mutations leave out.

```bash
omnigraph mutate capture_note --profile brain --params '{"slug":"nt-bike-chain","name":"Bike chain","kind":"idea","content":"Replace the chain before winter","when":"2026-09-25"}'
omnigraph query notes_recent --profile brain
```

Conventions that used to live in the cookbook's comments:

**Records and ids**

- Slugs carry a type prefix: `per-` people, `org-` organizations, `pl-` places, `ev-` events, `nt-` notes, `tk-` tasks, `proj-` projects, `area-` areas, `goal-` goals, `hab-` habits, `med-` media, `art-` artifacts. `per-self` is you: create it first with `relation: self`. `obsidian/`, `forge/` and `derived/` belong to the vault importer, the Forgejo importer and the [distiller](#distiller).
- Inserting an existing slug updates that record.
- `Knows` and `RelatedToPerson` are stored in both directions. The relation is inverted for parent/child and grandparent/grandchild.

**Notes**

- Keep notes atomic: one idea per node, linked with `RelatedNote`.
- `kind` separates journal, principle, preference, question and the rest.
- Captures without `when` sort as null in `notes_recent`.

**Tasks and planning**

- Tasks follow GTD and start in `inbox`. `direction` records who owes whom.
- Who you are waiting on is a `TaskForPerson` edge, not a text field.
- A project has an end, an area does not, and a goal has a timeframe.

**Events and habits**

- An event about a person uses `EventForPerson`; `AttendedBy` means they were present.
- `Person.cadence_days` is how often you want contact.
- Habit streaks are derived from the `completions` dates and are kept in sync by hand.

**Passages**

- The cookbook's `Chunk` is `Passage` here, with a 384-dimension `embedding` and a `PassageOf` edge to its `Artifact`. `Passage` has no key: give each row an explicit `id` in the load file and point its `PassageOf` edge at that id.

Agents holding `act-brain-agent` read and write `main` directly, because the only holders are Ryan's own chat and Claude Code, and a review step would stall every capture. A bad write is undone from the commit history. Proposals that deserve review still go on a branch such as `agent/<task>`, which Ryan merges.

The cookbook's demo seed (fictional "Alex Chen") is not loaded. To explore it, load it onto a throwaway branch and delete the branch afterwards.

## Obsidian vault

Ryan's Obsidian vault is imported into `brain` every 15 minutes by the `omnigraph-vault-import` CronJob in namespace `ai` ([vault-import](../../../../kubernetes/apps/ai/omnigraph/vault-import/app/)). It writes straight to `main` as `act-vault-import`, without a review branch. Ryan chose that on 2026-09-27.

### How it runs

One pod runs six steps in order. Each step logs one line of counts or one error line, never note names, contents or client terms.

1. `clone` shallow-clones `webgrip/obsidian-vault` over SSH from `forgejo-ssh.forgejo.svc.cluster.local`. It uses the deploy key in the `omnigraph-vault-import-deploy-key` Secret and checks the host key against the pinned [known_hosts](../../../../kubernetes/apps/ai/omnigraph/vault-import/app/known_hosts).
2. `snapshot` reads, with the ad-hoc queries in [snapshot.gq](../../../../kubernetes/apps/ai/omnigraph/vault-import/app/snapshot.gq): every `obsidian/` note with its outgoing `RelatedNote` edges and its `NoteFromArtifact` link, every `obsidian-file/` shadow artifact and its passages with their text, and which of those notes and passages already have a vector.
3. `plan` runs [vault_import.py](../../../../kubernetes/apps/ai/omnigraph/vault-import/app/vault_import.py). It compares the vault with the snapshot and writes delete mutations, merge-load files for the difference only, and heal files for its own vectorless rows.
4. `embed` fills the vectors of every Note and Passage row in those files (see [Write-time vectors](#write-time-vectors)).
5. `apply` runs the delete mutations, then the loads, then the heal loads, onto `main`.
6. `report` pushes how many of its rows still have no vector.

**Mapping.** Only `*.md` files are read. Hidden folders (`.obsidian`, `.trash`, `.git`), template folders and files over 1 MiB are skipped. A template folder is one named `templates`, or the folder set in `.obsidian/templates.json` or in the Templater plugin settings.

| `Note` field | From |
|---|---|
| `slug` | `obsidian/` plus the path without `.md`, lowercased, each segment reduced to `a-z0-9-`. Two paths that reduce to the same slug each get a hash suffix |
| `name` | Frontmatter `title`, else the file name |
| `content` | The body without frontmatter |
| `tags` | Frontmatter `tags` plus inline `#tags` outside code, lowercased and deduplicated |
| `kind` | `journal` when the file name is a date (`YYYY-MM-DD`) or the file sits in a daily-notes folder (`Daily`, `Journal` and similar, or the folder in `.obsidian/daily-notes.json`). Otherwise frontmatter `kind` or `type` when it is a valid `Note.kind`, else `idea` |
| `when` | Frontmatter `date`, else a date file name |
| `createdAt` | Kept from the graph for an existing note. For a new note, frontmatter `created`, else the import time |
| `updatedAt` | The import time of the run that changed the note |

`[[target]]`, `[[target|alias]]`, `[[target#heading]]` and `![[target]]` become `RelatedNote` edges when the target is another imported note, matched by path or by file name.

**Chunks.** A note's own vector covers only its first 1,024 tokens, which is about half of the vault's text. So every note with at least 80 characters of content is also cut into passages, the same `Passage` rows Forgejo documents use (brain retrieval RFC, decision D4). No schema change is needed.

| Row | What |
|---|---|
| Shadow `Artifact` `obsidian-file/<tail>` | `kind: document`, `source: notes-app`, no `content`, `content_sha256` over the chunker version, the title and the content. `<tail>` is the note slug without `obsidian/` |
| `NoteFromArtifact` | From the note to its shadow artifact, with the fixed id `vault:NoteFromArtifact:<note>><artifact>`, so it is never loaded twice |
| `Passage` `obsidian-file/<tail>#<i>` | At most 1,200 characters, packed by paragraph. A chunk starts at a heading (a `#` line inside a code fence is not one) with a `Title › Heading` line, or just the title before the first heading; the sections that follow join it, each heading kept as a line, while they fit. A section that does not fit starts its own chunk. A `PassageOf` edge to the shadow artifact |

The distiller skips shadow artifacts, because the note itself is distilled. On 2026-09-30 the 461 notes gave 394 chunked notes and about 1,700 passages with a median of about 900 characters. A first version started a chunk at every heading and made 37% of the chunks 200 characters or shorter; `content_sha256` carries the chunker version (`obsidian-chunks-v2`), so a chunker change redoes every note over a few runs.

**Only changes are written.** The importer keeps no state of its own. Every run recomputes the difference between the vault and what `brain` holds under `obsidian/`, and writes only that difference. This is simpler than a stored commit marker, and a failed run repairs itself on the next one. It is also required: a merge load replaces the whole row and clears its vector, so reloading unchanged notes every 15 minutes would keep every vault note without an embedding.

- A new or changed note is merge-loaded, with its vector.
- A note whose vault links changed has its outgoing `RelatedNote` edges deleted, then reloaded. A merge load does not deduplicate edges, so an edge is never loaded without that delete first. Edges from a vault note to a note outside `obsidian/` (added by an agent or by hand) are reloaded with it.
- Chunks are compared by id and text with the stored ones. Only a chunk whose text or position changed is written; unchanged chunks keep their row and vector, and chunk ids the note no longer needs are deleted.
- An `obsidian/` note that is no longer in the vault (deleted or renamed) is deleted in one mutation together with every passage the snapshot lists for its shadow artifact and the shadow artifact itself, in that order. The list must be complete: one passage left behind fails the whole mutation on `PassageOf @card(1..1)` and stops every later run. A shadow artifact whose note is already gone, and the chunks of a note that shrank under 80 characters, are pruned the same way.
- At most 300 notes, and about 300,000 characters of new chunk text, are chunked per run, so the first import spreads over a few runs (`chunk_deferred` in the counts line says how many wait). A note linked to another artifact already keeps that link (`link_conflicts`).

The vault owns everything under `obsidian/`. An edit made to such a note in the graph is overwritten on the next run when the file differs. Capture your own notes under another prefix, such as `nt-`.

A vault without importable notes never deletes anything: the plan step refuses and the run fails.

**Embeddings.** The importer brings its own vectors: the `embed` step fills every Note and Passage row it writes, and up to 300 of its vectorless rows a run are healed (see [Write-time vectors](#write-time-vectors)). A changed note is searchable by meaning as soon as its run lands. Keyword search sees new text at once too; the full-text index is only rebuilt at the 03:15 restart, which matters for `fuzzy()` alone.

**Write limits.** Load files are split at 2,000 rows or 16 MiB, counting about 6 KB for each vector the embed step will add, below the per-commit limit. Delete mutations are split at 500 statements, never inside one note's group. The CronJob allows 600 seconds; the embed step stops at 300.

### Client notes are tagged, not withheld

Owner decision 2026-09-27: client content may reach Claude and Fireworks under their DPAs ([personal archive RFC](../rfc/rfc-personal-archive.md), D4), so the whole vault is imported. An optional list of client terms (names, company names, domains) in OpenBao `secret/omnigraph/vault-client-terms`, field `terms`, one term per line, reaches the importer through the `omnigraph-vault-client-terms` ExternalSecret.

- A note whose path or text (frontmatter, tags and body) contains any term, case-insensitive and on word boundaries, gets the tag `client`, so a question can include or exclude client material.
- Without the Secret, or with no terms in it, everything is imported untagged.
- The counts line reports `tagged_client`. The terms themselves are never logged.
- The match is textual. A client note that never names a listed term stays untagged.

Deleting a note from `main` does not erase it from history. See [Forget a meeting](#forget-a-meeting) for destroying the data files.

### Setup (Ryan)

1. Create the private repo `webgrip/obsidian-vault` on Forgejo and push the vault with the Obsidian Git plugin. Leave `.obsidian/` in or out, the importer skips it either way.
2. Add the importer's public key as a **read-only** deploy key on that repo (Settings, Deploy keys, write access off). Print it with:

   ```bash
   export BAO_ADDR="$(just bao-addr)"
   bao kv get -field=public_key secret/omnigraph/vault-import-deploy-key
   ```

3. Optionally, store client terms without printing them, so client notes get the `client` tag. Paste one term per line, then press Ctrl-D:

   ```bash
   bao kv put secret/omnigraph/vault-client-terms terms=-
   ```

   To add a term later, run the same command with the full list. It replaces the field.

The next run after steps 1 and 2 imports the vault. ESO refreshes the terms every 5 minutes.

### Monitoring and failures

The job fails, and does not retry, with one of these lines:

- `vault repo not reachable`: the repo does not exist or the deploy key is not on it.
- `omnigraph not ready`: Omnigraph did not pass `/readyz` within 5 minutes; the curl error follows. It is down, or a network policy drops this pod.
- `omnigraph not reachable or act-vault-import refused`: Omnigraph answered `/readyz` but refused the query. The error after the colon says why; usually `act-vault-import` is not in `tokens.json` yet.
- `vault import failed`: the server refused the delete or a load batch.

`OmnigraphVaultImportStale` fires when the CronJob has had no successful run for 2 hours, or has never succeeded since it was created. It reads `kube_cronjob_status_last_successful_time` from kube-state-metrics. It fires until the setup above is done.

**Tests.** [test_omnigraph_vault_import.py](../../../../scripts/test_omnigraph_vault_import.py) covers the mapping, client tagging, the missing-terms path and the empty-vault guard with fixture vaults. It runs without network: `python3 scripts/test_omnigraph_vault_import.py`.

**Rotation.** Deleting the `omnigraph-vault-import-deploy-key` Secret generates a new key pair and pushes the new public key. Replace the deploy key on the repo. Deleting `omnigraph-vault-import-token` rotates the actor token. The aggregator picks it up within 15 minutes and Reloader restarts Omnigraph.

## Forgejo projects

Every repository Ryan's Forgejo account can see is imported into `brain` every hour, at minute 40, by the `omnigraph-forge-import` CronJob in namespace `ai` ([forge-import](../../../../kubernetes/apps/ai/omnigraph/forge-import/app/)). It writes straight to `main` as `act-forge-import`, the same way the vault importer does. Ryan decided this on 2026-09-28 (VIK-1259): repos become projects, and their READMEs, `docs/`, ADRs, issues and pull requests come with them. Client content may go to Claude and Fireworks under their DPAs, so nothing is filtered out. Repos of a client org carry the org name as a tag.

### How it runs

One pod runs three steps in order. Each step logs one line of counts or one error line.

1. `snapshot` reads everything under `forge/` on `brain/main` with the queries in [snapshot.gq](../../../../kubernetes/apps/ai/omnigraph/forge-import/app/snapshot.gq): projects, organizations, people, artifacts, decision notes, passage ids and the edges between them, and which passages and notes already have a vector. It does not read artifact or passage text.
2. `plan` runs [forge_import.py](../../../../kubernetes/apps/ai/omnigraph/forge-import/app/forge_import.py) against the Forgejo API at `http://forgejo-http.forgejo.svc.cluster.local:3000` with the read-only token. It compares Forgejo with the snapshot and writes delete mutations, merge-load files for the difference only, and heal files. For a changed artifact, and for the chunks it heals, it reads the stored chunks' ids and text back from Omnigraph, one artifact at a time.
3. `embed` fills the vectors of every Note and Passage row in those files (see [Write-time vectors](#write-time-vectors)).
4. `apply` runs the deletes, then the loads, then the heal loads, onto `main`.
5. `report` pushes how many of its rows still have no vector.

**Scope.** The importer reads `/user/repos` and the repos of every org in `/user/orgs`. [scope.json](../../../../kubernetes/apps/ai/omnigraph/forge-import/app/scope.json) narrows that:

- `skip_repos` are left out entirely. `webgrip/obsidian-vault` is listed because the [vault importer](#obsidian-vault) owns it, and `ryangr0/brain-eval` because it holds the private [brain eval set](#brain-eval), which must never enter the graph it measures.
- A mirror or fork gets only its `Project` node (tag `mirror` or `fork`) unless its upstream owner is in `owned_upstream_owners`. That keeps the GitHub action mirrors (`actions/*`, `docker/*` and similar) down to one node each, while mirrors of Ryan's own GitHub repos are imported whole.
- `third_party_repos` lists forks of third-party projects that live under an owned name, such as `webgrip/renovate`. They also get only their `Project` node. Forgejo cannot tell these apart from Ryan's own mirrors, so the list is kept by hand.
- Archived repos are imported, with the tag `archived` and status `completed`.

**Mapping.** Slugs are lowercase and stable. Owner and repo names keep `a-z0-9._-`, file paths are reduced to `a-z0-9-` per segment, and two paths that reduce to the same slug each get a hash suffix.

| Forgejo | `brain` | Slug |
|---|---|---|
| Repository | `Project`. `name` is `owner/repo`, `brief` the repo description, `description` the URL, language, mirror source and last activity. `kind` is `work` for an org repo and `side-project` for a user repo. `status` is `completed` when archived, `active` with activity in the last 180 days, else `paused`. `tags`: `forgejo`, the org name, the topics, and `archived`, `mirror`, `fork` or `private` where they apply | `forge/<owner>/<repo>` |
| Organization | `Organization` (`kind: company`), linked with `ProjectForOrganization` | `forge/org/<org>` |
| Author of an issue or pull request | `Person` with `name` and `brief: Forgejo user @<login>`, never an email. `relation` is `self` for the token owner and `professional` for everyone else. Deleted (ghost) users are skipped | `forge/user/<login>` |
| Root README | `Artifact` (`kind: document`) | `forge/<owner>/<repo>/readme` |
| `docs/**/*.md` (also `.markdown`, `.mdx`) | `Artifact` (`kind: document`) | `forge/<owner>/<repo>/doc/<path>` |
| ADR: a file under `docs/` in a folder named `adr*`, `decisions` or `decision-records`, or any file named `adr-*.md`. Index, README and template files are not ADRs | The file's `Artifact`, plus a `Note` of kind `decision` with the ADR text, its title, its `date:` as `when`, and tags `forgejo`, `adr` and the org name. Linked with `NoteAboutProject` and `NoteFromArtifact` | `forge/<owner>/<repo>/adr/<path>` |
| Issue | `Artifact` (`kind: post`) whose content starts with a header (number, title, state, opened and closed times, labels), then the body, then every comment with author and time | `forge/<owner>/<repo>/issue/<n>` |
| Pull request | The same, with state `merged` when merged and the head and base branches | `forge/<owner>/<repo>/pull/<n>` |

Every artifact has `source: other`, a `source_ref` (`forgejo:<owner>/<repo>:<path>@<blob sha>` for a file, `forgejo:<owner>/<repo>#<n>` for a thread), the Forgejo `url`, `content_sha256`, `ArtifactForProject` to its project and, for threads, `ArtifactFromPerson` to the author. `timestamp` is the thread's creation time, or the repo's last activity when a file was last written.

Files over 1 MiB and everything outside README, `docs/` and ADRs (code, configs) are left out. The counts line reports `skipped_large`.

**Passages.** The text of every artifact is split into `Passage` rows of at most 1,500 characters (a few hundred tokens), packed by paragraph. Each passage has the explicit id `<artifact slug>#<chunk index>` and a `PassageOf` edge to its artifact. `recall_passages` finds them by meaning and by keyword.

**Only changes are written.** The importer keeps no state of its own, for the same reason as the vault importer: a merge load replaces the whole row and clears its vector.

- A file is fetched only when its git blob sha differs from the one in its `source_ref`, so an unchanged repo costs one tree request and no downloads. Issues and pull requests are listed every run and compared by `content_sha256`.
- A changed artifact is merge-loaded. Its new chunks are compared by id and text with the stored ones, and only a chunk whose text or position changed is written, with a vector; unchanged chunks keep their row and vector. A comment appended to an issue therefore rewrites only the last chunk. A passage id that already exists is loaded as a node only: its `PassageOf` edge stays, and loading it again would violate `@unique`. Passage ids the new text no longer needs are deleted.
- Edges are compared per source. When they differ, the source's edges of that type are deleted and reloaded. Targets outside `forge/` (a link an agent or Ryan added) are reloaded with them.
- A row under `forge/` that Forgejo no longer has is deleted: a repo, a file, an issue, an org, or a person who no longer authored anything. Its passages are deleted first, because a passage must keep exactly one `PassageOf` edge and Omnigraph refuses to delete an artifact that still has passages.
- Load files are split at 2,000 rows or 16 MiB, and delete mutations at 500 statements, below the [per-commit write limit](#known-v011-limits). A passage and its `PassageOf` edge always land in the same file. Nodes load before passages, passages before edges, because a load refuses an edge to a missing node.

Forgejo owns everything under `forge/`. An edit made to such a row in the graph is overwritten the next time the source changes. Capture your own notes about a repo under another prefix and link them with `NoteAboutProject`.

A token that sees no repositories never deletes anything: the plan step refuses and the run fails. So does any Forgejo API error, before anything is written.

**Embeddings.** The importer brings its own vectors: the `embed` step fills every Note and Passage row it writes, and up to 1,500 of its vectorless rows a run are healed, oldest first (see [Write-time vectors](#write-time-vectors)). The CronJob allows 2,700 seconds; the embed step stops at 1,200.

### Setup (Ryan)

1. In Forgejo, open Settings, Applications, and generate a token named `omnigraph-forge-import` with these scopes, all read-only: `read:repository`, `read:issue`, `read:user`, `read:organization`. Do not add any write scope.
2. Store it without printing it. Paste the token, then press Ctrl-D:

   ```bash
   export BAO_ADDR="$(just bao-addr)"
   bao login -method=oidc
   bao kv put secret/omnigraph/forge-import token=-
   ```

ESO refreshes the `omnigraph-forge-import-forgejo` Secret within 5 minutes. The next run at minute 40 imports everything. To start sooner:

```bash
kubectl -n ai create job --from=cronjob/omnigraph-forge-import omnigraph-forge-import-manual
```

Review [scope.json](../../../../kubernetes/apps/ai/omnigraph/forge-import/app/scope.json) once the first run is done: search `brain` for projects tagged `mirror` or `fork`, and add any third-party fork that was imported whole to `third_party_repos`.

### Monitoring and failures

The job fails, and does not retry, with one of these lines:

- `no forge token`: the `omnigraph-forge-import-forgejo` Secret has no token. Do the setup above.
- `forge token rejected (HTTP 401)`: the token expired or was revoked. Generate a new one and store it the same way.
- `forgejo API <path> answered HTTP <code>` or `not reachable`: Forgejo is down or refused one request. Nothing was written.
- `the forge token sees no repositories`: the token lost its access. Nothing was deleted.
- `omnigraph not ready`: Omnigraph did not pass `/readyz` within 5 minutes; the curl error follows. It is down, or a network policy drops this pod.
- `omnigraph not reachable or act-forge-import refused`: Omnigraph answered `/readyz` but refused the query. The error after the colon says why; usually `act-forge-import` is not in `tokens.json` yet.
- `forge import failed`: the server refused a delete or load batch. The next run replans from the graph.

`OmnigraphForgeImportStale` fires when the CronJob has had no successful run for 3 hours, or has never succeeded since it was created. It reads `kube_cronjob_status_last_successful_time` from kube-state-metrics. It fires until the setup above is done.

**Tests.** [test_omnigraph_forge_import.py](../../../../scripts/test_omnigraph_forge_import.py) runs the planner against a fake Forgejo API over HTTP and a simulated graph that enforces Omnigraph's own refusals: a dangling edge, a duplicate edge, a second `PassageOf` for one passage, and deleting an artifact that still has passages. It covers the mapping, the schema enums, chunking, ADR detection, second-run idempotency, changed files and threads, deletes, rewired edges, batching and every fail-closed path. It runs without network: `python3 scripts/test_omnigraph_forge_import.py`. CI runs it in `e2e / Lint & static validation`.

**Network.** The pod may reach `omnigraph` on 8080, the `forgejo` pods on 3000, `litellm` on 4000 and `vmagent` in `observability` on 8429 (`omnigraph-forge-import-egress`). Forgejo admits it with a rule in `forgejo-allow-ingress`, and Omnigraph with `omnigraph-ingress`. The vault importer has the same LiteLLM and vmagent paths.

**Rotation.** Replace the Forgejo token with the same `bao kv put`, then revoke the old one in Forgejo. Deleting `omnigraph-forge-import-token` rotates the actor token. The aggregator picks it up within 15 minutes and Reloader restarts Omnigraph.

## Distiller

The importers bring documents into `brain`; they do not say what a document is about. The distiller reads notes, projects and artifacts with text; it skips `obsidian-file/` shadow artifacts and any artifact without content (`skipped_textless` in the counts line), and reads only its own `derived/distill/` state rows. Most Obsidian notes had no link to anything. The `omnigraph-distill` CronJob in namespace `ai` ([distill](../../../../kubernetes/apps/ai/omnigraph/distill/app/)) reads every document, asks a model what it is about, and links it to topics, people, organizations, projects, places and areas. It runs every hour at minute 55, after the importers, and writes straight to `main` as `act-distill`. Ryan decided this on 2026-09-28.

### What it writes

| Document | Topic | Person | Organization | Project | Place | Area |
|---|---|---|---|---|---|---|
| `Note` | `NoteAboutTopic` | `NoteAboutPerson` | `NoteAboutOrganization` | `NoteAboutProject` (not from `forge/` notes) | `NoteAboutPlace` | `NoteAboutArea` |
| `Artifact` | `ArtifactAboutTopic` | `MentionsPerson` | `ArtifactAboutOrganization` | `ArtifactAboutProject` (not to its own repo) | | |
| `Project` (brief, description and README) | `ProjectAboutTopic` | | | | | `ProjectInArea` |

Topics that often appear together are linked with `TopicRelatedTopic`, whose `documents` property counts the documents that name both. A pair needs 3 documents.

**Ownership.** The distiller owns two things and touches nothing else:

- Rows under `derived/`: `Topic` (`derived/topic/<name>`), the `Person`, `Organization` and `Place` rows it creates (`derived/person/`, `derived/org/`, `derived/place/`), one `Area` per area kind (`derived/area/<kind>`, used only when no `Area` of that kind exists), and one `Distillation` state row per document (`derived/distill/<document slug>`).
- Edges whose id starts with `derived:`, in the fixed-id form `derived:<EdgeType>:<from>><to>`. The prefix is how it tells its own edges from an agent's or Ryan's, so it never deletes an edge it did not write. A link Ryan or an agent made to the same target counts: the distiller then does not add its own and drops its copy.

It never writes an edge type an importer manages from that importer's rows (`NoteAboutProject` from `forge/` notes, `ArtifactForProject`, `ArtifactFromPerson`, `NoteFromArtifact`, `ProjectForOrganization`, `RelatedNote`), because the importer would delete it on its next relink. It never creates a `Project`; a project name must match an existing one.

### How it runs

1. `snapshot` reads, with the queries in [snapshot.gq](../../../../kubernetes/apps/ai/omnigraph/distill/app/snapshot.gq): every note, artifact and project with its text, every person, organization, place, area and topic, the `Distillation` rows, every edge the distiller writes, and every other edge that touches a `derived/` row. About 20 MB, most of it artifact text.
2. `plan` runs [distill.py](../../../../kubernetes/apps/ai/omnigraph/distill/app/distill.py). It calls LiteLLM, resolves names and writes delete mutations and merge-load files.
3. `apply` runs the deletes, then the loads (entities, then edges, then state rows) onto `main`.

The counts line has documents, pending, processed, failed, edges added and removed, entities and topics created and deleted, merges, tokens and `cost_usd`. It never logs names or text.

**Incremental.** A document is sent to the model only when the SHA-256 of its model input (kind, title, tags and the first 12,000 characters) differs from the `content_sha256` in its `Distillation` row, or the row's `extractor` (`v2:<model>`) differs. A state row is needed because a document that yields no links has nothing else to hold its hash, and a property on the `Note` or `Artifact` would be an edit to an importer's row. Changing the model or bumping `EXTRACTOR` reprocesses everything once.

- A changed document gets its new links; the `derived:` edges it no longer supports are deleted.
- A deleted document takes its edges with it (Omnigraph deletes a node's edges); the distiller then deletes its state row.
- A `derived/` entity that no edge references any more, including links other writers made, is deleted. An entity someone else links to stays.
- The state row is written last. If a run fails half way, the next run sees the old hash and redoes the document.

**Limits per run.** At most 600 documents and USD 1 of model spend; the rest waits for the next hour. Notes outside `forge/` go first, then ADR notes, projects and artifacts. The first backfill of the whole graph therefore takes several runs. Load files are split at 2,000 rows or 16 MiB and delete mutations at 500 statements, below the [per-commit write limit](#known-v011-limits).

### Extraction

[extraction.prompt.txt](../../../../kubernetes/apps/ai/omnigraph/distill/app/extraction.prompt.txt) is the system message, followed by the names of the known non-mirror projects. [extraction.schema.json](../../../../kubernetes/apps/ai/omnigraph/distill/app/extraction.schema.json) is the strict `response_format`: topics (at most 6, with a one-sentence general description and aliases, including the Dutch name), people, organizations, projects, places and areas (the `Area.kind` values), each with `about`. Only entities the document is about are linked, with one exception: an artifact's mentioned people are linked with `MentionsPerson` when they already exist. New people, organizations and places are created only from `about` entities.

Model choice, tested 2026-09-28 on 20 real documents (6 Dutch and 6 English Obsidian notes, 8 Forgejo docs), temperature 0, `reasoning_effort: low`:

| Model | Valid JSON | Cost for 20 | Mean latency | Notes |
|---|---|---|---|---|
| `fireworks-gpt-oss-120b` | 20/20 | USD 0.013 | 3.1 s | Chosen. English topic names with Dutch aliases for Dutch notes |
| `meeting-extract` | 20/20 | USD 0.007 reported | 3.7 s | The same Fireworks model; LiteLLM reports half the cost for identical token counts, so the real cost equals the row above |
| `chat-default` (MiniMax) | 16/20 | USD 0.057 | 13.6 s | Four answers were not valid JSON; more organizations and projects per document, several not in the text |

That is about USD 0.0007 per document, so a full backfill of the graph (about 3,400 documents) costs about USD 2.50. The key `omnigraph-distill` allows `fireworks-gpt-oss-120b`, `deepseek-chat` (LiteLLM's fallback when Fireworks fails, owner-approved) and the embedding model, with a budget of USD 5 per 30 days.

### Resolution

Every extracted name is matched against existing rows before anything is created:

1. **Name key.** Lowercase, accents folded, leading articles (`the`, `de`, `het`, `een`) and legal suffixes (`B.V.`, `Inc`, `GmbH`) dropped, everything but letters and digits removed, a plural `s` or `ies` reduced. A topic matches on its name, a person on name or first plus last name, an organization or place on its name, a project on its full name or repo name. A repo name shared by two projects matches the one that is not a mirror or fork, otherwise nothing. The person with `relation: self` also matches on first name and Forgejo login, so "Ryan" in a note is Ryan.
2. **Alias hit, confirmed by the model.** Topic aliases come from the model and are not trusted as keys on their own: when a name matches only another topic's alias, [merge.prompt.txt](../../../../kubernetes/apps/ai/omnigraph/distill/app/merge.prompt.txt) asks the chat model whether the two are the same concept. Yes links the document to that topic. No creates a new topic and removes the wrong alias from the old one, so the question is not asked again. An alias that is already another topic's name is never stored.
3. **Embedding candidates, confirmed by the model.** A topic that is still new after this is embedded by name with `granite-embedding-97m-multilingual-r2`. Its three nearest topics with cosine similarity at least 0.75, plus any topic whose alias equals its name, are candidates. At 0.97 or more it is merged directly; otherwise the model is asked, and only a yes merges. A merge adds the duplicate's name to the keeper's aliases and moves its links. Topic rows carry their name vector, so the next run compares without embedding them again.

4. **Alias audit.** Every alias a topic carries is put to the same confirmation once: "is `<alias>` the same concept as `<topic> (<description>)`?". A no removes the alias. The audit is recorded in a `Distillation` row for the topic (`derived/distill/derived/topic/<name>`, extractor `alias-audit-v1`, `content_sha256` over the sorted aliases), so a topic is audited again only when its aliases change. At most 1,500 questions per run; the rest waits (`alias_audits_deferred`). A question the model does not answer keeps the aliases and is asked again next run.

People, organizations and places are matched by key only: the embedding model scores different names of the same kind (two companies, two people) as close, so similarity would merge strangers.

Why the model confirms: on 141 topic names from the test documents, name embeddings alone gave no usable threshold. Of the 14 pairs above 0.85, two were the same concept; `MySQL`/`PostgreSQL` scored 0.907 and `Facturatie`/`Urenregistratie` 0.899, above true pairs such as `Christendom`/`Christianity` (0.848) and `Varnish`/`Varnish Cache` (0.797). Embedding name plus description was no better (`Docker`/`Kubernetes` 0.945). On 50 hand-labelled pairs (35 from the test documents, 15 from aliases the first live audit removed) the confirmation step said yes to 12 of 20 true duplicates and to none of 30 different concepts: precision 100%, recall 60%, the same in two repeated runs. It misses broader and narrower pairs (`GDPR`/`GDPR compliance`, `Roadmap`/`Roadmap management`) and some translations (`Christendom`/`Christianity`). The prompt names shorter and fuller names, abbreviations and translations as the same topic; without that sentence recall was 55%, precision unchanged. In the first live alias audit, 32 of 40 sampled removals were right (80%; wrongly removed were, for example, `Tempo` from `Grafana Tempo` and `eiwit` from `Egg whites`) and 14 of 15 sampled kept aliases were right. A missed merge leaves two topics; a wrong merge corrupts links, so the step is tuned to say no when unsure. Each question costs about USD 0.00005.

The first live run (extractor `v1`) trusted aliases as keys and merged on any alias collision. One wrong match then copied every name of the incoming topic onto the wrong one, and it spread: `containerd` collected `Docker`, `API design` collected `High availability`. `v2` replaced that with steps 2 to 4 and reprocessed every document; the audit cleans the aliases `v1` left on topics that survive.

### Quality, first backfill (2026-09-28)

- Obsidian notes with at least one edge: 11 of 461 before, 444 of 461 after the first 600 documents. All notes: 299 of 750 before, 733 after.
- Ten random documents (five Obsidian notes, one ADR note, two pull requests, two projects) got 55 links; 50 were right (about 92%). The misses were loose ones (`API` on a Magento note, `Learning` as an area of a support log) and a missed one: a daily log about DNS, DKIM and backups got no topic at all.
- Person extraction is the noisiest part: the first run created people such as `Developer Team` and `Solution Architect`, and Ryan himself as `Ryan` and `Ryangr0`. The prompt now excludes roles, teams and companies, and the owner is matched by first name and login.
- A topic can carry the name of a repo (`Ploeg`, `Glide`) next to the `Project`. Topics are not mapped onto projects by name, because generic topics collide with repo names (`Cloudflare`, `Renovate`, `Workflows`, `API Gateway`).

### Setup

Nothing to set up by hand. The actor token and the LiteLLM key are generated in the cluster. The first runs after deploy backfill the graph.

### Monitoring and failures

The job fails, and does not retry, with one of these lines:

- `omnigraph not ready`: Omnigraph did not pass `/readyz` within 5 minutes; the curl error follows. It is down, or a network policy drops this pod.
- `omnigraph not reachable or act-distill refused`: Omnigraph answered `/readyz` but refused the query. The error after the colon says why; usually `act-distill` is not in `tokens.json` yet.
- `distill refused: litellm ... not reachable` or `answered HTTP 401`: LiteLLM is down, or the `omnigraph-distill` key is not registered (`kubectl -n ai logs job/litellm-key-register-omnigraph-distill`). `HTTP 400` with a budget message: the key's budget is spent.
- `distill refused: the snapshot holds no documents`: the snapshot came back empty while state rows exist. Nothing was deleted.
- `distill failed: delete batch` or `load batch`: the server refused a write. The next run replans from the graph.
- `distill incomplete: N of M extractions failed`: more than a fifth of the model answers were unusable. What succeeded was written; the rest is retried next run.

LiteLLM answers of 429 and 5xx are retried up to five times with backoff (`retries` in the counts line); the key allows 600 requests a minute. A document the provider refuses with HTTP 400 (`refused`) gets a state row without links and is not sent again until it changes.

`OmnigraphDistillStale` fires when the CronJob has had no successful run for 3 hours, or never succeeded since it was created. `OmnigraphDistillBudgetNearlySpent` fires when the key has spent 80% of its 30-day budget (`litellm_key_spend` over `litellm_key_max_budget` from the LiteLLM exporter). Expected once during the first backfill; a repeat means something reprocesses documents every run.

**Tests.** [test_omnigraph_distill.py](../../../../scripts/test_omnigraph_distill.py) runs the planner against a simulated graph that enforces the schema's types, enums and edge endpoints and the write limits, with a fake LiteLLM. It covers parsing, resolution (keys, aliases, confirmed and refused merges, project ambiguity), importer-managed edges, second-run idempotence, changed and deleted documents, reference counting, foreign links, co-occurrence, the document and spend caps, failure paths and batching. [test-omnigraph-distill-mutation.sh](../../../../scripts/test-omnigraph-distill-mutation.sh) breaks resolution, merging, reference counting, ownership, the change check, the importer guard and the batch size one at a time, and requires each break to fail the suite and the unmodified distiller to pass. Both run offline in `e2e / Lint & static validation`.

**Network.** The pod may reach `omnigraph` on 8080 and `litellm` on 4000 (`omnigraph-distill-egress`). Omnigraph admits it with `omnigraph-ingress`; LiteLLM admits all of namespace `ai`.

**Rotation.** Deleting `omnigraph-distill-token` rotates the actor token; the aggregator picks it up within 15 minutes and Reloader restarts Omnigraph. Rotate the LiteLLM key by deleting the `litellm-key-omnigraph-distill` Secret and the `litellm-key-register-omnigraph-distill` Job.

**Undo.** Every `derived/` row and `derived:` edge comes from the distiller. To remove its work, suspend the CronJob, then delete those rows and edges as `act-ryan`; the importers' rows are untouched.

## Brain eval

The brain retrieval work ([RFC](../rfc/rfc-brain-retrieval.md)) ships a change only when it moves a measured score. The `omnigraph-brain-eval-*` CronJobs in namespace `ai` ([brain-eval](../../../../kubernetes/apps/ai/omnigraph/brain-eval/app/)) do the measuring. The harness is one stdlib Python program, [brain_eval.py](../../../../kubernetes/apps/ai/omnigraph/brain-eval/app/brain_eval.py), with [candidates.py](../../../../kubernetes/apps/ai/omnigraph/brain-eval/app/candidates.py) for drafting questions.

**Privacy.** The questions, expected documents, key facts, answers and per-question results live only in the private repo `ryangr0/brain-eval` (forge-import skips it). This repo holds the harness, generic prompts, synthetic fixtures and aggregate scores. Job logs carry case ids (`c01`), counts, timings and aggregate scores, never question text or slugs; metric labels come from a fixed allowlist. A test plants a sentinel phrase and fails if it reaches stdout, stderr or a metric.

### Jobs

| CronJob | When | Does | Cost |
|---|---|---|---|
| `omnigraph-brain-eval-retrieval` | 04:40 nightly | Profiles `p0` (today's `recall_notes`, `recall_passages` and `recall_topics`, interleaved by rank, invoked directly), `p0-rest` (the same through [brain-tools](#brain-tools) REST, whose ranking must equal `p0` case by case: `brain_eval_replica_identical_ratio`) and `p1` (brain-tools' fused pipeline) for every case, all pinned to one graph commit; the share of vectorless `Note`, `Passage` and `Topic` rows; a scan of a fresh clone of this public repo for any eval question | USD 0 |
| `omnigraph-brain-eval-answer` | Sunday 05:10 UTC | The judge's control pair, then B0: `chat-default` answers each case through the read-only raw bridge `omnigraph_brain_eval`, and `fireworks-deepseek-v4p1-flash` judges it | about USD 0.50 |
| `omnigraph-brain-eval-gate-retrieval` | manual | Retrieval only: `p0`, `p0-rest` and `p1` on one snapshot and the decision rule for `p0:p1`, with the guardrails search p95 at most 3 seconds and answers at most 6,000 characters | USD 0 |
| `omnigraph-brain-eval-gate` | manual | Retrieval plus answers with 3 repeats, the decision rule for `--compare baseline:candidate`, and up to ten answers in `calibration/pending/` | about USD 3 |
| `omnigraph-brain-eval-candidates` | manual | Drafts about 60 questions from sampled sources and cuts them to 36 provisional cases | about USD 1 |
| `omnigraph-brain-eval-experiment` | manual | E1: raw versus `type:`-prefixed vectors over each dev case's candidate pool, in memory | under USD 0.50 |
| `omnigraph-brain-eval-smoke` | manual | The whole path on public synthetic questions about this repo's runbooks, writing nothing: a retrieval run with a scratch case whose slug is renamed (its log must say `"stale": 1`), then the judge's control pair and B0 through the bridge. Run it after a LiteLLM or Omnigraph upgrade | under USD 0.10 |
| `omnigraph-brain-eval-store-backup-window` | 03:05 UTC nightly | Holds the eval store volume attached until 03:30 UTC so the Longhorn RecurringJob `brain-eval-store-backup` (03:15 UTC) can back it up; see [the eval store](#the-eval-store) | USD 0 |

Run one by hand with `kubectl -n ai create job --from=cronjob/<name> <name>-manual`.

Each eval pod runs its containers in order: `privacy-store` proves the eval repo private (below), `store` clones it, `eval` runs the harness, `privacy-publish` proves it private again, `publish` commits the results, and `report` pushes the aggregates to `vmagent-vmagent.observability:8429` with `job="omnigraph-brain-eval"` and stamps `brain_eval_last_success_timestamp_seconds{mode}`. The retrieval pod also clones this public repo (`public-repo`) for the leak check. A run that fails part way stamps nothing, so staleness means "no stored result". Finished Jobs are deleted after a day (`ttlSecondsAfterFinished`), so a failed one raises `KubeJobFailed` for at most that long.

**Answer mode needs MCP argument redaction.** LiteLLM 1.102.1 kept every MCP tool call's arguments in its spend log and trace spans, so an answer run would have copied every eval question into `litellm-db`. Since VIK-1403 LiteLLM stores `{"redacted": true}` instead ([LiteLLM: MCP tool arguments](../general/litellm.md#mcp-tool-arguments)), and the pods set `BRAIN_EVAL_MCP_ARGUMENTS_REDACTED=true`. The harness refuses answer mode on real cases without it; the control pair and `--synthetic` runs (public questions about this repo's runbooks) never need it. If the patch is ever removed or `LiteLLMMCPArgumentsStored` fires, set the variable back to `false` first.

### Identities

| Identity | Rights | Used for |
|---|---|---|
| `act-brain-eval` | `brain`: read and export on any branch; stored queries in a separate rule | every harness read, and the `omnigraph_brain_eval` bridge |
| `act-brain-reader` | `brain`: read on any branch; stored queries in a separate rule | `brain-tools` reads (RFC P4) |
| `act-brain-scribe` | `brain`: read and change on protected branches (`main`), nothing else | `brain-tools` `remember` (RFC P6) |
| LiteLLM key `omnigraph-eval` | `chat-default` (answers), `fireworks-gpt-oss-120b` (drafts questions), `fireworks-deepseek-v4p1-flash` (judge and relevance pooling), `deepseek-chat` (pooling fallback when the Fireworks budget is spent), the embedding model; MCP group `brain-eval-raw`; USD 10 per 30 days | the harness |

**Models.** No eval job calls an Anthropic model (owner decision 2026-09-29: the cheapest model that does the job, never Anthropic). The judge is another family than the answer model (MiniMax) and the question drafter (gpt-oss), because a judge grades its own family's style too kindly. The DeepSeek route on Fireworks is the cheapest DeepSeek route; it is kept only while it passes the control pair, and once Ryan's grades exist, while it agrees with 80% of them. Otherwise move to the next cheapest of another family: `deepseek-chat`, then `deepseek-reasoner`. A test reads the LiteLLM config and this key and fails when a job would call an Anthropic model, a model missing from the key, or a judge of the answer or drafting family.

`act-brain-scribe` can delete any row on `main`: its only guard is the scribe audit that `brain-tools` runs (RFC section 6.2).

### The eval store

The jobs read and write a git repository with the layout the repo README describes (`cases/`, `candidates/`, `calibration/`, `results/`).

- When `ssh://git@forgejo-ssh.forgejo.svc.cluster.local/ryangr0/brain-eval.git` answers with the deploy key, that repo is the store.
- Until then the jobs use a **provisional in-cluster store**: a bare repository on the PVC `omnigraph-brain-eval-store`. `brain_eval_store_provisional` is 1.
- The first run that reaches an empty Forgejo repo pushes every branch of the provisional store into it and writes a marker on the PVC. From then on an unreachable repo fails the run instead of silently writing to the old store.
- **State since 2026-09-29 20:21 UTC:** the store lives in the private repo. The manual job `omnigraph-brain-eval-retrieval-move` logged `anonymous_status 404, private true`, moved the provisional store and published its results there; `brain_eval_store_provisional` is 0. The PVC keeps only the marker and the old bare repository.
- Every stored run rewrites the repo's `README.md` and `calibration/README.md` from [repo-readme.md](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/kubernetes/apps/ai/omnigraph/brain-eval/app/repo-readme.md) and [calibration-readme.md](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/kubernetes/apps/ai/omnigraph/brain-eval/app/calibration-readme.md), so change those guides here, never in the private repo.

**Privacy gate.** A deploy key works on a public repo too, so the key alone proves nothing. Before `store` may use the Forgejo repo, and again right before every `publish`, a `repo-privacy` container reads `GET /api/v1/repos/ryangr0/brain-eval` on `forgejo-http:3000` without credentials. Only a 404 counts as private: it writes the verdict file that `store.sh` and `publish.sh` require before they touch the remote, and pushes `brain_eval_repo_private 1`. A 200 (anyone can read the repo) pushes `brain_eval_repo_private 0` and `brain_eval_run_valid 0` and stops the pod, which raises `OmnigraphBrainEvalRepoNotPrivate` (critical). Any other answer, including no connection, also stops the pod and marks the run invalid, because privacy could not be proven. A missing repo answers 404 as well, which is harmless: nothing is pushed until the deploy key reaches it.

**Backup of the provisional store.** Longhorn's `gitops-backup` job skips detached volumes (`allow-recurring-job-while-volume-detached` is false), and this volume is attached only while a job runs, so the `gitops-backup` enrolment alone never produced a backup. The volume therefore has its own RecurringJob, `brain-eval-store-backup` (task `backup`, 03:15 UTC, retain 14, group `brain-eval-store` stamped by the Kyverno rule `enrol-brain-eval-store`), and the CronJob `omnigraph-brain-eval-store-backup-window` mounts it read-only from 03:05 to 03:30 UTC so it is attached when that job fires. Both run in UTC, so daylight saving never moves them apart; a manual eval job started in that window on another node waits for the volume. A test (`StoreBackupWindow`) checks every scheduled eval CronJob against that window in winter and summer time, from its start to its `activeDeadlineSeconds`: the weekly answer run is therefore on UTC (05:10), and the nightly retrieval run, at 02:40 UTC in summer, has a 20-minute deadline. `OmnigraphBrainEvalStoreNotBackedUp` fires while the store is provisional and has no backup from the last 36 hours. Once the store has moved to Forgejo, Forgejo's own backup covers it.

**Setup (Ryan), done 2026-09-29.** These steps created the repo and gave the jobs write access; repeat them only to rebuild it:

1. In Forgejo, **+**, **New repository**: owner `ryangr0`, name `brain-eval`, **Make repository private** checked, no template, no README, no licence. Leave it empty. Add no collaborators and no push mirror.
2. Print the deploy key and add it under the repo's **Settings**, **Deploy keys**, **Add deploy key**, with **Enable write access** checked:

   ```bash
   export BAO_ADDR="$(just bao-addr)"
   bao kv get -field=public_key secret/omnigraph/brain-eval-deploy-key
   ```

3. Run the retrieval job by hand. Its `privacy-store` log says `"private": true` and its `store` log says `moved the provisional in-cluster store into the private Forgejo repo`.

### The set

36 cases, one YAML file each under `cases/`, in eight categories (docs-en 6, notes-nl 6, notes-en 4, cross-lingual 4, about 6, connect 4, temporal 3, unanswerable 3), one holdout per category. The candidates job built the first set:

1. It samples sources from a pinned snapshot: Obsidian notes of 300 or more characters (Dutch and English, two Dutch notes long enough that the question targets text past the first 1,024 tokens), forge documents and ADRs (at most two per repo), topics with 10 or more documents, a person with 3 or more, and pairs of related topics with 3 or more shared documents.
2. `fireworks-gpt-oss-120b` drafts two questions and 1 to 4 key facts per source ([draft.prompt.txt](../../../../kubernetes/apps/ai/omnigraph/brain-eval/app/draft.prompt.txt)). A question that repeats five consecutive words of its source is redrafted once, then dropped. Eight unanswerable questions are drafted against the list of covered topics, and temporal questions come from fixed templates.
3. Relevance pooling: the union of the top 10 from `p0`, a meaning-only leg and a keyword-only leg is graded 0, 1 or 2 by `fireworks-deepseek-v4p1-flash`, or by `deepseek-chat` once Fireworks answers 429 ([pool.prompt.txt](../../../../kubernetes/apps/ai/omnigraph/brain-eval/app/pool.prompt.txt)). The source document is grade 2, graded documents fill the rest of `expected`. An unanswerable question with any relevant document is dropped.
4. The cut keeps the first question of each source where it can, meets each category's count and picks one holdout per category. It never overwrites existing cases.

Every drafted case is `provisional: true`, and `brain_eval_set_provisional` stays 1, until Ryan has reviewed the cases, replaced at least 6 with questions he really asks (`origin: ryan`) and hand-graded 10 answers. The repo's own README says how.

### What is measured

- **Retrieval** (nightly): Recall@5, Recall@8, Hit@1, MRR@8, graded nDCG@8 (primary) and candidate recall@40 per category and split. Ground truth is per document: a passage counts as its artifact, `obsidian-file/x` as `obsidian/x`, a forge ADR note as its artifact. A case whose expected slug no longer exists is excluded and counted in `brain_eval_stale_cases`. Temporal cases compute their expectation at run time from a full scan of the type at the pinned commit and a Python filter, never from a stored query. Unanswerable cases are only scored in answer mode.
- **Answers**: key-fact recall, faithfulness, citation precision and abstention accuracy from the judge ([judge.prompt.txt](../../../../kubernetes/apps/ai/omnigraph/brain-eval/app/judge.prompt.txt), strict JSON, temperature 0, no fallbacks), plus tool calls, tool errors, USD and latency per answer. Every tool output is cut to 12,000 characters for the model and the judge alike. At most 6 tool turns. Each failed tool call gets one class from a fixed list, read from the shape of the bridge's error, never its text: `gq_foreign` is text that is not GQ at all (Cypher, SQL or a stored query's bare name: the parser stops at its first character), and `gq_parse`, `gq_type`, `gq_parameter` and `gq_rejected` are GQ the model wrote wrong; `policy_denied`, `not_found` and `resource_limit` are refusals; `server_error`, `server_unreachable` and `bridge_transport` are the stack's own failures; `tool_arguments` and `unknown_tool` are malformed calls. The counts go to the log (`tool_error_classes`), the private results and `brain_eval_tool_errors{profile,class}`.
- **Rigour**: every read of a retrieval run pins the same `graph_commit_id`, so two runs on one commit give identical scores. Every answer and gate run starts with a control pair (a planted correct answer must score 0.8 or more, a planted unsupported one 0.2 or less, and a verdict that is not valid JSON fails); a failure publishes only `brain_eval_judge_control_ok 0` and `brain_eval_run_valid 0` for that mode and exits non-zero. The judge may use 4,000 output tokens. A verdict that is cut off or is not JSON is asked for once more; an answer whose verdict is still unreadable stays unscored (`judge verdict unreadable` in the log, `judge_unreadable` in the result), and more than 10% of such answers make the run invalid. A per-run spend cap aborts the run and publishes `brain_eval_run_valid 0`. Answer and gate runs write up to ten answers to `calibration/pending/` for hand grading, and answer runs publish `brain_eval_judge_agreement` once graded files exist.
- **Decision rule** (gate mode, dev split): adopt a change only when the paired mean delta of the primary metric is at least +0.05, net wins are at least 3 (sign-test p reported), no category loses more than one case, and the guardrails hold.

The missing-vector share is counted with queries pinned to the same commit (rows that `nearest()` ranks have a vector), not with `/export`: exporting `Passage` stopped at the server's `ordered_scan_input_batch_bytes` limit on 2026-09-29.

Aggregates go to VictoriaMetrics as `brain_eval_*` (15 days); per-question results are the record, in `results/<date>/<mode>-<profile>.json`. Pushed samples leave instant queries after about 5 minutes, so the dashboard and alerts read `last_over_time(...[3d])` (`[8d]` for weekly answer series).

### Monitoring and failures

Grafana, folder AI, **Brain retrieval quality**: stat tiles and per-category tables for `p0` and B0, B0's tool errors by class, whether scores are provisional, stale cases, the judge's control pair and agreement, missing vectors, latency and spend.

| Alert | Fires when |
|---|---|
| `OmnigraphBrainEvalStale` | No stored retrieval run for 36 hours, or none in 3 days |
| `OmnigraphBrainEvalJudgeControlFailed` | The last answer run's judge failed the control pair |
| `OmnigraphBrainEvalRunInvalid` | A run hit its spend cap or an upstream error |
| `OmnigraphBrainEvalBudgetNearlySpent` | The `omnigraph-eval` key spent 80% of its 30-day budget |
| `OmnigraphBrainEvalCaseTextInPublicRepo` | Eight consecutive words (or the whole phrase, at 5 to 7 words) of an eval question or key fact appear in this public repo, or an expected slug that carries a note title, a capture or a person's name does (`obsidian/…` and its `obsidian-file/…` twin, `nt-…`, `derived/person/…`, as a whole slug). Temporal template questions are skipped, and so are the key facts of cases whose source document is in this repo, because those quote it. Slugs of forge documents, projects and topics are not scanned: they name public or generic things, and this repo's tests use generic ones |
| `OmnigraphBrainEvalRepoNotPrivate` | An anonymous read of `ryangr0/brain-eval` answered 200: the repo is readable by anyone (critical) |
| `OmnigraphBrainEvalStoreNotBackedUp` | The store is still provisional and its volume has no Longhorn backup from the last 36 hours |

The `eval` container ends with a `run invalid` line naming the reason: an upstream status (`omnigraph answered HTTP 403` means `act-brain-eval` lost a right), `the eval repo holds no cases yet`, a case file and line that do not parse, `passed the cap`, `no readable verdict for N of M answers`, or `unexpected <error> at brain_eval.py:<line> in <function> (<library file>:<line>)` for a bug in the harness.

`litellm answered HTTP 429` has two sources, and the code after it says which.

- **`throttling_error` is the `omnigraph-eval` key's own rate limit,** not a provider's. LiteLLM's proxy limiter counts the key's tokens and requests per fixed 60-second window (TPM 400,000, RPM 120, set in the [key register Job](../../../../kubernetes/apps/ai/litellm/keys/app/omnigraph-eval-key-register.job.yaml)) and answers `429` with `retry-after: 60` once a window is full. A B0 answer resends its whole conversation on every turn, with up to 12,000 characters per tool output, so a few tool-heavy answers and their verdicts can fill 400,000 tokens in one minute: that stopped `omnigraph-brain-eval-gate-b0-2` after 67 of 108 answers on 2026-09-29 (LiteLLM logged `Limit type: tokens. Current limit: 400000, Remaining: 3843`), while the harness gave up after 14 seconds of backoff. The harness now paces itself under 300,000 tokens and 90 requests a minute (`--tokens-per-minute`, `--requests-per-minute`; a test keeps both under 80% of the key's limits), and on a `429` whose `retry-after` is at most 120 seconds it waits that long plus a second and retries, up to four times per call, for model and tool calls alike. Each wait logs `litellm rate limited`; `brain_eval_paced_seconds{mode}` is the run's total pause. Raise the key's limits only as an owner decision.
- **A spent provider day budget** answers `429` too: the Fireworks provider, which serves `chat-default`, the drafter and the judge, is capped at USD 10 a day for every consumer together (`GET /provider/budgets` with the master key shows the spend and `budget_reset_at`). The judge never falls back to another model, and the answer model is on Fireworks too, so answer runs and the smoke job fail until the reset. Relevance pooling in the candidates job falls back to `deepseek-chat` (the DeepSeek provider, USD 5 a day) for the rest of the run and records the grading model per candidate in `pool.json` (`pooled_by_fallback` in the log).

**Tests.** [test_omnigraph_brain_eval.py](../../../../scripts/test_omnigraph_brain_eval.py) runs the harness against a fake Omnigraph, a fake LiteLLM with its MCP endpoint and a fake vmagent: metric maths against hand-computed values, document roll-up, stale exclusion, the independent temporal path (the fake's stored query disagrees with the scan), snapshot pinning, the control pair, the spend cap, the answer-mode redaction gate, calibration agreement, the label allowlist, the candidate cut, the sentinel, full-precision values, the key-fact and slug leak scans, the gate's control pair, the guide refresh, the model policy (no Anthropic model, every model on the key, a judge of another family), the schedules against the store backup window, the pacing under the eval key's limits and the wait for `retry-after` on a throttled model or tool call (never past 120 seconds), the tool error classes, and the privacy gate: the `repo-privacy` check against a fake Forgejo (404, 200, 503), and `store.sh` and `publish.sh` run with a fake `git` that must never push without a verdict. [test-omnigraph-brain-eval-mutation.sh](../../../../scripts/test-omnigraph-brain-eval-mutation.sh) breaks each of those in turn and requires the suite to fail, and the unmodified harness to pass. Both run in pre-commit and in `e2e / Lint & static validation`.

**Network.** `omnigraph-brain-eval-egress` allows `omnigraph` :8080, `litellm` :4000, `brain-tools` :8081 (REST profiles), the Forgejo pods on SSH :2222 (eval repo) and HTTP :3000 (anonymous clone of this public repo for the leak check) and `vmagent` :8429. Omnigraph admits it in `omnigraph-ingress`, Forgejo in `forgejo-allow-ingress`; LiteLLM admits all of `ai`, and `observability` has no NetworkPolicy.

## Brain tools

`brain-tools` (namespace `ai`) answers questions about `brain` with plain words, so no agent has to write GQ (brain retrieval RFC, P4). It runs as `act-brain-reader`, calls only the fixed stored queries in [brain.retrieval.gq](../../../../kubernetes/apps/ai/omnigraph/app/bundle/brain.retrieval.gq) and `recall_*`, and writes nothing.

| Port | Serves | Who may connect |
|---|---|---|
| 8080 | `/mcp`: MCP over stateless streamable HTTP (JSON responses), tools `search` and `read` | LiteLLM only |
| 8081 | REST `/api/search`, `/api/read` (GET or POST), `/metrics`, `/healthz`, `/readyz` | the brain eval jobs and `observability` |

**Tools.** `search(query, scope = all|notes|docs, limit = 8)` returns numbered sources, best first, each with a ref (`doc:<artifact>#<chunk>`, `note:<note>#<chunk>` or `note:nt-…`), a link (a forge document's own URL, otherwise `https://graph.<domain>/?graph=brain&node=<slug>`) and a snippet of at most 600 characters, then related topics, then a footer with the graph commit, whether it reranked, the time taken and "Private: cite, do not copy into git, tickets or public pages." An answer is at most 6,000 characters; the lowest ranks are cut first. `read(ref, around = 1)` opens a ref with one neighbouring chunk on each side, at most 4,000 characters; an Obsidian note ref reads its `obsidian-file/` shadow artifact, a capture its own text. Bad input, an unknown ref, an entity ref, an empty result and an unavailable brain each answer with a sentence that says what to do next; "the brain is unavailable" tells the model not to answer from memory. Every call has an 8-second deadline.

**Profiles.** `search` runs one of two pipelines; REST picks one per request with `profile`, MCP uses `BRAIN_TOOLS_PROFILE`.

- `p0` replicates the stored `recall_notes`, `recall_passages` and `recall_topics` interleaved by rank, the baseline of the eval.
- `p1` embeds the question once through LiteLLM (key `brain-tools`, the granite model only), strips Dutch and English stopwords for the keyword legs, and runs up to eight legs in parallel: forge passages, Obsidian passages and `nt-` captures, each by meaning and by keywords, plus topics for the related list. It fuses them by weighted reciprocal rank (k 60; keywords weigh 0.6 for a Dutch question), then collapses: passages of 80 characters or fewer are dropped unless nothing else is left, clones with the same text (numbers ignored) collapse into the newest with "+N similar", at most 2 chunks per document, and documents authored by a bot person (Renovate and similar) weigh 0.3 unless the question names the bot. When the question cannot be embedded it runs the keyword legs only and says `degraded: keyword-only`.

REST also takes `snapshot` (a graph commit id: every stored query, the bot cache included, reads that commit, so eval runs are reproducible) and `debug=1` (per-leg rows, keys and timings, and the fused scores). A REST answer carries `tool_chars`, the length of what the default `search` tool would return.

**Checks it runs itself.** Every 30 seconds it reads the stored-query catalog as `act-brain-reader`; `/readyz` fails while Omnigraph does not answer or a query it needs is missing, so LiteLLM gets a refused connection instead of a hanging call. It also compares the [embedding contract](../../../../kubernetes/apps/ai/omnigraph/embed-step/app/contract.json) with the `@embed` model and dimensions of `Passage`, `Note` and `Topic` in the live schema; on a mismatch it turns every meaning leg off rather than rank with a vector from another model. The set of documents authored by bot persons is cached for 15 minutes (`rt_artifact_authors`), and read at the pinned commit when a request pins one. Logs carry the tool, outcome, milliseconds, counts and graph commit, never a question, an answer or a slug.

**Who can call it.** LiteLLM registers it as MCP server `brain_tools` (tools `brain_tools-search` and `brain_tools-read`) in access group `brain-dogfood`, which only the `claude-code` key holds (decision D13: Claude Code gets `search` and `read` at the end of P4). In Claude Code they appear under the existing `omnigraph` server as `brain_tools-search` and `brain_tools-read`. P6 moves the server to the `brain` group for Open WebUI and adds `/mcp/read` for the eval key.

**Code and image.** The TypeScript source lives in [brain-tools/app/server](../../../../kubernetes/apps/ai/brain-tools/app/server/) and ships in the `brain-tools-server` ConfigMap; the pod runs it with Node 24's built-in type stripping on the digest-pinned official `node` image (through the Harbor Docker Hub proxy). It has no runtime dependencies: the MCP transport is a small JSON-RPC handler, proven against the official `@modelcontextprotocol/sdk` 1.31.0 client and through LiteLLM. This is provisional until the repository `webgrip/brain-tools` exists and releases a signed image through Forgejo Actions, Harbor, the CVE gate and cosign, like the explorer; then the Deployment switches to that image and the source leaves this repo.

**Tests.** [brain_tools.test.ts](../../../../scripts/brain-tools/brain_tools.test.ts) (`node --test`) runs the service against a fake Omnigraph and a fake LiteLLM over HTTP: fusion, the collapse rules, the Dutch weighting, degraded modes, snapshot pinning of every call, the caches, deadlines, the answer caps, `read`, the MCP transport rules, readiness, metrics and a sentinel that must never reach the log. [test-brain-tools-mutation.sh](../../../../scripts/test-brain-tools-mutation.sh) breaks 22 of those rules one at a time and requires each break to fail the suite, and the unmodified code to pass. [test_brain_tools_real_server.py](../../../../scripts/test_brain_tools_real_server.py) (`BRAIN_TOOLS_REAL_SERVER=1`) starts the pinned `omnigraph-server` with the working bundle and synthetic rows, runs brain-tools against it as `act-brain-reader`, and checks readiness, every `p1` leg, a pinned snapshot, `p0` against the stored queries invoked directly, `read` and MCP. Pre-commit runs all three when the code, the tests or `brain.retrieval.gq` change; CI runs the first two in `e2e / Lint & static validation` and the third in `e2e / Omnigraph bundle rehearsal`.

### Monitoring and failures

`VMServiceScrape/brain-tools` scrapes `:8081/metrics`: `brain_tools_calls_total{tool,surface,outcome}`, `brain_tools_latency_seconds{tool,surface}` (histogram), `brain_tools_searches_total{profile,mode}`, `brain_tools_upstream_requests_total{upstream,outcome}`, `brain_tools_catalog_complete`, `brain_tools_catalog_missing_queries`, `brain_tools_embedding_contract_ok`, `brain_tools_response_chars{tool}`, the cache gauges and `brain_tools_build_info`.

| Alert | Fires when |
|---|---|
| `BrainToolsDown` | The metrics endpoint is down or missing for 10 minutes |
| `BrainToolsCatalogIncomplete` | Omnigraph does not answer the catalog read, or a needed stored query is missing, for 10 minutes |
| `BrainToolsSearchSlow` | Search p95 over 3 seconds for 15 minutes |
| `BrainToolsUpstreamErrors` | Over 5% of requests to Omnigraph or LiteLLM fail for 15 minutes (at least 20 requests) |
| `BrainToolsDegraded` | Over 10% of `p1` searches ran keyword-only for 30 minutes (at least 5 searches): the sign that `tei-embeddings` is starved |
| `BrainToolsEmbeddingContractMismatch` | The contract and the schema disagree, or the schema cannot be read, for 15 minutes |
| `BrainToolsKeyBudgetNearlySpent` | The `brain-tools` key spent 80% of its USD 1 for 30 days |

First checks: `kubectl -n ai logs deploy/brain-tools --tail=50`, and `kubectl -n ai exec deploy/brain-tools -- wget -qO- http://127.0.0.1:8081/readyz`, which names missing queries and the contract verdict.

## Company meetings (`webgrip` and client graphs)

**One graph per client.** Omnigraph permissions stop at the graph and branch. There is no row-level security, so a `client` property would not keep clients apart. Every client graph shares [meetings.pg](../../../../kubernetes/apps/ai/omnigraph/app/bundle/meetings.pg) and [meetings.gq](../../../../kubernetes/apps/ai/omnigraph/app/bundle/meetings.gq). Each gets its own policy file and its own client actor. `main` must be protected.

**Validator.** [validate_omnigraph_policies.py](../../../../scripts/validate_omnigraph_policies.py) runs in pre-commit and in CI (`e2e / Lint & static validation`). It fails when:

- a graph has no policy (a graph with no policy is readable by every valid token);
- a client graph leaves `main` unprotected;
- one actor is granted on two client graphs, unless it is one of the allow-listed operators `act-admin`, `act-ryan` or `act-ingest`.

[test-validate-omnigraph-policies.sh](../../../../scripts/test-validate-omnigraph-policies.sh) is its mutation test.

### Ingest a meeting

1. Extract the meeting with the LiteLLM model `meeting-extract` (Fireworks `gpt-oss-120b`, temperature 0). Send [omnigraph_meeting_extraction.prompt.txt](../../../../scripts/omnigraph_meeting_extraction.prompt.txt) as the system message, the raw notes as the user message, and [omnigraph_meeting_extraction.schema.json](../../../../scripts/omnigraph_meeting_extraction.schema.json) as `response_format` `{"type":"json_schema","json_schema":{"name":"meeting_extraction","strict":true,"schema":…}}`. Save the message content as `extraction.json`. A short meeting costs about USD 0.001. If Fireworks fails, LiteLLM's `default_fallbacks` sends the notes to `deepseek-chat`; pass `"disable_fallbacks": true` in the request body when a client's notes must not leave Fireworks.
2. Run `just omnigraph-ingest-meeting webgrip extraction.json notes.txt`. The converter rejects:
   - quotes that are not verbatim in the notes;
   - owners who are not attendees;
   - bad dates or enum values.

   It then builds opaque ids with the graph's HMAC key (`secret/omnigraph/<graph>-hmac`) and loads the meeting as `act-ingest` onto a new branch, `ingest/<random>`.
3. Review the branch with the printed `commit list` command. Merge it with the printed `branch merge` command, which runs as you.

A load to `main` is refused. A failed load can leave an empty branch behind: delete it with `omnigraph branch delete <branch> --yes`.

Search is case-sensitive until a graph's first nightly optimize after its first ingest builds the full-text index. Merged passages and decisions get their vectors at the same nightly restart; until then `recall_notes` and `recall_decisions` rank them on keywords only.

### Add a client

In one commit:

1. Add `client-<name>` to [cluster.yaml](../../../../kubernetes/apps/ai/omnigraph/app/bundle/cluster.yaml) with `meetings.pg` and `meetings.gq`.
2. Add `client-<name>.policy.yaml`, copied from `webgrip.policy.yaml`, and drop its `explorers` and `glide` groups and their rules. `act-explorer` and `act-glide` are each one identity across graphs; keeping either on two client graphs fails the validator. Add a `client` group for `act-client-<name>` with `read` on `branch_scope: protected` and `invoke_query`.
3. Add the new policy file to the ConfigMap generator.
4. Create a new ExternalSecret and PushSecret pair for the client's token and its HMAC key, and add the token to the aggregator.

The validator must pass.

Graph ids and branch names can be probed by any valid token: an existing name answers 403, a missing one 404. Use an opaque graph id if the client list itself is confidential.

The component that knows which client a question is about holds that client's token. No agent should hold two client tokens.

### Forget a meeting

1. On a branch, run `forget_meeting_children` and then `forget_meeting`, and merge.
2. The meeting is then gone from `main`, but time travel, the change feed and the data files still hold it.
3. To destroy it, scale the deployment to 0 and run a maintenance pod on the PVC:
   - `omnigraph optimize --cluster file:///var/lib/omnigraph/state --graph <g>`
   - `omnigraph cleanup --keep 1 --confirm --cluster file:///var/lib/omnigraph/state --graph <g>`
4. Scale back to 1.

Older snapshots return an error afterwards and change-feed cursors get `410`. Deleted ids survive in index pages, which is why ids are HMAC-opaque. Backups keep the content for up to 7 days.

### Forget a client

In one commit, remove:

- the graph and its policy from `cluster.yaml`;
- the policy file and its generator entry;
- the client's token and HMAC key.

In the same commit, add `graph.client-<name>` to [approved-deletions](../../../../kubernetes/apps/ai/omnigraph/app/bundle/approved-deletions).

The bootstrap approves exactly that deletion, and apply removes the graph directory. Without the approval line the pod refuses to start: an unapproved apply would drop the policy and keep serving the graph to every token.

Remove the approval line in a later commit. Delete the OpenBao entries by hand. Backups expire after 7 days.

## Embeddings and recall

Every graph embeds text with `granite-embedding-97m-multilingual-r2` (384 dimensions, Dutch and English in one space). The chain is Omnigraph → LiteLLM (`granite-embedding-97m-multilingual-r2`) → `tei-embeddings` in namespace `ai`.

- **Model server.** `tei-embeddings` runs Text Embeddings Inference `cpu-1.9.4` on the ONNX Runtime backend. The `fetch-model` init container downloads the pinned revision from Hugging Face into the `tei-embeddings-models` volume and checks every file against [model.sha256](../../../../kubernetes/apps/ai/tei-embeddings/app/model/model.sha256); a mismatch stops the pod. After the first start it only re-verifies. The pod's only internet egress is HTTPS to Hugging Face hosts (`tei-embeddings-model-fetch`, a `toFQDNs` CiliumNetworkPolicy on `huggingface.co` and up to three label levels under `hf.co`), so a download that redirects to a CDN outside those domains times out in `fetch-model`. `--max-batch-tokens 1024` keeps it under 700Mi; longer inputs are truncated to their first 1024 tokens. Only LiteLLM pods may call it (`tei-embeddings-litellm-only`); the `observability` namespace may scrape `/metrics`. Alert: `TeiEmbeddingsDown`.
- **Key.** Omnigraph authenticates to LiteLLM with the virtual key `omnigraph-embeddings`, generated in-cluster by the `omnigraph-embed-key` ExternalSecret and registered by the `omnigraph-embed-key-register` Job: embedding model only, USD 1 per 30 days, 3000 requests per minute. The Job is idempotent: it looks the key up with the key itself, updates it when it drifted, and when the Secret holds a key LiteLLM does not know it deletes whatever key still holds the `omnigraph-embeddings` alias before registering the new one. The server refuses to start without `OMNIGRAPH_EMBED_API_KEY`, so the Secret must exist before the pod restarts. Rotate by deleting the `omnigraph-embed-key` Secret and the `omnigraph-embed-key-register` Job: ESO generates a new key, Reloader restarts Omnigraph, and the recreated Job revokes the old key.
- **Schema.** Each vector records its source and model, for example `embedding: Vector(384)? @embed("body", model="granite-embedding-97m-multilingual-r2")`. Queries fail fast when the provider serves another model. Changing the source or model is not an in-place migration: add a new property, backfill it, then drop the old one. The vectors are nullable and have no ANN `@index`: with an index, `optimize` fails (`KMeans cannot train 1 centroids with 0 vectors`) whenever a type's rows have lost all their vectors, which would stop the pod. `nearest()` scans every row instead, which is fast at this size.
- **Vectors.** Loads and mutations do not embed, and a merge load of a row without its vector clears the vector. The two importers therefore bring their own ([Write-time vectors](#write-time-vectors)), the distiller writes topic vectors itself, and the init container fills some of the rest at every start (see [Startup backfill](#startup-backfill)).
- **Contract.** The ConfigMap `omnigraph-embedding-contract` ([contract.json](../../../../kubernetes/apps/ai/omnigraph/embed-step/app/contract.json)) states the model, the dimensions, the text format (`type: <Type>` then `<field>: <value>` on the next line) and that stored vectors are L2-normalised. Writers that bring their own vectors read it, so every vector of a type lives in one space. [test_omnigraph_embedding_contract.py](../../../../scripts/test_omnigraph_embedding_contract.py) fails when it disagrees with the `@embed` models and dimensions in the schemas, the provider in `cluster.yaml` or the init container's `OMNIGRAPH_EMBED_MODEL`, and runs the pinned `omnigraph embed` against a recording fake embedder to prove the text format and the normalisation. `--self-test` breaks each input in turn and requires the test to fail. It runs in pre-commit next to the rehearsal and in CI. Measured with the pinned 0.11.0 CLI: `omnigraph embed` sends one row per request with `dimensions` set.
- **Queries.** `recall_notes` on `memory` and `brain`, `recall_passages` on `brain`, and `recall_notes` and `recall_decisions` on `webgrip` rank by `rrf(nearest(...), bm25(...))`. Rows without a vector still rank on keywords.

### Startup backfill

The init container fills missing vectors after `cluster apply` and before `optimize`, within fixed limits so that a restart never waits on a large backlog again. On 2026-09-28 an uncapped fill of 16,897 new passages kept every graph offline for about 2 hours (VIK-1348).

- It exports every type named in an `@embed` on `main` of every graph and keeps the rows with source text and no vector.
- It fills the types with the fewest missing rows first, so one large backlog cannot starve the others.
- Per type it takes at most `OMNIGRAPH_BACKFILL_MAX_ROWS` (500) rows, in parts of `OMNIGRAPH_BACKFILL_PART_ROWS` (100): each part is embedded under `timeout` and loaded back with `--mode merge` in its own commit. A failed part is logged and skipped.
- It stops starting parts once `OMNIGRAPH_BACKFILL_DEADLINE_SECONDS` (150) have passed since the backfill began, and kills the embedding of a part that runs past it.
- The window starts at an offset that moves every day, so a row that always fails cannot hold the same place at the head of the queue.

At `tei-embeddings`' speed on worker-2 (about 1,000 tokens a second, about 3 passages a second) a start fills about 400 passages. A restart with 20,001 vectorless passages served after 152 seconds in the drill below.

Log lines, searchable in VictoriaLogs with `namespace:ai container:apply-and-optimize "vector backfill"`:

| Line | Meaning |
|---|---|
| `vector backfill embedded <n> <graph> <type> rows into <target>` | Filled this start |
| `vector backfill capped: <n> <graph> <type> rows left for writers` | Still without a vector after this start |
| `vector backfill skipped a part of <n> <graph> <type> rows: ...` | That part failed or was killed at the deadline |
| `vector backfill skipped: <url> is not answering` | LiteLLM or `tei-embeddings` was down; nothing was filled |

Rows still without a vector rank on keywords only. Until the importers write their own vectors (brain retrieval RFC, P3), a large import is filled over several nights. To fill a known large backlog in one go, raise the three variables on the `apply-and-optimize` init container for one restart in a quiet hour, and put them back afterwards; the pod serves nothing while it fills.

**Drill.** `mise exec -- python3 scripts/omnigraph_rehearsal.py backfill-drill` seeds 20,000 vectorless passages into a throwaway cluster, restarts it through the working `bootstrap.sh` against a fake embedder throttled to 1,000 tokens a second, and fails when serving takes more than 180 seconds. Run it after changing the backfill or its variables. It takes about 3 minutes.

**Monitoring.** `OmnigraphUnreachable` (blackbox, 10 minutes) fires when the init container runs too long. The importers count their own vectorless rows ([Write-time vectors](#write-time-vectors)).

### Write-time vectors

The vault and Forgejo importers embed what they write, so a new or edited note or document is searchable by meaning as soon as its run lands, not after the next 03:15 restart. The startup backfill has not filled `brain` `Passage` rows since 2026-09-29 (VIK-1404), so this is also the only path that heals them.

**Embed step.** [embed_step.py](../../../../kubernetes/apps/ai/omnigraph/embed-step/app/embed_step.py) ships in the fixed-name ConfigMap `omnigraph-embed-step` and runs as the `embed` container between `plan` and `apply`, with the `omnigraph-embeddings` LiteLLM key (`omnigraph-embed-key` Secret).

- It fills `embedding` on every `Note` and `Passage` row in the plan's load files and heal files, in the text format of the [embedding contract](../../../../kubernetes/apps/ai/omnigraph/embed-step/app/contract.json): `type: <Type>` then `<field>: <value>`, the value trimmed with the contract's white-space set (never Python's bare `strip()`), cut to 8,000 characters. TEI reads only the first 1,024 tokens anyway; 8,000 characters is well past that and keeps the request small. Obsidian chunks (1,200 characters) and forge chunks (1,500) fit whole. A row with no text gets no vector and is not counted as missing.
- Vectors are L2-normalised and written with 8 significant digits, which keeps cosine at 0.99999994 or more and the files small. The planners count about 6 KB per vector when they split load files.
- Batches of 4 inputs, paced to 300 tokens a second from LiteLLM's reported usage, so chat and search embeddings keep most of `tei-embeddings`' capacity (about 1,000 tokens a second). TEI works through a request's inputs in turn, and a search that arrives meanwhile waits behind them: with batches of 16 (about 5,600 tokens) the TEI queue time p95 rose from about 3 ms to 4 s during the first heal on 2026-09-30; 4 inputs keep that wait near 1.4 s. Batch size does not change the vectors.
- Fail-soft: on a LiteLLM error (one `429` with a short `retry-after` is waited out) or at its deadline, it stops embedding. Changed rows are still written, without a vector, and heal rows are dropped; the next run heals them. The log says `embedding skipped: <n> rows written without a vector and <m> heals deferred (<reason>)`.
- JSONL is split on `\n` only: Python's `splitlines()` also splits on U+2028 and U+0085, which JSON strings carry unescaped.

**Heal mode.** Each run the planner also picks its own rows that have text and no vector, oldest first: at most 1,500 for forge-import and 300 for vault-import. It never heals a row the same run rewrites or deletes. Healed rows are merge-loaded with their stored text, `createdAt` and `updatedAt`, so a heal never looks like an edit.

**Writes retry only `read_set_conflict`.** [omnigraph_write.sh](../../../../kubernetes/apps/ai/omnigraph/embed-step/app/omnigraph_write.sh) wraps every delete and load: a 409 `read_set_conflict` (another writer's commit landed while this one prepared) is retried up to 8 times with 200 ms doubling backoff and jitter. `key_conflict`, a 503 (recovery required), a 413 or a refusal fail at once, and the failure line names the class, never the server's error text. The apply line reports `conflict_retries`.

**Gauge and alerts.** The `report` container pushes, per writer and type, to `vmagent-vmagent.observability:8429` with `job="omnigraph-embed-step"`:

| Series | Meaning |
|---|---|
| `omnigraph_embed_rows_missing{writer,type}` | The writer's rows still without a vector after the run: not yet healed, deferred heals and changed rows written without one |
| `omnigraph_embed_oldest_missing_age_seconds{writer,type}` | Age of the oldest of those rows |
| `omnigraph_embed_run_rows{writer,outcome}` | `embedded`, `skipped`, `healed`, `heal_dropped`, `textless` in the last run |
| `omnigraph_embed_run_tokens`, `omnigraph_embed_run_paced_seconds`, `omnigraph_embed_last_report_timestamp_seconds` | Per writer |

A push that fails is logged (`embed report not pushed`) and never fails the import. Pushed samples leave instant queries after about 5 minutes, so alerts and panels read `last_over_time`. `OmnigraphVectorsBacklog` fires when a writer has left more than 500 rows without a vector for 6 hours; `OmnigraphVectorsReportStale` when a writer has not reported for 3 hours. Grafana, *Brain retrieval quality*: vectorless rows, oldest vectorless row, the last run's outcomes and TEI queue time p95.

**Tests.** [test_omnigraph_embed_step.py](../../../../scripts/test_omnigraph_embed_step.py) covers the contract text, normalisation and precision, batching, pacing, the deadline, fail-soft, the report and the retry helper against a fake `omnigraph`. The importer suites run the embed step between plan and apply on their simulated graphs. [test-omnigraph-writers-mutation.sh](../../../../scripts/test-omnigraph-writers-mutation.sh) breaks 25 of these rules one at a time (the trim set, normalisation, precision, batch size, heals without a vector, `splitlines()`, pacing, the deadline, fail-soft, which conflicts are retried, the changed-chunk diff, the heal cap and its exclusions, the vector allowance, a prune missing a chunk, a kept renamed note, orphaned shadows, the chunk cap and size, relinking, fenced headings) and requires each to fail, and the unmodified code to pass. [test_omnigraph_writers_real_server.py](../../../../scripts/test_omnigraph_writers_real_server.py) (`OMNIGRAPH_WRITERS_REAL_SERVER=1`) runs both importers' real `snapshot.sh` and `apply.sh` against the pinned server: a vault import with vectors, a second run that writes nothing, a rename pruned in one mutation, a prune that misses one chunk refused, and a node-only heal that keeps the passage's `PassageOf` edge. Pre-commit runs the mutation test and the real-server test; CI runs all of them.

## Merge conflicts

Tested 2026-09-28 against a local v0.11 graph. When `main` and a branch both changed the same entity since the branch was made, `branch merge` refuses the whole merge and names each conflict, for example `merge conflicts: node type 'Note', entity id 'n1' (divergent_update)`. Nothing is partly merged.

The review UI does this per row with **Keep branch** and **Keep main** (see [Review mode](#review-mode)). By hand:

1. Decide the value you want for each named entity.
2. Make the row identical on both sides. To keep the branch's version, write the branch's full row on `main` as yourself (`act-ryan`). To keep `main`'s version, write `main`'s full row on the branch, or put the branch row back to its value at the fork. A value that matches neither side, even one differing in a single property, is refused again: the unit is the whole row.
3. Merge again. Entities that now match on both sides no longer conflict, and the rest of the branch lands.

Merging `main` into the branch first (`branch merge main --into <branch>`) works and makes the later merge a fast-forward, but it meets the same conflicts. If a branch has many conflicts, delete it and redo the work on a fresh branch from `main`. v0.11 has no rebase. The full conflict matrix and the review design are in the [branch workflow RFC](../rfc/rfc-omnigraph-branch-workflow.md).

## Known v0.11 limits

- **Schema changes need a graph with only `main`.** A bundle change that alters a graph's schema cannot be applied while that graph has any other branch: `cluster apply` fails, the init container stops and every graph is down. Before pushing a schema change, merge or delete open branches (agent proposals, `ingest/*` review branches). `omnigraph cluster plan` reports `schema_preview_unavailable` for a graph in that state.
- **One writer.** Maintenance commands must not run beside the server.
- **Write limit.** At most 8,192 rows or 32 MiB per touched type per commit. Split larger loads. An HTTP request body is capped at 32 MiB (413 `length limit exceeded`), which binds first when rows carry vectors: about 3,200 passages with full-precision floats, about 4,800 with 8 significant digits. Row 8,193 of one type answers 413 with a structured `resource_limit`.
- **Concurrent writers are not serialised.** A write that sees another commit land on the branch while it prepares answers 409 with `read_set_conflict` and writes nothing. Retry that case only, with backoff (200 ms doubling, jitter, 6 to 8 attempts). A 409 `key_conflict` (an `append` or strict insert of an existing id) never succeeds on retry, and a 503 means recovery is required: fail and let the next run replan. Measured 2026-09-29 with three writers: 2–7% of loads and most contended deletes got the conflict; with retries every load landed.
- **Deletes name ids.** Mutation predicates take only comparison operators, so `delete Passage where @id starts_with "..."` does not parse. A prune lists every passage id; one missed passage fails the whole mutation with `@card violation on edge PassageOf`.
- **Empty commits.** A merge load of rows identical to what is stored still writes a commit with no changes. `rebuild-full-text-indexes` also writes a commit on `main`, as the operator actor.
- **Policy CLI.** `omnigraph policy validate` and `policy explain` error with "matches 2 policy bundles" when a cluster-scope bundle exists. Test policy against the live server instead.
- **Direct access.** Direct `--store`/`--cluster` access bypasses Cedar policy. Access to the pod or PVC is effectively admin.
- **Branch names with `/`.** Branch names containing `/` must be URL-encoded (`%2F`) in `DELETE /branches/{name}`.

## Upgrade

1. Read the release notes.
2. Run the brain retrieval eval gate on the old version and keep its numbers (`kubectl -n ai create job --from=cronjob/omnigraph-brain-eval-gate omnigraph-brain-eval-gate-manual`, once RFC P2 has shipped it). v0.11 behaviour the retrieval depends on, such as the ranked-first rule, can change silently.
3. Scale the deployment to 0.
4. Snapshot the Longhorn volume.
5. Run `omnigraph upgrade --check`, then `omnigraph upgrade`, against the PVC from a maintenance pod using the new image.
6. Bump the image and the mise CLI pin in the same commit. The rehearsal refuses a commit where the two differ, and it runs the new CLI over the bundle, so run `mise install` first.
7. Run the eval gate again and compare with step 2 before relying on the new version.

From v0.12, `optimize` and `cleanup` can run beside live writers. At that point the 03:15 restart can become an in-place CronJob.
