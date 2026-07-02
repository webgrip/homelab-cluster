# Keep an external mirror as the cold-bootstrap + break-glass GitOps source

* Status: proposed
* Date: 2026-06-13

Technical Story: [RFC: Cutting the GitOps umbilical](../rfc/rfc-flux-forgejo-source.md)

## Context and Problem Statement

[ADR-0014](adr-0014-flux-source-forgejo.md) makes the in-cluster Forgejo the steady-state GitOps
source, creating a circular dependency: Forgejo is deployed *by* Flux, yet Flux would now depend on
Forgejo. Two failure modes fall out of it. **Forgejo outage:** Flux can't fetch new revisions, so
you can't GitOps your way back to health — including repairing the forge itself (single-replica,
CNPG-backed). **Cold bootstrap:** rebuilding from bare Talos, Flux must sync from a source that
exists *before* the cluster — which an in-cluster Forgejo, by definition, does not. A self-hosted
source is the goal; a *single* self-hosted source with no escape hatch just trades GitHub's lock-in
for a homemade single point of failure.

## Considered Options

* Retain GitHub as a demoted Forgejo→GitHub push-mirror (cold-bootstrap + break-glass source)

## Decision Outcome

Chosen option: "Retain GitHub as a demoted Forgejo→GitHub push-mirror (cold-bootstrap +
break-glass source)", because a *single* self-hosted source with no escape hatch just trades
GitHub's lock-in for a homemade single point of failure.

**Decouple the steady-state source from the disaster-recovery source.** Forgejo is authoritative
day-to-day (ADR-0014); **GitHub is retained — demoted to a Forgejo→GitHub push-mirror — as the
cold-bootstrap and break-glass source.** Concretely:

* A Forgejo **push-mirror** keeps GitHub a current, byte-for-byte downstream copy of `main`.
* **Cold bootstrap** targets the GitHub (external) URL — reachable before the cluster exists. Once
  Flux is up and Forgejo is reconciled, the source is repointed at Forgejo.
* **Break-glass** during a Forgejo outage is a documented one-liner: `kubectl patch` the
  `FluxInstance` (or generated `GitRepository`) back to the GitHub URL, reconcile the fix, point
  forward again.
* **Codeberg** is planned as a *second* off-site push-mirror
  ([ADR-0020](adr-0020-codeberg-offsite-push-mirror.md)), so the DR source isn't itself a single host.

### Positive Consequences

* The circular dependency is real but **survivable**: there is always an out-of-band, externally
  hosted copy to bootstrap or recover from.
* The break-glass repoint is a deliberate, rehearsed, reversible imperative action — the one
  sanctioned exception to GitOps-only, used only when GitOps itself is unreachable.
* Eventually re-homeable to Codeberg / a second off-cluster Forgejo, removing even the GitHub
  residue without reintroducing a single DR source.

### Negative Consequences

* A residual GitHub dependency remains **by design** — but inverted: GitHub becomes a *downstream*
  DR target, not the upstream authority. "Leaving GitHub" means it **no longer commands the
  cluster**, not that the bytes vanish.
* The push-mirror is a write path to keep honest: if it silently fails, the DR copy goes stale —
  cover it with alerting and verify it in the cutover validation.

## Links

* 2026-06-13 — proposed (executes together with [ADR-0014](adr-0014-flux-source-forgejo.md), which
  is still pending)
