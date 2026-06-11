#!/bin/sh
# Persist ONLY the unseal key as the openbao-keys Secret (idempotent apply). The root
# token is used + revoked by init.sh and is never stored. Skips when already initialized.
if [ -f /shared/skip ]; then
  echo "init skipped (already initialized); leaving existing openbao-keys"
  exit 0
fi
[ -s /shared/unseal-key ] || { echo "no unseal key to store"; exit 1; }
kubectl create secret generic openbao-keys -n security \
  --from-file=unseal-key=/shared/unseal-key \
  --dry-run=client -o yaml | kubectl apply -f -
echo "openbao-keys stored (unseal-key only; no root token)"
