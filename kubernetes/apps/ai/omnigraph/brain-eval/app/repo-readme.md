# brain-eval

The private evaluation set for brain retrieval in the homelab (RFC brain retrieval, P2). Nothing in this repository may be copied into a public repository, a ticket, a log or a chat that leaves the cluster.

## Layout

| Path | What |
|---|---|
| `cases/` | One YAML file per case. The eval jobs read only this folder |
| `candidates/<date>/pool.json` | Every drafted candidate with its pooled relevance grades |
| `calibration/pending/` | Answers waiting for a hand grade |
| `calibration/` | Graded answers the judge is checked against |
| `results/<date>/` | Per-question results of every run |

## Curate the set

The first set was drafted by the candidates job and cut to 36 cases automatically. Every drafted case says `provisional: true` and `origin: drafted`, and scores stay marked provisional until:

1. At least 6 cases are questions you really ask. Write them yourself with `origin: ryan`, replacing drafted cases of the same category so each category keeps its count.
2. Every case you keep is reviewed: fix the question, the expected documents and the key facts, then set `provisional: false`.
3. Ten answers are hand graded in `calibration/` (see `calibration/README.md`).

A case file:

```yaml
id: c01
split: dev
category: docs-en
language: en
provisional: false
origin: ryan
answerable: true
question: "..."
expected:
  - slug: "forge/webgrip/homelab-cluster/doc/docs/runbooks/example"
    grade: 2
key_facts:
  - "..."
```

- `split`: `dev` (tuned against) or `holdout` (one per category; never inspect while tuning).
- `category`: `docs-en`, `notes-nl`, `notes-en`, `cross-lingual`, `about`, `connect`, `temporal` or `unanswerable`. Keep 6, 6, 4, 4, 6, 4, 3 and 3 cases.
- `expected`: the documents that answer the question, grade 2 for a direct answer and 1 for a partial one. Use the slug the explorer shows. An Obsidian note is `obsidian/...`.
- `key_facts`: 1 to 4 statements a correct answer must contain.
- Unanswerable cases have `answerable: false` and no expected documents.
- Temporal cases have a `temporal` block (`kind`: `recent_notes`, `recent_docs` or `open_threads`, `days`, optional `project`) instead of expected documents; the job computes them at run time.

A case whose expected slug no longer exists is excluded and counted as stale. Remove or fix it here.
