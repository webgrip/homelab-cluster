# ADR-0015: Keep an external mirror as the cold-bootstrap + break-glass GitOps source

> Status: **Proposed** · Date: 2026-06-13 · Part of [RFC: Cutting the GitOps umbilical](../rfc/rfc-flux-forgejo-source.md)

## Context

[ADR-0014](adr-0014-flux-source-forgejo.md) makes the in-cluster Forgejo the steady-state GitOps source.
That creates a circular dependency: Forgejo is deployed *by* Flux, yet Flux would now depend on Forgejo.
Two failure modes fall out of it:

- **Forgejo outage.** Flux can't fetch new revisions; you can't GitOps your way back to health, including
  repairing the forge itself (single-replica, CNPG-backed).
- **Cold bootstrap.** Rebuilding from bare Talos, Flux must sync from a source that **exists before the
  cluster** — which an in-cluster Forgejo, by definition, does not. The `flux bootstrap` /
  `github-deploy.key` path is a *bootstrap-time* concern, distinct from the running `FluxInstance`.

A self-hosted source is the goal; a *single* self-hosted source with no escape hatch just trades GitHub's
lock-in for a homemade single point of failure.

## Decision

*(Proposed.)* **Decouple the steady-state source from the disaster-recovery source.** Forgejo is
authoritative day-to-day (ADR-0014); **GitHub is retained — demoted to a Forgejo→GitHub push-mirror —
as the cold-bootstrap and break-glass source.** Concretely:

- A Forgejo **push-mirror** keeps GitHub a current, byte-for-byte downstream copy of `main`.
- **Cold bootstrap** targets the GitHub (external) URL: it's reachable before the cluster exists. Once
  Flux is up and Forgejo is reconciled, the source is (re)pointed at Forgejo.
- **Break-glass** during a Forgejo outage is a documented one-liner: `kubectl patch` the `FluxInstance`
  (or generated `GitRepository`) back to the GitHub URL; Flux recovers and can reconcile fixes, then is
  pointed forward again.
- **Codeberg** is planned as a *second* off-site push-mirror later, so the DR source isn't itself a
  single host.

## Consequences

- The circular dependency is real but **survivable**: there is always an out-of-band, externally-hosted
  copy to bootstrap or recover from.
- A residual GitHub dependency remains **by design** — but inverted: GitHub is now a *downstream* DR
  target, not the upstream authority. "Leaving GitHub" means it no longer *commands* the cluster, not
  that the bytes vanish.
- The break-glass repoint is a deliberate, rehearsed, reversible imperative action — the one sanctioned
  exception to GitOps-only, used only when GitOps itself is unreachable.
- Two write paths to keep honest: the push-mirror must stay healthy (else the DR copy goes stale) — cover
  it with alerting and verify it in the cutover validation.
- Eventually re-homeable to Codeberg / a second off-cluster Forgejo, removing even the GitHub residue
  without reintroducing a single DR source.

## Alternatives considered

- **Forgejo as the only source, no fallback.** Maximal sovereignty, but a forge outage or cold rebuild
  becomes unrecoverable via GitOps. Rejected — replaces one SPOF with a worse one.
- **Keep the steady-state source external (never cut over).** Avoids the loop entirely but defeats the
  migration's purpose; the control plane stays third-party-owned. Rejected (that's just *not doing*
  ADR-0014).
- **A second in-cluster Forgejo as fallback.** Still inside the same cluster — shares its fate on a total
  loss. The fallback must be **off-cluster** to be meaningful. Rejected in favour of GitHub-now /
  Codeberg-later.
- **An external second Forgejo as the DR source instead of GitHub.** The eventual ideal (fully
  GitHub-free), but it's unbuilt; GitHub already exists, already mirrors, and is free to keep as the DR
  copy during the transition. Sequenced after cutover.
