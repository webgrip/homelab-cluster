# Authenticate Renovate to Forgejo with a static bot PAT

* Status: accepted
* Date: 2026-06-16

Technical Story: [RFC: Renovate on Forgejo](../rfc/rfc-renovate-forgejo.md)

## Context and Problem Statement

On GitHub, Renovate authenticates through a **GitHub App**: the `renovate-github-app-token`
CronJob exchanges an app ID, installation ID, and PEM private key for a **short-lived installation
token** every 30 minutes — machinery that exists because App tokens expire hourly and *must* be
re-minted. Forgejo has no "App" concept: it issues **personal access tokens** — long-lived,
scoped, tied to a user. There is nothing to rotate on a 30-minute cadence, and nothing to
exchange.

## Considered Options

* A static, scoped Forgejo PAT for a dedicated `renovate` bot user
* Keep minting short-lived tokens for Forgejo too
* Reuse a human's PAT (e.g. `Ryangr0`)
* OAuth2 application via Authentik
* Dynamic/short-lived Forgejo tokens

## Decision Outcome

Chosen option: "A static, scoped Forgejo PAT for a dedicated `renovate` bot user", because Forgejo
has no "App" concept — it issues long-lived, scoped personal access tokens, so there is nothing to
rotate on a 30-minute cadence and nothing to exchange.

Authenticate `webgrip-forgejo` with a **static, scoped Forgejo PAT** belonging to a dedicated
local `renovate` bot user. Both are **minted in-cluster by an idempotent Tier-1 provisioner Job**
([ADR-0003](adr-0003-bootstrap-task-pattern.md),
`kubernetes/apps/renovate/renovate-operator/forgejo-provisioner/`): it creates the bot user if
missing, reuses the stored token while it still authenticates, and otherwise mints a fresh scoped
token straight into the `renovate-forgejo-token` Secret as `RENOVATE_TOKEN` + `FORGEJO_TOKEN` (the
latter for the operator's discovery) — zero-touch, nothing hand-entered. **No token-minter CronJob
exists on the Forgejo path.** Required token scopes: `repo` (Read **and Write**), `user` (Read),
`issue` (Read **and Write**), `organization` (Read), plus `read:packages` only if Forgejo packages
become a datasource.

Registry credentials are not minted here: during dual-run the Forgejo job reuses the GitHub-App
minter's `RENOVATE_HOST_RULES` for GHCR — see
[ADR-0031](adr-0031-github-as-renovate-data-oracle.md).

The `renovate` bot is created via the admin path, **not** Authentik SSO, because the forge allows
external registration only (`ALLOW_ONLY_EXTERNAL_REGISTRATION=true`) and a non-interactive bot
shouldn't go through an OIDC login flow.

### Positive Consequences

* The GitHub-App token apparatus is **deleted, not ported**, on the Forgejo path: no CronJob, no
  RBAC, no `*/30` reconcile, no PEM key to safeguard — strictly fewer moving parts to fail.
* The bot is a **local Forgejo user**, deliberately outside Authentik SSO — machine identity that
  keeps working even if OIDC is down.
* At GitHub-path retirement, the `github-app-token` CronJob, its RBAC, and the GitHub-App keys in
  `renovate/operator` are removed — the rotation machinery leaves with the platform that needed it.

### Negative Consequences

* The trade-off is a **longer-lived credential**: a Forgejo PAT does not auto-expire, so its leak
  blast radius is larger. Mitigations: minimal scopes, a dedicated revocable bot identity, and the
  provisioner re-mints on its next run if the stored token no longer authenticates.

## Pros and Cons of the Options

### A static, scoped Forgejo PAT for a dedicated `renovate` bot user

* Good, because zero-touch: the provisioner mints the bot user and token in-cluster, nothing
  hand-entered, and re-mints if the stored token no longer authenticates.
* Good, because strictly fewer moving parts than the GitHub-App apparatus — no CronJob, no RBAC,
  no `*/30` reconcile, no PEM key to safeguard.
* Bad, because the PAT does not auto-expire, so its leak blast radius is larger.

### Keep minting short-lived tokens for Forgejo too

* Bad, because no App/installation-token exchange exists; a homegrown PAT-rotation CronJob would
  rebuild machinery the platform doesn't require.

### Reuse a human's PAT (e.g. `Ryangr0`)

* Bad, because no separable machine identity, can't be revoked without locking out the human,
  pollutes authorship/audit.

### OAuth2 application via Authentik

* Bad, because Renovate authenticates with a platform token, not an interactive OAuth flow; SSO
  for a headless bot adds an Authentik-up dependency for no gain.

### Dynamic/short-lived Forgejo tokens

* Bad, because out of scope now — revisit if Forgejo ever grows an installation-token equivalent.

## Links

* 2026-06-13 — proposed with the RFC (token then planned as a hand-entered OpenBao value +
  ExternalSecret)
* 2026-06-14 — sourcing refined: bot user + PAT minted in-cluster by an idempotent Tier-1
  provisioner Job ([ADR-0003](adr-0003-bootstrap-task-pattern.md)) — zero-touch
* 2026-06-16 — accepted
* 2026-07-03 — renumbered from ADR-0012 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
