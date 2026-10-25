#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
DRILL="${ROOT_DIR}/kubernetes/components/cnpg-restore-test/restore-drill.sh"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-docker.io/library/postgres:18-alpine}"
container="cnpg-drill-test-$$"
workspace="$(mktemp -d)"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$workspace"
}
trap cleanup EXIT

docker run -d --name "$container" -e POSTGRES_PASSWORD=drill "$POSTGRES_IMAGE" \
  -c wal_level=replica -c archive_mode=on >/dev/null
for _ in $(seq 1 60); do
  docker exec "$container" pg_isready -U postgres >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$container" psql -U postgres -qc "CREATE ROLE app LOGIN" -c "CREATE DATABASE app OWNER app" >/dev/null

mkdir -p "${workspace}/bin" "${workspace}/state"
cat >"${workspace}/bin/kubectl" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
pg() { docker exec -i "$DRILL_PG" psql -U postgres "$@"; }
args=("$@")
[[ "${args[0]}" == "-n" ]] && args=("${args[@]:2}")
case "${args[0]} ${args[1]:-}" in
  "get pods")
    selector="${args[3]}"
    cluster="${selector#cnpg.io/cluster=}"; cluster="${cluster%%,*}"
    if [[ "$cluster" == "$SOURCE_CLUSTER" && "$DRILL_MUTATION" == "no-primary" ]]; then exit 0; fi
    printf '%s-1' "$cluster" ;;
  "get backups.postgresql.cnpg.io")
    age=3600; [[ "$DRILL_MUTATION" == "stale-backup" ]] && age=$((3 * 86400))
    stopped="$(date -u -d "@$(( $(date +%s) - age ))" +%Y-%m-%dT%H:%M:%SZ)"
    printf '{"items":[{"spec":{"cluster":{"name":"%s"}},"status":{"phase":"completed","stoppedAt":"%s"}},{"spec":{"cluster":{"name":"other-db"}},"status":{"phase":"completed","stoppedAt":"%s"}}]}' \
      "$SOURCE_CLUSTER" "$stopped" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" ;;
  "get cluster.postgresql.cnpg.io")
    printf 'ghcr.io/cloudnative-pg/postgresql:18' ;;
  "exec "*)
    pod="${args[1]}"
    psql_args=("${args[@]:6}")
    if [[ "$pod" == "${RESTORE_CLUSTER}-1" ]]; then
      for i in "${!psql_args[@]}"; do [[ "${psql_args[$i]}" == "postgres" && "${psql_args[$((i-1))]}" == "-d" ]] && psql_args[$i]=restored; done
    fi
    docker exec -i "$DRILL_PG" psql "${psql_args[@]}" ;;
  "apply -f")
    manifest="$(cat)"
    grep -q '^kind: Cluster' <<<"$manifest"
    pg -qc "DROP DATABASE IF EXISTS restored" -c "CREATE DATABASE restored TEMPLATE postgres" >/dev/null
    case "$DRILL_MUTATION" in
      corrupt-canary) pg -d restored -qc "UPDATE backup_canary SET nonce = 'tampered'" >/dev/null ;;
      corrupt-lost-table) pg -d restored -qc "DROP TABLE backup_canary" >/dev/null ;;
      corrupt-lost-database) pg -qc "ALTER DATABASE app RENAME TO app_gone" >/dev/null ;;
    esac ;;
  "wait "*) ;;
  "delete cluster.postgresql.cnpg.io")
    pg -qc "DROP DATABASE IF EXISTS restored" >/dev/null ;;
  "delete configmap")
    rm -f "$DRILL_STATE/configmap.yaml" ;;
  "create -f")
    cat >"$DRILL_STATE/configmap.yaml" ;;
  *)
    echo "stub kubectl: unexpected call: $*" >&2; exit 2 ;;
esac
STUB
chmod +x "${workspace}/bin/kubectl"

run_drill() {
  local mutation="$1"
  rm -f "${workspace}/state/configmap.yaml"
  docker exec "$container" psql -U postgres -qc "ALTER DATABASE app_gone RENAME TO app" >/dev/null 2>&1 || true
  if [[ "$mutation" == "stale-wal" ]]; then
    docker exec "$container" psql -U postgres -qc "ALTER SYSTEM SET archive_command = 'false'" -c "SELECT pg_reload_conf()" >/dev/null
  else
    docker exec "$container" psql -U postgres -qc "ALTER SYSTEM SET archive_command = 'true'" -c "SELECT pg_reload_conf()" >/dev/null
  fi
  PATH="${workspace}/bin:${PATH}" DRILL_PG="$container" DRILL_MUTATION="$mutation" DRILL_STATE="${workspace}/state" \
    NAMESPACE=vikunja SOURCE_CLUSTER=vikunja-db RESTORE_CLUSTER=vikunja-db-restore \
    EXPECTED_DATABASE=app EXPECTED_ROLE=app ARCHIVE_TIMEOUT_SECONDS=20 \
    sh "$DRILL" >"${workspace}/${mutation}.log" 2>&1
}

failures=0
expect() {
  local mutation="$1" want="$2" got=pass reason
  run_drill "$mutation" || got=fail
  reason="$(grep -m1 'FAIL:' "${workspace}/${mutation}.log" || tail -n1 "${workspace}/${mutation}.log")"
  if [[ "$got" == "$want" ]]; then
    echo "ok    ${mutation}: ${got} (${reason})"
  else
    echo "WRONG ${mutation}: ${got}, wanted ${want}"; cat "${workspace}/${mutation}.log"; failures=$((failures + 1))
  fi
  if [[ "$want" == "pass" ]]; then
    grep -q 'backup.webgrip.io/restore-verified: "true"' "${workspace}/state/configmap.yaml" \
      || { echo "WRONG ${mutation}: no restore-verified ConfigMap recorded"; failures=$((failures + 1)); }
  elif [[ -f "${workspace}/state/configmap.yaml" ]]; then
    echo "WRONG ${mutation}: a failed drill recorded a verified restore"; failures=$((failures + 1))
  fi
}

expect good pass
expect stale-backup fail
expect stale-wal fail
expect corrupt-canary fail
expect corrupt-lost-table fail
expect corrupt-lost-database fail
expect no-primary fail
expect good pass

exit "$failures"
