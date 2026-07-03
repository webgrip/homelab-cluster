# Runbook: External Secrets (ESO)

Operations for the ESO + OpenBao secret backend. **Adding or migrating a secret is the
`external-secrets` skill** (recipes, shapes, store choice) — this page is triage, DR, and the
gotchas that cost real time. Rotating a value: [secret-rotation](secret-rotation.md).

The SOPS→ESO migration is **complete** except one app secret: **`zomboid/app/secret.sops.yaml`
is the last app still on SOPS.** The permanent SOPS floor (age key, `cluster-secrets`,
`talsecret`, `github-deploy-key`) stays.

## Dependency chain

```text
Git (ExternalSecret / PushSecret) ──▶ ESO controller ──▶ writes real k8s Secret ──▶ App pod
                                          │                     ▲
                  ClusterGenerator (random) ┘                   │ (cached — no runtime dep)
                  ClusterSecretStore: openbao   ──▶ OpenBao ───┘   (sealed until unsealed)
                  ClusterSecretStore: kube-store ──▶ writes into authentik ns (OIDC push)
```

**Cached-Secret invariant:** once ESO has written a Secret, the pod no longer needs ESO or
OpenBao to *run*. A backend outage (or a sealed OpenBao) only blocks *create/rotate*. Diagnose
accordingly: a broken app is almost never "OpenBao is down" unless you just changed that secret.

## What lives where

| Thing | Location |
| --- | --- |
| ESO operator | `kubernetes/apps/security/external-secrets/` (namespace `security`) |
| Random generator | `ClusterGenerator/password-generator` |
| External backend | `kubernetes/apps/security/openbao/` (single-node raft) |
| Stores | `ClusterSecretStore/openbao`, `ClusterSecretStore/openbao-db` (dynamic DB creds), `ClusterSecretStore/kube-store` |
| Auto-unseal | `openbao-unsealer` Deployment (`app/unsealer.yaml`) reads Secret `openbao-keys`; `bootstrap/init-cronjob.yaml` initialises a fresh vault |
| OpenBao config reconcile | `openbao-config` CronJob (`bootstrap/config-cronjob.yaml` + `config.sh`: auth, policies, engines) |
| UI login | Authentik OIDC — blueprint `kubernetes/apps/authentik/app/blueprints/35-oidc-openbao.yaml`; `mise exec -- just bao-login` |
| SOPS floor (forever) | `bootstrap/{sops-age,github-deploy-key}.sops.yaml`, `kubernetes/components/sops/cluster-secrets.sops.yaml`, `talos/talsecret.sops.yaml` |

OpenBao re-seals on every pod restart; the **`openbao-unsealer` handles it automatically**
(~1 min). Manual unseal is only a break-glass path — see [OpenBao restore](openbao-restore.md).

## Quick status checks

```bash
# Operator + stores
kubectl get pods -n security -l app.kubernetes.io/name=external-secrets
kubectl get clustersecretstore                      # want READY=True
kubectl get clustergenerator

# Per-secret sync state (READY=True, STATUS=SecretSynced)
kubectl get externalsecret -A
kubectl get pushsecret -A

# Confirm a Secret is ESO-owned
kubectl get secret <name> -n <ns> -o jsonpath='{.metadata.ownerReferences[0].kind}{"\n"}'
# → expect: ExternalSecret
```

## Recipe: seed the Codeberg Pages token (one-time, human)

The `forgejo/forgejo-codeberg` ExternalSecret reads `secret/codeberg/pages` property `token` and
publishes it (via the `forgejo-actions-secrets` CronJob, `optional: true`) as the `webgrip` org
Forgejo Actions secret `CODEBERG_TOKEN` — used by the `techdocs-deploy-codeberg` workflow
([ADR-0038](../adr/adr-0038-codeberg-pages-techdocs.md)). Until seeded, the ExternalSecret reports
`SecretSyncedError` and the CronJob logs "token not present yet; skipping" (benign).

1. **Mint a Codeberg PAT.** On codeberg.org (the account owning the Pages repo): Settings →
   Applications → Generate New Token, scope **`write:repository`**. Copy it (shown once).
2. **Seed it into OpenBao** (KV v2, logical path — do *not* type `data/`):

   ```bash
   mise exec -- just bao-login                       # OIDC browser login
   mise exec -- bao kv put secret/codeberg/pages token=<CODEBERG_PAT>
   ```

   Or the OpenBao UI (`openbao.${SECRET_DOMAIN}`, Authentik OIDC) → engine `secret/` →
   path `codeberg/pages` → key `token`.

3. **Verify sync** (ESO refreshes hourly; force it — human step, hook-blocked for agents):

   ```bash
   kubectl -n forgejo annotate externalsecret forgejo-codeberg force-sync="$(date +%s)" --overwrite
   kubectl -n forgejo get externalsecret forgejo-codeberg          # READY=True / SecretSynced
   ```

4. On the next CronJob tick (`:23`), the log flips to "created/updated org secret
   webgrip/CODEBERG_TOKEN".

## Troubleshooting

