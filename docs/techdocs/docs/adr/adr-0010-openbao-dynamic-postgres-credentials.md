# Adopt OpenBao's database engine for short-lived Postgres credentials

* Status: accepted
* Date: 2026-07-02

Technical Story:
[RFC: Dynamic Database Credentials via OpenBao](../rfc/rfc-dynamic-database-credentials.md)

## Context and Problem Statement

Application database passwords are static and long-lived. They sit in OpenBao KV and are easy to
rotate ([ADR-0009](adr-0009-secret-rotation-model.md)), but rotation is a manual, reactive act and
the credentials persist between rotations. OpenBao ships a **`database` secrets engine** that can
mint per-request, TTL-bounded Postgres roles and revoke them automatically — turning "rotate
often" from a chore into a default. Before this decision OpenBao ran **only** the KV-v2 engine, so
this is an additive capability, reconciled by the same scoped `config-admin` bootstrap that
already manages engines and policies.

## Considered Options

* OpenBao's `database` secrets engine
* Keep static creds + faster rotation (ADR-0009 with a short `refreshInterval`)
* CNPG-native password rotation (`managed.roles` on a schedule)
* Cert-based Postgres auth (`clientcert`) via OpenBao PKI

## Decision Outcome

Chosen option: "OpenBao's `database` secrets engine", because it mints per-request, TTL-bounded
Postgres roles and revokes them automatically — turning "rotate often" from a chore into a
default — as an additive capability reconciled by the same scoped `config-admin` bootstrap that
already manages engines and policies.

Enable the **`database` secrets engine** and use it to issue **short-lived, per-workload Postgres
credentials** for apps whose connection model tolerates periodic credential change. OpenBao
connects to each CNPG cluster as a dedicated, non-superuser **`vault_admin`** role that can
`CREATE`/`DROP ROLE`; per-app role definitions carry a `default_ttl` (~1h) and a `max_ttl`. These
ephemeral roles are **additive to**, not a replacement for, CNPG's own `<app>-db-app` role (which
stays as owner/break-glass). Roll out **pilot-first** (freshrss); apps that don't fit stay on
static credentials. Full design, boundary, and risks in the
[RFC](../rfc/rfc-dynamic-database-credentials.md); operations in the
[dynamic-db-credentials runbook](../runbooks/dynamic-db-credentials.md). Lives in
`kubernetes/apps/security/openbao/bootstrap/` (engine + `vault_admin` reconcile) and
`kubernetes/apps/security/openbao/app/clustersecretstore-db.yaml` (the `openbao-db` store).

### Positive Consequences

* Leaked DB credentials expire in ~an hour; access becomes **per-lease attributable** in the audit
  log; a single workload can be severed without touching others.
* Reversible per app: drop the ExternalSecret, repoint at the CNPG static secret — exercised for
  real on 2026-07-02 (see Links).
* Opens the door to OpenBao's **PKI** (short-lived mTLS certs) and **transit** engines on the same
  "OpenBao does more than KV" track.

### Negative Consequences

* A new privileged dependency: the `vault_admin` Postgres connection is a high-value credential
  that must be tightly scoped and audited — the design's central risk.
* Credential changes mean **reconnects**: only restart-tolerant (or pooler-fronted) apps are good
  candidates; heavy-pool / poor-reconnect apps stay static — dynamic creds are fit-for-purpose,
  not a mandate.

### Implementation notes (pilot: freshrss)

Decisions locked while building the freshrss pilot — see the
[operations runbook](../runbooks/dynamic-db-credentials.md):

* **Engine mount without root.** `init.sh` only mounts `database` on a *fresh* cluster and
  `generate-root` returns `405` here, so `config-admin` was granted a narrow `sys/mounts/database*`
  and the reconcile loop mounts the engine. Reversible; `config-admin` can already self-escalate via
  `sys/policies/acl/*`, so it is little new exposure.
* **No `rotate-root`.** `vault_admin`'s password is owned by CNPG `managed.roles` (reconciled ~30s);
  OpenBao rotating it would desync. It is a generate-once value, the same in the `security` (config
  job) and app namespaces, seeded via a KV round-trip.
