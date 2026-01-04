# External Secrets Operator (ESO) + Vault

This cluster integrates External Secrets Operator (ESO) with the in-cluster main Vault (`vault` namespace) so workloads can consume Kubernetes Secrets that are sourced from Vault.

```mermaid
flowchart LR
  Vault[Vault (KV v2)] --> ESO[External Secrets Operator]
  ESO --> K8sSecret[Kubernetes Secret]
  K8sSecret --> Workload[Workload Pods]
```

## What’s in Git

- ESO install: [kubernetes/apps/external-secrets](../../kubernetes/apps/external-secrets)
- Vault `ClusterSecretStore`: [kubernetes/apps/external-secrets/stores/app/vault-clustersecretstore.yaml](../../kubernetes/apps/external-secrets/stores/app/vault-clustersecretstore.yaml)
- Vault Kubernetes auth token review RBAC: [kubernetes/apps/vault/vault-kubernetes-auth-rbac.yaml](../../kubernetes/apps/vault/vault-kubernetes-auth-rbac.yaml)

Design notes:

- ESO runs in `external-secrets`.
- Vault runs in `vault`.
- ESO authenticates to Vault using **Vault Kubernetes auth** (no long-lived Vault tokens in Kubernetes).
- Vault policy is scoped to a KV v2 subtree intended for ESO reads.

Convention used by apps in this repo (org/env/cluster/app):

- `kv/webgrip/<env>/clusters/<cluster>/apps/<app>/<purpose>`

## One-time Vault setup

These steps configure Vault so ESO can log in using the Kubernetes JWT of the `external-secrets` ServiceAccount.

Prereqs:

- Main Vault is initialized and unsealed.
- You can authenticate to the main Vault with a token that has permissions to manage auth methods, policies, and mounts (for initial setup this is typically the Initial Root Token).

### Manual commands

Enable KV v2 at `kv/` (idempotent):

- `vault secrets enable -path=kv kv-v2 || true`

Enable Kubernetes auth at `kubernetes/` (idempotent):

- `vault auth enable -path=kubernetes kubernetes || true`

Configure Kubernetes auth (run inside the Vault pod so it can read the Vault pod’s ServiceAccount token for token review):

```sh
kubectl -n vault exec vault-0 -- sh -ec '
  set -eu
  export VAULT_ADDR=http://127.0.0.1:8200

  kubernetes_host=https://kubernetes.default.svc:443
  kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  token_reviewer_jwt=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)

  vault write auth/kubernetes/config \
    kubernetes_host="$kubernetes_host" \
    kubernetes_ca_cert="$kubernetes_ca_cert" \
    token_reviewer_jwt="$token_reviewer_jwt"
'
```

Create a policy for ESO reads (KV v2 requires `data/` + `metadata/` paths):

```sh
vault policy write external-secrets - <<'HCL'
path "kv/data/external-secrets/*" {
  capabilities = ["read"]
}

path "kv/metadata/external-secrets/*" {
  capabilities = ["list", "read"]
}
HCL
```

If you plan to use `PushSecret` to write into Vault, the policy must also allow `create` and `update` on the relevant `kv/data/...` path (and still allow access to `kv/metadata/...`).

Create a Kubernetes auth role for ESO:

```sh
vault write auth/kubernetes/role/external-secrets \
  bound_service_account_names=external-secrets \
  bound_service_account_namespaces=external-secrets \
  policies=external-secrets \
  ttl=1h
```

## Writing secrets in Vault (example)

Example: write a secret that ESO can read.

```sh
vault kv put kv/webgrip/prod/clusters/soyo/apps/example/app \
  username='demo' \
  password='demo-password'
```

Backstage example paths:

- `kv/webgrip/prod/clusters/soyo/apps/backstage/app`
- `kv/webgrip/prod/clusters/soyo/apps/backstage/db`

## Using secrets in Kubernetes (example)

A minimal example `ExternalSecret` manifest is available here (not applied by Flux by default):

- [kubernetes/apps/external-secrets/examples/external-secret-example.yaml](../../kubernetes/apps/external-secrets/examples/external-secret-example.yaml)

Apply it manually once Vault has the data:

- `kubectl apply -f kubernetes/apps/external-secrets/examples/external-secret-example.yaml`

## Pushing secrets into Vault (example)

Backstage’s database secret is pushed into Vault via a `PushSecret` in the Backstage app base:

- [kubernetes/apps/backstage/backstage/app/base/pushsecret-vault.yaml](../../kubernetes/apps/backstage/backstage/app/base/pushsecret-vault.yaml)

Backstage’s full integration (app secrets from Vault + DB creds pushed to Vault) is documented here:

- [docs/techdocs/docs/backstage-secrets-vault.md](backstage-secrets-vault.md)


## Troubleshooting

- If ESO reports it cannot authenticate:
  - Confirm the Vault role exists: `vault read auth/kubernetes/role/external-secrets`
  - Confirm Vault can token-review (RBAC applied): `kubectl get clusterrolebinding vault-kubernetes-auth`
- If ESO can authenticate but cannot read a secret:
  - Confirm the secret exists: `vault kv get kv/external-secrets/<name>`
  - Confirm policy paths match KV v2 (`kv/data/...` and `kv/metadata/...`).
