#!/bin/sh
set -eu
: "${NAMESPACE:?}"
OUT="${OUT:-/shared}"
CANARY_CONFIGMAP="etcd-backup-canary"
VERIFIED_CONFIGMAP="restore-verified-etcd-homelab-etcd"

canary_existed=false
kubectl -n "${NAMESPACE}" get configmap "${CANARY_CONFIGMAP}" >/dev/null 2>&1 && canary_existed=true

write_canary() {
  token="canary-$(date -u +%s)-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')-end"
  kubectl -n "${NAMESPACE}" delete configmap "${CANARY_CONFIGMAP}" --ignore-not-found=true >/dev/null
  kubectl -n "${NAMESPACE}" create configmap "${CANARY_CONFIGMAP}" --from-literal=canary="${token}" >/dev/null
  echo "wrote canary ${token}; the next etcd snapshot carries it"
}

[ -f "${OUT}/restore-verified" ] || { echo "FAIL: the restore step left no verified marker"; exit 1; }
if [ -f "${OUT}/no-canary" ]; then
  write_canary
  if [ "${canary_existed}" = "true" ]; then
    echo "FAIL: corrupt: a canary exists in the cluster but the restored snapshot has none"
    exit 1
  fi
  echo "first run: canary seeded, no verified restore recorded yet"
  exit 0
fi
write_canary
kubectl -n "${NAMESPACE}" delete configmap "${VERIFIED_CONFIGMAP}" --ignore-not-found=true >/dev/null
kubectl -n "${NAMESPACE}" create -f - >/dev/null <<YAML
apiVersion: v1
kind: ConfigMap
metadata:
  name: ${VERIFIED_CONFIGMAP}
  namespace: ${NAMESPACE}
  labels:
    backup.webgrip.io/restore-verified: "true"
    backup.webgrip.io/namespace: talos
    backup.webgrip.io/name: homelab-etcd
    backup.webgrip.io/kind: etcd
data:
  snapshot: "$(cat "${OUT}/snapshot-name")"
YAML
echo "recorded ${VERIFIED_CONFIGMAP}"
