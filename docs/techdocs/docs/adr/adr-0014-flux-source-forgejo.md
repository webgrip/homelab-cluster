# ADR-0014: Make Forgejo the authoritative GitOps source for Flux

> Status: **Proposed** · Date: 2026-06-13 · Part of [RFC: Cutting the GitOps umbilical](../rfc/rfc-flux-forgejo-source.md)

## Context

Flux reconciles the cluster from `github.com/webgrip/homelab-cluster` — the flux-operator
`FluxInstance` `sync.url`. It is the last GitHub dependency in the migration and the most load-bearing:
it is *how the cluster knows what it should be.* The forge (`forgejo.${SECRET_DOMAIN}`) is live,
public-read, CNPG-backed, and already mirrors this repo. Inspecting the live wiring, the cutover is
small: the `sync` block carries **no `pullSecret`** (Flux clones GitHub anonymously), and the webhook
`Receiver` is `type: github`, which Flux also uses for Gitea/Forgejo (GitHub-compatible payloads). The
single architectural weight is that Forgejo runs **inside** the cluster Flux manages — addressed by the
companion [ADR-0015](adr-0015-external-bootstrap-fallback-source.md).

## Decision

*(Proposed.)* Repoint the `FluxInstance` `sync.url` from GitHub to the **in-cluster Forgejo Service URL**
(`http://forgejo-http.forgejo.svc.cluster.local:3000/webgrip/homelab-cluster.git`), making Forgejo the
**authoritative steady-state GitOps source**. Use the cluster-internal Service deliberately — not
`forgejo.${SECRET_DOMAIN}` — so the reconcile loop depends on neither the external gateway, public DNS,
nor cert renewal. If the repo is private, add a `sync.pullSecret` holding a Forgejo **read** deploy
token (ESO/OpenBao); if it stays public-read like GitHub today, no secret is needed. The webhook
`Receiver` stays `type: github`; only a Forgejo repo webhook (reusing the existing HMAC secret) is added.
`homelab-cluster` must be Forgejo-**authoritative** first (mirror direction flipped to Forgejo→GitHub).
Full sequence and the gap-free cutover-commit mechanic are in the [RFC](../rfc/rfc-flux-forgejo-source.md).

## Consequences

- The cluster reconciles from infrastructure it **owns**; the last "GitHub" in the platform's control
  plane is gone from the *write/authoritative* path.
- **Forgejo's availability becomes the cluster's ability to change itself.** While Forgejo is down Flux
  degrades gracefully (running workloads persist) but cannot apply new state — including fixing Forgejo.
  This is the cost; the mitigation is [ADR-0015](adr-0015-external-bootstrap-fallback-source.md).
- Using the internal Service URL removes external DNS/ingress/TLS from the GitOps critical path — the
  loop survives a gateway or cert outage.
- The inbound pull-mirror **must** be flipped to a push-mirror, or Forgejo force-syncs from GitHub and
  silently discards in-Forgejo commits.
- Unblocks the Forgejo Renovate path adopting `homelab-cluster`
  ([ADR-0011](adr-0011-dual-run-renovate-forgejo.md)) and retiring the GitHub RenovateJob.
- Reversible by a one-line `sync.url` change (break-glass: `kubectl patch`), which is exactly the
  fallback ADR-0015 keeps warm.

## Alternatives considered

- **Public hostname (`forgejo.${SECRET_DOMAIN}`) for `sync.url`.** Simpler-looking, but puts the external
  gateway, public DNS, and cert renewal on the GitOps critical path and hairpins in-cluster traffic out
  and back. Rejected in favour of the internal Service URL.
- **Keep Flux on GitHub indefinitely.** Zero risk, but leaves the cluster's control plane owned by a
  third party — the one thing the whole migration exists to end. Rejected as the end-state (it remains
  the *fallback*, ADR-0015).
- **SSH (`git@forgejo-ssh…`) instead of HTTP Service.** Works, but adds a deploy-key + the dedicated SSH
  LoadBalancer to the critical path for no gain over the cluster-internal HTTP Service. Rejected.
- **Flip in one big-bang `flux bootstrap` against Forgejo.** Re-bootstrapping is heavier and riskier than
  editing `sync.url` in a tracked commit applied via the current source; the manifest edit is gap-free
  because the commit lands in both hosts. Rejected.
