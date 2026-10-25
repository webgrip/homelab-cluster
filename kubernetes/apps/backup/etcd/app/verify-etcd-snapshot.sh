#!/usr/bin/env bash
set -euo pipefail

readonly bucket="${S3_BUCKET:?}"
readonly prefix="${S3_PREFIX:-homelab}"
readonly max_age_seconds="${MAX_SNAPSHOT_AGE_SECONDS:-25200}"
readonly max_canary_age_seconds="${MAX_CANARY_AGE_SECONDS:-108000}"
readonly required_keys="${REQUIRED_KEYS:-/registry/namespaces/kube-system /registry/namespaces/flux-system /registry/namespaces/backup}"
readonly canary_key="${CANARY_KEY:-/registry/configmaps/backup/etcd-backup-canary}"
readonly out="${OUT:-/shared}"
readonly identity_file="${AGE_IDENTITY_FILE:-/drill-key/identity}"
workdir="$(mktemp -d)"
etcd_pid=""

finish() {
  if [ -n "$etcd_pid" ]; then
    kill "$etcd_pid" 2>/dev/null || true
    wait "$etcd_pid" 2>/dev/null || true
  fi
  rm -rf "$workdir"
}
trap finish EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

s3() {
  curl -fsS --aws-sigv4 "aws:amz:${S3_REGION}:s3" --user "${S3_ACCESS_KEY_ID}:${S3_SECRET_ACCESS_KEY}" "$@"
}

endpoint() {
  case "${S3_ENDPOINT}" in http://*|https://*) echo "${S3_ENDPOINT}" ;; *) echo "https://${S3_ENDPOINT}" ;; esac
}

fetch_newest_snapshot() {
  if [ -n "${SNAPSHOT_FILE:-}" ]; then
    newest="$(basename "$SNAPSHOT_FILE")"
    cp "$SNAPSHOT_FILE" "$workdir/snapshot.snap.age"
  else
    newest="$(s3 "$(endpoint)/${bucket}?list-type=2&prefix=${prefix}/" \
      | grep -o '<Key>[^<]*\.snap\.age</Key>' | sed 's/<[^>]*>//g' | sort | tail -n 1)"
    [ -n "$newest" ] || fail "stale: no snapshot under ${bucket}/${prefix}/"
    s3 -o "$workdir/snapshot.snap.age" "$(endpoint)/${bucket}/${newest}"
  fi
  local taken_at age
  taken_at="$(printf '%s' "$newest" | sed -E 's/.*-([0-9]{4}-[0-9]{2}-[0-9]{2}T[^.]+)\.snap\.age$/\1/')"
  age=$(( $(date -u +%s) - $(date -u -d "$taken_at" +%s) ))
  echo "newest snapshot ${newest}, taken ${age}s ago"
  [ "$age" -le "$max_age_seconds" ] || fail "stale: the newest snapshot is ${age}s old, limit ${max_age_seconds}s"
  printf '%s' "$newest" > "$out/snapshot-name"
}

decrypt_snapshot() {
  age --decrypt --identity "$identity_file" --output "$workdir/snapshot.db" "$workdir/snapshot.snap.age" \
    || fail "corrupt: cannot decrypt the snapshot with the drill identity"
}

restore_and_serve() {
  etcdutl snapshot status "$workdir/snapshot.db" --write-out=json >"$workdir/status.json" 2>&1 \
    || { cat "$workdir/status.json" >&2; fail "corrupt: etcdutl cannot read the snapshot"; }
  etcdutl snapshot restore "$workdir/snapshot.db" --data-dir "$workdir/restored" --name drill \
    --initial-cluster drill=http://127.0.0.1:12380 --initial-advertise-peer-urls http://127.0.0.1:12380 \
    >"$workdir/restore.log" 2>&1 || { cat "$workdir/restore.log" >&2; fail "corrupt: etcdutl snapshot restore failed"; }
  etcd --name drill --data-dir "$workdir/restored" \
    --listen-client-urls http://127.0.0.1:12379 --advertise-client-urls http://127.0.0.1:12379 \
    --listen-peer-urls http://127.0.0.1:12380 --initial-advertise-peer-urls http://127.0.0.1:12380 \
    --initial-cluster drill=http://127.0.0.1:12380 >"$workdir/etcd.log" 2>&1 &
  etcd_pid=$!
  local _
  for _ in $(seq 1 30); do
    etcdctl --endpoints=http://127.0.0.1:12379 endpoint health >/dev/null 2>&1 && return 0
    sleep 1
  done
  cat "$workdir/etcd.log" >&2
  fail "corrupt: etcd does not start on the restored data"
}

require_cluster_keys() {
  local key
  for key in $required_keys; do
    [ "$(etcdctl --endpoints=http://127.0.0.1:12379 get "$key" --keys-only | head -n 1)" = "$key" ] \
      || fail "corrupt: the restored etcd has no $key"
  done
  echo "restored etcd serves $(etcdctl --endpoints=http://127.0.0.1:12379 get /registry/ --prefix --keys-only | grep -c '^/registry/') Kubernetes objects"
}

check_canary() {
  local token written_at age
  token="$(etcdctl --endpoints=http://127.0.0.1:12379 get "$canary_key" --print-value-only | grep -ao 'canary-[0-9]\{10\}-[0-9a-f]*-end' | head -n 1 || true)"
  if [ -z "$token" ]; then
    echo "no canary in the restored etcd"
    touch "$out/no-canary"
    return 0
  fi
  written_at="$(printf '%s' "$token" | cut -d- -f2)"
  age=$(( $(date -u +%s) - written_at ))
  echo "restored canary written ${age}s ago"
  [ "$age" -le "$max_canary_age_seconds" ] || fail "stale: the restored canary is ${age}s old, limit ${max_canary_age_seconds}s"
}

rm -f "$out/no-canary" "$out/restore-verified"
fetch_newest_snapshot
decrypt_snapshot
if [ "${CORRUPT_ON_PURPOSE:-false}" = "true" ]; then
  size="$(stat -c %s "$workdir/snapshot.db")"
  printf '\xde\xad\xbe\xef\xde\xad\xbe\xef' | dd of="$workdir/snapshot.db" bs=1 seek=$((size / 2)) conv=notrunc status=none
fi
restore_and_serve
require_cluster_keys
check_canary
touch "$out/restore-verified"
echo "restore verified for $(cat "$out/snapshot-name")"
