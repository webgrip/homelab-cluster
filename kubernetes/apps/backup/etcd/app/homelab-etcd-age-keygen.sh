#!/usr/bin/env bash
set -euo pipefail
: "${BAO_ADDR:?}" "${BAO_ROLE:?}" "${SECRET_PATH:?}"
JWT_FILE="${JWT_FILE:-/var/run/secrets/kubernetes.io/serviceaccount/token}"
WORK="${WORK:-/keys}"

login() {
  jq -nc --arg role "$BAO_ROLE" --rawfile jwt "$JWT_FILE" '{role: $role, jwt: ($jwt | rtrimstr("\n"))}' \
    | curl -fsS -X POST --data @- "$BAO_ADDR/v1/auth/kubernetes/login" | jq -r '.auth.client_token'
}
token="${BAO_TOKEN:-$(login || true)}"
[ -n "$token" ] && [ "$token" != null ] || { echo "FAIL: OpenBao login as $BAO_ROLE returned no token"; exit 1; }

status="$(curl -sS -o /dev/null -w '%{http_code}' -H "X-Vault-Token: $token" "$BAO_ADDR/v1/secret/metadata/$SECRET_PATH")"
case "$status" in
  200) echo "secret/$SECRET_PATH already exists; the identities were generated before, nothing to do"; exit 0 ;;
  404) ;;
  *) echo "FAIL: reading secret/$SECRET_PATH metadata returned HTTP $status"; exit 1 ;;
esac

umask 077
age-keygen -o "$WORK/escrow" 2>/dev/null
age-keygen -o "$WORK/drill" 2>/dev/null
escrow_recipient="$(age-keygen -y "$WORK/escrow")"
drill_recipient="$(age-keygen -y "$WORK/drill")"

grep '^AGE-SECRET-KEY-' "$WORK/drill" >"$WORK/drill.key"
grep '^AGE-SECRET-KEY-' "$WORK/escrow" >"$WORK/escrow.key"
code="$(jq -nc \
    --arg recipients "$escrow_recipient,$drill_recipient" \
    --rawfile drill "$WORK/drill.key" \
    --rawfile escrow "$WORK/escrow.key" \
    '{options: {cas: 0}, data: {AGE_X25519_PUBLIC_KEY: $recipients, AGE_DRILL_IDENTITY: ($drill | rtrimstr("\n")), AGE_ESCROW_IDENTITY: ($escrow | rtrimstr("\n"))}}' \
  | curl -sS -o "$WORK/response" -w '%{http_code}' -X POST -H "X-Vault-Token: $token" --data @- "$BAO_ADDR/v1/secret/data/$SECRET_PATH")"
rm -f "$WORK/escrow" "$WORK/drill" "$WORK/escrow.key" "$WORK/drill.key"
case "$code" in
  200|204) ;;
  *) echo "FAIL: writing secret/$SECRET_PATH returned HTTP $code: $(jq -c '.errors // .' "$WORK/response" 2>/dev/null)"; exit 1 ;;
esac
rm -f "$WORK/response"
echo "generated the escrow and drill identities into secret/$SECRET_PATH; recipients: $escrow_recipient,$drill_recipient"
