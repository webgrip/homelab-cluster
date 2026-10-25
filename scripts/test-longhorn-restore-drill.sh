#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
APP="${ROOT_DIR}/kubernetes/apps/backup/restore-drills/app"
workspace="$(mktemp -d)"
trap 'rm -rf "$workspace"' EXIT
failures=0

report() {
  local label="$1" want="$2" got="$3" log="$4"
  local reason
  reason="$(grep -m1 -E 'FAIL:|verified' "$log" || tail -n1 "$log")"
  if [[ "$got" == "$want" ]]; then
    echo "ok    ${label}: ${got} (${reason})"
  else
    echo "WRONG ${label}: ${got}, wanted ${want}"; cat "$log"; failures=$((failures + 1))
  fi
}

now="$(date +%s)"
make_volume() {
  local dir="${workspace}/vol-$1" newest="$2"
  mkdir -p "${dir}/git/gitea-repositories/webgrip/homelab-cluster.git/objects"
  echo "ref: refs/heads/main" >"${dir}/git/gitea-repositories/webgrip/homelab-cluster.git/HEAD"
  echo x >"${dir}/git/gitea-repositories/webgrip/homelab-cluster.git/objects/pack"
  touch -d "@${newest}" "${dir}/git/gitea-repositories/webgrip/homelab-cluster.git/HEAD" "${dir}/git/gitea-repositories/webgrip/homelab-cluster.git/objects/pack"
}
make_volume good "$((now - 7200))"
make_volume stale "$((now - 9 * 86400))"
make_volume corrupt "$((now - 7200))"
rm "${workspace}/vol-corrupt/git/gitea-repositories/webgrip/homelab-cluster.git/HEAD"
mkdir -p "${workspace}/vol-empty"

expect_verify() {
  local label="$1" want="$2" got=pass
  ROOT="${workspace}/vol-${label}" REQUIRED_PATHS="git/gitea-repositories/webgrip/homelab-cluster.git/HEAD" \
    FRESH_PATH=git/gitea-repositories MIN_FILES=1 BACKUP_CREATED_AT="$((now - 3600))" \
    sh "${APP}/verify-volume.sh" >"${workspace}/verify-${label}.log" 2>&1 || got=fail
  report "verify-${label}" "$want" "$got" "${workspace}/verify-${label}.log"
}
expect_verify good pass
expect_verify stale fail
expect_verify corrupt fail
expect_verify empty fail

mkdir -p "${workspace}/bin"
cat >"${workspace}/bin/kubectl" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
args=("$@"); [[ "${args[0]}" == "-n" ]] && args=("${args[@]:2}")
case "${args[0]} ${args[1]:-}" in
  "get volumes.longhorn.io")
    if [[ "${args[2]}" == "-o" ]]; then
      printf '{"items":[{"metadata":{"name":"pvc-src"},"status":{"kubernetesStatus":{"namespace":"forgejo","pvcName":"forgejo-data"}}}]}'
    else
      case "$DRILL_MUTATION" in
        restore-failure) printf '{"status":{"restoreRequired":true,"state":"attached","conditions":[{"type":"Restore","reason":"RestoreFailure","message":"checksum mismatch"}]}}' ;;
        faulted) printf '{"status":{"restoreRequired":true,"state":"attached","robustness":"faulted"}}' ;;
        never-finishes) printf '{"status":{"restoreRequired":true,"state":"attached"}}' ;;
        *) printf '{"status":{"restoreRequired":false,"state":"detached","robustness":"unknown"}}' ;;
      esac
    fi ;;
  "get backups.longhorn.io")
    age=7200; [[ "$DRILL_MUTATION" == "stale-backup" ]] && age=$((3 * 86400))
    printf '{"items":[{"metadata":{"name":"backup-new"},"status":{"state":"Completed","url":"s3://b@garage/?backup=backup-new&volume=pvc-src","volumeSize":"1073741824","backupCreatedAt":"%s"}},{"metadata":{"name":"backup-err"},"status":{"state":"Error","url":"x","volumeSize":"1","backupCreatedAt":"%s"}}]}' \
      "$(date -u -d "@$(( $(date +%s) - age ))" +%Y-%m-%dT%H:%M:%SZ)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" ;;
  "get pod")
    [[ "$DRILL_MUTATION" == "verifier-fails" ]] && printf Failed || printf Succeeded ;;
  "create -f")
    manifest="$(cat)"
    grep -q '^kind: ConfigMap' <<<"$manifest" && printf '%s' "$manifest" >"$DRILL_STATE/configmap.yaml"
    grep -q '^kind: Volume' <<<"$manifest" && printf '%s' "$manifest" >"$DRILL_STATE/volume.yaml"
    true ;;
  "wait "* | "logs "* | "delete "*) ;;
  *) echo "stub kubectl: unexpected $*" >&2; exit 2 ;;
esac
STUB
chmod +x "${workspace}/bin/kubectl"

expect_drill() {
  local label="$1" want="$2" got=pass state="${workspace}/state-$1"
  mkdir -p "$state"
  PATH="${workspace}/bin:${PATH}" DRILL_MUTATION="$label" DRILL_STATE="$state" \
    NAMESPACE=backup SOURCE_NAMESPACE=forgejo SOURCE_PVC=forgejo-data VERIFIER_IMAGE=img \
    RESTORE_TIMEOUT_SECONDS=2 POLL_SECONDS=1 \
    sh "${APP}/longhorn-restore-drill.sh" >"${workspace}/drill-${label}.log" 2>&1 || got=fail
  report "drill-${label}" "$want" "$got" "${workspace}/drill-${label}.log"
  if [[ "$want" == pass ]]; then
    grep -q 'backup.webgrip.io/restore-verified: "true"' "${state}/configmap.yaml" \
      && grep -q 'backup=backup-new' "${state}/volume.yaml" \
      || { echo "WRONG drill-${label}: the newest completed backup was not restored and recorded"; failures=$((failures + 1)); }
  elif [[ -f "${state}/configmap.yaml" ]]; then
    echo "WRONG drill-${label}: a failed drill recorded a verified restore"; failures=$((failures + 1))
  fi
}
expect_drill good pass
expect_drill stale-backup fail
expect_drill restore-failure fail
expect_drill faulted fail
expect_drill never-finishes fail
expect_drill verifier-fails fail

exit "$failures"
