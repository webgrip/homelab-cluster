# Secret rotation model — vault write + Reloader, dynamic creds as the endgame

* Status: accepted
* Date: 2026-07-01

Technical Story: [RFC: Security Hardening](../rfc/rfc-security-hardening.md)

## Context and Problem Statement

With the [SOPS → ESO/OpenBao migration](../blogs/2026-06-12-the-long-goodbye-to-sops.md) done,
secrets are values in OpenBao surfaced as Kubernetes Secrets by External Secrets — which changes
what "rotate a secret" *means*, and the cluster needs one written-down procedure rather than
per-secret folklore. The enabling piece is already deployed: **Stakater Reloader** in
`kube-system`, which restarts a workload when a Secret/ConfigMap it consumes changes — but it is
**opt-in per workload** via the `reloader.stakater.com/auto: "true"` annotation, so coverage is a
property of each app, not automatic.

## Considered Options

* A single vault write + ESO refresh + opt-in Reloader
* Reloader `--auto-reload-all`
* Scheduled blanket rotation (cron)
* Leave it undocumented

## Decision Outcome

Chosen option: "A single vault write + ESO refresh + opt-in Reloader", because one write at the
source propagates automatically with no human ceremony, while explicit per-workload opt-in keeps
at-rest-key consumers out of the restart path.

Rotation is a **single vault write**, propagated automatically:

1. Change the value at its source in **OpenBao** (`bao kv put secret/<app>/<name> …`).
2. The app's **`ExternalSecret`** re-reads it within its `refreshInterval` (default **1h**) and
   updates the Kubernetes Secret in place.
3. **Reloader** sees the Secret change and restarts the consuming workload — *provided that
   workload carries the `reloader.stakater.com/auto: "true"` annotation.* Annotating
   rotatable-secret consumers is therefore a required step, tracked in
   [Adding Applications](../general/adding-applications.md).
4. **Urgent rotation** (suspected leak) doesn't wait for the poll: force an immediate ESO re-sync
   (`kubectl annotate externalsecret <name> force-sync=$(date +%s) --overwrite`) — an explicit
   operator action, outside the GitOps loop, for incident response only.

**At-rest encryption keys are explicitly out of scope for rotation** (`AUTHENTIK_SECRET_KEY`,
Dependency-Track `secret.key`, app `*_ENCRYPTION_KEY`s): regenerating them corrupts data already
encrypted with the old key. Their consumers should **not** carry the auto-reload annotation.

### Positive Consequences

* Rotation is an operation, not a ceremony — no `sops --encrypt`, no commit, no manual restart.
* Propagation latency is bounded by `refreshInterval`, **tunable per secret** (ExternalSecrets
  default to the conservative 1h); the urgent path bypasses it entirely.

### Negative Consequences

* Reloader coverage is a **checklist item**, not a guarantee — a rotated value behind an
  un-annotated workload sits unused until the next restart. The at-rest exclusion makes this a
  feature, not only a gap.
* This model rotates **static** credentials well but never makes them *short-lived*. The endgame —
  no long-lived DB credentials at all — is now piloted:
  [ADR-0016](adr-0016-openbao-dynamic-postgres-credentials.md) mints TTL-bounded Postgres creds
  from OpenBao's `database` engine.

## Pros and Cons of the Options

### A single vault write + ESO refresh + opt-in Reloader

* Good, because rotation needs no `sops --encrypt`, no commit, and no manual restart.
* Good, because explicit opt-in keeps at-rest-key consumers out of the restart path.
* Bad, because coverage is a per-workload checklist item — a rotated value behind an un-annotated
  workload sits unused until the next restart.

### Reloader `--auto-reload-all`

* Good, because simpler coverage.
* Bad, because blunt: it would restart apps on *at-rest-key* changes too, and turn any ESO blip
  into a fleet-wide restart.

### Scheduled blanket rotation (cron)

* Bad, because security theater for static secrets with no signal of compromise; it churns pods
  for no gain — dynamic creds (short TTL by design) are the principled version of "rotate often".

### Leave it undocumented

* Bad, because the point of the migration was to remove the human from the secret loop; an
  undocumented rotation path puts them right back in it.

## Links

* 2026-06-12 — accepted
* 2026-07-01 — the dynamic-credential endgame left the RFC stage:
  [ADR-0016](adr-0016-openbao-dynamic-postgres-credentials.md) accepted, freshrss pilot under way
* 2026-07-03 — renumbered from ADR-0009 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
