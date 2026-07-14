---
status: proposed
date: 2026-07-14
---

# All inference is metered through a self-hosted LiteLLM proxy

Technical Story: [RFC: Dark factory](../rfc/rfc-dark-factory.md), Decision 3 (ratified 2026-07-14) —
the keystone that unblocks the in-cluster dispatcher.

## Context and Problem Statement

The dark-factory program hands tickets to agents that produce Forgejo PRs unattended, and the same
program wants developers and agents to be interchangeable operators of one pipeline. Both need LLM
inference. Two problems block that today:

* **No in-cluster credential.** [RFC: Dark factory](../rfc/rfc-dark-factory.md) parks the in-cluster
  dispatcher (its Decision 2) because "no Anthropic credential exists in-cluster" — an unattended
  Job has nothing to authenticate inference with, and dropping a raw provider key into the cluster
  gives every workload uncapped spend against a shared account.
* **No budget or attribution.** A developer's key and an agent's key must each carry a spend ceiling
  and a per-identity ledger, or a runaway loop (HAZ-02) or a careless human bills the whole account
  with no way to see who spent what.

The homelab runs no local GPU (NL power cost makes always-on inference GPU uneconomic), so upstream
inference is an external provider API (Anthropic / OpenAI) either way. The question is not *whether*
to call out — it is what sits in front of those calls to issue budgeted, attributable, revocable
credentials to devs and agents alike.

## Considered Options

* **LiteLLM proxy, self-hosted in-cluster** (chosen)
* **Envoy AI Gateway** (already in the cluster as the ingress data plane)
* **A SaaS AI gateway** — Portkey, OpenRouter, or Cloudflare AI Gateway
* **Raw provider keys via ESO, no proxy** — hand each workload a scoped key directly

## Decision Outcome

Chosen option: **"LiteLLM proxy, self-hosted in-cluster"**, because it is the only option that
issues **per-identity virtual keys with a hard dollar budget and a spend ledger** while staying off
any external control plane — which is exactly the shape of both problems above.

Load-bearing specifics:

* **Runtime.** LiteLLM proxy as a HelmRelease under `kubernetes/apps/`, worker-pinned via the
  `worker-pool` component (it is not part of the soyo recovery set).
* **State.** A CloudNativePG `Cluster` (Tier 2, barman backups to Garage) holds keys, teams, and the
  spend ledger — the same CNPG pattern every other stateful app uses.
* **Provider keys.** Upstream Anthropic / OpenAI keys and the LiteLLM master key live in **OpenBao**,
  surfaced as a Kubernetes Secret by an **ExternalSecret** (ESO) — never in git, never a `*.sops.yaml`.
* **Virtual keys.** One per identity — developer, `agent/*` pool, or **per task** — each carrying a
  hard `max_budget`, `tpm`/`rpm` caps, and a model allow-list. The per-task key is the mechanism the
  dispatcher (RFC phase 4) uses to bound a single run's spend.
* **Identity.** Keys map to **Authentik** users / teams, aligning with the identity system-of-record
  plan; agents are service identities (dedicated LiteLLM teams).
* **Telemetry.** Spend, latency, and error metrics scrape into **VictoriaMetrics**; a Grafana panel
  reports spend-per-key; a budget-breach alert routes to **ntfy**. **Caveat (2026-07-14):** OSS
  LiteLLM ships **no Prometheus `/metrics`** endpoint (Enterprise-gated), so the metrics path is a
  small exporter over the CNPG spend ledger / `/spend` API — which also yields **dollars** (a
  token-only gateway never sees spend). Latency/error traces do come free via the `otel` callback →
  VictoriaTraces.
* **Kill-switch.** Revoking a key, or dropping a team budget to €0, is an instant, global,
  GitOps-reversible stop — the answer to the RFC's open "kill-switch convention" question.

**Envoy AI Gateway** is explicitly *deferred, not rejected*: it complements LiteLLM in front (org-wide
routing, provider failover, token-rate-limiting) in the phase-5 SOTA graduation, but it carries no
dollar-budget key ledger, so it cannot be the metering layer this decision needs.

