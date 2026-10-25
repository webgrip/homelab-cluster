#!/bin/sh
set -eu
: "${NAMESPACE:?}"
: "${SOURCE_NAMESPACE:?}"
: "${SOURCE_PVC:?}"
: "${VERIFIER_IMAGE:?}"
DRILL="restore-drill-${SOURCE_PVC}"
MAX_BACKUP_AGE_SECONDS="${MAX_BACKUP_AGE_SECONDS:-129600}"
RESTORE_TIMEOUT_SECONDS="${RESTORE_TIMEOUT_SECONDS:-10800}"
POLL_SECONDS="${POLL_SECONDS:-30}"
VERIFY_UID="${VERIFY_UID:-65534}"
LH="longhorn-system"

log() {
  echo "[longhorn-restore-drill] $*"
}

fail() {
  log "FAIL: $*"
  exit 1
}

remove_drill_objects() {
  kubectl -n "${NAMESPACE}" delete pod "${DRILL}" --ignore-not-found=true --wait=true >/dev/null 2>&1 || true
  kubectl -n "${NAMESPACE}" delete pvc "${DRILL}" --ignore-not-found=true --wait=true >/dev/null 2>&1 || true
  kubectl delete pv "${DRILL}" --ignore-not-found=true --wait=true >/dev/null 2>&1 || true
  kubectl -n "${LH}" delete volumes.longhorn.io "${DRILL}" --ignore-not-found=true --wait=true >/dev/null 2>&1 || true
}

source_volume() {
  kubectl -n "${LH}" get volumes.longhorn.io -o json | jq -r --arg ns "${SOURCE_NAMESPACE}" --arg pvc "${SOURCE_PVC}" '
    [.items[]
      | select(.status.kubernetesStatus.namespace == $ns and .status.kubernetesStatus.pvcName == $pvc)
      | select(.metadata.name | startswith("restore-drill-") | not)
      | .metadata.name] | first // empty'
}

newest_backup() {
  kubectl -n "${LH}" get backups.longhorn.io -l "backup-volume=$1" -o json | jq -c '
    [.items[]
      | select(.status.state == "Completed")
      | {url: .status.url, size: .status.volumeSize, name: .metadata.name,
         at: (.status.backupCreatedAt | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601)}]
    | sort_by(.at) | last // empty'
}

wait_for_restore() {
  waited=0
  while [ "${waited}" -lt "${RESTORE_TIMEOUT_SECONDS}" ]; do
    status="$(kubectl -n "${LH}" get volumes.longhorn.io "${DRILL}" -o json)"
    if echo "${status}" | jq -e '[.status.conditions[]? | select(.type == "Restore" and .reason == "RestoreFailure")] | length > 0' >/dev/null; then
      fail "corrupt: Longhorn reports a restore failure: $(echo "${status}" | jq -r '[.status.conditions[]? | select(.type == "Restore") | .message] | join(" ")')"
    fi
    if echo "${status}" | jq -e '.status.robustness == "faulted"' >/dev/null; then
      fail "corrupt: the restored volume is faulted"
    fi
    if echo "${status}" | jq -e '.status.restoreRequired == false and .status.state == "detached"' >/dev/null; then
      return 0
    fi
    sleep "${POLL_SECONDS}"
    waited=$((waited + POLL_SECONDS))
  done
  fail "the restore did not finish within ${RESTORE_TIMEOUT_SECONDS}s"
}

create_restore_volume() {
  kubectl -n "${LH}" create -f - >/dev/null <<YAML
apiVersion: longhorn.io/v1beta2
kind: Volume
metadata:
  name: ${DRILL}
  namespace: ${LH}
  labels:
    backup.webgrip.io/drill: "true"
spec:
  fromBackup: "${backup_url}"
  size: "${size}"
  numberOfReplicas: 1
  frontend: blockdev
  dataEngine: v1
  accessMode: rwo
YAML
}

