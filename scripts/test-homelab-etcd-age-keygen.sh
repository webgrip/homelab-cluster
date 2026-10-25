#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
APP="${ROOT_DIR}/kubernetes/apps/backup/etcd/app"
POLICY="${ROOT_DIR}/kubernetes/apps/security/openbao/bootstrap/homelab-etcd-age-keygen.hcl"
OPENBAO_IMAGE="$(sed -n 's/^ *image: \(docker.io\/openbao\/openbao:[^ ]*\)$/\1/p' "${ROOT_DIR}/kubernetes/apps/security/openbao/bootstrap/snapshot-cronjob.yaml" | head -n 1)"
RUNNER_IMAGE="$(sed -n 's/^ *image: \(harbor.webgrip.dev\/webgrip\/infra-runner:[^ ]*\)$/\1/p' "${APP}/age-keygen.yaml" | head -n 1)"
workspace="$(mktemp -d)"
chmod 777 "$workspace"
vault="age-keygen-vault-$$"
port=$((30000 + RANDOM % 10000))

cleanup() {
  docker rm -f "$vault" >/dev/null 2>&1 || true
  rm -rf "$workspace"
}
trap cleanup EXIT

docker run -d --name "$vault" -p "127.0.0.1:${port}:8200" -e BAO_DEV_ROOT_TOKEN_ID=root "$OPENBAO_IMAGE" server -dev -dev-listen-address=0.0.0.0:8200 >/dev/null
for _ in $(seq 1 30); do curl -fsS "http://127.0.0.1:${port}/v1/sys/health" >/dev/null 2>&1 && break; sleep 1; done
bao_root() { docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN=root "$vault" bao "$@"; }
docker cp "$POLICY" "${vault}:/tmp/keygen.hcl"
bao_root policy write keygen /tmp/keygen.hcl >/dev/null
printf 'path "secret/data/backup/homelab-etcd" {\n  capabilities = ["create"]\n}\n' >"${workspace}/no-metadata.hcl"
docker cp "${workspace}/no-metadata.hcl" "${vault}:/tmp/no-metadata.hcl"
bao_root policy write no-metadata /tmp/no-metadata.hcl >/dev/null
keygen_token="$(bao_root token create -policy=keygen -field=token)"
no_metadata_token="$(bao_root token create -policy=no-metadata -field=token)"

failures=0
run() {
  local label="$1" want="$2" token="$3" got=pass
  mkdir -p "${workspace}/${label}"; chmod 777 "${workspace}/${label}"
  docker run --rm --network host -v "${APP}:/app:ro" -v "${workspace}/${label}:/keys" \
    -e BAO_ADDR="http://127.0.0.1:${port}" -e BAO_ROLE=homelab-etcd-age-keygen -e SECRET_PATH=backup/homelab-etcd \
    -e BAO_TOKEN="$token" --entrypoint bash "$RUNNER_IMAGE" /app/homelab-etcd-age-keygen.sh \
    >"${workspace}/${label}.log" 2>&1 || got=fail
  if [[ "$got" == "$want" ]]; then
    echo "ok    ${label}: ${got} ($(tail -n1 "${workspace}/${label}.log"))"
  else
    echo "WRONG ${label}: ${got}, wanted ${want}"; cat "${workspace}/${label}.log"; failures=$((failures + 1))
  fi
}
check() {
  local label="$1"; shift
  if "$@"; then echo "ok    ${label}"; else echo "WRONG ${label}"; failures=$((failures + 1)); fi
}
field() { bao_root kv get -mount=secret -field="$1" backup/homelab-etcd; }

run bad-token-fails fail not-a-token
check "nothing written after a failed login" bash -c "! docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN=root $vault bao kv get -mount=secret backup/homelab-etcd >/dev/null 2>&1"
run metadata-unreadable-fails fail "$no_metadata_token"
check "nothing written when existence cannot be checked" bash -c "! docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN=root $vault bao kv get -mount=secret backup/homelab-etcd >/dev/null 2>&1"
run first-run-generates pass "$keygen_token"
drill_identity="$(field AGE_DRILL_IDENTITY)"
escrow_identity="$(field AGE_ESCROW_IDENTITY)"
recipients="$(field AGE_X25519_PUBLIC_KEY)"
printf '%s\n' "$drill_identity" >"${workspace}/drill.key"
printf '%s\n' "$escrow_identity" >"${workspace}/escrow.key"
chmod 644 "${workspace}/drill.key" "${workspace}/escrow.key"
two_distinct_identities() { [[ "$drill_identity" == AGE-SECRET-KEY-1* && "$escrow_identity" == AGE-SECRET-KEY-1* && "$drill_identity" != "$escrow_identity" ]]; }
check "identities are two distinct age secret keys" two_distinct_identities
check "both recipients decrypt a snapshot encrypted to the stored list" docker run --rm -v "${workspace}:/w" -e RECIPIENTS="$recipients" --entrypoint bash "$RUNNER_IMAGE" -c '
  set -euo pipefail
  echo canary >/tmp/plain
  args=(); IFS=, read -ra rs <<<"$RECIPIENTS"; for r in "${rs[@]}"; do args+=(-r "$r"); done
  age "${args[@]}" -o /tmp/enc /tmp/plain
  [ "$(age -d -i /w/drill.key /tmp/enc)" = canary ] && [ "$(age -d -i /w/escrow.key /tmp/enc)" = canary ]'
check "no identity printed" bash -c "! grep -rq 'AGE-SECRET-KEY' ${workspace}/*.log"
check "no key file left behind" [ -z "$(ls -A "${workspace}/first-run-generates")" ]
run second-run-is-a-no-op pass "$keygen_token"
check "second run kept version 1 and the same identity" [ "$(bao_root kv metadata get -mount=secret -format=json backup/homelab-etcd | jq -r .data.current_version)$(field AGE_DRILL_IDENTITY)" == "1${drill_identity}" ]
overwrite="$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H "X-Vault-Token: ${keygen_token}" \
  --data '{"data":{"AGE_DRILL_IDENTITY":"replaced"}}' "http://127.0.0.1:${port}/v1/secret/data/backup/homelab-etcd")"
check "the keygen policy cannot overwrite existing identities (HTTP ${overwrite})" [ "$overwrite" == 403 ]
check "identity unchanged after the overwrite attempt" [ "$(field AGE_DRILL_IDENTITY)" == "$drill_identity" ]

exit "$failures"
