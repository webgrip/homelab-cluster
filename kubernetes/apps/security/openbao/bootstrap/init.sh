#!/bin/sh
# Auto-init: if OpenBao is uninitialized, initialize it and write the generated
# unseal key + root token to an emptyDir for the store container to persist as a
# Kubernetes Secret. Idempotent: a no-op once initialized.
export BAO_ADDR="http://openbao.security.svc.cluster.local:8200"

# Wait for the API to answer (exit 2 = sealed-but-reachable, which is fine here).
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
else
  echo "initializing openbao"
  out="$(bao operator init -key-shares=1 -key-threshold=1)"
  printf '%s\n' "$out" | awk '/Unseal Key 1:/ { printf "%s", $NF }' > /shared/unseal-key
  printf '%s\n' "$out" | awk '/Initial Root Token:/ { printf "%s", $NF }' > /shared/root-token
  [ -s /shared/unseal-key ] && [ -s /shared/root-token ] || { echo "init parse failed"; exit 1; }
  echo "initialized"
fi
