# ADR-0012: Authenticate Renovate to Forgejo with a static bot PAT

> Status: **Accepted** (2026-06-16) · Date: 2026-06-13 · Part of [RFC: Renovate on Forgejo](rfc-renovate-forgejo.md)
>
> **Refinement (2026-06-16):** the static bot PAT is now **minted in-cluster by an idempotent
> provisioner Job** ([ADR-0019](adr-0019-bootstrap-task-pattern.md)) — which also creates the bot user
> — rather than hand-entered into OpenBao. The decision (a long-lived, scoped Forgejo bot token, not a
> GitHub-App-style rotating token) is unchanged; the *sourcing* is now zero-touch.

## Context

On GitHub, Renovate authenticates through a **GitHub App**: a CronJob (`renovate-github-app-token`)
exchanges an app ID, installation ID, and PEM private key for a **short-lived installation token**
every 30 minutes, writes it to `renovate-runtime-token`, and — in the same step — assembles a
`RENOVATE_HOST_RULES` JSON so GHCR is authenticated with that same rotating token. This machinery
exists because GitHub App tokens expire hourly and *must* be re-minted.

Forgejo has no "App" concept. It issues **personal access tokens** — long-lived, scoped, tied to a
user — created by an admin or by the user. There is nothing to rotate on a 30-minute cadence, and
nothing to exchange. The cluster already has the right home for such a value: OpenBao + ESO, the
backend that holds every other Forgejo-ecosystem secret ([External Secrets](../external-secrets-plan.md)).

## Decision

Authenticate `webgrip-forgejo` with a **static, scoped Forgejo PAT** belonging to a dedicated local
`renovate` bot user. Store the token once in OpenBao (`renovate/forgejo`) and project it via a single
**ExternalSecret** into `renovate-forgejo-token` as `RENOVATE_TOKEN` + `FORGEJO_TOKEN` (the latter for
the operator's discovery). **No token-minter CronJob exists on the Forgejo path.** Required token
scopes: `repo` (Read **and Write**), `user` (Read), `issue` (Read **and Write**), `organization`
(Read), plus `read:packages` only if Forgejo packages become a datasource.

Registry credentials (`RENOVATE_HOST_RULES`) are likewise **static** here: because GHCR auth no longer
rides on a rotating App token but on a fixed `read:packages` PAT
([ADR-0013](adr-0013-github-as-renovate-data-oracle.md)), the entire host-rules JSON is stored in
OpenBao and materialised verbatim by ESO — nothing is computed at runtime.

The `renovate` bot is created via the `gitea_admin` break-glass / `forgejo admin user create` path,
**not** Authentik SSO, because the forge allows external registration only
(`ALLOW_ONLY_EXTERNAL_REGISTRATION=true`) and a non-interactive bot shouldn't go through an OIDC login
flow.

## Consequences

- The whole GitHub-App token apparatus on the Forgejo path is **deleted, not ported**: no CronJob, no
  RBAC, no `*/30` reconcile, no PEM private key to safeguard. One static secret replaces a running
  rotation loop — strictly simpler and fewer moving parts to fail.
- The trade-off is a **longer-lived credential**. A Forgejo PAT does not auto-expire like an
  installation token, so its blast radius on leak is larger. Mitigations: minimal scopes, a dedicated
  bot identity (revocable independently of any human), and rotation via the standard
  OpenBao-write → ESO-refresh model ([ADR-0009](adr-0009-secret-rotation-model.md)) if needed.
- The bot is a **local Forgejo user**, deliberately outside Authentik SSO — consistent with treating
  it as machine identity, and it keeps working even if OIDC is down.
- At GitHub-path retirement, the `github-app-token` CronJob, its RBAC, and the GitHub-App keys in
  `renovate/operator` are removed — the rotation machinery leaves with the platform that needed it.

## Alternatives considered

- **Keep minting short-lived tokens for Forgejo too.** Forgejo has no App/installation-token exchange,
  so this would mean a homegrown PAT-rotation CronJob re-creating tokens via the API — rebuilding
  machinery the platform doesn't require. Rejected; complexity with no expiry benefit the platform asks
  for.
- **Reuse a human's PAT (e.g. `Ryangr0`).** No separable machine identity, can't be revoked without
  locking out the human, and pollutes authorship/audit. Rejected — bots get their own account.
- **OAuth2 application via Authentik.** Forgejo supports OIDC login, but Renovate authenticates with a
  platform token, not an interactive OAuth flow; wiring SSO for a headless bot adds a runtime
  dependency (Authentik up) for no gain. Rejected.
- **Eventually adopt dynamic/short-lived Forgejo tokens** if Forgejo grows an installation-token
  equivalent — revisit then; out of scope now.
