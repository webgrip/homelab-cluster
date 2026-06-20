---
name: roadmap-topup
description: Re-inventory the whole cluster/repo and refresh roadmap.md, kept topped up at 100 open improvement items. Use when asked to "inventarize", "take inventory", "refresh/top-up the roadmap", or "what should we do next" at a strategic level.
---

# Inventory → top up the roadmap to 100

Maintains `/roadmap.md` (repo root): a living, prioritized backlog held at **exactly 100 open
items**. Each run re-inventories live state, moves shipped work to the Done log, and refills new
findings so the open count stays 100.

## Output contract (`roadmap.md` structure — keep it)

1. **Header** — one-line "living backlog … topped up at 100 … maintained by `roadmap-topup`", the
   re-inventory date, and the tag legend `[Priority · Impact · Effort]` (P0–P3 · H/M/L · S/M/L).
2. **Where we stand (live, <date>)** — Flux readiness + suspended; etcd/memory; and a **verified
   hardening-posture line** (the exact counts from step 1 below).
3. **✅ Done log (recent)** — compress the last few batches; cite week/commit themes, not every commit.
4. **▶ Do next** — ~8 highest-leverage item numbers.
5. **The 100** — grouped by theme (security audit→enforce, network, auth, pod-hardening, supply-chain,
   Talos, secrets, HA/PDB, backup/DR, Garage, Flux/capacity, observability, CI, DX/automation,
   docs/horizon). Each line: `N. <title> — [P · I · E]`. Numbering is 1–100; each themed block starts
   with its true ordinal (CommonMark renders it right despite the MD029 lint warning — ignore that).
6. **Sequencing notes** — the real dependencies/gates (e.g. Hubble→default-deny; one app→fleet).

## Process

### 1. Capture live ground truth (don't trust the old roadmap's numbers)
```bash
git log --oneline <last-roadmap-commit>..HEAD          # what shipped since last run
git status --porcelain=v1                              # owner WIP (do NOT stage it — see step 5)
./scripts/posture-counts.sh                            # verified posture: PDB/NetPol/Cilium/Quota/SecurityPolicy + Kyverno Audit-vs-Enforce + ns netpol coverage
```
Cross-check live cluster read-only via MCP: `mcp__kubernetes__*` (Flux NOT-READY/suspended,
replica counts) and `mcp__grafana__query_prometheus` (e.g. confirm a metric exists before proposing
an alert on it — `count(<metric>) or vector(-1)`; node memory; etcd frag).

### 2. Fan out 3 parallel deep audits (one message, 3 `Agent` calls, `subagent_type: Explore`)
Dimensions: **(a) security/hardening**, **(b) reliability/HA/backup-DR**, **(c) CI/shift-left/DX**.
Brief each with the **full "ALREADY DONE" list** (from the Done log + step-1 git log) so they only
return *open* gaps, and ask for **25–40 candidate items each** as `title · file:line · Impact · Effort`.
Tell them to verify, not guess (e.g. is policy X still Audit? does ns Y still lack a netpol?).

### 3. Reconcile → exactly 100
- **Filter agent noise:** drop inaccurate claims (verify against the repo); the agents over-report.
  Common false positives: "namespaces missing ks.yaml" (the pattern is `namespace.yaml` + per-app
  `ks.yaml`), benign control-plane bind addresses, double-counting.
- **Mark done:** anything shipped since last run → move to the Done log, delete from the 100.
- **Reframe partials:** e.g. "label ns for netpol" → "platform ns still need netpol" once app ns are done.
- **Dedupe + add new:** fold duplicates; add genuinely-new findings until the open list is **exactly 100**.
- **Re-tag priority honestly:** P0 = live risk or cheap correctness *now* (usually very few). Don't
  inflate. Carry forward owner-action items (e.g. off-site key escrow) at their real priority.

### 4. Rewrite `roadmap.md` in full (Write, not surgical edits) per the output contract.

### 5. Validate, commit, push
- Cosmetic markdownlint (MD029/MD022/MD060) is expected — ignore.
- The owner commits concurrently on the **same local `main`**. **Stage only your own files**
  (`git add roadmap.md` + any skill file) — never `git add -A`. Commit with
  `git -c commit.gpgsign=false commit` (via `mise exec --` so lefthook's zizmor resolves), then
  `git fetch` + push (clean fast-forward; their WIP stays untouched).

## Notes
- The number is a forcing function: holding at 100 forces you to keep finding real work, not to pad.
  If you genuinely can't find 100 real items, record fewer and say so — don't invent filler.
- This skill *plans*; it doesn't implement. Implementing an item is a separate, normal change.
- Run cadence: after a big sprint, or on request. Each run is one well-scoped fan-out + one commit.