Use the [diagnostics](#diagnostics) below to inspect each symptom.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `ExternalSecret` shows `SecretSyncedError` | Remote key/property missing in OpenBao, or the store is `NotReady` | Seed the key at `secret/<name>` (KV v2); if the store is down, see the next row. |
| `ClusterSecretStore/openbao` `READY=False` | OpenBao sealed or down, or the Kubernetes auth role/policy is missing | `openbao-0` sits `0/1` while sealed — the unsealer should clear it in ~1 min; if not, [OpenBao restore](openbao-restore.md). Verify the `external-secrets` k8s auth role + policy (`openbao-config` CronJob logs). |
| Generator `ExternalSecret` never creates | `generators.external-secrets.io` CRDs absent | `ClusterGenerator` needs ESO ≥ v0.12 — bump the chart or fall back to a namespaced `Generator`. |
| `PushSecret` reports `Failed` / forbidden | ESO ServiceAccount lacks write RBAC in the target ns | Add the `Role` / `RoleBinding` for the ESO SA. |
| App broke right after migration | ESO Secret key names differ from the old keys | Match them exactly — fix `target.template` / `data[].secretKey`. |
| App broke but the secret is unchanged | Not an ESO problem — the cached Secret is intact | Look elsewhere. |
| New random value where data was already encrypted | An at-rest key was wrongly put on a generator | Restore from backup; never regenerate at-rest keys ([secret-rotation §5.4](secret-rotation.md)). |

### Diagnostics

```bash
# Inspect a failing ExternalSecret / store / PushSecret
kubectl describe externalsecret NAME -n NS
kubectl describe clustersecretstore openbao
kubectl describe pushsecret NAME -n NS

# Is the generator CRD installed?
kubectl get crd | grep generators.external-secrets

# Compare produced keys against the expected set
kubectl get secret NAME -n NS -o jsonpath='{.data}' | jq keys

# ESO controller logs
kubectl logs -n security deploy/external-secrets --tail=200 | grep -iE 'error|store|generator'

# Force a re-sync (annotation only — no manifest change; human step, hook-blocked for agents)
kubectl annotate externalsecret NAME -n NS force-sync="$(date +%s)" --overwrite
```

## Gotchas

- **`bao operator generate-root` does NOT work on this cluster** — `GET
  sys/generate-root/attempt` returns **405 "unsupported operation"** (confirmed via both the
  `openbao` Service and the `openbao-0` headless address, with `openbao-0` active). The assumed
  "recover an emergency root token from the unseal key" break-glass path is therefore
  **unavailable**. Consequence: you **cannot enable a new secrets engine** (e.g. `sys/mounts/*`
  for dynamic DB creds) on the running cluster this way. Options: grant the scoped `config-admin`
  role `sys/mounts/*` (low real delta — it can already self-escalate via `sys/policies/acl/*` +
  `auth/+/role/*` writes), or do a destructive wipe + reinit. Do **not** cite `generate-root` as a
  live recovery path.
- **OpenBao OIDC login needs RS256** — pin a `signing_key` (default `"authentik Self-signed
  Certificate"`) on the Authentik OIDC provider, or Authentik falls back to **HS256** and OpenBao
  login fails. Applies to the `auth/oidc/config` role for the OpenBao UI.
- **The local kubeconform PostToolUse hook false-positives** on (a) HTTPRoute `${SECRET_DOMAIN}`
  hostnames and (b) Authentik blueprints (no `kind`, custom `!Find` / `!Format` tags) — both are
  correct manifests; do **not** "fix" them. Validate via the docker `flux-local build ks` path
  (`scripts/run-flux-local-test.sh`) instead.

## Disaster recovery

**Cluster rebuild order:** Talos (`talsecret`) → `scripts/bootstrap-apps.sh` (applies the
SOPS floor: `sops-age`, `github-deploy-key`, `cluster-secrets`) → Flux → **ESO** → random +
OIDC ExternalSecrets reconcile with no backend → **OpenBao** (`openbao-0` boots **sealed**) →
init/unseal + Kubernetes auth role exist (or restored) → `openbao` store Ready →
external-class ExternalSecrets reconcile.

**Restoring OpenBao contents:**

- OpenBao stores its data in its **integrated-raft PVC**, not a database. The nightly
  `openbao-snapshot` CronJob ships a raft snapshot to Garage S3. Restore with
  `bao operator raft snapshot restore` after init+unseal — full procedure:
  [OpenBao restore](openbao-restore.md).
- A fresh/empty OpenBao **cannot be unsealed with a new key** to read old data — you need the
  **original unseal key** (Secret `openbao-keys`, backed up offline) plus the snapshot. The unseal
  key is the crown jewel; losing it means losing OpenBao's contents.

**If OpenBao contents are lost entirely:** re-seed from the original providers. Each external
secret is one of:

- *re-derivable at provider* — regenerate (Cloudflare tokens, GitHub PAT, Garage keys, Twitch,
  Discord webhook, ACME/DNS). Just mint new ones and seed.
- *must-restore-from-backup* — at-rest encryption keys seeded into OpenBao (n8n
  `N8N_ENCRYPTION_KEY`, invoiceninja `APP_KEY`, etc.). Losing these corrupts data — they must
  come from the OpenBao raft snapshot or a separately-held copy.

Tag each secret accordingly when seeding so this list stays accurate.

## See also

- `external-secrets` skill — add/migrate recipes (canonical).
- [Secret rotation](secret-rotation.md) — rotating a provided/external value.
- [OpenBao restore](openbao-restore.md) — unseal, raft snapshot restore.
- [External Secrets plan](../rfc/external-secrets-plan.md) — original architecture + inventory (historical).
- [Authentik OIDC login failures](authentik-oidc-login.md) — OIDC debugging.
