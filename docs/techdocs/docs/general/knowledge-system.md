# Knowledge system

How the second brain, agent memory and company knowledge fit together, and how to use them.
Operations (tokens, importers, upgrades, failures) live in the [Omnigraph runbook](../runbooks/omnigraph.md)
and the [Open WebUI runbook](../runbooks/open-webui.md). Epic: VIK-1259.

## In one paragraph

Knowledge lives in **Omnigraph**, a graph database with git-style branches, running in the cluster.
You and your AI assistants reach it through **LiteLLM**, which is the single gateway for models *and*
tools. Importers keep it fed from Obsidian and Forgejo, and a distiller reads every document and links
it to the topics, people, organisations, projects, places and areas it is about. Every AI client has its own identity with a
written policy: your own assistant writes straight in, background agents only propose on branches, and
**only you merge**. Every write is a commit, so anything can be traced and undone.

## The layers

```mermaid
flowchart LR
  subgraph Sources
    OB[Obsidian vault]
    FJ[Forgejo repos]
    MT[Meeting notes]
    ML[Mail, Slack, calls, docs]
  end
  subgraph Knowledge
    AR[(Archive: raw text<br/>planned)]
    OG[(Omnigraph<br/>memory · brain · webgrip)]
    DS[Distiller, hourly]
  end
  subgraph Doors
    CH[Open WebUI chat]
    CC[Claude Code]
    GL[Glide agents]
    EX[Explorer]
  end
  OB -->|vault importer, 15 min| OG
  FJ -->|forge importer, hourly| OG
  MT -->|just omnigraph-ingest-meeting| OG
  ML -.->|parked| AR
  AR -.->|distil| OG
  OG -->|documents| DS
  DS -->|topics and links| OG
  CH --> LL[LiteLLM<br/>models + MCP tools]
  CC --> LL
  GL --> LL
  LL --> OG
  EX -->|read-only| OG
```

