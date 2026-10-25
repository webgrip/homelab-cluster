#!/bin/sh
set -eu

: "${NAMESPACE:?}"
: "${SOURCE_CLUSTER:?}"
RESTORE_CLUSTER="${RESTORE_CLUSTER:-${SOURCE_CLUSTER}-restore}"
BARMAN_OBJECT_NAME="${BARMAN_OBJECT_NAME:-${SOURCE_CLUSTER}-store}"
EXPECTED_DATABASE="${EXPECTED_DATABASE:-}"
EXPECTED_ROLE="${EXPECTED_ROLE:-}"
RESTORE_STORAGE_SIZE="${RESTORE_STORAGE_SIZE:-10Gi}"
MAX_BACKUP_AGE_SECONDS="${MAX_BACKUP_AGE_SECONDS:-129600}"
ARCHIVE_TIMEOUT_SECONDS="${ARCHIVE_TIMEOUT_SECONDS:-900}"
READY_TIMEOUT="${READY_TIMEOUT:-45m}"
VERIFIED_CONFIGMAP="restore-verified-cnpg-${SOURCE_CLUSTER}"

log() {
  echo "[cnpg-restore-drill] $*"
}

fail() {
  log "FAIL: $*"
  exit 1
}

primary_pod_of() {
  kubectl -n "$NAMESPACE" get pods -l "cnpg.io/cluster=$1,cnpg.io/instanceRole=primary" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
}

psql_in() {
  kubectl -n "$NAMESPACE" exec "$1" -c postgres -- psql -U postgres -d postgres -v ON_ERROR_STOP=1 -Atc "$2"
}

