# ADR-0010: Adopt OpenBao's database engine for short-lived Postgres credentials

> Status: **Proposed** · Date: 2026-06-12 · Part of [RFC: Dynamic Database Credentials](rfc-dynamic-database-credentials.md)

## Context

Application database passwords are static and long-lived. They're now in OpenBao KV and easy to
rotate ([ADR-0009](adr-0009-secret-rotation-model.md)), but rotation is still a manual, reactive act
and the credentials persist between rotations. OpenBao ships a **`database` secrets engine** that can
mint per-request, TTL-bounded Postgres roles and revoke them automatically — turning "rotate often"
from a chore into a default. OpenBao currently runs **only** the KV-v2 engine, so this is an
additive capability, reconciled by the same scoped `config-admin` bootstrap that already manages
engines and policies.

## Decision

*(Proposed.)* Enable the **`database` secrets engine** and use it to issue **short-lived, per-workload
Postgres credentials** for apps whose connection model tolerates periodic credential change. OpenBao
connects to each CNPG cluster as a dedicated, non-superuser **`vault_admin`** role that can
`CREATE`/`DROP ROLE`; per-app role definitions carry a `default_ttl` (~1h) and a `max_ttl`. These
ephemeral roles are **additive to**, not a replacement for, CNPG's own `<app>-db-app` role (which
stays as owner/break-glass). Roll out via a **pilot-first** sequence; apps that don't fit stay on
static credentials. Full design, boundary, and risks in the
[RFC](rfc-dynamic-database-credentials.md).

## Consequences

- Leaked DB credentials expire in ~an hour; access becomes **per-lease attributable** in the audit
  log; a single workload can be severed without touching others.
- A new privileged dependency: the `vault_admin` Postgres connection is a high-value credential that
  must be tightly scoped and audited — the design's central risk.
- Credential changes mean **reconnects**: Reloader restarts the consumer on each rotation, so only
  restart-tolerant apps are good candidates. Heavy-pool / poor-reconnect apps stay static — dynamic
  creds are fit-for-purpose, not a mandate.
- Reversible per app: drop the ExternalSecret, repoint at the CNPG static secret.
- Opens the door to OpenBao's **PKI** (short-lived mTLS certs) and **transit** (encryption-as-a-
  service, retiring app at-rest keys) engines on the same "OpenBao does more than KV" track.

## Alternatives considered

- **Keep static creds + faster rotation** (ADR-0009 with a short `refreshInterval`) — simpler, no new
  engine, but the credential still *exists* between rotations and rotation is still operator-driven.
  The right answer for apps that can't tolerate connection churn; not the edge for those that can.
- **CNPG-native password rotation** — CNPG can reconcile a `managed.roles` password on a schedule,
  but it's coarse (whole-role, not per-workload), not attributable, and still long-ish-lived.
- **cert-based Postgres auth (`clientcert`)** via OpenBao PKI — elegant and passwordless, but a bigger
  lift (mTLS to Postgres, cert distribution) and better sequenced *after* the database engine proves
  the dynamic-credential pattern. Captured as future work in the RFC.
