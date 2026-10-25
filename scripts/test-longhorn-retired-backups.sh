#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
SCRIPT="${ROOT_DIR}/scripts/longhorn-retired-backups.sh"
workspace="$(mktemp -d)"
trap 'rm -rf "$workspace"' EXIT

volume() { jq -nc --arg n "$1" --argjson l "$2" --arg ns "$3" '{metadata: {name: $n, labels: $l}, status: {kubernetesStatus: {namespace: $ns, pvcName: $n}}}'; }
backup() { jq -nc --arg n "$1" --arg v "$2" --arg j "$3" '{metadata: {name: $n}, status: {volumeName: $v, state: "Completed", backupCreatedAt: "2026-10-25T02:00:00Z", size: "1000000000", labels: {RecurringJob: $j}}}'; }
bv() { jq -nc --arg v "$1" '{metadata: {name: "\($v)-bv"}, spec: {volumeName: $v}, status: {dataStored: "5000000000"}}'; }
fixture() {
  local dir="$1" bulk_runs="$2"
  mkdir -p "$dir"
  jq -n '{items: [
    {metadata: {name: "daily"}, spec: {task: "backup", groups: ["daily"]}},
    {metadata: {name: "bulk"}, spec: {task: "backup", groups: ["bulk"]}},
    {metadata: {name: "trim"}, spec: {task: "filesystem-trim", groups: ["default"]}}]}' >"${dir}/recurringjobs.json"
  jq -n --argjson a "$(volume app '{"recurring-job-group.longhorn.io/daily":"enabled"}' prod)" \
        --argjson b "$(volume metrics '{"recurring-job-group.longhorn.io/default":"enabled"}' obs)" \
        --argjson c "$(volume big '{"recurring-job-group.longhorn.io/bulk":"enabled"}' store)" \
        --argjson d "$(volume direct '{"recurring-job.longhorn.io/daily":"enabled"}' prod)" \
        '{items: [$a, $b, $c, $d]}' >"${dir}/volumes.json"
  jq -n --argjson a "$(bv app)" --argjson b "$(bv metrics)" --argjson c "$(bv big)" --argjson d "$(bv gone)" --argjson e "$(bv direct)" \
        '{items: [$a, $b, $c, $d, $e]}' >"${dir}/backupvolumes.json"
  {
    backup app-1 app daily; backup app-2 app daily
    backup metrics-1 metrics bulk
    backup big-old-1 big daily; backup big-old-2 big daily
    for i in $(seq 1 "$bulk_runs"); do backup "big-new-$i" big bulk; done
    backup gone-1 gone daily
    backup direct-1 direct daily
  } | jq -s '{items: .}' >"${dir}/backups.json"
}

mkdir -p "${workspace}/bin"
cat >"${workspace}/bin/kubectl" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${KUBECTL_CALLS:?}"
STUB
chmod +x "${workspace}/bin/kubectl"
export PATH="${workspace}/bin:${PATH}"

failures=0
run() {
  local label="$1" want_code="$2" bulk_runs="$3" mode="$4" confirm="${5:-}" code=0
  fixture "${workspace}/${label}" "$bulk_runs"
  KUBECTL_CALLS="${workspace}/${label}.calls" FIXTURES="${workspace}/${label}" CONFIRM="$confirm" \
    "$SCRIPT" "$mode" >"${workspace}/${label}.log" 2>&1 || code=$?
  touch "${workspace}/${label}.calls"
  if [[ "$code" == "$want_code" ]]; then echo "ok    ${label}: exit ${code}"; else
    echo "WRONG ${label}: exit ${code}, wanted ${want_code}"; cat "${workspace}/${label}.log"; failures=$((failures + 1)); fi
}
check() {
  local label="$1"; shift
  if "$@"; then echo "ok    ${label}"; else echo "WRONG ${label}"; failures=$((failures + 1)); fi
}
deleted() { grep -q -- "$2" "${workspace}/$1.calls"; }
kept() { ! deleted "$@"; }

run list-is-read-only 0 2 list
check "list deletes nothing" [ ! -s "${workspace}/list-is-read-only.calls" ]
check "list names the unenrolled volume" grep -q 'metrics-bv' "${workspace}/list-is-read-only.log"
check "list names the orphaned BackupVolume as review-only" grep -q 'gone-bv  1 backups' "${workspace}/list-is-read-only.log"

run delete-without-confirm-refused 65 2 delete
check "refused delete deletes nothing" [ ! -s "${workspace}/delete-without-confirm-refused.calls" ]

run delete-before-replacements 0 1 delete delete-retired-backups
check "unenrolled BackupVolume deleted" deleted delete-before-replacements 'backupvolumes.longhorn.io metrics-bv'
check "superseded backups kept until the current job ran twice" kept delete-before-replacements 'big-old'

run delete-after-replacements 0 2 delete delete-retired-backups
check "superseded backups deleted once replaced" deleted delete-after-replacements 'backups.longhorn.io big-old-1 big-old-2'
check "replacement backups kept" kept delete-after-replacements 'big-new'
check "enrolled volume kept" kept delete-after-replacements 'app'
check "directly labelled volume counts as enrolled" kept delete-after-replacements 'direct'
check "orphaned BackupVolume never deleted" kept delete-after-replacements 'gone'

exit "$failures"
