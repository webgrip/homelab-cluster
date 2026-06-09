# Runbook: External Secrets (ESO)

Operational procedures for the [External Secrets migration](../external-secrets-plan.md):
deploying ESO, migrating a secret per class, standing up and seeding Infisical, and
recovering from failures. Read the plan first for the *why* and the full secret inventory.

## Dependency chain

```text
Git (ExternalSecret / PushSecret) ──▶ ESO controller ──▶ writes real k8s Secret ──▶ App pod
                                          │                     ▲
                  ClusterGenerator (random) ┘                   │ (cached — no runtime dep)
                  ClusterSecretStore: infisical ──▶ Infisical ──┘   needs CNPG infisical-db
                  ClusterSecretStore: kube-store ──▶ writes into authentik ns (OIDC push)
```

**Cached-Secret invariant:** once ESO has written a Secret, the pod no longer needs ESO or
Infisical to *run*. A backend outage only blocks *create/rotate*. Diagnose accordingly: a
broken app is almost never "Infisical is down" unless you just changed that secret.

## What lives where

| Thing | Location |
| --- | --- |
| ESO operator | `kubernetes/apps/security/external-secrets/` (namespace `security`) |
| Random generator | `ClusterGenerator/password-generator` |
| External backend | `kubernetes/apps/security/infisical/` + CNPG `infisical-db` |
| Stores | `ClusterSecretStore/infisical`, `ClusterSecretStore/kube-store` |
| SOPS floor (forever) | `bootstrap/{sops-age,github-deploy-key}.sops.yaml`, `kubernetes/components/sops/cluster-secrets.sops.yaml`, `talos/talsecret.sops.yaml` |
| SOPS floor (backend) | `infisical/app/{infisical-secret,eso-auth}.sops.yaml` |

## Quick status checks

```bash
# Operator + stores
kubectl get pods -n security -l app.kubernetes.io/name=external-secrets
kubectl get clustersecretstore                      # want READY=True
kubectl get clustergenerator

# Per-secret sync state (READY=True, STATUS=SecretSynced)
kubectl get externalsecret -A
kubectl get pushsecret -A

# Confirm an ESO-owned Secret exists before deleting its *.sops.yaml
kubectl get secret <name> -n <ns> -o jsonpath='{.metadata.ownerReferences[0].kind}{"\n"}'
# → expect: ExternalSecret
```

## Deploy ESO (Wave 0)

GitOps only — never `kubectl apply` the manifests by hand.