* **Defensive revocation is mandatory.** A bare `DROP ROLE` fails if the ephemeral role owns objects
  or has live sessions: `pg_terminate_backend` → `REASSIGN OWNED TO <owner>` → `DROP OWNED` →
  `DROP ROLE`.
* **PG16+ grant constraint.** A non-superuser `CREATEROLE` role can only `GRANT` membership in a role
  it holds `ADMIN OPTION` on. Verify `admin_option = t` for `vault_admin` on the app role; if CNPG's
  `inRoles` didn't set it, a one-time `GRANT <role> TO vault_admin WITH ADMIN OPTION`.
* **ESO reads a separate store.** The KV `openbao` store (`path: secret`) cannot read
  `database/creds/*`; a dedicated `openbao-db` store (`path: database`, `version: v1`) is required.
  ESO re-reads (mints a new lease) each refresh — size `refreshInterval` < `default_ttl`.

#### Zero-downtime is a property of the workload shape, not the secret

Rotation means the app must adopt a new credential. The discriminator is **whether two of the app's
pods can coexist during a restart**:

* **Surge-capable** (multi-replica, or a Deployment with no single-attach RWO volume) → an ordinary
  **rolling restart is already zero-downtime**; dynamic creds need only an ExternalSecret on
  `creds/<app>` + Reloader. Use a **longer TTL** (8–24h) so rotation isn't a constant rolling
  restart. No pooler.
* **RWO single-attach** (single-replica + `Recreate`, e.g. freshrss/n8n/forgejo) → a restart is a
  real gap. Zero-downtime requires a **PgBouncer sidecar**: the app talks to it on loopback with a
  *stable* credential; only the pooler→Postgres credential rotates, reloaded (`SIGHUP`/`RELOAD`)
  without dropping client connections. Here a **short TTL** (~1h) is free of app restarts.

At-rest encryption keys stay out of scope (regenerating corrupts data); OpenBao's **transit** engine
is *not* a workaround because no app in the cluster supports an external KMS — they hold a local key.

## Pros and Cons of the Options

### OpenBao's `database` secrets engine

* Good, because a leaked credential expires in ~an hour, access is per-lease attributable, and a
  single workload can be severed without touching others.
* Bad, because the `vault_admin` Postgres connection is a new high-value privileged dependency
  that must be tightly scoped and audited.
* Bad, because credential changes mean reconnects — only restart-tolerant (or pooler-fronted) apps
  are good candidates.

### Keep static creds + faster rotation (ADR-0009 with a short `refreshInterval`)

Right for apps that can't tolerate connection churn; not the edge for those that can — see
[ADR-0009](adr-0009-secret-rotation-model.md).

* Good, because simpler.
* Bad, because the credential still *exists* between rotations and rotation stays operator-driven.

### CNPG-native password rotation (`managed.roles` on a schedule)

* Bad, because coarse (whole-role, not per-workload), not attributable, still long-ish-lived.

### Cert-based Postgres auth (`clientcert`) via OpenBao PKI

Captured as future work in the [RFC](../rfc/rfc-dynamic-database-credentials.md).

* Good, because elegant and passwordless.
* Bad, because a bigger lift (mTLS to Postgres, cert distribution); sequenced *after* the database
  engine proves the pattern.

## Links

* 2026-06-12 — proposed with the RFC
* 2026-07-01 — infrastructure landed: `database` engine mounted via the `config-admin` reconcile
  loop, freshrss `vault_admin` role, dedicated `openbao-db` ClusterSecretStore + PgBouncer
  pipeline (`07ae7ec0`, `4439875b`)
* 2026-07-01 — freshrss pilot cut over to the PgBouncer sidecar on dynamic creds (`678b1da`);
  status → accepted
* 2026-07-02 — pilot **reverted** to static creds (`03f222e`): credential mint blocked on the
  PG16 `ADMIN OPTION` constraint and the PgBouncer sidecar could not start
* 2026-07-02 — cutover **re-applied** (`e805c83a`, accidentally swept into a VictoriaMetrics
  commit while fixes were still in flight)
* 2026-07-02 — pilot **re-reverted** to static creds (`391eeb19`): the PgBouncer sidecar needs
  hands-on runtime iteration. The decision stands; the pilot is paused, not abandoned
