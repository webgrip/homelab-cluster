#!/bin/sh
set -eu
: "${OPENBAO_UNSEAL_KEY:?}"
MAX_CANARY_AGE_SECONDS="${MAX_CANARY_AGE_SECONDS:-108000}"
ESCROW_FINGERPRINT="${ESCROW_FINGERPRINT:-}"
SNAPSHOT="${SNAPSHOT:-/shared/openbao.snap}"
WORK="${WORK:-/tmp/restore-drill}"
PORT="${PORT:-8299}"
export BAO_ADDR="http://127.0.0.1:${PORT}"
unset BAO_TOKEN

fail() {
  echo "FAIL: $*"
  exit 1
}

field() {
  awk -v label="$1" 'index($0, label) == 1 { print $NF; exit }'
}

start_scratch_server() {
  rm -rf "${WORK}"
  mkdir -p "${WORK}/raft"
  cat >"${WORK}/scratch.hcl" <<HCL
storage "raft" {
  path    = "${WORK}/raft"
  node_id = "restore-drill"
}
listener "tcp" {
  address                                 = "127.0.0.1:${PORT}"
  tls_disable                             = true
  disable_unauthed_generate_root_endpoints = false
}
api_addr     = "http://127.0.0.1:${PORT}"
cluster_addr = "http://127.0.0.1:$((PORT + 1))"
HCL
  bao server -config="${WORK}/scratch.hcl" >"${WORK}/server.log" 2>&1 &
  server_pid=$!
  trap 'kill "${server_pid}" 2>/dev/null || true' EXIT
  for _ in $(seq 1 60); do
    rc=0
    bao status >/dev/null 2>&1 || rc=$?
    [ "${rc}" = "2" ] && return 0
    sleep 1
  done
  cat "${WORK}/server.log"
  fail "the scratch OpenBao server did not start"
}

wait_for_seal_state() {
  for _ in $(seq 1 60); do
    sealed="$(bao status -format=json 2>/dev/null | tr -d ' \n' | sed -n 's/.*"sealed":\([a-z]*\).*/\1/p')"
    [ "${sealed}" = "$1" ] && return 0
    sleep 1
  done
  fail "the scratch server never reached sealed=$1"
}

restore_snapshot() {
  init_output="$(bao operator init -key-shares=1 -key-threshold=1)"
  scratch_key="$(echo "${init_output}" | field "Unseal Key 1:")"
  scratch_root="$(echo "${init_output}" | field "Initial Root Token:")"
  bao operator unseal "${scratch_key}" >/dev/null
  wait_for_seal_state false
  BAO_TOKEN="${scratch_root}" bao operator raft snapshot restore -force "${SNAPSHOT}" \
    || fail "corrupt: the snapshot does not restore"
  wait_for_seal_state true
}

unseal_with_production_key() {
  bao operator unseal "${OPENBAO_UNSEAL_KEY}" >/dev/null 2>&1 \
    || fail "the unseal key does not open this snapshot"
  wait_for_seal_state false
}

json_field() {
  tr -d '\n' | sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"
}

sys_post() {
  wget -qO- --header 'Content-Type: application/json' --post-data "$2" "${BAO_ADDR}/v1/sys/$1"
}

mint_scratch_root_token() {
  otp="$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 26)"
  nonce="$(sys_post generate-root/attempt "{\"otp\":\"${otp}\"}" | json_field nonce)"
  [ -n "${nonce}" ] || fail "cannot start root generation on the scratch server"
  encoded="$(sys_post generate-root/update "{\"key\":\"${OPENBAO_UNSEAL_KEY}\",\"nonce\":\"${nonce}\"}" | json_field encoded_token)"
  [ -n "${encoded}" ] || fail "generate-root returned no token"
  decode_root_token "${encoded}" "${otp}"
}

decode_root_token() {
  padding=$(( (4 - ${#1} % 4) % 4 ))
  printf '%s%s' "$1" "$(printf '%*s' "${padding}" '' | tr ' ' '=')" \
    | base64 -d | od -An -tu1 -v | tr -s ' \n' '  ' \
    | awk -v otp="$2" '
        BEGIN { for (i = 1; i < 256; i++) ord[sprintf("%c", i)] = i }
        { n = split($0, b, " "); for (i = 1; i <= n; i++) printf "%c", xor(b[i] + 0, ord[substr(otp, i, 1)]) }'
}

check_canary() {
  written_at="$(BAO_TOKEN="$1" bao kv get -mount=secret -field=written_at backup-canary/openbao 2>/dev/null || true)"
  [ -n "${written_at}" ] || fail "corrupt: the restored vault has no backup canary"
  age=$(( $(date +%s) - written_at ))
  echo "restored canary written ${age}s ago"
  [ "${age}" -le "${MAX_CANARY_AGE_SECONDS}" ] || fail "stale: restored canary is ${age}s old, limit ${MAX_CANARY_AGE_SECONDS}s"
}

check_escrow_fingerprint() {
  rm -f "${WORK}/escrow-verified"
  if [ -z "${ESCROW_FINGERPRINT}" ]; then
    echo "no escrow fingerprint registered; the escrowed copy of the unseal key stays unverified"
    return 0
  fi
  actual="$(printf '%s' "${OPENBAO_UNSEAL_KEY}" | sha256sum | cut -d' ' -f1)"
  [ "${actual}" = "${ESCROW_FINGERPRINT}" ] \
    || fail "escrow: the live unseal key does not match the escrowed fingerprint"
  echo "the live unseal key matches the escrowed fingerprint"
  touch "${WORK}/escrow-verified"
}

[ -s "${SNAPSHOT}" ] || fail "no snapshot at ${SNAPSHOT}"
start_scratch_server
restore_snapshot
unseal_with_production_key
root="$(mint_scratch_root_token)"
check_canary "${root}"
check_escrow_fingerprint
touch "${WORK}/restore-verified"
echo "restore verified: snapshot $(cat /shared/snapshot-name 2>/dev/null || basename "${SNAPSHOT}") restores, unseals with the live key and holds a fresh canary"
