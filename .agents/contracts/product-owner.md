# Board contract — homelab-cluster

The repo contract layer of the product-owner-contract skill: ids and small facts for this
repository's Vikunja project. The skill reads this file on board work; it is not loaded into
every agent session.

- MCP server: `vikunja` · project: `Homelab Roadmap` (id 3) · instance list cap
  (maxitemsperpage): 250
- The custom board front end has its own project: `Vellum` (id 6, since 2026-07-18) —
  the board page itself (`kubernetes/apps/vikunja/board`, served at
  `vikunja.<domain>/board`); same conventions/labels as the main board
- The agent-execution program has one project: `Unfold` (id 10, formerly Glide). It holds Unfold itself (Ploeg and
  the Unfold application, repo `webgrip/unfold`, formerly `webgrip/glide`) and everything around it: LiteLLM inference plane, MCP gateway,
  agent identity/budgets, classifiers, factory observability. Merged into it: `De Vloer` (id 14,
  2026-09-29), `Dark Factory` (id 5), `Ploeg Test` and `Ploeg Bench` tickets (2026-09-30). Each
  ticket's `repo/*` label names the repo its work lands in; ploegd routes by that label (ADR-0038,
  live since 2026-10-10, f06c40cb): no label → `webgrip/unfold`, `repo/homelab-cluster` →
  homelab-cluster; any other `repo/*` is refused with a comment, never misrouted. Registered
  targets live under `ploeg.config.targets` in `kubernetes/apps/ploeg/unfold/app/helmrelease.yaml`
- Fixture boards, never backlogs: `Ploeg Test` (id 11, Unfold's test task source and the `unfold`
  team's route) and `Ploeg Bench` (id 49, benchmark trials, one fresh ticket per trial; id 48 is
  an archived empty duplicate). Pinned by id in the ploegd routing config
- Enumerating a board: `tasks_list` returns one capped page and reports the page size as
  "Found N" (95 of 267 on Glide, 2026-09-30), and search is unreliable. For inventory or
  counts, query the `vikunja-db` primary read-only (`cnpg.io/cluster=vikunja-db`,
  `cnpg.io/instanceRole=primary`; never the `cnpg-disaster-recovery` copy, which is a stale restore)
- CI/CD improvement work lives in its own project: `CI/CD` (id 9, since 2026-07-18) — runner pool, image supply
  chain, pipeline efficiency (mechanics
  reference: docs/techdocs/docs/general/ci-image-flow.md); same conventions/labels as the
  main board. The techdocs *serving* decision stays on Homelab Roadmap (#340)
- Product boards exist alongside the infra boards: `Erfbeeld` (id 4, repo
  `webgrip/nuala-nalatenschap`) is the factory's pilot product (ADR-0048 pilots on its tickets)
  and the target of the product-research intake lane (VIK-462); product boards keep their own
  label taxonomy (`area/*`, `wave/*`, `status/*`) and their docs live in the product repo, not
  in this repo's techdocs
- Ticket prefix: `VIK` (commit trailers `VIK-<taskID>`; see
  [rfc-dark-factory](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/docs/techdocs/docs/rfc/rfc-dark-factory.md) for the full agent-execution program)
- Labels — **the board is authoritative, not this file.** Enumerate with `labels_list` before
  applying any. Only the *dimensions* below are contract; the values are board state and are not
  transcribed here.
  - `theme/<kebab>` — one per ticket, from whatever the board currently defines
  - `impact/H|M|L`
  - **3D estimation** (since 2026-07-18): `effort/S|M|L` (work size) ·
    `time/hours|days|weeks` (wall-clock lead incl. soaks/waits) · `uncertainty/low|med|high`
    (how well-understood; `high` ⇒ never `agent-ready` — spike/de-risk first)
  - `do-next` (≤10) · `ready` / `needs-refinement` / `review` / `agent-ready` ·
    `agent/<name>` (claims)
  - If no existing `theme/*` fits, that is a taxonomy decision for a human — raise it; do not
    create a label to unblock a write.
  - *Why this is not a list:* it was one until 2026-08-01, naming nine `theme/security-*` values,
    **none of which existed on the instance**. An agent trusting it either fails to label or
    invents taxonomy to make the write succeed. Enumerated state does not belong in a file that
    nothing validates.
- **Stages** (since 2026-07-18) are DERIVED from labels + done, never stored separately —
  every surface (MCP agents, Vellum board, stock UI) reads the same truth:
  **Backlog** (`needs-refinement` or unlabelled) → **To Do** (`ready`; DoR incl. all three
  estimation labels) → **Doing** (`agent/<name>` claim) → **Reviewing** (`review` label;
  agent finished, human accepts) → **Done** (completed). **DoD**: a completion is accepted only
  with an evidence comment proving (1) **deployed** — verified against real state, not a proxy,
  and (2) **monitored** — names the signal that would catch regression (alert/dashboard/
  scheduled check), or states why none applies (docs-only)
- **Epics = parent tasks** (since 2026-07-18): a ticket titled `Epic: …` carries `subtask`
  relations to its children and the `meta` label; epics keep theme+impact labels but are EXEMPT
  from estimation/lifecycle labels, are never agent-workable themselves, and close only when every
  subtask closes. Wire membership with `relation_create(kind: subtask)` (parent→child); a child
  has at most ONE parent. `theme/*` labels stay the cross-project dimension; the Vellum front
  end renders the hierarchy ("By epic" view with roll-up progress)
- Open target: ≈100 tickets · stock-UI kanban buckets, if used, mirror the derived stages
  (Backlog / To Do / Doing / Reviewing / Done) — labels are authoritative, buckets are display
- **Pick-up order** (since 2026-07-18): each project's **description** carries a
  `Pick-up queue` — an ordered list (`VIK-<id> — title`), **top = picked up first**, covering
  every `do-next` holder plus a next-up tail. Agents take the topmost eligible entry; the PO
  inserts new tickets where they fit and drops entries on close. The MCP has no position API
  (the product-owner skill's adapters/vikunja.md), so raw Vikunja drag-order alone is NOT the queue — but the **Vellum
  board's Stages view keeps them in sync**: dragging in its To Do column rewrites the
  description queue (marker: `refreshed <date> (board)`), so PO ordering happens there or via
  the MCP round-trip, never in the stock Vikunja UI
- Top-up ground truth: `git log --oneline <last-sweep>..HEAD` · `./scripts/posture-counts.sh` ·
  live read-only MCP checks · audit dimensions: security/hardening · reliability/HA/backup-DR ·
  CI/shift-left/DX
- Instance ops (token rotation, bridge/OOM issues):
  [runbooks/mcp-vikunja.md](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/docs/techdocs/docs/runbooks/mcp-vikunja.md)

Decisions are still recorded in git (`docs/techdocs/docs/adr/`, `rfc/`); the board holds work
items, not decision records.
