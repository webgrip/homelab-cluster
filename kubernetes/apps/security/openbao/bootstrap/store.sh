#!/bin/sh
# Persist the freshly-generated keys as the openbao-keys Secret (idempotent apply).
# Skips when init found OpenBao already initialized.
if [ -f /shared/skip ]; then
  echo "init skipped (already initialized); leaving existing openbao-keys"
  exit 0
fi
[ -s /shared/root-token ] || { echo "no keys to store"; exit 1; }
kubectl create secret generic openbao-keys -n security \
  --from-file=unseal-key=/shared/unseal-key \
  --from-file=root-token=/shared/root-token \
  --dry-run=client -o yaml | kubectl apply -f -
echo "openbao-keys stored"
