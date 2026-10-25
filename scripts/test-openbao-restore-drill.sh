#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
BOOTSTRAP="${ROOT_DIR}/kubernetes/apps/security/openbao/bootstrap"
OPENBAO_IMAGE="${OPENBAO_IMAGE:-$(sed -n 's/^ *image: \(docker.io\/openbao\/openbao:[^ ]*\)$/\1/p' "${BOOTSTRAP}/snapshot-cronjob.yaml" | head -n 1)}"
workspace="$(mktemp -d)"
chmod 777 "$workspace"
containers=()

cleanup() {
  for c in "${containers[@]}"; do docker rm -f "$c" >/dev/null 2>&1 || true; done
  rm -rf "$workspace"
}
trap cleanup EXIT

field() {
  awk -v label="$1" 'index($0, label) == 1 { print $NF; exit }'
}

start_vault() {
  local name="$1"
  cat >"${workspace}/${name}.hcl" <<HCL
storage "raft" {
  path    = "/tmp/raft"
  node_id = "${name}"
}
listener "tcp" {
  address     = "127.0.0.1:8200"
  tls_disable = true
}
api_addr     = "http://127.0.0.1:8200"
cluster_addr = "http://127.0.0.1:8201"
HCL
  docker run -d --name "${name}-$$" -v "${workspace}:/w" -e BAO_ADDR=http://127.0.0.1:8200 --entrypoint sh "$OPENBAO_IMAGE" \
    -c "mkdir -p /tmp/raft && exec bao server -config=/w/${name}.hcl" >/dev/null
  containers+=("${name}-$$")
  for _ in $(seq 1 60); do
    rc=0; docker exec "${name}-$$" bao status >/dev/null 2>&1 || rc=$?
    [[ "$rc" == "2" ]] && return 0
    sleep 1
  done
  docker logs "${name}-$$"; exit 1
}

bao_in() {
  local name="$1"; shift
  docker exec -e BAO_TOKEN="${root_token:-}" "${name}-$$" bao "$@"
}

start_vault production
init="$(bao_in production operator init -key-shares=1 -key-threshold=1)"
production_key="$(field "Unseal Key 1:" <<<"$init")"
root_token="$(field "Initial Root Token:" <<<"$init")"
bao_in production operator unseal "$production_key" >/dev/null
sleep 3
bao_in production secrets enable -path=secret kv-v2 >/dev/null
bao_in production kv put -mount=secret backup-canary/openbao written_at="$(( $(date +%s) - 3 * 86400 ))" >/dev/null
bao_in production operator raft snapshot save /w/stale.snap
bao_in production kv put -mount=secret backup-canary/openbao written_at="$(date +%s)" >/dev/null
bao_in production operator raft snapshot save /w/good.snap
bao_in production kv metadata delete -mount=secret backup-canary/openbao >/dev/null
bao_in production operator raft snapshot save /w/no-canary.snap
docker exec -u 0 "production-$$" sh -c 'chmod 666 /w/*.snap'
cp "${workspace}/good.snap" "${workspace}/corrupt.snap"
size="$(stat -c %s "${workspace}/corrupt.snap")"
printf '\xde\xad\xbe\xef\xde\xad\xbe\xef' | dd of="${workspace}/corrupt.snap" bs=1 seek=$((size / 2)) conv=notrunc status=none

root_token=""
start_vault other
other_key="$(field "Unseal Key 1:" <<<"$(bao_in other operator init -key-shares=1 -key-threshold=1)")"
fingerprint="$(printf '%s' "$production_key" | sha256sum | cut -d' ' -f1)"

failures=0
expect() {
  local label="$1" want="$2" snapshot="$3" key="$4" escrow="$5" got=pass
  docker run --rm -v "${workspace}:/w" -v "${BOOTSTRAP}/restore-drill.sh:/scripts/restore-drill.sh:ro" \
    -e OPENBAO_UNSEAL_KEY="$key" -e SNAPSHOT="/w/${snapshot}" -e WORK=/tmp/drill -e ESCROW_FINGERPRINT="$escrow" \
    --entrypoint sh "$OPENBAO_IMAGE" -c 'sh /scripts/restore-drill.sh && ls /tmp/drill/escrow-verified >/dev/null 2>&1 && echo ESCROW-RECORDED; true' \
    >"${workspace}/${label}.log" 2>&1
  grep -q '^restore verified' "${workspace}/${label}.log" || got=fail
  local reason
  reason="$(grep -m1 -E '^(FAIL|restore verified)' "${workspace}/${label}.log" || tail -n1 "${workspace}/${label}.log")"
  if [[ "$got" == "$want" ]]; then
    echo "ok    ${label}: ${got} (${reason})"
  else
    echo "WRONG ${label}: ${got}, wanted ${want}"; cat "${workspace}/${label}.log"; failures=$((failures + 1))
  fi
}

expect good pass good.snap "$production_key" ""
expect stale-canary fail stale.snap "$production_key" ""
expect corrupt-snapshot fail corrupt.snap "$production_key" ""
expect missing-canary fail no-canary.snap "$production_key" ""
expect wrong-unseal-key fail good.snap "$other_key" ""
expect escrow-mismatch fail good.snap "$production_key" "0000000000000000000000000000000000000000000000000000000000000000"
expect escrow-match pass good.snap "$production_key" "$fingerprint"
grep -q ESCROW-RECORDED "${workspace}/escrow-match.log" \
  && echo "ok    escrow-match: escrow marker recorded" \
  || { echo "WRONG escrow-match: no escrow marker"; failures=$((failures + 1)); }
grep -q ESCROW-RECORDED "${workspace}/good.log" \
  && { echo "WRONG good: escrow marker recorded without a fingerprint"; failures=$((failures + 1)); } \
  || echo "ok    good: no escrow marker without a fingerprint"

mkdir -p "${workspace}/fetch/bin" "${workspace}/fetch/shared"
cat >"${workspace}/fetch/bin/aws" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
case "$3 $4" in
  "s3 ls") printf '%s\n' $FETCH_LISTING | awk '{ print "2026-10-25 03:00:20 1048576 " $0 }' ;;
  "s3 cp") cp /dev/null "$6" ;;
esac
STUB
chmod +x "${workspace}/fetch/bin/aws"
expect_fetch() {
  local label="$1" want="$2" listing="$3" got=pass
  sed 's#/shared/#'"${workspace}"'/fetch/shared/#g' "${BOOTSTRAP}/restore-drill-fetch.sh" >"${workspace}/fetch/fetch.sh"
  PATH="${workspace}/fetch/bin:${PATH}" FETCH_LISTING="$listing" S3_ENDPOINT=s3.example S3_BUCKET=b \
    sh "${workspace}/fetch/fetch.sh" >"${workspace}/fetch-${label}.log" 2>&1 || got=fail
  if [[ "$got" == "$want" ]]; then
    echo "ok    fetch-${label}: ${got} ($(tail -n1 "${workspace}/fetch-${label}.log"))"
  else
    echo "WRONG fetch-${label}: ${got}, wanted ${want}"; cat "${workspace}/fetch-${label}.log"; failures=$((failures + 1))
  fi
}
fresh="openbao-$(date -u -d '-2 hours' +%Y%m%d-%H%M%S).snap"
old="openbao-$(date -u -d '-3 days' +%Y%m%d-%H%M%S).snap"
expect_fetch fresh pass "$old $fresh"
expect_fetch stale fail "$old"
expect_fetch empty fail ""

exit "$failures"
