# Vault Transit Auto-Unseal

This cluster runs two Vault instances:

- **Unseal Vault** (`vault-unseal`): small Vault that hosts the Transit key used for unsealing.
- **Main Vault** (`vault`): your “real” Vault, configured with `seal "transit" { ... }`.

Why two? In a homelab you typically don’t have a cloud KMS or an HSM. Transit is the common on-prem compromise: you only manually unseal a small “unseal Vault” after reboots; the main Vault then unseals automatically.

## What happened here (truthful timeline)

This is what happened during bring-up in this repo/cluster:

- `vault-unseal` was brought up and became healthy (`Seal Type shamir`, `Initialized true`, `Sealed false`).
- A transit policy was created with:
	- `vault policy write vault-unseal -` using a `printf '%s\n' ... | vault policy write ...` pipeline.
- A transit token was created with:
	- `vault token create -orphan -policy=vault-unseal -period=24h`
- The main Vault (`vault-0`) initially stayed `NotReady` because it was **not initialized** (`Initialized false`, `Sealed true`, `Seal Type transit`).
- Earlier in the process, the main Vault previously failed with `403 permission denied / invalid token` when talking to the unseal Vault transit endpoint. After the token/secret wiring was corrected, the token worked.
- The main Vault was initialized by executing `vault operator init` **inside** the `vault-0` container, and the sensitive output (recovery keys + root token) was saved to:
	- `/home/vault/main-vault-init-20260103T203442Z.txt`
- After that, `vault-0` became ready and reported `Initialized true` and `Sealed false`.

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

Important:

- Only one port-forward can bind to a local port at a time.
- When switching between `vault-unseal` and `vault`, stop the previous port-forward (`Ctrl+C`) before starting the next.

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

Important: make sure you are talking to the **unseal Vault** here.

- `vault-unseal` should report `Seal Type shamir`.
- The **main Vault** (`vault`) should report `Seal Type transit`.

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

Notes on lifetime:

- With `-period=24h`, the token expires in ~24h **unless renewed**.
- Periodic tokens are renewable; renewing extends them back out by the period.
- If you want less “gotcha” risk, choose a longer period (example: `-period=720h` for ~30 days) or add a renewal reminder/automation.

If you want to try a **non-expiring** token (homelab-only tradeoff), Vault may allow it depending on server limits:

- Create: `vault token create -orphan -policy=vault-unseal -ttl=0`
- Verify: `vault token lookup <TOKEN>` and confirm it shows `token_duration ∞` (or similar)

Many Vault setups enforce `token_max_ttl` / max lease TTL, which can prevent truly non-expiring tokens.

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

If you do not have the Vault CLI installed locally, you can initialize from inside the pod (this is what was done here). This command writes the sensitive init output to a file inside the container:

```sh
kubectl -n vault exec vault-0 -- sh -ec '
	set -eu
	export VAULT_ADDR=http://127.0.0.1:8200
	ts=$(date -u +%Y%m%dT%H%M%SZ)
	out=/home/vault/main-vault-init-$ts.txt
	umask 077
	vault operator init >"$out"
	echo "init_saved_to=$out"
'
```

Then copy it to your workstation and delete it from the pod:

- `kubectl -n vault cp vault-0:/home/vault/main-vault-init-<TIMESTAMP>.txt ./main-vault-init-<TIMESTAMP>.txt`
- `kubectl -n vault exec vault-0 -- rm -f /home/vault/main-vault-init-<TIMESTAMP>.txt`

Until you run `vault operator init` on the main Vault once, it will typically report:

- `Initialized false`
- `Sealed true`

and the pod will stay `NotReady`. This is expected; initializing is the step that creates the initial recovery keys and stores what it needs for transit auto-unseal.

Important notes:

- With auto-unseal enabled, Vault uses **recovery keys** (not classic unseal keys).
- You should not need to run `vault operator unseal` on the main Vault after restart (once Transit is configured and unseal Vault is available).

## After a node reboot

1) Start with the unseal Vault:

- Port-forward `vault-unseal`
- `vault operator unseal` until unsealed

2) Main Vault should come up unsealed automatically.

## Vault UI access

Port-forward the UI service and open it in a browser:

- `kubectl -n vault port-forward svc/vault-ui 8200:8200`
- `http://127.0.0.1:8200/ui`

### Logging in (step-by-step)

1) Ensure you are viewing the **main Vault** UI (namespace `vault`), not the unseal Vault:

- The URL should be the one you opened from the port-forward above.

2) On the login screen, select **Token**.

3) Use the **Initial Root Token** from your main Vault init output (the file you copied to your workstation during `vault operator init`).

- This is the line that starts with `Initial Root Token:`.
- Do **not** paste recovery keys into the UI. Recovery keys are for recovery operations, not for normal login.

4) Paste the token and click **Sign In**.

Security note:

- Keep the init output file out of Git and treat the root token as highly sensitive.
- For day-to-day usage, create a non-root token/user and avoid using the root token routinely.

## Verification

Check seal status:

- `vault status`

If the main Vault is stuck sealed, confirm:

- `vault-unseal` is running and unsealed
- `VAULT_SEAL_TRANSIT_TOKEN` is correct and has the `vault-unseal` policy
- The key exists: `vault list transit/keys`

If the main Vault is **uninitialized** you will see:

- `Initialized false`
- `Sealed true`

In that state, auto-unseal cannot “finish” anything because there is no initialized barrier to unseal yet. You must run `vault operator init` once.

If the main Vault is failing with `permission denied` / `invalid token` when calling the unseal Vault transit endpoint, validate the token has access to the transit key:

```sh
kubectl -n vault exec vault-0 -- sh -ec '
	PLAINTEXT=$(printf test | base64)
	VAULT_ADDR=http://vault-unseal.vault-unseal.svc:8200 VAULT_TOKEN="$VAULT_SEAL_TRANSIT_TOKEN" \
		vault write -format=json transit/encrypt/vault-unseal plaintext="$PLAINTEXT" >/dev/null && echo ok || echo fail
'
```

Expected output: `ok`

## Token rotation (recommended)

If you used a periodic token:

- `vault token lookup <TOKEN>` (verify it is renewable)
- Renew periodically from your workstation or a future automation path you trust.

In this repo, the token is stored in SOPS, so rotating it is:

- Create new token in `vault-unseal`
- Update [kubernetes/apps/vault/vault-transit-seal.sops.yaml](../../kubernetes/apps/vault/vault-transit-seal.sops.yaml)
- Restart main Vault: `kubectl -n vault rollout restart statefulset/vault`

## When is `vault operator init` required?

Truthfully:

- **Every new Vault instance needs an init once.** That includes `vault-unseal` and the main `vault`.
- In a working cluster, init is a **one-time** operation per Vault storage backend.
- You do **not** re-run init on normal restarts or node reboots.
- You will need to init again if you intentionally wipe/replace the Vault data (for example: a new cluster with new PVCs, or if the data volume is lost).

For your two-Vault setup:

- After a reboot: unseal `vault-unseal`, then the main Vault should auto-unseal.
- For a fresh cluster: you must initialize both Vaults again (and re-create the transit key/policy/token and store the token where the main Vault can read it).
