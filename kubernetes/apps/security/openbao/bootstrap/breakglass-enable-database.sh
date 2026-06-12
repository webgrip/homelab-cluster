#!/bin/sh
# BREAK-GLASS (one-shot): mount the `database` secrets engine on an ALREADY-bootstrapped,
# no-live-root OpenBao. Uses the documented recovery path — `generate-root` with the unseal
# key from the openbao-keys Secret — to obtain a TEMPORARY root, enables the engine if absent,
# then REVOKES root. Idempotent: re-running is a harmless no-op (engine already mounted -> skip).
# Never echoes the token or the encoded/otp material. Remove this Job from git once it has
# completed once (prune: true). See RFC: Dynamic Database Credentials / ADR-0010.
export BAO_ADDR="http://openbao-0.openbao-internal.security.svc.cluster.local:8200"
export HOME=/tmp

# Always clean up: cancel any pending root generation, and revoke any root we obtained (retried).
cleanup() {
  bao operator generate-root -cancel >/dev/null 2>&1 || true
  [ -z "${BAO_TOKEN:-}" ] && return 0
  i=0
  while [ "$i" -lt 6 ]; do
    if bao token revoke -self >/dev/null 2>&1; then echo "temporary root revoked"; return 0; fi
    i=$((i + 1)); sleep 2
  done
  echo "WARN: temporary root NOT revoked — break-glass again to generate+revoke, or re-key OpenBao"
}
trap cleanup EXIT INT TERM

[ -n "${OPENBAO_UNSEAL_KEY:-}" ] || { echo "no unseal key in env"; exit 1; }

# Wait until reachable and unsealed (rc 0). rc 2 = sealed (the unsealer Deployment handles it).
n=0
until bao status >/dev/null 2>&1; do
  n=$((n + 1)); [ "$n" -gt 80 ] && { echo "openbao not ready (still sealed/unreachable)"; exit 1; }
  sleep 3
done

bao operator generate-root -cancel >/dev/null 2>&1 || true   # clear any stale attempt

echo "==> generate-root: init"
INIT_JSON="$(bao operator generate-root -init -format=json 2>/dev/null)"
NONCE="$(printf '%s' "$INIT_JSON" | grep -o '"nonce"[ ]*:[ ]*"[^"]*"' | head -1 | sed 's/.*"nonce"[ ]*:[ ]*"//; s/"$//')"
OTP="$(printf '%s' "$INIT_JSON" | grep -o '"otp"[ ]*:[ ]*"[^"]*"' | head -1 | sed 's/.*"otp"[ ]*:[ ]*"//; s/"$//')"
[ -n "$NONCE" ] && [ -n "$OTP" ] || { echo "generate-root init parse failed"; exit 1; }

echo "==> generate-root: submit unseal key share"
UPD_JSON="$(bao operator generate-root -nonce="$NONCE" -format=json "$OPENBAO_UNSEAL_KEY" 2>/dev/null)"
ENC="$(printf '%s' "$UPD_JSON" | grep -o '"encoded_root_token"[ ]*:[ ]*"[^"]*"' | head -1 | sed 's/.*"encoded_root_token"[ ]*:[ ]*"//; s/"$//')"
[ -n "$ENC" ] || ENC="$(printf '%s' "$UPD_JSON" | grep -o '"encoded_token"[ ]*:[ ]*"[^"]*"' | head -1 | sed 's/.*"encoded_token"[ ]*:[ ]*"//; s/"$//')"
[ -n "$ENC" ] || { echo "generate-root produced no encoded token"; exit 1; }

echo "==> generate-root: decode"
DEC="$(bao operator generate-root -decode="$ENC" -otp="$OTP" 2>/dev/null)"
ROOT="$(printf '%s' "$DEC" | sed -n 's/.*[Rr]oot [Tt]oken:[ ]*//p' | tr -d '[:space:]')"
[ -n "$ROOT" ] || ROOT="$(printf '%s' "$DEC" | grep -o '"token"[ ]*:[ ]*"[^"]*"' | head -1 | sed 's/.*"token"[ ]*:[ ]*"//; s/"$//')"
[ -n "$ROOT" ] || ROOT="$(printf '%s' "$DEC" | tr -d '[:space:]')"
[ -n "$ROOT" ] || { echo "generate-root decode failed"; exit 1; }
export BAO_TOKEN="$ROOT"
echo "    temporary root obtained"

echo "==> enable database engine if absent"
if bao secrets list -format=json 2>/dev/null | grep -q '"database/"'; then
  echo "    database/ already mounted — no-op"
else
  bao secrets enable -path=database database && echo "    database/ mounted" || { echo "    enable FAILED"; exit 1; }
fi

echo "==> engine mounts now present:"
bao secrets list 2>/dev/null | awk 'NR>2 {print "    "$1}' | grep -E 'database/|secret/' || true
echo "==> break-glass complete (temporary root revoked by trap on exit)"
