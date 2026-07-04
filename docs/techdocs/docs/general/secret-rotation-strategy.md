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
| **D — At-rest encryption keys** | `N8N_ENCRYPTION_KEY`, DT `secret.key`, invoiceninja `APP_KEY`, harbor `secretKey` | **No** (it *encrypts*) | **Rotatable only if the key isn't the direct data key** — via envelope encryption, app-native rekey, or disk-level encryption. Some apps support it, some don't (see §D). |
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
- **Break-glass (on suspected compromise): the label sweep.** The mechanism to regenerate a C secret
  is `kubectl delete secret <name>` → ESO recreates it with a fresh value → Reloader restarts the
  consumer → the provisioner re-registers (bot creds). The **sharp edge**: D-level at-rest keys are
  *also* generate-once ESO secrets, so a blind "delete all generated" would regenerate a data key and
  corrupt data. Make it safe by driving it off a label: put `rotate.webgrip.io/on-compromise: "true"`
  on every C secret (**never** a D key), then break-glass is one action —
  `kubectl delete secret -l rotate.webgrip.io/on-compromise=true -A` — with D structurally excluded.
  (See the OpenBao-side break-glass — `bao lease revoke -prefix <mount>/` — in the
  [dynamic-db-credentials runbook](../runbooks/dynamic-db-credentials.md); the two are complementary:
  leases for dynamically-minted creds, the label sweep for generated ones.)

### D — At-rest encryption keys → rotatable *if the key isn't the direct data key*

The earlier "un-rotatable" framing was too absolute. **The principle: never let the rotatable secret
directly encrypt the data.** Put a cheap-to-re-wrap key between them (**envelope encryption**:
data → **DEK** (data key) → wrapped by a **KEK** (key-encryption key); rotating the KEK just re-wraps
the tiny DEK, no bulk re-encryption), or move encryption below the app (disk), or use the app's own
rekey path. Search terms: *envelope encryption, KEK/DEK, key wrapping, rewrap, TDE*.

Four approaches, most-achievable first:

1. **Disk-level encryption — the baseline win (app-agnostic).** An encrypted StorageClass / LUKS under
   the PVCs (CNPG delegates at-rest encryption to the StorageClass — it doesn't encrypt volumes
   itself). LUKS *is* envelope encryption: passphrases occupy **key slots** wrapping one master volume
   key, so you rotate by adding a new slot key and removing the old — **no disk re-encryption**. Root
   the LUKS/StorageClass key in OpenBao so *that* is centrally rotatable. Defends **stolen disk / PVC /
   backup** — not a live app compromise (the app still sees plaintext). Highest leverage, zero app
   cooperation.
2. **App-native rekey — free security where it exists:**
   - **n8n** ✅ — native envelope encryption + rotation (`N8N_ENV_FEAT_ENCRYPTION_KEY_ROTATION`): the
     master key wraps a rotating data key; existing records re-encrypt lazily on next write. (One-way,
     no downgrade after enabling — back up first.)
   - **InvoiceNinja / Laravel** ✅-with-work — `APP_PREVIOUS_KEYS` keeps old ciphertext decryptable
     during a transition, then a re-encrypt migration job upgrades rows. (Rotating logs out sessions.)
   - **Dependency-Track** ⚠️ partial — Tink file-keyset KEK rotation for *new* secrets only; no
     re-crypt of existing (external-KMS providers are planned).
   - **Harbor `secretKey`** ❌ — maintainers confirm no rotation without full DB re-encryption; treat
     as fixed for the deployment's life, store in OpenBao, restrict access, "rebuild + re-enter" on
     compromise rather than rotate.
   - **Authentik `SECRET_KEY`** — **reclassify: it's a signing key, not an at-rest data key.** Rotating
     it just invalidates sessions (users re-login); no data migration, no corruption. Rotatable anytime.
3. **OpenBao `transit` as a KMS (encryption-as-a-service):** apps call transit to encrypt/decrypt;
   `rotate` adds a key version, old ciphertext still decrypts, `rewrap` upgrades lazily. **Only works
   for code you write, or apps that natively support a KMS backend** — not the stock apps above. The
   direction to prefer as apps grow KMS support (DT's planned providers, pg_tde below).
4. **DB-engine TDE (`pg_tde`, Percona/EDB):** KMS-rooted, re-wrap-only rotation for *all* DB data at
   once, principal key held in OpenBao — but needs a TDE-capable Postgres, not stock CNPG. A future
   upgrade for the highest-value databases; overkill cluster-wide today.

**Recommendation:** (1) do **disk-level encryption rooted in OpenBao** as the baseline — it makes the
app key stop being the only boundary and is rotatable via LUKS slots; (2) turn on **native rekey**
where the app has it (n8n, Laravel); (3) **reclassify Authentik** as a signing key (rotate freely);
(4) accept **Harbor as fixed-and-guarded**; (5) reserve **transit / pg_tde** for code-you-write and
future hot-DB upgrades. Threat-model note: disk/DB encryption defends stolen media; app-level DEKs
defend the leaked-DB-dump/column case — pick per asset.

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
5. **Class C break-glass** — add `rotate.webgrip.io/on-compromise: "true"` to the C secrets and a
   one-command label sweep + incident runbook (safe because D keys are never labeled). Cheap, and it's
   the thing you actually want the day something is compromised.
6. **Class D baseline** — **disk-level encryption (encrypted StorageClass / LUKS) rooted in OpenBao**,
   app-agnostic and rotatable via key slots. Then turn on **native rekey** where the app supports it
   (n8n, Laravel), and **reclassify Authentik** as a signing key.
7. **Class C** scheduled bot-cred rotation and **provider-side automation** for Class B — lower
   priority, modest value.
8. **Class D advanced** (transit-as-KMS for own code, `pg_tde` for hot DBs) — future.

## Honest limits

- **SaaS API tokens can't be minted dynamically by *our* OpenBao today** — no in-core engine for
  GitHub/Cloudflare/DockerHub. But the space is moving: OpenBao ships an official
  [`openbao-plugin-secrets-oauthapp`](https://github.com/openbao/openbao-plugin-secrets-oauthapp)
  (OAuth brokering, incl. a "Custom" provider), there's a community
  [`vault-plugin-secrets-github`](https://github.com/martinbaillie/vault-plugin-secrets-github)
  (1-hour GitHub App tokens), and Terraform Cloud tokens are native. Cloudflare/DockerHub need a
  custom plugin or stay static-with-fast-propagation. Follow it in the
  [OpenBao GitHub Discussions](https://github.com/orgs/openbao/discussions) and the
  [`openbao/openbao-plugins`](https://github.com/openbao/openbao-plugins) repo.
- **At-rest keys are rotatable only indirectly** — via envelope encryption, app-native rekey, or
  disk-level encryption (see §D). A few of our apps genuinely can't (Harbor); Authentik's key isn't
  even an at-rest key.
- **Single-replica RWO apps** pay a restart to rotate anything read at startup, unless fronted by a
  pooler (**PgBouncer** for Postgres, **ProxySQL** for MySQL) or made HA — worth it only for hot paths.
  Redis needs neither (ACL multi-password); prefer making an app HA over adding a pooler where you can.

## See also

[ADR-0015 — secret rotation model](../adr/adr-0015-secret-rotation-model.md) ·
[ADR-0016 — dynamic Postgres credentials](../adr/adr-0016-openbao-dynamic-postgres-credentials.md) ·
[dynamic-db-credentials runbook](../runbooks/dynamic-db-credentials.md) ·
[the pilot postmortem](../blogs/2026-07-03-dynamic-db-credentials-pilot.md)