bind_restore_volume() {
  kubectl create -f - >/dev/null <<YAML
apiVersion: v1
kind: PersistentVolume
metadata:
  name: ${DRILL}
  labels:
    backup.webgrip.io/drill: "true"
spec:
  capacity:
    storage: "${size}"
  volumeMode: Filesystem
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: longhorn-single
  csi:
    driver: driver.longhorn.io
    fsType: ext4
    volumeHandle: ${DRILL}
  claimRef:
    namespace: ${NAMESPACE}
    name: ${DRILL}
YAML
  kubectl -n "${NAMESPACE}" create -f - >/dev/null <<YAML
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${DRILL}
  namespace: ${NAMESPACE}
  annotations:
    policy.webgrip.io/allow-stateful-delete: "true"
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: longhorn-single
  volumeName: ${DRILL}
  resources:
    requests:
      storage: "${size}"
YAML
}

run_verifier() {
  kubectl -n "${NAMESPACE}" create -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: ${DRILL}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: longhorn-restore-verifier
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  nodeSelector:
    node.webgrip.io/pool: worker
  securityContext:
    runAsNonRoot: true
    runAsUser: ${VERIFY_UID}
    runAsGroup: ${VERIFY_UID}
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: verify
      image: ${VERIFIER_IMAGE}
      command: ["/bin/sh", "/scripts/verify-volume.sh"]
      env:
        - {name: ROOT, value: /data}
        - {name: REQUIRED_PATHS, value: "${REQUIRED_PATHS:-}"}
        - {name: FRESH_PATH, value: "${FRESH_PATH:-}"}
        - {name: FRESH_WITHIN_SECONDS, value: "${FRESH_WITHIN_SECONDS:-172800}"}
        - {name: MIN_FILES, value: "${MIN_FILES:-1}"}
        - {name: BACKUP_CREATED_AT, value: "${backup_at}"}
      resources:
        requests: {cpu: 50m, memory: 64Mi}
        limits: {memory: 256Mi}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities: {drop: ["ALL"]}
      volumeMounts:
        - {name: data, mountPath: /data, readOnly: true}
        - {name: scripts, mountPath: /scripts, readOnly: true}
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: ${DRILL}
        readOnly: true
    - name: scripts
      configMap:
        name: longhorn-restore-drill
YAML
  kubectl -n "${NAMESPACE}" wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${DRILL}" --timeout=30m >/dev/null 2>&1 || true
  kubectl -n "${NAMESPACE}" logs "${DRILL}" || true
  phase="$(kubectl -n "${NAMESPACE}" get pod "${DRILL}" -o jsonpath='{.status.phase}')"
  [ "${phase}" = "Succeeded" ] || fail "the restored filesystem did not pass verification (verifier phase ${phase})"
}

record_verified_restore() {
  configmap="restore-verified-longhorn-${SOURCE_PVC}"
  kubectl -n "${NAMESPACE}" delete configmap "${configmap}" --ignore-not-found=true >/dev/null
  kubectl -n "${NAMESPACE}" create -f - >/dev/null <<YAML
apiVersion: v1
kind: ConfigMap
metadata:
  name: ${configmap}
  namespace: ${NAMESPACE}
  labels:
    backup.webgrip.io/restore-verified: "true"
    backup.webgrip.io/namespace: ${SOURCE_NAMESPACE}
    backup.webgrip.io/name: ${SOURCE_PVC}
    backup.webgrip.io/kind: longhorn
data:
  backup: "${backup_name}"
YAML
  log "restore verified for ${SOURCE_NAMESPACE}/${SOURCE_PVC}"
}

volume="$(source_volume)"
[ -n "${volume}" ] || fail "no Longhorn volume backs ${SOURCE_NAMESPACE}/${SOURCE_PVC}"
backup="$(newest_backup "${volume}")"
[ -n "${backup}" ] || fail "stale: ${volume} has no completed backup"
backup_at="$(echo "${backup}" | jq -r .at)"
backup_url="$(echo "${backup}" | jq -r .url)"
backup_name="$(echo "${backup}" | jq -r .name)"
size="$(echo "${backup}" | jq -r .size)"
age=$(( $(date +%s) - backup_at ))
log "newest backup ${backup_name} of ${volume} is ${age}s old"
[ "${age}" -le "${MAX_BACKUP_AGE_SECONDS}" ] || fail "stale: newest backup is ${age}s old, limit ${MAX_BACKUP_AGE_SECONDS}s"

trap remove_drill_objects EXIT
remove_drill_objects
create_restore_volume
log "restoring ${backup_name} into ${DRILL}"
wait_for_restore
bind_restore_volume
run_verifier
remove_drill_objects
trap - EXIT
record_verified_restore