| Layer | Holds | Good for | Status |
|---|---|---|---|
| **Archive** (raw data) | Every email, message, transcript and document, whole | "Find where X was said" | Parked, see the [personal archive RFC](../rfc/rfc-personal-archive.md) |
| **Documents** (in Omnigraph) | Notes, READMEs, docs, ADRs, issues and pull requests as the importers bring them, with their passages | "Find the note where I wrote about X" | Live |
| **Knowledge** (in Omnigraph) | Topics, people, organisations, projects, places and areas, linked to the documents that are about them, and topics linked to topics that appear together | "Everything I have on Kubernetes networking", "which notes and repos are about client X" | Live, built by the [distiller](../runbooks/omnigraph.md#distiller) |

The importers fill the documents layer; the distiller turns it into the knowledge layer. It asks a model
(Fireworks `gpt-oss-120b` through LiteLLM) what each document is about, matches the answer against what
the graph already has, and adds links under its own `derived/` namespace. It never edits a document.

Omnigraph does not replace the raw data. Short, self-written material (Obsidian notes, READMEs, ADRs,
issues) goes straight into the graph; long or bulk text belongs in the archive once it exists.

## The graphs

| Graph | What it is | Who writes `main` |
|---|---|---|
| `brain` | Your second brain: notes, people, tasks, projects, Forgejo, Obsidian | You, your chat and Claude Code, the Obsidian and Forgejo importers |
| `memory` | What AI agents learn across sessions | You (agents propose on branches) |
| `webgrip` | Company meetings: decisions and action items. Each client gets its own sealed `client-<name>` graph | You (meeting ingests land on `ingest/*` branches) |

## How things get in

| Source | How | Lands | You do |
|---|---|---|---|
| **Talking to it** | "Remember …" in the chat or Claude Code | `brain` `main`, at once; found by keyword at once, by meaning only after the 03:15 restart (see [How finding things works](#how-finding-things-works)) | Nothing |
| **Obsidian** | Obsidian Git pushes the vault to `webgrip/obsidian-vault`; the importer syncs every 15 minutes | `brain` `main`; `[[links]]` become links, daily notes become journal entries, notes matching a client term get the tag `client` | One-time setup: [Obsidian vault](../runbooks/omnigraph.md#obsidian-vault) |
| **Forgejo** | Hourly importer over every repo you can see | `brain` `main`: repos as projects, READMEs, `docs/`, ADRs as decisions, issues, PRs, people | One-time: a read-only token, see [Forgejo projects](../runbooks/omnigraph.md#forgejo-projects) |
| **Distiller** | Hourly, after the importers, over every new or changed note, artifact and project | `brain` `main`: `Topic` rows and links from documents to topics, people, organisations, projects, places and areas, all under `derived/` | Nothing |
| **Meeting notes** | `just omnigraph-ingest-meeting <graph> extraction.json notes.txt` | An `ingest/*` branch of `webgrip` or a client graph | Review and merge |
| **Glide agents** | Their own tools through LiteLLM | A `glide/<run>` branch of `memory`, `brain` or `webgrip` | Review and merge |
| **Mail, Slack, calls, documentation** | Through the archive | Archive first, distilled into the graph | Parked |

## How finding things works

Measured on 2026-09-28. The plan that fixes the gaps below is the
[brain retrieval RFC](../rfc/rfc-brain-retrieval.md).

`brain` holds 750 notes, 2,615 Forgejo documents (cut into 17,011 passages of at most 1,500
characters) and 2,544 topics. Two kinds of search exist in the graph:

- **By keyword** (`bm25`, `search`): sees a row the moment it is written. The analyzer is
  English: it lowercases, stems English words and drops English stopwords. Dutch words are not
  stemmed and Dutch function words ("de", "het", "welke") count as keywords, so a Dutch question
  can pull unrelated Dutch documents.
- **By meaning** (`nearest`): Dutch and English in one space, through the in-cluster embedding
  model. It only sees rows that have a vector, and it reads at most the first 1,024 tokens (about
  4,000–5,000 characters) of a text. Half of the Obsidian note text lies past that point.

Hybrid search that combines the two already exists as stored queries on `brain`: `recall_notes`,
`recall_passages` and `recall_topics`. **Your chat and Claude Code cannot call them by name.** The
LiteLLM MCP bridge (`@modernrelay/omnigraph-mcp` 0.10.0) only offers raw tools, such as `query`
with a hand-written query and `mutate`, so the model has to write the query language itself.
Cheap models often get that wrong, and `recall_notes` returns whole notes (tens of thousands of
tokens for ten results). Purpose-built brain tools (`search`, `read`, `about`, `connect`,
`recent`, `open_items`, `remember`) replace this; see the RFC.

When a row gets its vector:

| Row | Vector |
|---|---|
| New note, document, passage or capture | At the next omnigraph start (03:15 every night). Until then it ranks on keywords only |
| Edited Obsidian note or Forgejo document | The importer rewrites the whole row without a vector, and forge-import rewrites every passage of a changed document, so the edited item ranks on keywords only until 03:15 |
| Topic | At once: the distiller supplies the vector itself |

## How to use it

### Chat: `https://chat.<domain>`

1. Pick a model. The default, `chat-default`, is Fireworks MiniMax with the cheapest DeepSeek model as fallback; the Claude models stay selectable.
2. Under the message box, open the tools menu and switch on **Omnigraph**, once per chat.
3. Talk to it. You see a tool call each time it reads or writes the graph.

| You want to | Say |
|---|---|
| Capture | "Remember: the heat pump needs a service every 2 years, last done March 2026." |
| Track a promise | "Add a task: send Pieter the quote by Friday, I owe him." |
| Record a person | "Remember Jan: works at Client X, prefers calls." |
| Recall | "What do I know about Jan?" · "What have I promised people?" |
| Use your projects | "Which of my repos have open issues?" · "What do my ADRs say about secrets?" |
| Follow a topic | "Which notes and repos are about Magento?" · "What topics come up with Kubernetes?" |
| Review | "What did I save this week?" |

The chat's key sees `memory` and `brain` only. It cannot see `webgrip` or the Glide tools.

### Claude Code

Connect once (the key never prints):

```bash
export BAO_ADDR="$(just bao-addr)"
bao token lookup >/dev/null 2>&1 || bao login -method=oidc
claude mcp add --transport http --scope user omnigraph \
  "https://$(kubectl get httproute litellm -n ai -o jsonpath='{.spec.hostnames[0]}')/mcp/" \
  --header "Authorization: Bearer $(bao kv get -mount=secret -field=key litellm/keys/claude-code)"
```

`claude mcp list` should show `omnigraph ✔ Connected`. New tools load when a session starts, so
restart Claude Code once. Then ask in any session: "check my brain for …", "remember that …". The
key is tools-only (it cannot call models) with a small budget.

### Explorer: `https://graph.<domain>`

A read-only visual map of `brain`, `memory` and `webgrip`. Pick a graph at the top, search with `/`,
click a node to inspect it, press `F` to fit. It loads the whole graph into the browser at start (on
`brain` about 6,500 nodes; passages and distiller bookkeeping are skipped), so it opens on everything
at once, noise included. Opening on search and a node's neighbourhood instead is phase P8 of the
[brain retrieval RFC](../rfc/rfc-brain-retrieval.md). With only one or two nodes the camera jumps
while it loads (VIK-1296); it settles once there is real content.

### Review: `https://graph-review.<domain>`

The same app in review mode: an inbox of open branches, an exact merge preview, conflicts per row,
merge, reject and update branch. Only you get in. Details: [review
mode](../runbooks/omnigraph.md#review-mode).

### Terminal

`just omnigraph-login` caches your own token (`act-ryan`, the only identity that can merge) in
`~/.omnigraph/credentials`. After that the `omnigraph` CLI works against the `homelab` server, for
example `omnigraph branch list --server homelab --graph brain`.

### Glide agents

A Glide run reaches `memory`, `brain` and `webgrip` through the `omnigraph_glide_*` tools in LiteLLM.
It reads `main` freely and writes only on its own branch, `glide/<run>`. The cluster side is live; the
Glide side (handing each run its tools) is VIK-1300, specified in
[Glide runs on Omnigraph](../rfc/spec-glide-omnigraph.md).

## Branches and review

`main` is protected on every graph. What each writer may do:

| Writer | Identity | Writes | Merges |
|---|---|---|---|
| You (CLI) | `act-ryan` | Anywhere | Yes |
| Your chat and Claude Code | `act-brain-agent` | `brain` `main` directly | No |
| Obsidian importer | `act-vault-import` | Its own `obsidian/` notes on `brain` `main` | No |
| Forgejo importer | `act-forge-import` | Its own `forge/` rows on `brain` `main` | No |
| Distiller | `act-distill` | Its own `derived/` rows and `derived:` links on `brain` `main` | No |
| Glide agents | `act-glide` | Unprotected branches (`glide/<run>`) of all three graphs | No |
| Review mode | `act-review` | Any branch of all three graphs, on your click | Yes, on your click |
| In-cluster agents on `memory` | `act-agent` | Their own branches of `memory` | No |
| Meeting ingest | `act-ingest` | `ingest/*` branches; cannot read | No |
| Explorer | `act-explorer` | Nothing | No |

**Reviewing a branch** happens in review mode at `https://graph-review.<domain>`. From the terminal, as yourself:

```bash
omnigraph branch list --server homelab --graph brain
omnigraph commit list --server homelab --graph brain --branch glide/<run> --json
omnigraph branch merge glide/<run> --into main --server homelab --graph brain
omnigraph branch delete glide/<run> --server homelab --graph brain --yes
```

If `main` changed the same row since the branch was made, the merge is refused and names the conflicting rows. Review mode resolves them per row; by hand, write the value you want on `main`, then merge again; see [merge conflicts](../runbooks/omnigraph.md#merge-conflicts).

**Keep branches short-lived.** Any open branch on a graph blocks the next schema change to that graph,
and a failed schema apply stops every graph until it is fixed. Merge or delete branches instead of
letting them pile up. Details: [open `glide/*` branches block schema
changes](../runbooks/omnigraph.md#open-glide-branches-block-schema-changes).

## Safety

| Concern | How it is handled |
|---|---|
| Who can reach it | LAN only, through `envoy-internal`. Nothing is on the internet. |
| Who can log in | Authentik at the gateway. The chat also requires the `knowledge-graph-chatters` group, the explorer `knowledge-graph-viewers`; both hold only you. |
| What an AI may do | Its identity's policy, enforced by Omnigraph on every request, whatever the model is told. |
| Which tools a key sees | LiteLLM `object_permission.mcp_access_groups` per key: chat and Claude Code `memory` + `brain`; Glide runs `glide`. |
| Secrets | Generated in the cluster, stored in OpenBao, delivered by External Secrets. Never in git. |
| Mistakes | Every write is a commit. Find it with `commit list`, undo it with a follow-up write or by restoring from history. |

**Residual risks, stated plainly:**

- **Prompt injection.** Imported text (an issue, a doc, a note) can carry instructions aimed at the
  model. Your chat and Claude Code write `brain` `main` directly, so an injected instruction could add or
  change rows there. The commit history shows it and allows undo; it does not prevent it. Glide writes
  wait for your merge.
- **Where your data goes.** Whatever the model reads is sent to the model's provider. The owner rule
  (2026-09-28): everything runs through LiteLLM, Fireworks first, the cheapest DeepSeek model as the
  fallback, Claude on request. Client content may reach all three, so a Fireworks outage sends chats,
  client material included, to DeepSeek.
- **Branch names are a convention.** Omnigraph protects `main`, not a name prefix, so a Glide run could
  write on another unprotected branch. `main` stays protected.
- **Deleting is not forgetting.** Old versions stay in the storage files until a cleanup runs. For real
  erasure follow [forget a meeting](../runbooks/omnigraph.md#forget-a-meeting).

## When something looks wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| Chat page reloads in a loop | A stale cached page from an expired session | Ctrl+Shift+R once; sessions now refresh themselves |
| "Something went wrong" at Authentik | A leftover login attempt | Close all chat and Authentik tabs, open the chat again |
| The model answers without calling a tool | Omnigraph is not switched on in that chat | Tools menu, switch on Omnigraph |
| A tool call answers 403 | The identity is not allowed that action (for example a Glide write to `main`) | Expected; work on a branch and merge as yourself |
| New or edited notes are found by keyword but not by meaning | Vectors are filled at the nightly restart, and an edit clears the row's vector | Wait until after 03:15; the [brain retrieval RFC](../rfc/rfc-brain-retrieval.md) makes writers supply vectors |
| A Dutch question returns unrelated Dutch documents | The keyword search is English-only and treats Dutch function words as keywords | Ask with a few key words, or in English |
| Text deep inside a long note is not found by meaning | Only the first 1,024 tokens of a note get a vector | Search with its exact words; chunked notes are phase P3 of the RFC |
| The model writes broken queries or dumps huge notes | The MCP bridge has no stored-query tools, so the model writes queries by hand | Ask for a keyword search on passages; brain tools are phase P4–P6 of the RFC |
| A new note has no topics yet | The distiller runs at minute 55 and handles at most 600 documents per run | Wait for the next run; `OmnigraphDistillStale` fires if it stops |
| `OmnigraphVaultImportStale` or `OmnigraphForgeImportStale` | The importer's setup is incomplete or it failed | See the importer's section in the [runbook](../runbooks/omnigraph.md) |
| Claude answers look like DeepSeek | The Anthropic key failed and LiteLLM fell back | Check the key in OpenBao (`secret/litellm`); VIK-1251 adds an alert |

## Roadmap

| Ticket | What |
|---|---|
| VIK-1259 | [Brain retrieval](../rfc/rfc-brain-retrieval.md): an eval set, chunked notes, vectors at write time, brain tools, the Brain preset, a search-first explorer |
| VIK-1348 | Keep the nightly vector backfill from holding every graph offline |
| VIK-1300 | Glide hands each run its Omnigraph tools |
| VIK-1260 | The archive layer, then mail (VIK-1254), Slack (VIK-1290), calls (VIK-1253) |
| VIK-1251 | Alert when Claude requests silently fall back |
| VIK-1296 | Explorer camera on tiny graphs |
