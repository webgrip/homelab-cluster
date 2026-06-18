# ADR-0009: Secret rotation model — vault write + Reloader, dynamic creds as the endgame

> Status: **Accepted** · Date: 2026-06-12 · Part of [RFC: Security Hardening](../rfc/rfc-security-hardening.md)

## Context

With the [SOPS → ESO/OpenBao migration](../blogs/2026-06-12-the-long-goodbye-to-sops.md) done,
secrets are no longer encrypted files in git — they are values in OpenBao surfaced as Kubernetes
Secrets by External Secrets. That changes what "rotate a secret" *means*, and the cluster needs one
defined, written-down procedure rather than per-secret folklore. The enabling piece is already
deployed: **Stakater Reloader** in `kube-system`, which restarts a workload when a Secret/ConfigMap
it consumes changes — but it is **opt-in per workload** via the `reloader.stakater.com/auto: "true"`
annotation, so coverage is a property of each app, not automatic.

## Decision

Rotation is a **single vault write**, propagated automatically:

1. Change the value at its source in **OpenBao** (`bao kv put secret/<app>/<name> …`).
2. The app's **`ExternalSecret`** re-reads it within its `refreshInterval` (default **1h**) and
   updates the Kubernetes Secret in place.
3. **Reloader** sees the Secret change and restarts the consuming workload — *provided that workload
   carries the `reloader.stakater.com/auto: "true"` annotation.* Annotating rotatable-secret
   consumers is therefore a required step, tracked in [Adding Applications](../general/adding-applications.md).
4. **Urgent rotation** (suspected leak) doesn't wait for the poll: force an immediate ESO re-sync
   (`kubectl annotate externalsecret <name> force-sync=$(date +%s) --overwrite`) — an explicit
   operator action, outside the GitOps loop, for incident response only.

**At-rest encryption keys are explicitly out of scope for rotation** (`AUTHENTIK_SECRET_KEY`,
Dependency-Track `secret.key`, app `*_ENCRYPTION_KEY`s): regenerating them corrupts data already
encrypted with the old key. Their consumers should **not** carry the auto-reload annotation.

## Consequences

- Rotation is an operation, not a ceremony — no `sops --encrypt`, no commit, no manual restart.
- Propagation latency is bounded by `refreshInterval` and is **tunable per secret** (lower it on
  high-value credentials; the urgent path bypasses it entirely). All 37 ExternalSecrets currently
  sit at the conservative 1h default.
- Reloader coverage is a **checklist item**, not a guarantee — a rotated value behind an
  un-annotated workload will sit unused until the next restart. The at-rest exclusion makes this a
  feature, not only a gap.
- This model rotates **static** credentials well but never makes them *short-lived*. The real
  endgame is to stop having long-lived DB credentials at all — see
  [RFC: Dynamic Database Credentials](../rfc/rfc-dynamic-database-credentials.md).

## Alternatives considered

- **Reloader `--auto-reload-all`** (reload every workload on any mounted-secret change, no
  annotation) — simpler coverage, but blunt: it would restart apps on *at-rest-key* changes too,
  and turn any ESO blip into a fleet-wide restart. Rejected in favor of explicit opt-in.
- **Scheduled blanket rotation** (rotate everything on a cron) — security theater for static
  secrets with no signal of compromise; churns pods for no gain. Dynamic creds (short TTL by design)
  are the principled version of "rotate often."
- **Leave it undocumented** — rely on memory. Rejected; the point of the migration was to remove the
  human from the secret loop, and an undocumented rotation path puts them right back in it.
