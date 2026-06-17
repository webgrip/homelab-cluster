# Runbook: Rotating the `cosign-webgrip` OpenBao Transit signing key

**Status:** active · **Scope:** OpenBao Transit key `cosign-webgrip` used to sign + attest
webgrip Harbor images · **Related:** [supply-chain-enforcement-roadmap.md](../supply-chain-enforcement-roadmap.md)

> ⚠️ **Why this is dangerous.** Kyverno (`image-verify-harbor-audit`) verifies Harbor images
> against a **static public key** held in the `cosign-webgrip-pub` ConfigMap. cosign always signs
> with the **latest** Transit key version. If you rotate the key and swap the ConfigMap to *only*
> the new public key, every image signed with the **old** version stops verifying. In **Audit**
> mode that is just noisy PolicyReports; once Harbor verification is in **Enforce** mode it is a
> **cluster-wide admission outage** (running pods can't be re-admitted, new pods are blocked).
> The whole point of this runbook is: **carry both keys during the overlap, then retire the old one.**

## 0. Key facts

- Transit key: `cosign-webgrip` (type `ecdsa-p256`), created via break-glass (see roadmap §1.4).
- OpenBao Transit supports **key versions**: rotating adds version N+1; older versions remain able
  to verify until you raise `min_decryption_version`.
- cosign (`--key hashivault://cosign-webgrip`) signs with the **latest** version and embeds the
  matching public key in the signature.
- Kyverno reads the trusted public key from ConfigMap `cosign-webgrip-pub` (key `cosign.pub`) in the
  `security` namespace. `publicKeys` accepts **multiple PEMs** (newline-separated) — an image
  verifies if it matches **any** of them. This is what makes a zero-downtime overlap possible.
- Rotation and `min_decryption_version` changes need elevated Transit access that `config-admin`
  does **not** have — perform them via the one-time **break-glass `generate-root`** ceremony
  (roadmap §1.4) or a dedicated, audited rotation policy.

## 1. When to rotate

- **Scheduled hygiene:** annually, or per your crypto policy.
- **Suspected compromise** of the runner / OpenBao / the key: rotate immediately and treat old
  signatures as untrusted (§4, emergency path).
- **Algorithm change:** moving key type (e.g. to ed25519) — same procedure, new key version.

## 2. Zero-downtime rotation (planned)

Run from a shell with `bao` + `jq`, `BAO_ADDR` pointed at OpenBao (e.g.
`kubectl -n security port-forward svc/openbao 8200:8200`).

```bash
# --- 2.1 Elevate (break-glass generate-root; see roadmap §1.4) ---
UNSEAL=$(kubectl -n security get secret openbao-keys -o jsonpath='{.data.unseal-key}' | base64 -d)
init=$(bao operator generate-root -init -format=json)
ENC=$(bao operator generate-root -nonce="$(jq -r .nonce <<<"$init")" -format=json "$UNSEAL" | jq -r .encoded_token)
export BAO_TOKEN=$(bao operator generate-root -decode="$ENC" -otp="$(jq -r .otp <<<"$init")" -format=json | jq -r .token)

# --- 2.2 Capture the CURRENT (old) public key, then rotate ---
OLD_PUB=$(bao read -format=json transit/keys/cosign-webgrip | jq -r '.data.keys | to_entries | max_by(.key | tonumber) | .value.public_key')
bao write -f transit/keys/cosign-webgrip/rotate            # creates the next version
NEW_PUB=$(bao read -format=json transit/keys/cosign-webgrip | jq -r '.data.keys | to_entries | max_by(.key | tonumber) | .value.public_key')

bao token revoke -self                                     # drop root again
```

```bash
# --- 2.3 Publish BOTH public keys to Kyverno (overlap window) ---
# Put old + new PEMs in cosign-webgrip-pub so images signed with either version verify.
# Edit kubernetes/apps/kyverno/policies/app/cosign-webgrip-pub.configmap.yaml so data."cosign.pub"
# contains BOTH PEM blocks, one after the other:
#   -----BEGIN PUBLIC KEY-----   (new)
#   ...
#   -----END PUBLIC KEY-----
#   -----BEGIN PUBLIC KEY-----   (old)
#   ...
#   -----END PUBLIC KEY-----
# Commit + let Flux reconcile. Confirm Kyverno reloaded the ConfigMap context.
```

```bash
# --- 2.4 Re-sign everything currently in use with the NEW version ---
# New releases sign with the new version automatically. For images already deployed, re-sign by
# digest (cosign uses the latest version): for each in-use harbor.webgrip.dev/webgrip/<img>@<digest>,
# run the release workflow again OR a one-off cosign sign/attest with --key hashivault://cosign-webgrip.
# Track coverage from Harbor + PolicyReports (roadmap §3.7) until no image verifies ONLY against OLD_PUB.
```

```bash
# --- 2.5 Retire the old version (after overlap, once nothing relies on it) ---
# Re-elevate (2.1), then refuse old-version signatures and drop the old PEM from the ConfigMap:
bao write transit/keys/cosign-webgrip/config min_decryption_version=<new_version_number>
# then remove the OLD PEM from cosign-webgrip-pub.configmap.yaml, commit, reconcile.
```

## 3. Pre-flight checklist

- [ ] Harbor verification is still **Audit** (do scheduled rotations before flipping to Enforce, or
      treat as a change-managed event if already enforced).
- [ ] You have the unseal key and can complete `generate-root`.
- [ ] You captured `OLD_PUB` **before** `rotate` (you cannot derive it afterward from a min-version-raised key).
- [ ] An inventory of in-use `harbor.webgrip.dev/webgrip/*` images exists (to re-sign in 2.4).

## 4. Emergency path (key compromise)

If the key is believed compromised, you must invalidate old signatures **fast**, accepting an
admission gap:

1. Rotate (2.1–2.2).
2. Publish **only the new** public key to `cosign-webgrip-pub` (do **not** keep the old PEM).
3. `bao write transit/keys/cosign-webgrip/config min_decryption_version=<new_version>` to stop the
   old version verifying/signing.
4. Re-sign all legitimate in-use images ASAP (2.4). Until done, those images **fail verification** —
   so do this with Harbor verification in **Audit** (or expect blocked admissions under Enforce; have
   a PolicyException ready, see roadmap §4.1).
5. Investigate the compromise; rotate any other credentials the runner could reach.

## 5. Rollback

- The rotation itself is additive (a new key version); it is not destructive until 2.5
  (`min_decryption_version`). If something looks wrong **before** 2.5, simply revert the
  `cosign-webgrip-pub` ConfigMap change (one commit) — old signatures keep verifying against the
  old PEM and new ones against the new PEM.
- Do **not** raise `min_decryption_version` until you have confirmed (via PolicyReports) that no
  in-use image depends on the old version.

## 6. Verification

```bash
# A freshly signed image verifies against the NEW key:
cosign verify --key <(printf '%s' "$NEW_PUB") harbor.webgrip.dev/webgrip/<img>@<digest>
# Kyverno: no harbor verify failures for re-signed images (roadmap §3.7 one-liners).
```
