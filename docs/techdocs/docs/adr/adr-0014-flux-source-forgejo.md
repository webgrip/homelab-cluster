# Make Forgejo the authoritative GitOps source for Flux

* Status: proposed
* Date: 2026-07-02

Technical Story: [RFC: Cutting the GitOps umbilical](../rfc/rfc-flux-forgejo-source.md)

## Context and Problem Statement

Flux reconciles the cluster from `github.com/webgrip/homelab-cluster` — the flux-operator
`FluxInstance` `sync.url`. It is the last and most load-bearing GitHub dependency in the migration:
it is *how the cluster knows what it should be*. The in-cluster forge is live, public-read,
CNPG-backed, and already mirrors this repo, and the cutover is mechanically small: the `sync` block
carries no `pullSecret` (Flux clones anonymously), and the webhook `Receiver` is `type: github`,
which Flux also uses for Forgejo. The one architectural weight — Forgejo runs *inside* the cluster
Flux manages — is addressed by the companion [ADR-0015](adr-0015-external-bootstrap-fallback-source.md).

## Considered Options

* Repoint `sync.url` to the in-cluster Forgejo Service URL
* Public hostname (`forgejo.${SECRET_DOMAIN}`) for `sync.url`
* Keep Flux on GitHub indefinitely
* SSH (`git@forgejo-ssh…`) instead of the HTTP Service
* Big-bang `flux bootstrap` against Forgejo

## Decision Outcome

Chosen option: "Repoint `sync.url` to the in-cluster Forgejo Service URL", because it makes
Forgejo the authoritative steady-state GitOps source while keeping the reconcile loop off the
external gateway, public DNS, and cert renewal — via a one-line, gap-free edit.

Repoint the `FluxInstance` `sync.url` from GitHub to the **in-cluster Forgejo Service URL**
(`http://forgejo-http.forgejo.svc.cluster.local:3000/webgrip/homelab-cluster.git`), making Forgejo
the authoritative steady-state GitOps source. The cluster-internal Service is deliberate — not
`forgejo.${SECRET_DOMAIN}` — so the reconcile loop depends on neither the external gateway, public
DNS, nor cert renewal. If the repo goes private, add a `sync.pullSecret` holding a Forgejo read
deploy token (ESO/OpenBao); public-read needs none. The webhook `Receiver` stays `type: github`;
only a Forgejo repo webhook (reusing the existing HMAC secret) is added. Prerequisite:
`homelab-cluster` must be Forgejo-authoritative first — the last repo through
[ADR-0024](adr-0024-forgejo-leading-application-repos.md)'s cutover. Sequence and the gap-free
cutover-commit mechanic: [RFC](../rfc/rfc-flux-forgejo-source.md).

### Positive Consequences

* The cluster reconciles from infrastructure it owns; GitHub leaves the write/authoritative path.
* Unblocks the Forgejo Renovate path adopting `homelab-cluster` and retiring the GitHub RenovateJob
  ([ADR-0011](adr-0011-dual-run-renovate-forgejo.md)), and sequences the Codeberg mirror
  ([ADR-0020](adr-0020-codeberg-offsite-push-mirror.md)).
* Reversible by a one-line `sync.url` change (break-glass: `kubectl patch`) — exactly the fallback
  ADR-0015 keeps warm.

### Negative Consequences

* **Forgejo's availability becomes the cluster's ability to change itself.** While Forgejo is down,
  Flux degrades gracefully (running workloads persist) but cannot apply new state — including fixes
  to Forgejo. Mitigation: [ADR-0015](adr-0015-external-bootstrap-fallback-source.md).
* The inbound pull-mirror **must** be flipped to a push-mirror first, or Forgejo force-syncs from
  GitHub and silently discards in-Forgejo commits.

## Pros and Cons of the Options

### Repoint `sync.url` to the in-cluster Forgejo Service URL

* Good, because the reconcile loop depends on neither the external gateway, public DNS, nor cert
  renewal.
* Good, because the cutover is mechanically small: the `sync` block carries no `pullSecret` (Flux
  clones anonymously) and the `type: github` webhook `Receiver` also works for Forgejo.
* Bad, because Forgejo runs *inside* the cluster Flux manages — the architectural weight addressed
  by [ADR-0015](adr-0015-external-bootstrap-fallback-source.md).

### Public hostname (`forgejo.${SECRET_DOMAIN}`) for `sync.url`

* Bad, because it puts the gateway, public DNS, and cert renewal on the GitOps critical path and
  hairpins in-cluster traffic out and back.

### Keep Flux on GitHub indefinitely

* Bad, because it leaves the cluster's control plane owned by a third party; retained only as the
  *fallback* ([ADR-0015](adr-0015-external-bootstrap-fallback-source.md)).

### SSH (`git@forgejo-ssh…`) instead of the HTTP Service

* Bad, because it adds a deploy key + the dedicated SSH LoadBalancer to the critical path for no
  gain.

### Big-bang `flux bootstrap` against Forgejo

* Bad, because it is heavier and riskier than a one-line `sync.url` edit, which is gap-free because
  the commit lands in both hosts.

## Links

* 2026-06-13 — proposed
* 2026-07-02 — still pending: the `FluxInstance` syncs from GitHub, gated on
  [ADR-0024](adr-0024-forgejo-leading-application-repos.md) reaching this repo
