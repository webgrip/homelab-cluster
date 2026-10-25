#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
RECONCILE="${ROOT_DIR}/scripts/garage-offsite-reconcile.sh"
GARAGE_IMAGE="${GARAGE_IMAGE:-docker.io/dxflrs/garage:v2.1.0}"
workspace="$(mktemp -d)"
container="garage-reconcile-test-$$"
stub_pid=""

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  [[ -n "$stub_pid" ]] && kill "$stub_pid" 2>/dev/null
  rm -rf "$workspace"
}
trap cleanup EXIT

admin_port=$((20000 + RANDOM % 10000))
s3_port=$((admin_port + 1))
cat >"${workspace}/garage.toml" <<TOML
metadata_dir = "/var/lib/garage/meta"
data_dir = "/var/lib/garage/data"
db_engine = "lmdb"
replication_factor = 1
rpc_bind_addr = "[::]:3901"
rpc_public_addr = "127.0.0.1:3901"
rpc_secret = "$(openssl rand -hex 32)"
[s3_api]
s3_region = "garage"
api_bind_addr = "[::]:3900"
[admin]
api_bind_addr = "[::]:3903"
admin_token = "test-admin-token"
TOML
docker run -d --name "$container" -p "127.0.0.1:${admin_port}:3903" -p "127.0.0.1:${s3_port}:3900" \
  -v "${workspace}/garage.toml:/etc/garage.toml:ro" "$GARAGE_IMAGE" >/dev/null
for _ in $(seq 1 30); do docker exec "$container" /garage status >/dev/null 2>&1 && break; sleep 1; done
node="$(docker exec "$container" /garage status 2>/dev/null | awk '/HEALTHY NODES/ { getline; getline; print $1 }')"
docker exec "$container" /garage layout assign -z dc1 -c 1G "$node" >/dev/null 2>&1
docker exec "$container" /garage layout apply --version 1 >/dev/null 2>&1

export GARAGE_ADMIN_URL="http://127.0.0.1:${admin_port}"
export GARAGE_ADMIN_TOKEN="test-admin-token"
api() { curl -sS -H "Authorization: Bearer ${GARAGE_ADMIN_TOKEN}" -H 'Content-Type: application/json' "$@"; }
for _ in $(seq 1 30); do [[ "$(api "${GARAGE_ADMIN_URL}/v2/GetClusterHealth" | jq -r .status 2>/dev/null)" == healthy ]] && break; sleep 1; done

mkdir -p "${workspace}/bin" "${workspace}/vault"
cat >"${workspace}/bin/bao" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
dir="${FAKE_VAULT_DIR:?}"
case "$1 $2" in
  "kv put")
    path="$3"; shift 3
    file="${dir}/$(printf '%s' "$path" | tr '/' '_')"
    : >"$file"
    for kv in "$@"; do
      k="${kv%%=*}"; v="${kv#*=}"
      [[ "$v" == - ]] && v="$(cat)"
      printf '%s=%s\n' "$k" "$v" >>"$file"
    done ;;
  "kv get")
    field="${3#-field=}"; path="$4"
    file="${dir}/$(printf '%s' "$path" | tr '/' '_')"
    [[ -f "$file" ]] || exit 2
    sed -n "s/^${field}=//p" "$file" ;;
  *) echo "fake bao: unsupported $*" >&2; exit 1 ;;
esac
STUB
chmod +x "${workspace}/bin/bao"
export PATH="${workspace}/bin:${PATH}"
export FAKE_VAULT_DIR="${workspace}/vault"

cat >"${workspace}/state.yaml" <<'YAML'
host: unused@127.0.0.1
endpoint: https://s3.example
region: garage
quotaHeadroom: 1MiB
buckets:
  - name: landing
    maxSize: 2MiB
  - name: etcd-snapshots
    maxSize: 5GiB
keys:
  - name: landing-writer
    grants:
      landing: [read, write]
  - name: etcd-writer
    vault:
      path: s3/etcd-writer
      bucket: etcd-snapshots
    grants:
      etcd-snapshots: [write]
  - name: verifier
    vault:
      path: s3/verifier
      bucket: landing
    grants:
      landing: [read]
      etcd-snapshots: [read]
YAML

