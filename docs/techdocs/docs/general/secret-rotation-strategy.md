# Secret rotation strategy — every secret class, every pod type

How we make **all** secrets in the cluster rotatable — not just database credentials. The dynamic-DB
work ([ADR-0016](../adr/adr-0016-openbao-dynamic-postgres-credentials.md), the
[explainer](dynamic-db-credentials-explained.md)) is the flagship, but it only covers one class. This
doc categorizes every secret, maps it to the pod type that holds it, and sets the rotation approach —
including the honest limits, because **not every secret can be made "dynamic," and some can't rotate
at all.**

## The five secret classes

| Class | What it is | Can OpenBao *mint* it? | Rotation model |
|---|---|---|---|
| **A — Dynamic DB creds** | Postgres / MySQL app logins | **Yes** — `database` engine | Minted short-lived; auto-revoked. *No human in the loop.* |
| **B — Provided external creds** | API tokens (GitHub, Cloudflare), S3/object keys, OIDC client secrets, webhook tokens | **No** — the external system owns the value | Rotate at the source → write to OpenBao KV → ESO re-reads → consumer reloads |
| **C — Generated entropy** | session/CSRF keys, bot/robot passwords, admin passwords | Generated *in-cluster* (ESO generator), not minted per-request | Regenerate + (for bot creds) re-register at the target |
| **D — At-rest encryption keys** | `N8N_ENCRYPTION_KEY`, `AUTHENTIK_SECRET_KEY`, DT `secret.key`, invoiceninja `APP_KEY`, harbor `secretKey` | **No** | **Un-rotatable** — regenerating corrupts stored data. Pinned, generate-once. |
| **E — TLS / PKI** | leaf certs, issuer creds | cert-manager mints/renews certs | Already auto-rotated by cert-manager (out of scope here) |

**The hard truth about "easily rotatable API tokens":** OpenBao has dynamic engines for databases
(in use), plus AWS/GCP/SSH/PKI/Consul (not wired) — but **none for GitHub, Cloudflare, DockerHub,
Authentik-OIDC, or internal S3 (Garage/MinIO)**. So every API token in the cluster is **Class B**:
you cannot mint it dynamically. "Easily rotatable" for these means the *propagation* is automatic —
change it once at the provider, and it flows to the pod without hand-editing manifests.

## Secret class × pod type

| | app-server | database | operator/controller | job / cronjob | ci-runner |
|---|---|---|---|---|---|
| **A** Dynamic DB | freshrss (✓) → n8n, forgejo… | — | — | — | — |
| **B** External token | grafana (github-api, oauth), harbor (registry-proxy, s3), forgejo (oidc, s3) | — | cloudflared, external-dns, cert-manager, flux-receiver, KEDA scaler | renovate, sbom-uploader, backups | forgejo-actions (ci-pat, codeberg), ARC/GHA app |
| **C** Generated | searxng session key, grafana/backstage session | CNPG DB passwords (7) | — | — | forgejo/harbor bot passwords |
| **D** At-rest key | n8n, authentik, dep-track, invoiceninja, harbor, sparkyfitness, backstage | — | — | — | — |

## The rotation approach, per class

### A — Dynamic DB credentials → the OpenBao database engine
**Done for freshrss.** Roll out by workload shape (this is the reusable win):

- **Surge-capable app** (multi-replica or stateless, no single-attach RWO volume): dynamic creds +
  an ordinary rolling restart = **zero downtime, no pooler**. → authentik, grafana, guac, backstage,
  devex, sparkyfitness-server.
- **Single-replica RWO app** (restart = downtime): needs the **PgBouncer sidecar** (the freshrss
  template). → n8n, forgejo, dependency-track. MySQL (invoiceninja) needs a MySQL pooler; harbor
  needs its Multi-Attach fix first.

Use a **longer TTL** for the rolling-restart apps (8–24h) so rotation isn't a constant restart;
a **short TTL** (~1h) for pooler apps, where rotation is restart-free.

### B — Provided external creds → the ADR-0015 write-and-propagate model
This is the answer for **API tokens, S3 keys, and OIDC secrets**. They can't be minted, so "rotation"
is: **regenerate at the provider → `bao kv put secret/<path>` → ESO re-reads → Reloader restarts the
consumer.** To make it *easy* and *fast*:

1. **Lower `refreshInterval`** to `15m` on the highest-value tokens (S3, GitHub PAT, Cloudflare,
   OIDC) so a rotation lands within minutes instead of an hour.
2. **Zero-downtime propagation follows the same workload-shape rule** — multi-replica/stateless
   consumers (cloudflared ×2, authentik-server ×2, the stateless controllers, and every job/runner
   which just re-reads on its next run) get it for free. Single-replica RWO consumers eat a brief
   restart (see the hard cases below).
3. **Automate the provider side where an API exists** — e.g., a scheduled job that mints a fresh
   Cloudflare/GitHub token and writes it to OpenBao, closing the "regenerate at the provider" gap.
   (Where no API exists, it stays a manual `bao kv put`.)

### C — Generated entropy → regenerate + re-register
- **Self-contained** (session/CSRF keys): regenerate the ESO Secret + restart. Low value (ADR-0015
  calls scheduled rotation of these "theater") — do it on a long cadence or on suspicion only.
- **Bot/robot passwords** (Forgejo/Harbor): two-sided — the value must be re-registered on the
  target. Each already has a provisioner that does exactly that; scheduled rotation = a small job that
  regenerates then re-triggers the provisioner. (Deferred; modest value.)

### D — At-rest encryption keys → do not rotate
Genuinely un-rotatable without an app-level re-encryption migration (regenerating corrupts stored
data). OpenBao's **transit** engine is *not* a workaround, because none of these apps support an
external KMS — they hold a local key. Leave them pinned (`refreshInterval: "0"`), un-annotated for
Reloader, and documented as out-of-scope. This is the honest boundary.

## The "hard" cases — single-replica RWO reading a secret at startup

These read their secret only at process start on a ReadWriteOnce volume, so rotating **any** of their
secrets (not just DB creds) means a `Recreate` restart = brief downtime — the same problem freshrss
solved for its DB cred:

`n8n`, `invoiceninja`, `forgejo`, `grafana`, `harbor`, `dependency-track`, `gitea-mirror`,
`authentik-worker`.

For their **DB creds**, the pooler pattern gives zero-downtime. For their **Class B/C secrets**
(API tokens, session keys), the options are: (a) accept the brief restart on rotation (fine for
low-traffic apps — Reloader handles it), (b) make the app re-read the secret from a mounted file at
runtime (app-specific, like freshrss's PHP-config trick), or (c) leave rare-rotation secrets to a
maintenance-window restart. Most of these are low-traffic; **a Reloader-triggered restart is the
pragmatic default**, reserving the pooler/file-reread effort for genuinely hot paths.

## Prioritized plan

1. **Finish hardening the freshrss dynamic-cred route** (P1 done — object grants; then drop
   `shareProcessNamespace`, rotate `vault_admin`, tighten netpol — see the
   [ADR-0016](../adr/adr-0016-openbao-dynamic-postgres-credentials.md) roadmap).
2. **Class B fast-propagation:** lower `refreshInterval` to 15m on the high-value external tokens
   (S3, GitHub PAT, Cloudflare DNS/Tunnel, OIDC) and confirm each consumer is Reloader-wired. *This
   is the cheapest, highest-coverage win for "easily rotatable API tokens."*
3. **Class A rollout Phase 2** — the surge-capable Postgres apps (rolling-restart, no pooler).
4. **Class A rollout Phase 3** — the RWO Postgres apps via the freshrss pooler template; then MySQL.
5. **Class C** (bot-cred scheduled rotation) and **provider-side automation** for Class B — lower
   priority, modest value.
6. **Class D** — no action; document the boundary.

## Honest limits

- **API tokens can't be dynamic** — no OpenBao engine for our providers; best case is fast, automatic
  *propagation* of a value you still rotate at the source.
- **At-rest keys can't rotate at all** without re-encryption.
- **Single-replica RWO apps** pay a restart to rotate anything read at startup, unless fronted by a
  pooler (DB) or reworked to re-read at runtime — worth it only for hot paths.

## See also

[ADR-0015 — secret rotation model](../adr/adr-0015-secret-rotation-model.md) ·
[ADR-0016 — dynamic Postgres credentials](../adr/adr-0016-openbao-dynamic-postgres-credentials.md) ·
[dynamic-db-credentials runbook](../runbooks/dynamic-db-credentials.md) ·
[the pilot postmortem](../blogs/2026-07-03-dynamic-db-credentials-pilot.md)
