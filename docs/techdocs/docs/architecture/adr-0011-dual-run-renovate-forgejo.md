# ADR-0011: Dual-run Renovate across GitHub and Forgejo during the transition

> Status: **Accepted** (2026-06-16) · Date: 2026-06-13 · Part of [RFC: Renovate on Forgejo](rfc-renovate-forgejo.md)

## Context

Renovate must move from GitHub to the in-cluster [Forgejo](../forgejo.md). The obvious move — flip the
existing `webgrip-gitops` RenovateJob's `platform` from `github` to `forgejo` — fails against the
migration's reality in two ways at once:

- **Most repos are still authoritative on GitHub.** The forge migration is *content-first,
  cutover-last*; repos move to Forgejo one at a time, and `homelab-cluster` (the repo Flux reconciles
  from) moves last. Flipping in place would immediately stop dependency updates for every repo still
  living on GitHub.
- **The Forgejo side is mostly mirrors.** `gitea-mirror` runs continuous inbound sync (GitHub →
  Forgejo), and Renovate's Forgejo autodiscover **skips mirror repos** (and can't push to them). A
  flipped job would discover almost nothing it could act on.

So the transition is inherently a period where *both* platforms host live, authoritative repos. The
operator (mogenius `renovate-operator`) supports multiple independent `RenovateJob` resources, each
with its own provider, admin config, and credentials.

## Decision

Run **two RenovateJobs in parallel** for the duration of the migration: the existing `webgrip-gitops`
(`provider.name: github`) untouched, and a **new `webgrip-forgejo`** (`provider.name: forgejo`,
`endpoint: https://forgejo.${SECRET_DOMAIN}/api/v1`) added alongside it. A repo is served by exactly
one side, gated on **"is this repo Forgejo-authoritative (inbound mirror off)?"** The Forgejo job is
purely additive and starts **scoped to a single pilot repo**; its `discoveryFilters` widen as repos
flip. At the final GitOps source cutover, the entire GitHub path is **retired in one move** (job,
ConfigMap, token-minter CronJob + RBAC, OpenBao keys).

## Consequences

- Dependency updates never stop during the migration — each platform serves the repos it owns.
- The de-mirror step becomes the **single gate**: a repo joins the Forgejo job only once its inbound
  mirror is off, which also prevents both bots opening competing PRs on the same repo.
- Temporary duplication: two admin ConfigMaps and two credentials to keep coherent (mitigated by
  sharing one `.renovaterc.json5` repo policy across both).
- A clean, reversible rollback at any point: suspend/delete `webgrip-forgejo`; the GitHub path is
  unaffected.
- A crisp end-state: retirement is a deletion, not a risky cutover — by the time the GitHub job is
  removed, the Forgejo job has already proven itself on every migrated repo.

## Alternatives considered

- **Flip `webgrip-gitops` in place to `forgejo`.** Smallest diff, but strands every GitHub-authoritative
  repo and finds only mirrors on Forgejo. Rejected — it inverts the migration's ordering.
- **Pause Renovate entirely until the GitOps cutover, then switch.** Avoids dual-run complexity but
  leaves the estate without dependency/vulnerability PRs for the (long) tail of the migration, and
  cuts over an unproven Forgejo path big-bang. Rejected — too long a blind spot, too risky a finale.
- **A single autodiscover job spanning both platforms.** Not supported — a RenovateJob targets one
  provider/endpoint. Would require provider-level federation that doesn't exist.
