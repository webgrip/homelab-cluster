---
name: external-secrets
description: Add or manage secrets via External Secrets Operator + OpenBao — the cluster's secret backend that is replacing SOPS. Use when wiring a new secret, migrating a SOPS secret, or working with ExternalSecret / PushSecret / ClusterSecretStore / OpenBao.
---

# External Secrets (ESO + OpenBao)

Secrets are migrating off SOPS to **ESO** (engine) + **OpenBao** KV v2 (backend, ns `security`).
Full state/history + every gotcha: [[external-secrets-eso-openbao]]. Rollout plan:
`docs/techdocs/docs/runbooks/secret-migration-rollout.md`.

## Stores + generator (cluster-scoped)
- `ClusterSecretStore/openbao` — **READ** (apps source secrets here). Vault provider, mount `secret`, v2, k8s-auth role `external-secrets`.
- `ClusterSecretStore/openbao-push` — **WRITE, migration only** (PushSecret seeds existing Secrets in). Remove after migration.
- `ClusterGenerator/password-generator` — random entropy (len 64).
- KV path convention `secret/<app>/<purpose>`; `remoteRef.key` omits the mount → `<app>/<purpose>`.

## Add a NEW secret
- **Random/session entropy** (no human value): `ExternalSecret` `dataFrom.sourceRef.generatorRef` → `password-generator`, `refreshInterval: "0"` (generate-once), `rewrite` to the env key.
- **Provided value** (token/password/key): put it in OpenBao (`openbao.${SECRET_DOMAIN}` UI, or `bao kv put secret/<app>/<name> k=v`), then `ExternalSecret` (store `openbao`, `creationPolicy: Owner`): per-key `data[].remoteRef{key,property}`, or `dataFrom: [{extract: {key: <app>/<name>}}]` for all keys.

## Migrate a SOPS secret (proven recipe — value-preserving, reversible)
1. **Seed:** add a `PushSecret` (`external-secrets.io/v1alpha1`, store `openbao-push`) with one `data[].match` per key → `secret/<app>/<name>`. Wait for `True/Synced`. (No "push all" shorthand — list every key.)
2. **Swap (one commit):** swap the `.sops.yaml` ref in the kustomization for an `ExternalSecret` (use `dataFrom.extract` for multi-key), `git rm` the sops file. Verify Secret `ownerReferences→ExternalSecret`, key count exact, app healthy.
- **Adopt** a live-but-unmanaged Secret (unwired SOPS): same swap; `creationPolicy: Owner` takes over the existing Secret in place (no delete-gap).
- **Component secrets** (`cnpg-backup`, `*-s3`): put PushSecret+ExternalSecret **in the component** (no `namespace:` → rendered per-ns; ESO adopts each copy). `cnpg-backup` fans out to ~8 namespaces.
- Flux+ESO latency ~5–10 min per phase → batch. Confirm `grep -c '^kind: Secret'` == 1 before `git rm`.

## OpenBao bootstrap (fully GitOps, NO live root token)
`kubernetes/apps/security/openbao/`: on a fresh volume `openbao-init` CronJob inits → unseals →
one-time root setup → **`bao token revoke -self`** → stores ONLY the unseal key in the `openbao-keys`
Secret. `openbao-config` CronJob reconciles policies/roles/identity/OIDC as the scoped `config-admin`
role (k8s auth, not root). Re-bootstrap: scale STS to 0 → delete PVC → scale to 1 (plain
`delete pod && delete pvc` fails — Longhorn re-grabs the PVC before the StatefulSet recreates it).

## Gotchas
- `dataFrom: [{extract: {key: <path>}}]` pulls ALL keys back (verified exact); the PushSecret still lists each.
- **k8s API returns pretty-printed JSON** — shell parsers must tolerate whitespace: `grep '"k": *"[^"]*"'`, `sed 's/.*: *"//; s/"$//'`.
- Don't generate manifests inside a bash function/pipeline here — `sed`/`cat`/`kubectl` hit PATH/empty issues; use Write/Edit tools. And never `rm` with broad globs (`*-secrets.*` deleted committed files; recovered via `git restore`).
- Validate via the docker `flux-local build ks <name>` path; the kubeconform hook false-positives on `${SECRET_DOMAIN}` HTTPRoutes + Authentik blueprints (don't "fix" those).
- ESO `PushSecret` write policy needs create/update/delete on **both** `secret/data/*` AND `secret/metadata/*` (it writes KV-v2 metadata too).