newest_backup_stopped_at() {
  kubectl -n "$NAMESPACE" get backups.postgresql.cnpg.io -o json \
    | jq -r --arg cluster "$SOURCE_CLUSTER" '
        [.items[]
          | select(.spec.cluster.name == $cluster)
          | select((.status.phase // "") | ascii_downcase == "completed")
          | .status.stoppedAt // empty
          | sub("\\.[0-9]+Z$"; "Z")
          | fromdateiso8601]
        | max // empty'
}

require_fresh_base_backup() {
  stopped_at="$(newest_backup_stopped_at)"
  [ -n "$stopped_at" ] || fail "stale: no completed base backup of $SOURCE_CLUSTER"
  age=$(( $(date +%s) - stopped_at ))
  log "newest completed base backup finished ${age}s ago"
  [ "$age" -le "$MAX_BACKUP_AGE_SECONDS" ] || fail "stale: newest base backup is ${age}s old, limit ${MAX_BACKUP_AGE_SECONDS}s"
}

write_canary() {
  canary_nonce="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  psql_in "$source_primary" "CREATE TABLE IF NOT EXISTS backup_canary (id int PRIMARY KEY, nonce text NOT NULL, written_at timestamptz NOT NULL)" >/dev/null
  psql_in "$source_primary" "INSERT INTO backup_canary VALUES (1, '$canary_nonce', now()) ON CONFLICT (id) DO UPDATE SET nonce = excluded.nonce, written_at = excluded.written_at" >/dev/null
  canary_segment="$(psql_in "$source_primary" "SELECT pg_walfile_name(pg_switch_wal())")"
  log "canary $canary_nonce written in WAL segment $canary_segment"
}

wait_until_canary_archived() {
  waited=0
  while [ "$waited" -lt "$ARCHIVE_TIMEOUT_SECONDS" ]; do
    archived="$(psql_in "$source_primary" "SELECT coalesce(last_archived_wal, '') >= '$canary_segment' FROM pg_stat_archiver")"
    if [ "$archived" = "t" ]; then
      log "WAL segment $canary_segment is archived"
      return 0
    fi
    sleep 10
    waited=$((waited + 10))
  done
  fail "stale: WAL segment $canary_segment was not archived within ${ARCHIVE_TIMEOUT_SECONDS}s"
}

delete_restore_cluster() {
  kubectl -n "$NAMESPACE" delete cluster.postgresql.cnpg.io "$RESTORE_CLUSTER" --ignore-not-found=true --wait="$1" >/dev/null 2>&1 || true
}

create_restore_cluster() {
  source_image="$(kubectl -n "$NAMESPACE" get cluster.postgresql.cnpg.io "$SOURCE_CLUSTER" -o jsonpath='{.status.image}')"
  [ -n "$source_image" ] || fail "cannot read the running image of $SOURCE_CLUSTER"
  kubectl -n "$NAMESPACE" apply -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: $RESTORE_CLUSTER
  namespace: $NAMESPACE
  labels:
    backup.webgrip.io/drill: "true"
  annotations:
    policy.webgrip.io/allow-stateful-delete: "true"
spec:
  instances: 1
  imageName: $source_image
  inheritedMetadata:
    annotations:
      policy.webgrip.io/allow-stateful-delete: "true"
  affinity:
    nodeSelector:
      node.webgrip.io/pool: worker
  resources:
    requests:
      cpu: 100m
      memory: 384Mi
    limits:
      memory: 768Mi
  storage:
    size: $RESTORE_STORAGE_SIZE
    storageClass: longhorn
  bootstrap:
    recovery:
      source: clusterBackup
  externalClusters:
    - name: clusterBackup
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: $BARMAN_OBJECT_NAME
          serverName: $SOURCE_CLUSTER
EOF
}

verify_restored_cluster() {
  kubectl -n "$NAMESPACE" wait --for=condition=Ready "cluster.postgresql.cnpg.io/$RESTORE_CLUSTER" --timeout="$READY_TIMEOUT" >/dev/null
  restore_primary="$(primary_pod_of "$RESTORE_CLUSTER")"
  [ -n "$restore_primary" ] || fail "the restored cluster has no primary pod"
  [ "$(psql_in "$restore_primary" "SELECT 1")" = "1" ] || fail "corrupt: the restored database does not answer SELECT 1"
  if [ -n "$EXPECTED_DATABASE" ]; then
    [ "$(psql_in "$restore_primary" "SELECT count(*) FROM pg_database WHERE datname = '$EXPECTED_DATABASE'")" = "1" ] \
      || fail "corrupt: database $EXPECTED_DATABASE is missing after restore"
  fi
  if [ -n "$EXPECTED_ROLE" ]; then
    [ "$(psql_in "$restore_primary" "SELECT count(*) FROM pg_roles WHERE rolname = '$EXPECTED_ROLE'")" = "1" ] \
      || fail "corrupt: role $EXPECTED_ROLE is missing after restore"
  fi
  restored_nonce="$(psql_in "$restore_primary" "SELECT nonce FROM backup_canary WHERE id = 1" 2>/dev/null || true)"
  [ "$restored_nonce" = "$canary_nonce" ] \
    || fail "corrupt: restored canary is '${restored_nonce}', expected '$canary_nonce'"
  log "restored canary matches; recovery reached the WAL written moments ago"
}

record_verified_restore() {
  kubectl -n "$NAMESPACE" delete configmap "$VERIFIED_CONFIGMAP" --ignore-not-found=true >/dev/null
  kubectl -n "$NAMESPACE" create -f - >/dev/null <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: $VERIFIED_CONFIGMAP
  namespace: $NAMESPACE
  labels:
    backup.webgrip.io/restore-verified: "true"
    backup.webgrip.io/namespace: $NAMESPACE
    backup.webgrip.io/name: $SOURCE_CLUSTER
    backup.webgrip.io/kind: cnpg
data:
  canarySegment: "$canary_segment"
  canaryNonce: "$canary_nonce"
EOF
  log "recorded $VERIFIED_CONFIGMAP"
}

source_primary="$(primary_pod_of "$SOURCE_CLUSTER")"
[ -n "$source_primary" ] || fail "$SOURCE_CLUSTER has no running primary to write a canary into"
require_fresh_base_backup
write_canary
wait_until_canary_archived
trap 'delete_restore_cluster false' EXIT
delete_restore_cluster true
create_restore_cluster
verify_restored_cluster
delete_restore_cluster true
trap - EXIT
record_verified_restore
log "restore verified for $NAMESPACE/$SOURCE_CLUSTER"
