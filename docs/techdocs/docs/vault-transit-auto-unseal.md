# Vault Transit Auto-Unseal

This cluster runs two Vault instances:

- **Unseal Vault** (`vault-unseal`): small Vault that hosts the Transit key used for unsealing.
- **Main Vault** (`vault`): your “real” Vault, configured with `seal "transit" { ... }`.

Why two? In a homelab you typically don’t have a cloud KMS or an HSM. Transit is the common on-prem compromise: you only manually unseal a small “unseal Vault” after reboots; the main Vault then unseals automatically.

## Files

- Unseal Vault install: [kubernetes/apps/vault-unseal](../../kubernetes/apps/vault-unseal)
- Main Vault install: [kubernetes/apps/vault](../../kubernetes/apps/vault)
- Main Vault seal settings (token is SOPS-encrypted): [kubernetes/apps/vault/vault-transit-seal.sops.yaml](../../kubernetes/apps/vault/vault-transit-seal.sops.yaml)

## Bring-up (first time)

### 1) Deploy

Wait for Flux to reconcile and create pods in both namespaces:

- `kubectl -n vault get pods`
- `kubectl -n vault-unseal get pods`

### 2) Initialize + unseal the **unseal Vault**

Port-forward the unseal Vault service:

- `kubectl -n vault-unseal port-forward svc/vault-unseal 8200:8200`
- `export VAULT_ADDR=http://127.0.0.1:8200`

If `8200` is already in use on your workstation, use a different local port (example: `8201:8200`) and set `VAULT_ADDR` accordingly.

Initialize Vault (save the output somewhere safe):

- `vault operator init`

Unseal (repeat until it reports unsealed):

- `vault operator unseal`

Sanity check (example output):

```sh
vault status
```

```
Key             Value
---             -----
Seal Type       shamir
Initialized     true
Sealed          false
Total Shares    5
Threshold       3
Version         1.20.4
Storage Type    file
HA Enabled      false
```

### 3) Enable Transit + create a key

Log in using the root token from init:

- `vault login <ROOT_TOKEN>`

Enable Transit (idempotent):

- `vault secrets enable transit || true`

Create the seal key (idempotent):

- `vault write -f transit/keys/vault-unseal || true`

### 4) Create a least-privilege policy for sealing

Write a policy that can only encrypt/decrypt using that key:

```sh
printf '%s\n' \
	'path "transit/encrypt/vault-unseal" { capabilities = ["update"] }' \
	'path "transit/decrypt/vault-unseal" { capabilities = ["update"] }' \
	| vault policy write vault-unseal -
```

Expected output:

```
Success! Uploaded policy: vault-unseal
```

### 5) Create a token for the main Vault

Create a token with that policy.

Recommended for homelab: an **orphan periodic** token so you can renew it (instead of a fixed TTL) and so it doesn't depend on a parent token.

Example (human-readable table output; look for the `token` row):

- `vault token create -orphan -policy=vault-unseal -period=24h`

Expected output (example):

```
Key                  Value
---                  -----
token                hvs.<REDACTED>
token_accessor       <REDACTED>
token_duration       24h
token_renewable      true
token_policies       ["default" "vault-unseal"]
```

If you want a copy/paste-friendly command that prints *only* the token:

```sh
vault token create -orphan -policy=vault-unseal -period=24h -format=json \
  | sed -n 's/.*"client_token":"\([^"]*\)".*/\1/p'
```

### 6) Store the token in Git (SOPS)

Edit the SOPS secret and set `VAULT_SEAL_TRANSIT_TOKEN` to the token you created:

- `sops ../../kubernetes/apps/vault/vault-transit-seal.sops.yaml`

Commit/push so Flux applies it.

### 7) Initialize the **main Vault**

Port-forward the main Vault service:

- `kubectl -n vault port-forward svc/vault 8200:8200`
- `export VAULT_ADDR=http://127.0.0.1:8200`

Initialize the main Vault:

- `vault operator init`

Important notes:

- With auto-unseal enabled, Vault uses **recovery keys** (not classic unseal keys).
- You should not need to run `vault operator unseal` on the main Vault after restart (once Transit is configured and unseal Vault is available).

## After a node reboot

1) Start with the unseal Vault:

- Port-forward `vault-unseal`
- `vault operator unseal` until unsealed

2) Main Vault should come up unsealed automatically.

## Verification

Check seal status:

- `vault status`

If the main Vault is stuck sealed, confirm:

- `vault-unseal` is running and unsealed
- `VAULT_SEAL_TRANSIT_TOKEN` is correct and has the `vault-unseal` policy
- The key exists: `vault list transit/keys`

## Token rotation (recommended)

If you used a periodic token:

- `vault token lookup <TOKEN>` (verify it is renewable)
- Renew periodically from your workstation or a future automation path you trust.

In this repo, the token is stored in SOPS, so rotating it is:

- Create new token in `vault-unseal`
- Update [kubernetes/apps/vault/vault-transit-seal.sops.yaml](../../kubernetes/apps/vault/vault-transit-seal.sops.yaml)
- Restart main Vault: `kubectl -n vault rollout restart statefulset/vault`
