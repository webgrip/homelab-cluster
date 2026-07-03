# Dual-run Renovate across GitHub and Forgejo during the transition

* Status: accepted
* Date: 2026-07-02

Technical Story: [RFC: Renovate on Forgejo](../rfc/rfc-renovate-forgejo.md)

## Context and Problem Statement

Renovate must move from GitHub to the in-cluster [Forgejo](../general/forgejo.md). The obvious
move — flip the existing `webgrip-gitops` RenovateJob's `platform` from `github` to `forgejo` —
fails twice at once. **Most repos are still authoritative on GitHub** (the forge migration is
content-first, cutover-last; `homelab-cluster` moves last), so flipping in place would stop
updates for every GitHub-resident repo. And **the Forgejo side is mostly mirrors** — `gitea-mirror`
syncs GitHub → Forgejo, and Renovate's Forgejo autodiscover skips mirror repos (and can't push to
them) — so a flipped job would discover almost nothing it could act on. The transition is
inherently a period where *both* platforms host live, authoritative repos; the mogenius
`renovate-operator` supports multiple independent `RenovateJob` resources.

## Considered Options

* Two RenovateJobs in parallel
* Flip `webgrip-gitops` in place to `forgejo`
* Pause Renovate until the GitOps cutover
* A single autodiscover job spanning both platforms

## Decision Outcome

Chosen option: "Two RenovateJobs in parallel", because the transition is inherently a period where
*both* platforms host live, authoritative repos — flipping the single job in place would stop
updates for every GitHub-resident repo while discovering almost nothing actionable on the
mirror-heavy Forgejo side.

Run **two RenovateJobs in parallel** for the duration of the migration: the existing
`webgrip-gitops` (`provider.name: github`) untouched, and a new **`webgrip-forgejo`**
(`provider.name: forgejo`) added alongside it. A repo is served by exactly one side, gated on
**"is this repo Forgejo-authoritative (inbound mirror off)?"** The Forgejo job started scoped to a
single pilot repo; its `discoveryFilters` widen as repos flip. At the final GitOps source cutover
([ADR-0011](adr-0011-flux-source-forgejo.md)) the entire GitHub path is retired in one move (job,
ConfigMap, token-minter CronJob + RBAC, OpenBao keys). Lives in
`kubernetes/apps/renovate/renovate-operator/jobs/`.

### Positive Consequences

* Dependency updates never stop during the migration — each platform serves the repos it owns.
* The de-mirror step becomes the **single gate**: a repo joins the Forgejo job only once its
  inbound mirror is off, which also prevents both bots opening competing PRs on the same repo.
* A clean, reversible rollback at any point: suspend/delete `webgrip-forgejo`; the GitHub path is
  unaffected.
* A crisp end-state: retirement is a deletion, not a risky cutover — by the time the GitHub job is
  removed, the Forgejo job has already proven itself on every migrated repo.

### Negative Consequences

* Temporary duplication: two admin ConfigMaps and two credentials to keep coherent.

## Pros and Cons of the Options

### Two RenovateJobs in parallel

* Good, because dependency updates never stop — each platform serves the repos it owns.
* Good, because retirement is a deletion, not a risky cutover — the Forgejo job proves itself on
  every migrated repo before the GitHub job is removed.
* Bad, because temporary duplication: two admin ConfigMaps and two credentials to keep coherent.

### Flip `webgrip-gitops` in place to `forgejo`

* Bad, because it strands every GitHub-authoritative repo and finds only mirrors on Forgejo;
  inverts the migration's ordering.

### Pause Renovate until the GitOps cutover

* Bad, because it leaves the estate without dependency/vulnerability PRs for the long tail of the
  migration and cuts over an unproven path big-bang.

### A single autodiscover job spanning both platforms

* Bad, because not supported — a RenovateJob targets one provider/endpoint.

## Links

* 2026-06-13 — proposed with the RFC; dormant Forgejo path scaffolded
* 2026-06-16 — accepted; operator webhook sync enabled
* 2026-07-02 — still the operating state: both jobs run, repos join the Forgejo side as they
  de-mirror; GitHub-path retirement remains gated on the Flux source cutover
  ([ADR-0011](adr-0011-flux-source-forgejo.md), still Proposed)
* 2026-07-03 — renumbered from ADR-0011 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
