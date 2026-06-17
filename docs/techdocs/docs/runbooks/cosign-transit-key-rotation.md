# Runbook: Rotating the `cosign-webgrip` OpenBao Transit signing key

**Status:** active · **Scope:** OpenBao Transit key `cosign-webgrip` used to sign + attest
webgrip Harbor images · **Related:** [supply-chain-enforcement-roadmap.md](../supply-chain-enforcement-roadmap.md)

> ⚠️ **Why this is delicate.** Kyverno (`image-verify-harbor-audit`) verifies Harbor images
> against the public key(s) held in the `cosign-webgrip-pub` ConfigMap (namespace `security`).
> cosign always signs with the **latest** Transit key version. If only the new public key is
> trusted, every image signed with the **old** version stops verifying. In **Audit** mode that
> is just noisy PolicyReports; once Harbor verification is in **Enforce** mode it is a
> **cluster-wide admission outage**. The safe path is to **trust both keys during the overlap,
> then retire the old one** — which, in this cluster, is handled for you (see §0).

## 0. Key facts — read this first

- Transit key: `cosign-webgrip` (type `ecdsa-p256`), created via break-glass (see roadmap §1.4).
- OpenBao Transit supports **key versions**: rotating adds version N+1; older versions remain
  trusted until you raise `min_decryption_version`.
- cosign (`--key hashivault://cosign-webgrip`) signs with the **latest** version and embeds the
  matching public key in the signature.
- **The `cosign-webgrip-pub` ConfigMap is generated, not hand-edited.** The
  [`cosign-pubkey-publish` CronJob](../../../../kubernetes/apps/security/cosign-pubkey/app/publish.cronjob.yaml)
  runs every 30 min, reads OpenBao, and writes **every still-trusted public key version**
  (every version `>= min_decryption_version`, newest first) into ConfigMap
  `cosign-webgrip-pub` (key `cosign.pub`) in the `security` namespace. Kyverno's `publicKeys`
  accepts **multiple newline-separated PEMs** and verifies an image against **any** of them.
- **Consequence:** the overlap window is automatic. After you `rotate`, the publisher trusts
  old **and** new within one tick (≤30 min). Retiring the old version is just raising
  `min_decryption_version` — the next tick drops its PEM from the ConfigMap. **You never edit
  the ConfigMap by hand**, and there is no committed manifest for it.
- Rotation and `min_decryption_version` changes need elevated Transit access that `config-admin`
  does **not** have — perform them via the one-time **break-glass `generate-root`** ceremony
  (roadmap §1.4) or a dedicated, audited rotation policy.

## 1. When to rotate

- **Scheduled hygiene:** annually, or per your crypto policy.
- **Suspected compromise** of the runner / OpenBao / the key: rotate immediately and retire the
  old version fast (§4, emergency path).
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

# --- 2.2 Rotate (adds the next version; the old one stays trusted) ---
bao write -f transit/keys/cosign-webgrip/rotate
bao read transit/keys/cosign-webgrip   # note latest_version and min_decryption_version

bao token revoke -self                  # drop root again
```

```text
# --- 2.3 Overlap is automatic — DO NOTHING to the ConfigMap ---
# Within one publisher tick (<=30 min) cosign-webgrip-pub holds BOTH the old and new PEMs, so
# images signed with either version verify. To converge immediately instead of waiting, run the
# publisher now:
#   kubectl -n security create job cosign-pubkey-publish-now --from=cronjob/cosign-pubkey-publish
# Confirm both keys landed:
#   kubectl -n security get configmap cosign-webgrip-pub -o jsonpath='{.data.cosign\.pub}' \
#     | grep -c 'BEGIN PUBLIC KEY'        # expect 2 during the overlap
```

```bash
# --- 2.4 Re-sign everything currently in use with the NEW version ---
# New releases sign with the new version automatically. For images already deployed, re-sign by
# digest (cosign uses the latest version): for each in-use harbor.${SECRET_DOMAIN}/webgrip/<img>@<digest>,
# run the release workflow again OR a one-off cosign sign/attest with --key hashivault://cosign-webgrip.
# Track coverage from Harbor + PolicyReports (roadmap §3.7) until nothing relies ONLY on the old version.
```

```bash
# --- 2.5 Retire the old version (after overlap, once nothing relies on it) ---
# Re-elevate (2.1), then refuse the old version. The publisher drops its PEM on the next tick;
# no ConfigMap edit, no commit.
bao write transit/keys/cosign-webgrip/config min_decryption_version=<new_version_number>
bao token revoke -self
# (optional) converge now instead of waiting <=30 min:
#   kubectl -n security create job cosign-pubkey-publish-now --from=cronjob/cosign-pubkey-publish
```

## 3. Pre-flight checklist

- [ ] Harbor verification is still **Audit** (do scheduled rotations before flipping to Enforce, or
      treat as a change-managed event if already enforced).
- [ ] You have the unseal key and can complete `generate-root`.
- [ ] An inventory of in-use `harbor.${SECRET_DOMAIN}/webgrip/*` images exists (to re-sign in 2.4).
- [ ] The `cosign-pubkey-publish` CronJob is healthy (last run succeeded) — it is what carries the
      overlap. `kubectl -n security get cronjob cosign-pubkey-publish`.

## 4. Emergency path (key compromise)

If the key is believed compromised, you must invalidate old signatures **fast**, accepting an
admission/verification gap:

1. Rotate (2.1–2.2).
2. **Immediately** raise `min_decryption_version` to the new version (2.5) so the old version stops
   being trusted — do **not** wait for an overlap.
3. Trigger the publisher now so the ConfigMap converges to **only** the new key (don't wait 30 min):
   `kubectl -n security create job cosign-pubkey-publish-now --from=cronjob/cosign-pubkey-publish`.
4. Re-sign all legitimate in-use images ASAP (2.4). Until done, those images **fail verification** —
   so do this with Harbor verification in **Audit** (or expect blocked admissions under Enforce; have
   a PolicyException ready, see roadmap §4.1).
5. Investigate the compromise; rotate any other credentials the runner could reach.

## 5. Rollback

- The rotation itself is additive (a new key version) and the publisher already trusts both, so
  **before** you raise `min_decryption_version` there is nothing to roll back.
- If you raised `min_decryption_version` too early, **lower it again** (re-elevate per 2.1, then
  `bao write transit/keys/cosign-webgrip/config min_decryption_version=<older_version>`). The next
  publisher tick re-adds the old PEM and old signatures verify again.
- Do **not** raise `min_decryption_version` until you have confirmed (via PolicyReports) that no
  in-use image depends on the old version.

## 6. Verification

```bash
# A freshly signed image verifies against the NEW key:
NEW_PUB=$(bao read -format=json transit/keys/cosign-webgrip | jq -r '.data.keys | to_entries | max_by(.key|tonumber) | .value.public_key')
cosign verify --key <(printf '%s' "$NEW_PUB") harbor.${SECRET_DOMAIN}/webgrip/<img>@<digest>
# ConfigMap reflects the expected number of trusted versions:
kubectl -n security get configmap cosign-webgrip-pub -o jsonpath='{.data.cosign\.pub}' | grep -c 'BEGIN PUBLIC KEY'
# Kyverno: no harbor verify failures for re-signed images (roadmap §3.7 one-liners).
```
