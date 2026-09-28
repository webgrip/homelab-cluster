# Omnigraph

Omnigraph v0.11 runs one server in namespace `ai` with three graphs: `memory` (shared agent memory), `brain` (Ryan's second brain) and `webgrip` (internal company meetings). Every graph, schema, stored query and permission rule is declared in the [bundle](../../../../kubernetes/apps/ai/omnigraph/app/bundle/). Push a change to the bundle and the pod applies it on its next start.

## How it runs

- One pod, `strategy: Recreate`, data on the Longhorn PVC `omnigraph-state` with `file://` storage. Garage is deliberately not used: Omnigraph relies on S3 `If-None-Match`/`If-Match` conditional writes, it is not qualified on Garage, and an ignored precondition would corrupt data silently.
- The init container runs [bootstrap.sh](../../../../kubernetes/apps/ai/omnigraph/app/bundle/bootstrap.sh):
  1. Copies the bundle out of the ConfigMap, because Omnigraph refuses bundle files reached through symlinks.
  2. Imports state on first boot.
  3. Refuses to start if the plan contains an unapproved deletion.
  4. Applies the bundle.
  5. Fills missing vectors on `main` of every graph (see [Embeddings and recall](#embeddings-and-recall)). A failure here is logged and skipped; it never stops the pod.
  6. Optimizes every applied graph and rebuilds full-text indexes when optimize reports stale coverage.
- The `omnigraph-maintenance-restart` CronJob restarts the pod at 03:15. In v0.11, `optimize` next to a live server blocks writes, so it only runs at startup.
- The PVC is enrolled in the `gitops-backup` Longhorn job (daily, 7 kept, offsite).
- Renovate never automerges Omnigraph (image or mise CLI). Minor releases change the storage format.

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

Each token is generated in-cluster by the `omnigraph-actor-tokens` ExternalSecret, pushed to OpenBao at `secret/omnigraph/<actor>` (field `token`), and assembled into the server's `tokens.json` by the `omnigraph-tokens` ExternalSecret.

Add an actor by creating a new generator ExternalSecret and PushSecret pair, then adding one line to the aggregator. Do not add keys to `omnigraph-actor-tokens`. It is generate-once, so a new key only appears after its Secret is deleted, and deleting it rotates every existing token.

Give an in-cluster consumer its token with an ExternalSecret against the `openbao` store at `omnigraph/<actor>`. Then open the network path on both ends, because namespace `ai` is default-deny and every pod in it carries its own egress allow: add the consumer to `omnigraph-ingress` (a `namespaceSelector` for another namespace, a `podSelector` for a pod in `ai`), and give a pod in `ai` an egress rule to `app: omnigraph` on 8080. Today only LiteLLM (the `omnigraph_memory` and `omnigraph_brain` MCP bridges), the explorer, the vault importer and the gateway may connect. The full matrix is in [LiteLLM: network](../general/litellm.md#network-namespace-ai).

## Explorer

`https://graph.<domain>` is a read-only visual explorer ([webgrip/omnigraph-explorer](https://forgejo.webgrip.dev/webgrip/omnigraph-explorer), which documents the app itself). It runs as `omnigraph-explorer` in namespace `ai`.

- **Who gets in.** The route sits behind the gateway's OIDC `SecurityPolicy` with its own Authentik client, `omnigraph-explorer` ([ADR-0060](../adr/adr-0060-gateway-oidc-for-apps-without-a-login.md)). Authentik only issues a token to members of `knowledge-graph-viewers`, the group of the `knowledge-graph-view` capability. That capability is granted to Ryan by name, not through a role, because the explorer shows the brain and client meetings.
- **What it can do.** The pod serves the SPA and proxies `/og/*` to `omnigraph:8080`. The proxy adds `Authorization: Bearer <act-explorer>` itself, strips cookies, and forwards only `GET` on `healthz`, `branches`, `commits` and `schema`, plus `POST` on `export`. The browser never sees the token, and `act-explorer` is refused `change`, `branch_*` and `graph_list` by policy anyway.
- **Token.** `omnigraph-explorer-token` generates it and pushes it to `secret/omnigraph/explorer`. The aggregator adds it to `tokens.json` and the explorer reads it back with `omnigraph-explorer-upstream`. Rotate it by deleting the `omnigraph-explorer-token` Secret; Reloader restarts both pods.
- **Graphs in the picker.** `OMNIGRAPH_EXPLORER_GRAPHS` on the Deployment. A graph also needs an `explorers` group and `explorers-read-and-export` rule in its policy, or every request answers 403. `OMNIGRAPH_EXPLORER_HEAVY_TYPES` (default `Chunk`) lists node types the explorer skips unless asked, together with every edge that touches them. On `brain` the passage type is `Passage`, so add it to the list.
- **Monitoring.** `blackbox-omnigraph-explorer` reads `memory` branches through the pod (nginx, proxy, token and policy in one request). `blackbox-omnigraph-explorer-gate` checks that an anonymous request to the route is sent to Authentik. The alerts are `OmnigraphExplorerBackendDown` and `OmnigraphExplorerGateOpen`.

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

`brain` has a second bridge in the same pod: server `omnigraph_brain`, access group `brain`, running as `act-brain-agent` with `OMNIGRAPH_BRAIN_TOKEN` from the `litellm-omnigraph-brain` Secret (`secret/omnigraph/brain-agent`). Its tools carry the prefix `omnigraph_brain-`. Under the current policy `act-brain-agent` reads only on unprotected branches, so a tool call must first create a branch from `main` (`omnigraph_brain-branches_create`) and query that branch; a query on `main` answers 403.

Two keys see both groups: `open-webui` for [Open WebUI](open-webui.md) and `claude-code` for Claude Code on Ryan's workstation (setup in [Open WebUI: Claude Code](open-webui.md#claude-code)).

## Second brain (`brain`)

The schema is the ModernRelay `second-brain` cookbook. Two additions: `Note.content` and `Artifact.content` are indexed for full-text search, and [brain.capture.gq](../../../../kubernetes/apps/ai/omnigraph/app/bundle/brain.capture.gq) adds `capture_note`, `capture_task`, `capture_person` and `set_task_status`, which take the optional fields the cookbook's `add_*` mutations leave out.

```bash
omnigraph mutate capture_note --profile brain --params '{"slug":"nt-bike-chain","name":"Bike chain","kind":"idea","content":"Replace the chain before winter","when":"2026-09-25"}'
omnigraph query notes_recent --profile brain
```

Conventions that used to live in the cookbook's comments:

**Records and ids**

- Slugs carry a type prefix: `per-` people, `org-` organizations, `pl-` places, `ev-` events, `nt-` notes, `tk-` tasks, `proj-` projects, `area-` areas, `goal-` goals, `hab-` habits, `med-` media, `art-` artifacts. `per-self` is you: create it first with `relation: self`.
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

One pod runs four steps in order. Each step logs one line of counts or one error line, never note names, contents or client terms.

1. `clone` shallow-clones `ryangr0/obsidian-vault` over SSH from `forgejo-ssh.forgejo.svc.cluster.local`. It uses the deploy key in the `omnigraph-vault-import-deploy-key` Secret and checks the host key against the pinned [known_hosts](../../../../kubernetes/apps/ai/omnigraph/vault-import/app/known_hosts).
2. `snapshot` reads every `obsidian/` note on `brain/main`, with its outgoing `RelatedNote` edges, using the ad-hoc queries in [snapshot.gq](../../../../kubernetes/apps/ai/omnigraph/vault-import/app/snapshot.gq).
3. `plan` runs [vault_import.py](../../../../kubernetes/apps/ai/omnigraph/vault-import/app/vault_import.py). It compares the vault with the snapshot and writes a delete mutation and merge-load files for the difference only.
4. `apply` runs the delete mutation, then the loads, onto `main`.

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

**Only changes are written.** The importer keeps no state of its own. Every run recomputes the difference between the vault and what `brain` holds under `obsidian/`, and writes only that difference. This is simpler than a stored commit marker, and a failed run repairs itself on the next one. It is also required: a merge load replaces the whole row and clears its vector, so reloading unchanged notes every 15 minutes would keep every vault note without an embedding.

- A new or changed note is merge-loaded.
- A note whose vault links changed has its outgoing `RelatedNote` edges deleted, then reloaded. A merge load does not deduplicate edges, so an edge is never loaded without that delete first. Edges from a vault note to a note outside `obsidian/` (added by an agent or by hand) are reloaded with it.
- An `obsidian/` note that is no longer in the vault is deleted. Its edges go with it.

The vault owns everything under `obsidian/`. An edit made to such a note in the graph is overwritten on the next run when the file differs. Capture your own notes under another prefix, such as `nt-`.

A vault without importable notes never deletes anything: the plan step refuses and the run fails.

**Embeddings.** Loads do not embed. A new or changed note ranks on keywords only until the 03:15 restart fills its vector (see [Embeddings and recall](#embeddings-and-recall)). An import right after 03:15 waits almost a day. The full-text index is rebuilt at the same restart.

**Write limits.** Load files are split at 2,000 rows or 16 MiB, below the per-commit limit.

### Client notes are tagged, not withheld

Owner decision 2026-09-27: client content may reach Claude and Fireworks under their DPAs ([personal archive RFC](../rfc/rfc-personal-archive.md), D4), so the whole vault is imported. An optional list of client terms (names, company names, domains) in OpenBao `secret/omnigraph/vault-client-terms`, field `terms`, one term per line, reaches the importer through the `omnigraph-vault-client-terms` ExternalSecret.

- A note whose path or text (frontmatter, tags and body) contains any term, case-insensitive and on word boundaries, gets the tag `client`, so a question can include or exclude client material.
- Without the Secret, or with no terms in it, everything is imported untagged.
- The counts line reports `tagged_client`. The terms themselves are never logged.
- The match is textual. A client note that never names a listed term stays untagged.

Deleting a note from `main` does not erase it from history. See [Forget a meeting](#forget-a-meeting) for destroying the data files.

### Setup (Ryan)

1. Create the private repo `ryangr0/obsidian-vault` on Forgejo and push the vault with the Obsidian Git plugin. Leave `.obsidian/` in or out, the importer skips it either way.
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
- `omnigraph not reachable or act-vault-import refused`: Omnigraph is restarting, or `act-vault-import` is not in `tokens.json` yet.
- `vault import failed`: the server refused the delete or a load batch.

`OmnigraphVaultImportStale` fires when the CronJob has had no successful run for 2 hours, or has never succeeded since it was created. It reads `kube_cronjob_status_last_successful_time` from kube-state-metrics. It fires until the setup above is done.

**Tests.** [test_omnigraph_vault_import.py](../../../../scripts/test_omnigraph_vault_import.py) covers the mapping, client tagging, the missing-terms path and the empty-vault guard with fixture vaults. It runs without network: `python3 scripts/test_omnigraph_vault_import.py`.

**Rotation.** Deleting the `omnigraph-vault-import-deploy-key` Secret generates a new key pair and pushes the new public key. Replace the deploy key on the repo. Deleting `omnigraph-vault-import-token` rotates the actor token. The aggregator picks it up within 15 minutes and Reloader restarts Omnigraph.

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
2. Add `client-<name>.policy.yaml`, copied from `webgrip.policy.yaml`, and drop its `explorers` group and rule. `act-explorer` is one identity across graphs; keeping it on two client graphs fails the validator. Add a `client` group for `act-client-<name>` with `read` on `branch_scope: protected` and `invoke_query`.
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
- **Vectors.** Loads and mutations do not embed. The init container fills the vectors that are missing on `main` at every start, so the 03:15 restart embeds what was merged that day. It exports each type named in an `@embed`, keeps the rows with source text and no vector, embeds them with `omnigraph embed` and loads them back with `--mode merge`. A merge load of a row without its vector clears the vector until the next start. If LiteLLM or `tei-embeddings` is down, the init container logs `vector backfill skipped` or `vector backfill for <graph> <type> failed` and starts anyway.
- **Queries.** `recall_notes` on `memory` and `brain`, `recall_passages` on `brain`, and `recall_notes` and `recall_decisions` on `webgrip` rank by `rrf(nearest(...), bm25(...))`. Rows without a vector still rank on keywords.

## Known v0.11 limits

- **Schema changes need a graph with only `main`.** A bundle change that alters a graph's schema cannot be applied while that graph has any other branch: `cluster apply` fails, the init container stops and every graph is down. Before pushing a schema change, merge or delete open branches (agent proposals, `ingest/*` review branches). `omnigraph cluster plan` reports `schema_preview_unavailable` for a graph in that state.
- **One writer.** Maintenance commands must not run beside the server.
- **Write limit.** At most 8,192 rows or 32 MiB per touched type per commit. Split larger loads.
- **Policy CLI.** `omnigraph policy validate` and `policy explain` error with "matches 2 policy bundles" when a cluster-scope bundle exists. Test policy against the live server instead.
- **Direct access.** Direct `--store`/`--cluster` access bypasses Cedar policy. Access to the pod or PVC is effectively admin.
- **Branch names with `/`.** Branch names containing `/` must be URL-encoded (`%2F`) in `DELETE /branches/{name}`.

## Upgrade

1. Read the release notes.
2. Scale the deployment to 0.
3. Snapshot the Longhorn volume.
4. Run `omnigraph upgrade --check`, then `omnigraph upgrade`, against the PVC from a maintenance pod using the new image.
5. Bump the image and the mise CLI pin in the same commit.

From v0.12, `optimize` and `cleanup` can run beside live writers. At that point the 03:15 restart can become an in-place CronJob.