1. Scaffold `kubernetes/apps/security/external-secrets/` per the [plan](../external-secrets-plan.md#eso-install)
   (`ks.yaml` + `app/{ocirepository,helmrelease,kustomization,clustergenerator,clustersecretstore-kube,rbac-authentik-push}.yaml`).
2. Add `- ./external-secrets/ks.yaml` to `kubernetes/apps/security/kustomization.yaml`.
3. Validate: `./scripts/run-flux-local-test.sh` then `./scripts/run-flux-local-diff.sh`.
4. Commit (`git -c commit.gpgsign=false commit`; if `format-yaml` reformats, `git add -A` and recommit) and push.
5. Confirm: HelmRelease Ready, ESO CRDs present (`kubectl get crd | grep external-secrets`),
   `kube-store` Ready (it needs no backend).

## Recipe: migrate a random secret

For throwaway/session entropy only. **Never** for at-rest encryption keys (see
[the at-rest list](../external-secrets-plan.md#at-rest-encryption-keys-never-regenerate)).

1. Add `app/externalsecret.yaml` using the
   [generator pattern](../external-secrets-plan.md#random-generator-clustergenerator-per-secret-externalsecret):
   one `dataFrom` entry per key, `refreshInterval: "0"`, `target.name` = the **exact** old
   Secret name, `deletionPolicy: Retain`.
2. Add `dependsOn: [{name: external-secrets, namespace: security}]` to the app's `ks.yaml`.
3. Validate, commit, push.
4. Confirm the Secret exists and is `ExternalSecret`-owned, the app restarts cleanly
   (reloader picks up the change), and the feature works.
5. **Only then** remove the `*.sops.yaml` from `app/kustomization.yaml`, delete the file,
   validate, commit, push.

## Recipe: eliminate an OIDC client secret

Order: grafana → forgejo → n8n → backstage. Per provider:

1. **Generate** the shared secret in the app's namespace (generator `ExternalSecret`,
   key `client_secret`, `refreshInterval: "0"`).
2. **PushSecret** it into `authentik` as `oidc-<app>-shared` via `kube-store`
   (see the [OIDC pattern](../external-secrets-plan.md#oidc-client_secret-auto-elimination)).
3. **Mount** into Authentik: add the env var to `global.env` in the Authentik HelmRelease.
4. **Set** `client_secret: !Env OIDC_<APP>_CLIENT_SECRET` (and pin `client_id`) in the
   provider blueprint `attrs`.
5. Reconcile Authentik (restart the worker if a new blueprint stalls — see
   [Authentik OIDC login](authentik-oidc-login.md)).
6. **Verify a real login** end-to-end.
7. Delete the old `*-oidc-secret.sops.yaml`.

Rollback: revert the blueprint `!Env` and `global.env` edits and restore the SOPS secret;
Authentik re-mints on the next blueprint apply.

## Stand up Infisical + seed (Wave 4)

The manifests are **already scaffolded** at `kubernetes/apps/security/infisical/` (CNPG
`infisical-db` + ObjectStore, a valkey `redis.yaml`, the Infisical app via app-template, an
`httproute.yaml` for `infisical.${SECRET_DOMAIN}`, the `clustersecretstore.yaml`, and two
SOPS-floor **templates**). They are **UNWIRED** — not in `security/kustomization.yaml` — so
nothing deploys until you complete step A. Infisical runs via app-template (bundled
postgres/redis disabled); `DB_CONNECTION_URI` is sourced straight from the CNPG-generated
`infisical-db-app` `uri` key.

### Step A — bring up Infisical (human; the SOPS floor)

1. Create the server's crypto secret from its template:

   ```bash
   cd kubernetes/apps/security/infisical/app
   cp infisical-app-secret.template.yaml infisical-app-secret.sops.yaml
   # set AUTH_SECRET=$(openssl rand -base64 32) and ENCRYPTION_KEY=$(openssl rand -hex 16)
   sops --encrypt --in-place infisical-app-secret.sops.yaml
   ```

2. Reference it: add `- ./infisical-app-secret.sops.yaml` to
   `kubernetes/apps/security/infisical/app/kustomization.yaml`.
3. Wire the app in: add to `kubernetes/apps/security/kustomization.yaml`:

   ```yaml
   - ./infisical/database/ks.yaml
   - ./infisical/ks.yaml
   ```

4. Validate (`./scripts/run-flux-local-test.sh`), commit, push. Confirm `infisical-db` is
   healthy and the `infisical` HelmRelease is Ready.
   - **If Infisical can't connect to Postgres** (TLS): the CNPG `uri` has no sslmode. Add
     `?sslmode=no-verify` by switching `DB_CONNECTION_URI` to an assembled value, or set the
     env directly. Verify on first boot.
   - First boot runs DB migrations automatically; give it a minute before it's Ready.

### Step B — machine identity + activate the store (human)

1. Open `https://infisical.${SECRET_DOMAIN}`, create the admin account, a project **`homelab`**
   and environment **`prod`**.
2. Create a **Machine Identity** (Universal Auth), scoped **read-only** to `homelab/prod`.
3. Seed its creds from the template and reference it:

   ```bash
   cd kubernetes/apps/security/infisical/app
   cp eso-auth.template.yaml eso-auth.sops.yaml
   # paste the machine identity's Client ID / Client Secret
   sops --encrypt --in-place eso-auth.sops.yaml
   # add `- ./eso-auth.sops.yaml` to ./kustomization.yaml
   ```

4. Commit, push. Confirm `kubectl get clustersecretstore infisical` → READY=True.

After this, migrate external secrets with the recipe below (seed each value into Infisical's
UI under `homelab/prod`, then add the matching `ExternalSecret`).

## Recipe: migrate an external secret

1. **Seed** the value into Infisical (UI/CLI) under the agreed key/properties (e.g.
   `garage-forgejo` → `access_key_id` / `secret_access_key`). Use the existing decrypted
   value for at-rest keys.
2. Add `app/externalsecret.yaml` using the matching
   [shape](../external-secrets-plan.md#external-externalsecret-three-shapes) (existingSecret /
   bulk env / per-key), `secretStoreRef: { kind: ClusterSecretStore, name: infisical }`,
   preserving exact Secret name + key names.
3. Add the `dependsOn`, validate, commit, push.
4. Confirm sync + app health, then delete the `*.sops.yaml`.

For the **shared S3 components**, edit the component itself (`kubernetes/components/cnpg-backup/`
etc.) so every consuming namespace gets the ESO-produced Secret with the same name/keys.

## Troubleshooting

Use the [diagnostics](#diagnostics) below to inspect each symptom.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `ExternalSecret` shows `SecretSyncedError` | Remote key/property missing in Infisical, or the store is `NotReady` | Seed the key in Infisical; if the store is down, see the next row. |
| `ClusterSecretStore/infisical` `READY=False` | Infisical pod down, wrong `hostAPI`, or bad machine-identity creds | Check the Infisical pod and the `eso-auth` Secret values. |
| Generator `ExternalSecret` never creates | `generators.external-secrets.io` CRDs absent | `ClusterGenerator` needs ESO ≥ v0.12 — bump the chart or fall back to a namespaced `Generator`. |
| `PushSecret` reports `Failed` / forbidden | ESO ServiceAccount lacks write RBAC in `authentik` | Add the `Role` / `RoleBinding` for the ESO SA. |
| App broke right after migration | ESO Secret key names differ from the old SOPS keys | Match them exactly — fix `target.template` / `data[].secretKey`. |
| App broke but the secret is unchanged | Not an ESO problem — the cached Secret is intact | Look elsewhere. |
| New random value where data was already encrypted | An at-rest key was wrongly put on a generator | Restore from SOPS/backup; never regenerate at-rest keys. |

### Diagnostics

```bash
# Inspect a failing ExternalSecret / store / PushSecret
kubectl describe externalsecret NAME -n NS
kubectl describe clustersecretstore infisical
kubectl describe pushsecret NAME -n NS

# Is the generator CRD installed?
kubectl get crd | grep generators.external-secrets

# Compare produced keys against the old SOPS secret
kubectl get secret NAME -n NS -o jsonpath='{.data}' | jq keys

# ESO controller logs
kubectl logs -n security deploy/external-secrets --tail=200 | grep -iE 'error|store|generator'

# Force a re-sync (annotate; still GitOps-friendly — no manifest change)
kubectl annotate externalsecret NAME -n NS force-sync="$(date +%s)" --overwrite
```

## Disaster recovery

**Cluster rebuild order:** Talos (`talsecret`) → `scripts/bootstrap-apps.sh` (applies the
SOPS floor: `sops-age`, `github-deploy-key`, `cluster-secrets`) → Flux → **ESO** → random +
OIDC ExternalSecrets reconcile with no backend → **Infisical** (CNPG `infisical-db` +
`ENCRYPTION_KEY` from SOPS) → machine identity exists / re-seeded → `infisical` store Ready →
external-class ExternalSecrets reconcile.

**Restoring Infisical contents:**

- Infisical's data is in the CNPG `infisical-db` cluster, backed up to Garage like every other
  DB. Restore it via the [CNPG restore playbook](../cnpg-restore-playbook.md).
- The restored DB is unreadable without the SOPS `ENCRYPTION_KEY` — that key is the crown
  jewel; keep the age key safe.

**If Infisical contents are lost entirely:** re-seed from the original providers. Each external
secret is one of:

- *re-derivable at provider* — regenerate (Cloudflare tokens, GitHub PAT, Garage keys, Twitch,
  Discord webhook, ACME/DNS). Just mint new ones and seed.
- *must-restore-from-backup* — at-rest encryption keys seeded into Infisical (n8n
  `N8N_ENCRYPTION_KEY`, invoiceninja `APP_KEY`, etc.). Losing these corrupts data — they must
  come from the CNPG backup or a separately-held copy.

Tag each secret accordingly when seeding so this list stays accurate.

## See also

- [External Secrets plan](../external-secrets-plan.md) — architecture, inventory, waves.
- [Authentik OIDC login failures](authentik-oidc-login.md) — for OIDC-elimination debugging.
- [CloudNativePG restore playbook](../cnpg-restore-playbook.md) — for Infisical DB recovery.
