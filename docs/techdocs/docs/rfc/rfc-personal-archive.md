# RFC: Personal archive — all mail, calls and chats, searchable from the chat

> Status: **Proposed, parked** (owner: Obsidian import first) · Date: 2026-09-27 · Epic: VIK-1259

> **TL;DR.** The owner wants years of mail, call recordings and chat history usable from
> Open WebUI and Claude Code. Omnigraph's `brain` graph is the wrong place to pour that in: it is
> a typed, curated graph with a single writer and a full-text index that only refreshes on the
> nightly optimize. Proposal: **two layers**. Layer 1, the **archive**, keeps every item whole
> (originals in Garage, a search index in a CNPG Postgres with full-text and `pgvector`,
> embeddings from the in-cluster TEI model), and is exposed as MCP search tools through LiteLLM.
> Layer 2, the **brain**, holds people, organisations, projects, decisions and commitments
> distilled from the personal part of the archive, each linked back to its source; client items
> distil into their client's graph. Client content may reach Anthropic and Fireworks under their
> DPAs, and DeepSeek as the fallback. Order: Gmail → Slack → calls → Discord export → brain
> distillation → WhatsApp revisited. Parked until the Obsidian import runs.

## Why

- **All three graphs were empty on 2026-09-27.** The front doors work (Open WebUI and Claude Code
  reach `memory` and `brain` through LiteLLM's MCP gateway, VIK-1250), but nothing feeds them.
  The owner's own words: "I have so much information. All my mail, all my WhatsApp, all my
  Discord, all my calls, recordings."
- **Volume changes the design.** A decade of mail and chat is hundreds of thousands of items.
  Extracting every one of them into graph entities with an LLM is slow and costly, and most items
  (newsletters, "ok thanks", receipts) carry no entity worth keeping. Search over the originals
  answers most questions; the graph earns its place for relationships ("what do I owe Pieter",
  "who have I not spoken to in three months").
- **Client data is mixed in.** Mail and calls contain client information and other people's
  personal data. The company graphs isolate clients strictly
  ([omnigraph runbook](../runbooks/omnigraph.md)); a personal archive must not become the way
  around that, neither at ingest nor at question time.

## Owner decisions (2026-09-27)

| # | Question | Decision |
| --- | --- | --- |
| D1 | Mail source | Google: personal Gmail, the Workspace mailbox (webgrip.nl) and further Google accounts still to be named |
| D2 | WhatsApp | Skipped for now |
| D3 | Calls | A phone call-recorder app, audio files on disk or cloud, and recording going forward |
| D4 | Client data and external models | **Revised twice on 2026-09-27/28:** client and company content may go to Anthropic and Fireworks under their DPAs, and the owner then made the cheapest DeepSeek model the fallback for Fireworks, so it may reach DeepSeek too |
| D5 | Discord | One-off import of the GDPR data package |
| D6 | Slack | Several workspaces, some administered by others: one private read-only Slack app per workspace, installed with that workspace admin's approval. On Slack's free plan the API reaches 90 days of history |
| D7 | Timing | Parked on 2026-09-27; the Obsidian vault import goes first |

## Design

```text
sources ──► collectors ──► Garage  s3://archive/<source>/…        (originals, immutable)
                              │
                              ▼
                        normaliser ──► archive DB (CNPG Postgres)
                              │          items · chunks · tsvector · pgvector(384)
                              │          class = personal | client:<id> | unknown
                              ▼
                  distiller (personal only, LLM via LiteLLM)
                              │
                              ▼
                 Omnigraph brain, ingest/* branch ──► owner review ──► main

chat / Claude Code ──► LiteLLM MCP ──► archive_search (class-filtered) + omnigraph_brain
```

### Layer 1: the archive

**Originals** land unmodified in a Garage bucket `archive`, keyed by source and a stable id
(Gmail message id, file hash). They are the thing to re-process from when the normaliser or the
embedding model changes, so they are never rewritten.

**Index: a dedicated CNPG Postgres, not an Omnigraph graph.**

| Option | For | Against |
| --- | --- | --- |
| **Postgres + `tsvector` + `pgvector`** (chosen) | Keyword search is fresh the moment a row commits; filtering by class is a `WHERE` clause, which is where the D4 leak control lives; CNPG is the estate standard with backups, restore drills and alerts already built; 1M chunks × 384 floats ≈ 1.5 GiB of vectors, fine on worker-1 | One more database; `pgvector` must be present in the CNPG image (verify the catalog's `18.6-system-trixie` image; otherwise add it as a CNPG extension image) |
| Omnigraph `archive` graph | One system; Lance handles the row counts | Full-text index only rebuilt by the nightly optimize, so today's mail is not keyword-searchable until tomorrow; single writer contends with the brain's writers; a schema change needs the graph to have no branches and takes every graph down if it fails ([known limits](../runbooks/omnigraph.md#known-v011-limits)) |
| Meilisearch / OpenSearch | Hybrid search built in | A new engine to operate, back up and monitor; OpenSearch's JVM footprint costs watts all day |

**Chunks and embeddings.** Each item splits into passages of a few hundred tokens; each passage
is embedded by `granite-embedding-97m-multilingual-r2` through LiteLLM (in-cluster TEI, so this
step never leaves the house, whatever the class). Multilingual matters: the corpus is Dutch and
English.

**Classification (D4) without an external model.** Every item carries `class`:

1. The Workspace mailbox defaults to `client:*`/company; the personal Gmail defaults to `personal`.
2. A git-declared list of client domains and phone numbers maps a sender, recipient or caller
   to `client:<id>`; any match wins over the default.
3. Anything the rules cannot place is `unknown`, which is treated as client.

**Model routing.** Everything runs through LiteLLM: Fireworks first, `deepseek-chat` as the
fallback (D4). The class tag stays on every item: it keeps client graphs apart at distillation and
lets the answer cite which client a passage came from.

### Layer 2: the brain

A distiller job reads new items and asks `meeting-extract` (Fireworks, via LiteLLM)
for people, organisations, projects, decisions, commitments and tasks, with the source item id
on each. It loads them onto an `ingest/<date>` branch of `brain` as `act-ingest`, which needs a
grant on `brain` (today it only has the company graphs). Client-classified items distil into that client's graph, never into `brain`. The owner merges through the review UX
(VIK-1258). Typed captures from the chat are a separate, pending decision (below).

### Sources

**Gmail (D1), Phase A.**

- *Backfill:* a Google Takeout `mbox` export uploaded to `s3://archive/inbox/`. That is one
  download, with no API quota to drain.
- *Incremental:* the Gmail API `history.list` since the last `historyId`, every 15 minutes.
  - *Personal Gmail:* an OAuth client in the owner's own Google Cloud project, scope
    `gmail.readonly`. **The consent screen must be set to "In production".** In "Testing",
    Google expires refresh tokens after 7 days and the sync silently stops. An unverified app
    for its own owner's use is allowed.
  - *Workspace:* the owner administers the domain, so a service account with domain-wide
    delegation avoids the refresh-token problem entirely.
  - Credentials live in OpenBao and reach the collector through an ExternalSecret.
- *Attachments:* stored as originals. The text of PDFs and Office files is extracted in-cluster;
  images are left alone.

**Calls and recordings (D3), Phase B.**

- *Drop path:* the phone's recorder folder syncs to `s3://archive/inbox/audio/` (FolderSync or
  a similar app with an S3 target, on Wi-Fi). Existing audio files are uploaded to the same
  prefix.
- *Transcription:* the revised D4 allows Fireworks Whisper through LiteLLM. Self-hosted
  faster-whisper (CTranslate2, int8, a batch Job on worker-2) stays the comparison point on
  cost and power.
- *Speed and power: estimates, to be measured on the first real hour of audio.*
  - `large-v3-turbo` int8 on 8 cores runs somewhere around 0.3–0.6× real time.
  - An hour of calls a day then costs about 20–40 minutes of CPU at roughly +50 W. That is
    ≈ 20–35 Wh a day, about 1–1.5 W continuous, or about €3–5 a year.
- *Diarisation* (who spoke when) is a later nice-to-have; the transcript is useful without it.
- *Recording going forward:* Dutch law lets a participant record a call for personal use. For
  business calls, tell the other party; the GDPR applies once the recording is stored for
  company purposes.

**Discord (D5), Phase C.** Request the data package in Discord's settings (Privacy & Safety →
Request all of my data); it arrives by mail within days. It contains the owner's own messages per
channel, so the other side of a conversation is missing. Import is one-off; verify the package
layout when it arrives. No self-bots: they break Discord's terms.

**WhatsApp (D2), Phase E, deferred.** There is no official API for personal chats. Per-chat
export is manual. Unofficial WhatsApp-Web bridges work but can get the number banned. Revisit
when the rest runs.

## Failure modes and monitoring

| Pipeline | Failure | Signal |
| --- | --- | --- |
| Gmail sync | Refresh token expired or revoked; the API quota was hit | `archive_source_last_success_timestamp{source="gmail"}` older than 2 h → alert |
| Gmail sync | The history id fell out of Google's window (a sync paused for days) | The collector logs a full-resync marker; the alert above fires first |
| Audio | Transcription backlog grows | Count of objects under `inbox/audio/` older than 24 h > 0 → alert |
| Embeddings | TEI down, so chunks sit without vectors | Rows with a NULL embedding older than 1 h → alert |
| Classification | A client domain is missing from the list | Weekly report: top `unknown`-class senders, sent to ntfy for the owner to classify |
| Archive DB | The usual CNPG failure classes | The existing CNPG alerts, backup schedule and restore drill |

## Phases

| Phase | Delivers | Board |
| --- | --- | --- |
| A | Archive DB + Garage bucket + Gmail backfill and sync + `archive_search` MCP tool | new archive-layer ticket, VIK-1254 |
| B | Audio drop path + self-hosted transcription into the archive | VIK-1253 |
| C | Discord data-package import | VIK-1256 |
| D | Distiller: personal items → `brain` review branches | VIK-1252, VIK-1258 |
| E | WhatsApp revisited | VIK-1256 |

The universal inbox (VIK-1252) becomes the `s3://archive/inbox/` prefix plus the normaliser,
rather than a separate system.

## Open decisions for the owner

1. **Direct brain writes from the chat.** Does `act-brain-agent` get read everywhere and change on
   `main` for typed captures (recoverable through the commit history), or stay on review branches?
2. **Open WebUI backup.** Enrol `ai/open-webui-data` in the Longhorn backup policy.
3. **The Slack workspace admins' approval** for each read-only app, and which further Google accounts D1 covers.
4. **The client list:** which domains, phone numbers and Discord servers count as client.
