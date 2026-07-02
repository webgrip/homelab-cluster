# ADR-0011: Dual-run Renovate across GitHub and Forgejo during the transition

> Status: **Accepted** · Date: 2026-06-13 · Part of [RFC: Renovate on Forgejo](../rfc/rfc-renovate-forgejo.md)

## Context

Renovate must move from GitHub to the in-cluster [Forgejo](../general/forgejo.md). The obvious
move — flip the existing `webgrip-gitops` RenovateJob's `platform` from `github` to `forgejo` —
fails twice at once. **Most repos are still authoritative on GitHub** (the forge migration is
content-first, cutover-last; `homelab-cluster` moves last), so flipping in place would stop
updates for every GitHub-resident repo. And **the Forgejo side is mostly mirrors** — `gitea-mirror`
syncs GitHub → Forgejo, and Renovate's Forgejo autodiscover skips mirror repos (and can't push to
them) — so a flipped job would discover almost nothing it could act on. The transition is
inherently a period where *both* platforms host live, authoritative repos; the mogenius
`renovate-operator` supports multiple independent `RenovateJob` resources.

## Decision

Run **two RenovateJobs in parallel** for the duration of the migration: the existing
`webgrip-gitops` (`provider.name: github`) untouched, and a new **`webgrip-forgejo`**
(`provider.name: forgejo`) added alongside it. A repo is served by exactly one side, gated on
**"is this repo Forgejo-authoritative (inbound mirror off)?"** The Forgejo job started scoped to a
single pilot repo; its `discoveryFilters` widen as repos flip. At the final GitOps source cutover
([ADR-0014](adr-0014-flux-source-forgejo.md)) the entire GitHub path is retired in one move (job,
ConfigMap, token-minter CronJob + RBAC, OpenBao keys). Lives in
`kubernetes/apps/renovate/renovate-operator/jobs/`.

## Alternatives considered

- **Flip `webgrip-gitops` in place to `forgejo`** — strands every GitHub-authoritative repo and
  finds only mirrors on Forgejo; inverts the migration's ordering.
- **Pause Renovate until the GitOps cutover** — leaves the estate without dependency/vulnerability
  PRs for the long tail of the migration and cuts over an unproven path big-bang.
- **A single autodiscover job spanning both platforms** — not supported; a RenovateJob targets one
  provider/endpoint.

## Consequences

- Dependency updates never stop during the migration — each platform serves the repos it owns.
- The de-mirror step becomes the **single gate**: a repo joins the Forgejo job only once its
  inbound mirror is off, which also prevents both bots opening competing PRs on the same repo.
- Temporary duplication: two admin ConfigMaps and two credentials to keep coherent.
- A clean, reversible rollback at any point: suspend/delete `webgrip-forgejo`; the GitHub path is
  unaffected.
- A crisp end-state: retirement is a deletion, not a risky cutover — by the time the GitHub job is
  removed, the Forgejo job has already proven itself on every migrated repo.

## Status log

- 2026-06-13 — Proposed with the RFC; dormant Forgejo path scaffolded.
- 2026-06-16 — Accepted; operator webhook sync enabled.
- 2026-07-02 — Still the operating state: both jobs run, repos join the Forgejo side as they
  de-mirror; GitHub-path retirement remains gated on the Flux source cutover
  ([ADR-0014](adr-0014-flux-source-forgejo.md), still Proposed).