failures=0
run() {
  local label="$1" want_code="$2" mode="$3" state="${4:-${workspace}/state.yaml}" code=0
  "$RECONCILE" "$mode" "$state" >"${workspace}/${label}.log" 2>&1 || code=$?
  if [[ "$code" == "$want_code" ]]; then
    echo "ok    ${label}: exit ${code} ($(tail -n1 "${workspace}/${label}.log"))"
  else
    echo "WRONG ${label}: exit ${code}, wanted ${want_code}"; cat "${workspace}/${label}.log"; failures=$((failures + 1))
  fi
}
check() {
  local label="$1"; shift
  if "$@"; then echo "ok    ${label}"; else echo "WRONG ${label}"; failures=$((failures + 1)); fi
}
bucket() { api "${GARAGE_ADMIN_URL}/v2/GetBucketInfo?globalAlias=$1"; }
key_id() { api "${GARAGE_ADMIN_URL}/v2/ListKeys" | jq -r --arg n "$1" '[.[] | select(.name == $n)] | sort_by(.created) | first | .id // empty'; }
perms() { bucket "$1" | jq -c --arg k "$(key_id "$2")" '.keys[] | select(.accessKeyId == $k) | .permissions'; }
s3() {
  docker run --rm --network host -e AWS_ACCESS_KEY_ID="$1" -e AWS_SECRET_ACCESS_KEY="$2" -e AWS_DEFAULT_REGION=garage \
    -v "${workspace}:/w" docker.io/amazon/aws-cli:2.36.50 --endpoint-url "http://127.0.0.1:${s3_port}" "${@:3}"
}

api -X POST "${GARAGE_ADMIN_URL}/v2/CreateBucket" -d '{"globalAlias":"legacy"}' >/dev/null
api -X POST "${GARAGE_ADMIN_URL}/v2/CreateKey" -d '{"name":"legacy-key"}' >/dev/null
api -X POST "${GARAGE_ADMIN_URL}/v2/CreateKey" -d '{"name":"landing-writer"}' >/dev/null
api -X POST "${GARAGE_ADMIN_URL}/v2/CreateBucket" -d '{"globalAlias":"landing"}' >/dev/null
api -X POST "${GARAGE_ADMIN_URL}/v2/AllowBucketKey" -d "$(jq -nc --arg b "$(bucket landing | jq -r .id)" --arg k "$(key_id landing-writer)" \
  '{bucketId: $b, accessKeyId: $k, permissions: {read: true, write: true, owner: true}}')" >/dev/null
writer_secret="$(api "${GARAGE_ADMIN_URL}/v2/GetKeyInfo?id=$(key_id landing-writer)&showSecretKey=true" | jq -r .secretAccessKey)"
head -c 3145728 /dev/urandom >"${workspace}/blob"
s3 "$(key_id landing-writer)" "$writer_secret" s3 cp /w/blob s3://landing/blob >/dev/null

run fresh-plan-reports-drift 2 plan
check "plan changed nothing" [ -z "$(key_id verifier)" ]
run apply-converges 0 apply
grep -q 'plan: garage-fsn1 matches' "${workspace}/apply-converges.log" \
  && echo "ok    apply re-planned to zero drift" || { echo "WRONG apply did not verify convergence"; failures=$((failures + 1)); }
run second-plan-is-clean 0 plan
run second-apply-is-a-no-op 0 apply
grep -q 'apply: 0 change' "${workspace}/second-apply-is-a-no-op.log" \
  && echo "ok    second apply changed nothing" || { echo "WRONG second apply changed something"; cat "${workspace}/second-apply-is-a-no-op.log"; failures=$((failures + 1)); }

