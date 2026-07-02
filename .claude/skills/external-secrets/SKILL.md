---
name: external-secrets
description: Add or manage secrets via External Secrets Operator + OpenBao — the cluster's secret backend that is replacing SOPS. Use when wiring a new secret, migrating a SOPS secret, or working with ExternalSecret / PushSecret / ClusterSecretStore / OpenBao.
---

# External Secrets (ESO + OpenBao)

Secrets live in **ESO** (engine) + **OpenBao** KV v2 (backend, ns `security`); the SOPS
migration is complete except `zomboid` (+ the SOPS floor). Background + ops/DR:
`docs/techdocs/docs/runbooks/external-secrets.md`.

## Stores + generator (cluster-scoped)
- `ClusterSecretStore/openbao` — **READ** (apps source secrets here). Vault provider, mount `secret`, v2, k8s-auth role `external-secrets`.
- `ClusterSecretStore/openbao-push` — **WRITE, migration only** (PushSecret seeds existing Secrets in). Remove after migration.
- `ClusterGenerator/password-generator` — random entropy (len 64). Length-exact variants
  `password-generator-16` / `password-generator-32` for secrets that demand a precise length
  (e.g. Harbor `secretKey`=16, `CSRF_KEY`=32). All in `…/external-secrets/stores/clustergenerator.yaml`.
- KV path convention `secret/<app>/<purpose>`; `remoteRef.key` omits the mount → `<app>/<purpose>`.

## Add a NEW secret

**Decide by origin first.** If a human never has to *know* the value, it is entropy → **generate it
in-cluster, never hand-enter it into OpenBao**. Only values that originate *outside* the cluster
(provider API tokens, OIDC client secrets, S3 access keys from Garage/an external system) go through
OpenBao. The agent has no `bao` CLI/token and cannot write OpenBao — so a design that needs manual
`bao kv put` for entropy is wrong; convert it to generators.

- **Random/internal entropy** (admin passwords, session/CSRF keys, app secret keys — no human value):
  `ExternalSecret` `dataFrom.sourceRef.generatorRef` → `password-generator` (or the `-16`/`-32`
  length-exact variant), `refreshInterval: "0"` (generate-once) + `target.deletionPolicy: Retain`,
  `rewrite` `password` → the env key. **Multi-key:** add one `dataFrom` entry per key — each
  `generatorRef` invocation yields an independent value (reference the same generator N times for N
  distinct values). Multi-key example: `kubernetes/apps/harbor/harbor/app/harbor-admin.externalsecret.yaml`
  (admin pw via `password-generator-32` + `secretKey` via `password-generator-16`; Harbor's
  CSRF/registry/jobservice secrets are chart-managed, not in this ESO).
  - **At-rest encryption keys** (Harbor `secretKey`, anything that decrypts stored data): generate-once
    + `Retain` is safe on a *fresh* install, but **regenerating corrupts existing data** — never delete
    the Secret on a populated app. (For pre-existing data you must preserve the *current* value: store
    it in OpenBao once instead of generating.)
- **Provided/external value** (token/password/key from outside): put it in OpenBao
  (`openbao.${SECRET_DOMAIN}` UI via Authentik OIDC, or `bao kv put secret/<app>/<name> k=v` — a human
  step, not the agent's), then `ExternalSecret` (store `openbao`, `creationPolicy: Owner`): per-key
  `data[].remoteRef{key,property}`, or `dataFrom: [{extract: {key: <app>/<name>}}]` for all keys.

## CLI access (`bao`)
The `bao` CLI is pinned in `.mise.toml` (`aqua:openbao/openbao/bao`, matched to the server version).
There is **no static token / no root** — auth is Authentik OIDC. Helpers in the `justfile`:
- `just bao-addr` — prints the OpenBao URL from the live HTTPRoute (no hardcoded domain).
- `just bao-login` — `bao login -method=oidc` (browser); token caches in `~/.vault-token`.
- `just harbor-s3-cred` — gum-prompted one-time write of `secret/harbor/s3` (value never hits history).
The **agent can't run `bao`** (no token, OIDC is interactive) — entering a *provided* value is always a human step.

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
- **Generator + `refreshInterval: "0"` = truly generate-once.** Adding a NEW key to such an ExternalSecret is NOT picked up on a spec change (ESO sees the target Secret as fulfilled). To add/seed the key, delete the derived Secret once (`kubectl delete secret <name>` — ESO recreates it with all current `dataFrom` entries; safe only before the app stores at-rest data, since it also regenerates the existing values).
- `dataFrom: [{extract: {key: <path>}}]` pulls ALL keys back (verified exact); the PushSecret still lists each.
- **k8s API returns pretty-printed JSON** — shell parsers must tolerate whitespace: `grep '"k": *"[^"]*"'`, `sed 's/.*: *"//; s/"$//'`.
- Don't generate manifests inside a bash function/pipeline here — `sed`/`cat`/`kubectl` hit PATH/empty issues; use Write/Edit tools. And never `rm` with broad globs (`*-secrets.*` deleted committed files; recovered via `git restore`).
- Validate via the docker `flux-local build ks <name>` path; the kubeconform hook false-positives on `${SECRET_DOMAIN}` HTTPRoutes + Authentik blueprints (don't "fix" those).
- ESO `PushSecret` write policy needs create/update/delete on **both** `secret/data/*` AND `secret/metadata/*` (it writes KV-v2 metadata too).
