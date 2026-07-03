#!/bin/sh
# Fresh-cluster bootstrap: init + unseal, then do ONLY the root-requiring one-time setup
# (enable KV + auth methods, create the scoped config-admin role), then REVOKE root.
# Writes only the unseal key to /shared. The openbao-config job (config-admin) reconciles
# policies / other roles / identity / OIDC. No live root token is ever stored.
export BAO_ADDR="http://openbao.security.svc.cluster.local:8200"

n=0
while true; do
  bao status >/dev/null 2>&1 && break
  [ "$?" = "2" ] && break
  n=$((n + 1)); [ "$n" -gt 60 ] && { echo "openbao unreachable"; exit 1; }
  sleep 3
done

if bao operator init -status >/dev/null 2>&1; then
  echo "already initialized; nothing to do"
  : > /shared/skip
  exit 0
fi

echo "initializing openbao"
out="$(bao operator init -key-shares=1 -key-threshold=1)"
UNSEAL="$(printf '%s\n' "$out" | awk '/Unseal Key 1:/ { printf "%s", $NF }')"
ROOT="$(printf '%s\n' "$out" | awk '/Initial Root Token:/ { printf "%s", $NF }')"
[ -n "$UNSEAL" ] && [ -n "$ROOT" ] || { echo "init parse failed"; exit 1; }
printf '%s' "$UNSEAL" > /shared/unseal-key

bao operator unseal "$UNSEAL" >/dev/null
export BAO_TOKEN="$ROOT"

echo "==> one-time root setup (KV, database engine, auth methods, config-admin role)"
bao secrets enable -path=secret kv-v2
# Dynamic database credentials (RFC: Dynamic Database Credentials / ADR-0016). Mounting a
# secrets engine needs root, which only exists here, on a fresh cluster — config-admin
# deliberately cannot mount. config.sh (config-admin) then owns the connections/roles.
# NB: an ALREADY-bootstrapped cluster has no live root, so it needs a one-time break-glass
# `generate-root` to run this same enable; see the RFC's activation note.
bao secrets enable -path=database database
# Transit engine for keyless-to-CI image signing: the cosign private key is generated in
# OpenBao and never leaves it (the Forgejo runner calls transit/sign via the cosign-signer
# policy). Mounting needs root — fresh-cluster only here. An ALREADY-bootstrapped cluster
# has no live root, so enabling Transit + creating this key is a one-time break-glass
# `generate-root` op (same as the database engine above).
bao secrets enable -path=transit transit
bao write transit/keys/cosign-webgrip type=ecdsa-p256 >/dev/null
bao auth enable kubernetes
bao write auth/kubernetes/config kubernetes_host="https://kubernetes.default.svc" >/dev/null
bao auth enable oidc 2>/dev/null || true
# JWT auth for Forgejo Actions OIDC tokens — gives CI a per-workflow identity for image
# signing (config + role are owned by config.sh). Mounting needs root: fresh-cluster here;
# an already-bootstrapped cluster enables it via the same one-time break-glass generate-root.
bao auth enable -path=forgejo jwt 2>/dev/null || true
bao policy write config-admin /scripts/config-admin.hcl
bao write auth/kubernetes/role/openbao-config \
  bound_service_account_names=openbao-config bound_service_account_namespaces=security \
  policies=config-admin ttl=20m >/dev/null

echo "==> revoking root token (none retained anywhere)"
bao token revoke -self >/dev/null 2>&1 || true
echo "bootstrap done; root revoked; openbao-config will reconcile the rest"