### Consequences

* Good, because the in-cluster dispatcher's blocker dissolves: the plane *is* the in-cluster
  credential, with a budget attached — RFC Decision 2 and phase 4 unblock.
* Good, because developers get metered, attributable inference on day one from the same mechanism —
  human/agent parity is real, not aspirational.
* Good, because spend is bounded and observable per identity: hard `max_budget` + VM dashboards +
  ntfy breach alerts turn HAZ-02 (runaway spend) from an open risk into a capped one.
* Bad (accepted), because upstream inference is still an external SaaS API call — a real dependency
  and real euro spend. It sits off the ops critical path (a dev tool, not a deadman), so it is
  acceptable under the no-SaaS-in-the-ops-path doctrine *provided budgets are hard ceilings, not
  alerts*. This is the one trade-off, surfaced once.
* Bad, because it adds a stateful in-cluster service (LiteLLM + its CNPG DB) to operate and back up.

### Confirmation

* A developer key and an `agent/*` key each authenticate an inference call through the in-cluster
  LiteLLM endpoint and appear as distinct rows in the spend ledger.
* Setting a key's `max_budget` low and exhausting it returns a budget error (a *hard* stop), not a
  warning that still serves tokens.
* The Grafana spend-per-key panel and the ntfy budget-breach alert both fire in a drill.
* `grep -rn litellm kubernetes/apps` shows the HelmRelease, ESO-sourced secret, and CNPG Cluster;
  no provider key appears in git or in a `*.sops.yaml`.

## Pros and Cons of the Options

### LiteLLM proxy, self-hosted in-cluster

* Good, because per-identity virtual keys carry hard dollar budgets, tpm/rpm, and model allow-lists.
* Good, because it keeps a spend ledger for attribution and stays fully self-hosted.
* Good, because it reuses the cluster's CNPG + OpenBao/ESO + VictoriaMetrics patterns unchanged.
* Neutral, because it fronts external providers — it meters SaaS, it does not remove it.
* Bad, because it is another stateful service to run and back up.

### Envoy AI Gateway

* Good, because it is already the ingress data plane — no new proxy technology.
* Good, because it does routing, provider failover, and token-rate-limiting well.
* Bad, because it has no dollar-budget virtual-key ledger — it cannot meter spend per identity,
  which is the core requirement. Complements LiteLLM in front (phase 5); does not replace it.

### A SaaS AI gateway (Portkey / OpenRouter / Cloudflare)

* Good, because budgets, keys, and dashboards come turnkey with no service to operate.
* Bad, because it puts an external control plane in the inference path — rejected under the
  no-SaaS-in-the-ops-path doctrine.

### Raw provider keys via ESO, no proxy

* Good, because it is the least infrastructure — just an ExternalSecret per workload.
* Bad, because there is no budget ceiling, no per-identity ledger, and no kill-switch short of
  rotating the shared provider key — it solves neither problem.

## More Information

* Technical story: [RFC: Dark factory](../rfc/rfc-dark-factory.md) — Decision 3, phases 2 and 4.
* 2026-07-14 — proposed; ratified in principle in the RFC's SOTA extension, pending phase-2 build.
* 2026-07-14 — phase-2 scaffold shipped (`kubernetes/apps/ai/litellm`, commit c39b2b2f); proxy live
  (DB-connected, health 200). Amended the Telemetry clause: OSS LiteLLM has no Prometheus `/metrics`
  (Enterprise-gated) — the metrics path is a CNPG-ledger exporter, tracked as a follow-up.
* Supported by [ADR-0045](adr-0045-opencode-runtime-server-side-guards.md) — the `opencode` runtime
  that consumes these keys.
* Relates to [ADR-0043](adr-0043-vikunja-roadmap-system-of-record.md) and
  [ADR-0040](adr-0040-vikunja-task-management.md) — the board the plane serves.
