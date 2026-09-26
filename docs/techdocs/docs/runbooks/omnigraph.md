# Omnigraph

Omnigraph v0.11 runs one server in namespace `ai` with three graphs: `memory` (shared agent memory), `brain` (Ryan's second brain) and `webgrip` (internal company meetings). Every graph, schema, stored query and permission rule is declared in the [bundle](../../../../kubernetes/apps/ai/omnigraph/app/bundle/). Push a change to the bundle and the pod applies it on its next start.

## How it runs

- One pod, `strategy: Recreate`, data on the Longhorn PVC `omnigraph-state` with `file://` storage. Garage is deliberately not used: Omnigraph relies on S3 `If-None-Match`/`If-Match` conditional writes, it is not qualified on Garage, and an ignored precondition would corrupt data silently.
- The init container runs [bootstrap.sh](../../../../kubernetes/apps/ai/omnigraph/app/bundle/bootstrap.sh):
  1. Copies the bundle out of the ConfigMap, because Omnigraph refuses bundle files reached through symlinks.
  2. Imports state on first boot.
  3. Refuses to start if the plan contains an unapproved deletion.
  4. Applies the bundle.
  5. Optimizes every applied graph and rebuilds full-text indexes when optimize reports stale coverage.
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
| `act-brain-agent` | `brain`: read and write on proposal branches only; Ryan merges |
| `act-ingest` | `webgrip` (and future client graphs): create unprotected branches and load onto them. It cannot read anything |
| `act-explorer` | `brain`, `memory` and `webgrip`: read and export on any branch, nothing else. Only the explorer's proxy holds it |

Each token is generated in-cluster by the `omnigraph-actor-tokens` ExternalSecret, pushed to OpenBao at `secret/omnigraph/<actor>` (field `token`), and assembled into the server's `tokens.json` by the `omnigraph-tokens` ExternalSecret.

Add an actor by creating a new generator ExternalSecret and PushSecret pair, then adding one line to the aggregator. Do not add keys to `omnigraph-actor-tokens`. It is generate-once, so a new key only appears after its Secret is deleted, and deleting it rotates every existing token.

Give an in-cluster consumer its token with an ExternalSecret against the `openbao` store at `omnigraph/<actor>`. Also allow its namespace in the `omnigraph-ingress` NetworkPolicy.

## Explorer

`https://graph.<domain>` is a read-only visual explorer ([webgrip/omnigraph-explorer](https://forgejo.webgrip.dev/webgrip/omnigraph-explorer), which documents the app itself). It runs as `omnigraph-explorer` in namespace `ai`.

- **Who gets in.** The route sits behind the gateway's OIDC `SecurityPolicy` with its own Authentik client, `omnigraph-explorer` ([ADR-0060](../adr/adr-0060-gateway-oidc-for-apps-without-a-login.md)). Authentik only issues a token to members of `knowledge-graph-viewers`, the group of the `knowledge-graph-view` capability. That capability is granted to Ryan by name, not through a role, because the explorer shows the brain and client meetings.
- **What it can do.** The pod serves the SPA and proxies `/og/*` to `omnigraph:8080`. The proxy adds `Authorization: Bearer <act-explorer>` itself, strips cookies, and forwards only `GET` on `healthz`, `branches`, `commits` and `schema`, plus `POST` on `export`. The browser never sees the token, and `act-explorer` is refused `change`, `branch_*` and `graph_list` by policy anyway.
- **Token.** `omnigraph-explorer-token` generates it and pushes it to `secret/omnigraph/explorer`. The aggregator adds it to `tokens.json` and the explorer reads it back with `omnigraph-explorer-upstream`. Rotate it by deleting the `omnigraph-explorer-token` Secret; Reloader restarts both pods.
- **Graphs in the picker.** `OMNIGRAPH_EXPLORER_GRAPHS` on the Deployment. A graph also needs an `explorers` group and `explorers-read-and-export` rule in its policy, or every request answers 403. `OMNIGRAPH_EXPLORER_HEAVY_TYPES` (default `Chunk`) lists node types the explorer skips unless asked, together with every edge that touches them.
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

**Not yet usable**

- `Chunk.embedding` needs precomputed vectors and no embedding model is configured, so leave `Chunk` unused.

Agents holding `act-brain-agent` work on a branch, for example `agent/<task>` created from `main`. You review and merge. Branch scoping limits writes, not reads: an agent can read everything on `main` through a branch it creates. Keep it away from anything it should not see.

The cookbook's demo seed (fictional "Alex Chen") is not loaded. To explore it, load it onto a throwaway branch and delete the branch afterwards.

## Company meetings (`webgrip` and client graphs)

**One graph per client.** Omnigraph permissions stop at the graph and branch. There is no row-level security, so a `client` property would not keep clients apart. Every client graph shares [meetings.pg](../../../../kubernetes/apps/ai/omnigraph/app/bundle/meetings.pg) and [meetings.gq](../../../../kubernetes/apps/ai/omnigraph/app/bundle/meetings.gq). Each gets its own policy file and its own client actor. `main` must be protected.

**Validator.** [validate_omnigraph_policies.py](../../../../scripts/validate_omnigraph_policies.py) runs in pre-commit and in CI (`e2e / Lint & static validation`). It fails when:

- a graph has no policy (a graph with no policy is readable by every valid token);
- a client graph leaves `main` unprotected;
- one actor is granted on two client graphs, unless it is one of the allow-listed operators `act-admin`, `act-ryan` or `act-ingest`.

[test-validate-omnigraph-policies.sh](../../../../scripts/test-validate-omnigraph-policies.sh) is its mutation test.

### Ingest a meeting

1. Have Claude read the raw notes and write an extraction JSON in this shape: `{"meeting":{"title","held_on","kind","summary"},"attendees":[{"name","side","role"?,"email"?,"absent"?}],"decisions":[{"statement","topic","quote","agreed_with":[names],"status"?}],"action_items":[{"title","owner"|null,"due"?,"quote"}]}`. Keep `quote` verbatim. `side` is `internal`, `client` or `third_party`.
2. Run `just omnigraph-ingest-meeting webgrip extraction.json notes.txt`. The converter rejects:
   - quotes that are not verbatim in the notes;
   - owners who are not attendees;
   - bad dates or enum values.

   It then builds opaque ids with the graph's HMAC key (`secret/omnigraph/<graph>-hmac`) and loads the meeting as `act-ingest` onto a new branch, `ingest/<random>`.
3. Review the branch with the printed `commit list` command. Merge it with the printed `branch merge` command, which runs as you.

A load to `main` is refused. A failed load can leave an empty branch behind: delete it with `omnigraph branch delete <branch> --yes`.

Search is case-sensitive until a graph's first nightly optimize after its first ingest builds the full-text index.

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

## Known v0.11 limits

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
