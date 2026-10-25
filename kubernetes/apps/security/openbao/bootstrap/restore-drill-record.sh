#!/bin/sh
set -eu
: "${NAMESPACE:?}"
WORK="${WORK:-/shared/work}"

record() {
  configmap="$1" name="$2" kind="$3"
  kubectl -n "${NAMESPACE}" delete configmap "${configmap}" --ignore-not-found=true >/dev/null
  kubectl -n "${NAMESPACE}" create -f - >/dev/null <<YAML
apiVersion: v1
kind: ConfigMap
metadata:
  name: ${configmap}
  namespace: ${NAMESPACE}
  labels:
    backup.webgrip.io/restore-verified: "true"
    backup.webgrip.io/namespace: ${NAMESPACE}
    backup.webgrip.io/name: ${name}
    backup.webgrip.io/kind: ${kind}
data:
  snapshot: "$(cat /shared/snapshot-name 2>/dev/null || true)"
YAML
  echo "recorded ${configmap}"
}

[ -f "${WORK}/restore-verified" ] || { echo "FAIL: the restore step left no verified marker"; exit 1; }
record restore-verified-openbao-openbao-raft openbao-raft openbao
if [ -f "${WORK}/escrow-verified" ]; then
  record restore-verified-escrow-openbao-unseal-key openbao-unseal-key escrow
fi