check "owner removed from landing-writer" [ "$(perms landing landing-writer)" == '{"read":true,"write":true,"owner":false}' ]
check "etcd-writer is write-only" [ "$(perms etcd-snapshots etcd-writer)" == '{"read":false,"write":true,"owner":false}' ]
check "verifier is read-only on both" [ "$(perms landing verifier)$(perms etcd-snapshots verifier)" == '{"read":true,"write":false,"owner":false}{"read":true,"write":false,"owner":false}' ]
check "etcd-snapshots quota is the declared 5 GiB" [ "$(bucket etcd-snapshots | jq .quotas.maxSize)" == 5368709120 ]
check "landing quota held at usage + headroom, not below usage" [ "$(bucket landing | jq .quotas.maxSize)" == 1073741824 ]
check "unmanaged bucket survives" [ "$(bucket legacy | jq -r '.globalAliases[0]')" == legacy ]
check "unmanaged key survives" [ -n "$(key_id legacy-key)" ]
check "vault holds the new key id" [ "$(bao kv get -field=S3_ACCESS_KEY_ID secret/s3/etcd-writer)" == "$(key_id etcd-writer)" ]
verifier_secret="$(bao kv get -field=S3_SECRET_ACCESS_KEY secret/s3/verifier)"
check "vault secret is the real secret" [ "$(api "${GARAGE_ADMIN_URL}/v2/GetKeyInfo?id=$(key_id verifier)&showSecretKey=true" | jq -r .secretAccessKey)" == "$verifier_secret" ]
check "no secret printed by plan or apply" bash -c "! grep -rqF -e '$verifier_secret' -e '$(bao kv get -field=S3_SECRET_ACCESS_KEY secret/s3/etcd-writer)' ${workspace}/*.log"
check "verifier key can read landing" s3 "$(key_id verifier)" "$verifier_secret" s3 ls s3://landing/
check "verifier key cannot write landing" bash -c "! docker run --rm --network host -e AWS_ACCESS_KEY_ID=$(key_id verifier) -e AWS_SECRET_ACCESS_KEY=$verifier_secret -e AWS_DEFAULT_REGION=garage -v ${workspace}:/w docker.io/amazon/aws-cli:2.36.50 --endpoint-url http://127.0.0.1:${s3_port} s3 cp /w/garage.toml s3://landing/x >/dev/null 2>&1"

api -X POST "${GARAGE_ADMIN_URL}/v2/AllowBucketKey" -d "$(jq -nc --arg b "$(bucket etcd-snapshots | jq -r .id)" --arg k "$(key_id etcd-writer)" \
  '{bucketId: $b, accessKeyId: $k, permissions: {read: true, write: false, owner: true}}')" >/dev/null
api -X POST "${GARAGE_ADMIN_URL}/v2/UpdateBucket?id=$(bucket etcd-snapshots | jq -r .id)" -d '{"quotas":{"maxSize":null,"maxObjects":null}}' >/dev/null
run drifted-grant-and-quota-detected 2 plan
grep -q 'deny etcd-writer on etcd-snapshots: -read,-owner' "${workspace}/drifted-grant-and-quota-detected.log" \
  && grep -q 'quota etcd-snapshots: none -> 5 GiB' "${workspace}/drifted-grant-and-quota-detected.log" \
  && echo "ok    drift names the extra grant and the lifted quota" || { echo "WRONG drift lines"; cat "${workspace}/drifted-grant-and-quota-detected.log"; failures=$((failures + 1)); }
run drift-repaired 0 apply
check "drifted grant repaired" [ "$(perms etcd-snapshots etcd-writer)" == '{"read":false,"write":true,"owner":false}' ]

rm -f "${FAKE_VAULT_DIR}/secret_s3_verifier"
run lost-vault-secret-detected 2 plan
run lost-vault-secret-restored 0 apply
check "restored vault secret matches Garage" [ "$(bao kv get -field=S3_SECRET_ACCESS_KEY secret/s3/verifier)" == "$verifier_secret" ]

bao kv put secret/s3/verifier S3_ACCESS_KEY_ID=GK000000000000000000000000 S3_SECRET_ACCESS_KEY=x
run vault-id-mismatch-refused 5 plan
bao kv put secret/s3/verifier S3_ACCESS_KEY_ID="$(key_id verifier)" S3_SECRET_ACCESS_KEY="$verifier_secret"

api -X POST "${GARAGE_ADMIN_URL}/v2/CreateKey" -d '{"name":"verifier"}' >/dev/null
run duplicate-key-name-refused 4 plan

mkdir -p "${workspace}/degraded/v2"
printf '{"status":"degraded"}' >"${workspace}/degraded/v2/GetClusterHealth"
stub_port=$((admin_port + 2))
python3 -m http.server "$stub_port" --bind 127.0.0.1 --directory "${workspace}/degraded" >/dev/null 2>&1 &
stub_pid=$!
sleep 1
GARAGE_ADMIN_URL="http://127.0.0.1:${stub_port}" run degraded-cluster-refused 3 apply

LIFECYCLE_APP="${ROOT_DIR}/kubernetes/apps/backup/etcd/app"
K8S_IMAGE="$(sed -n 's/^ *image: \(harbor.webgrip.dev\/dockerhub\/alpine\/k8s:[^ ]*\)$/\1/p' "${LIFECYCLE_APP}/cronjob-lifecycle.yaml" | head -n 1)"
lifecycle() {
  local label="$1" want="$2" writer="$3" reader="$4" got=pass
  docker run --rm --network host -v "${LIFECYCLE_APP}:/app:ro" \
    -e BUCKET=etcd-snapshots -e LIFECYCLE_FILE=/app/homelab-etcd-lifecycle.json \
    -e WRITER_ACCESS_KEY_ID="$(key_id "$writer")" -e WRITER_ENDPOINT="http://127.0.0.1:${s3_port}" \
    -e WRITER_SECRET_ACCESS_KEY="$(api "${GARAGE_ADMIN_URL}/v2/GetKeyInfo?id=$(key_id "$writer")&showSecretKey=true" | jq -r .secretAccessKey)" \
    -e READER_ACCESS_KEY_ID="$(key_id "$reader")" -e READER_ENDPOINT="http://127.0.0.1:${s3_port}" \
    -e READER_SECRET_ACCESS_KEY="$(api "${GARAGE_ADMIN_URL}/v2/GetKeyInfo?id=$(key_id "$reader")&showSecretKey=true" | jq -r .secretAccessKey)" \
    --entrypoint sh "$K8S_IMAGE" /app/apply-lifecycle.sh >"${workspace}/lifecycle-${label}.log" 2>&1 || got=fail
  if [[ "$got" == "$want" ]]; then
    echo "ok    lifecycle-${label}: ${got} ($(tail -n1 "${workspace}/lifecycle-${label}.log"))"
  else
    echo "WRONG lifecycle-${label}: ${got}, wanted ${want}"; cat "${workspace}/lifecycle-${label}.log"; failures=$((failures + 1))
  fi
}
lifecycle write-only-writer-and-read-only-reader pass etcd-writer verifier
lifecycle reader-cannot-read fail etcd-writer etcd-writer
lifecycle writer-cannot-write fail verifier verifier
cat >"${workspace}/bin/aws" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *get-bucket-lifecycle-configuration*) echo '{"Rules":[{"ID":"expire-7d","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":30}}]}' ;;
esac
STUB
chmod +x "${workspace}/bin/aws"
mismatch=pass
BUCKET=b LIFECYCLE_FILE="${LIFECYCLE_APP}/homelab-etcd-lifecycle.json" WRITER_ACCESS_KEY_ID=a WRITER_SECRET_ACCESS_KEY=s WRITER_ENDPOINT=e \
  READER_ACCESS_KEY_ID=a READER_SECRET_ACCESS_KEY=s READER_ENDPOINT=e sh "${LIFECYCLE_APP}/apply-lifecycle.sh" >"${workspace}/lifecycle-mismatch.log" 2>&1 || mismatch=fail
[[ "$mismatch" == fail ]] && echo "ok    lifecycle-read-back-differs: fail ($(head -n1 "${workspace}/lifecycle-mismatch.log"))" \
  || { echo "WRONG lifecycle-read-back-differs: pass"; failures=$((failures + 1)); }
rm -f "${workspace}/bin/aws"

kill "$stub_pid" 2>/dev/null; stub_pid=""
printf 'GARAGE_ADMIN_TOKEN=%s\n' "$GARAGE_ADMIN_TOKEN" >"${workspace}/garage.env"
cat >"${workspace}/bin/ssh" <<STUB
#!/usr/bin/env bash
set -euo pipefail
[[ "\$1 \$2 \$3" == "-o BatchMode=yes unused@127.0.0.1" ]] || { echo "fake ssh: unexpected \$*" >&2; exit 255; }
remote="\${4//\/etc\/garage\/env/${workspace}/garage.env}"
exec sh -c "\${remote//127.0.0.1:3903/127.0.0.1:${admin_port}}"
STUB
chmod +x "${workspace}/bin/ssh"
api -X POST "${GARAGE_ADMIN_URL}/v2/DeleteKey?id=$(api "${GARAGE_ADMIN_URL}/v2/ListKeys" | jq -r '[.[] | select(.name == "verifier")] | sort_by(.created) | last | .id')" >/dev/null
(unset GARAGE_ADMIN_URL GARAGE_ADMIN_TOKEN; run ssh-transport-plan-is-clean 0 plan)

exit "$failures"
