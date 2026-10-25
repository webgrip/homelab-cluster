#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 [list|delete]" >&2
  echo "  list    (default) read-only: show Longhorn backups no recurring job will ever prune, and their size" >&2
  echo "  delete  delete exactly what list shows as deletable; needs CONFIRM=delete-retired-backups" >&2
  exit 64
}

mode="${1:-list}"
[[ "$mode" == list || "$mode" == delete ]] || usage
MIN_REPLACEMENT_BACKUPS="${MIN_REPLACEMENT_BACKUPS:-2}"

fetch() {
  if [[ -n "${FIXTURES:-}" ]]; then
    cat "${FIXTURES}/$1.json"
  else
    kubectl -n longhorn-system get "$1.longhorn.io" -o json
  fi
}

snapshot="$(mktemp -d)"
trap 'rm -rf "$snapshot"' EXIT
for kind in recurringjobs volumes backupvolumes backups; do fetch "$kind" >"${snapshot}/${kind}.json"; done

plan="$(jq -n \
  --argjson min "$MIN_REPLACEMENT_BACKUPS" \
  --slurpfile jobs_file "${snapshot}/recurringjobs.json" \
  --slurpfile volumes_file "${snapshot}/volumes.json" \
  --slurpfile backupvolumes_file "${snapshot}/backupvolumes.json" \
  --slurpfile backups_file "${snapshot}/backups.json" '
  $jobs_file[0] as $jobs | $volumes_file[0] as $volumes
  | $backupvolumes_file[0] as $backupvolumes | $backups_file[0] as $backups
  | def backup_jobs: [$jobs.items[] | select(.spec.task == "backup")];
  def enrolled($v):
    ($v.metadata.labels // {}) as $l
    | [backup_jobs[]
       | select(
           ($l["recurring-job.longhorn.io/\(.metadata.name)"] == "enabled")
           or any(.spec.groups[]?; $l["recurring-job-group.longhorn.io/\(.)"] == "enabled"))
       | .metadata.name];
  ($volumes.items | map({key: .metadata.name, value: .}) | from_entries) as $vol
  | [$backups.items[] | select(.status.state == "Completed")] as $done
  | [$backupvolumes.items[] | (.spec.volumeName // .status.volumeName) as $name | {
      backupVolume: .metadata.name,
      volume: $name,
      pvc: (($vol[$name].status.kubernetesStatus // {}) | "\(.namespace // "?")/\(.pvcName // "?")"),
      live: ($vol[$name] != null),
      stored: ((.status.dataStored // "0") | tonumber),
      jobs: (if $vol[$name] then enrolled($vol[$name]) else [] end),
      backups: [$done[] | select(.status.volumeName == $name)
                | {name: .metadata.name, job: (.status.labels.RecurringJob // ""), at: .status.backupCreatedAt,
                   size: ((.status.size // "0") | tonumber)}]
    }]
  | map(. as $bv | . + {
      verdict: (
        if ($bv.live | not) then "orphaned"
        elif ($bv.jobs | length) == 0 then "unenrolled"
        else "enrolled" end),
      stale: [$bv.backups[] | select(.job != "" and (.job as $j | $bv.jobs | index($j) | not))],
      replacements: [$bv.backups[] | select(.job as $j | $bv.jobs | index($j))]
    })
  | {
      unenrolled: [.[] | select(.verdict == "unenrolled")],
      orphaned: [.[] | select(.verdict == "orphaned")],
      superseded: [.[] | select(.verdict == "enrolled" and (.stale | length) > 0)
                   | . + {ready: ((.replacements | length) >= $min)}]
    }')"

gb() { jq -nr --argjson b "$1" '"\($b / 1000000000 * 10 | round / 10) GB"'; }

echo "== Unenrolled volumes: every backup of the volume goes, the whole BackupVolume is deleted"
jq -r '.unenrolled[] | "\(.backupVolume)\t\(.pvc)\t\(.backups | length) backups\t\(.stored)"' <<<"$plan" \
  | while IFS=$'\t' read -r bv pvc n stored; do printf '  %s  %-40s %-12s frees %s\n' "$bv" "$pvc" "$n" "$(gb "$stored")"; done
echo "== Superseded backups: made by a recurring job the volume no longer runs, so nothing prunes them"
jq -r '.superseded[] | "\(.backupVolume)\t\(.pvc)\t\(.stale | length)\t\(.stale | map(.job) | unique | join(","))\t\(.replacements | length)\t\(.ready)\t\(.stored)\t\([.backups[].size] | max // 0)"' <<<"$plan" \
  | while IFS=$'\t' read -r bv pvc n old_jobs repl ready stored newest; do
      printf '  %s  %-40s %s old %s backups; %s from the current job%s; frees at most %s\n' \
        "$bv" "$pvc" "$n" "$old_jobs" "$repl" "$([[ "$ready" == true ]] || echo ", NOT YET: wait for ${MIN_REPLACEMENT_BACKUPS}")" \
        "$(gb $(( stored > newest ? stored - newest : 0 )))"
    done
echo "== Orphaned BackupVolumes (no live volume): never deleted here, review by hand"
jq -r '.orphaned[] | "  \(.backupVolume)  \(.backups | length) backups"' <<<"$plan"

whole="$(jq '[.unenrolled[].stored] | add // 0' <<<"$plan")"
echo "Total: $(gb "$whole") from unenrolled volumes, plus up to the superseded amounts above (shared blocks stay)."

[[ "$mode" == delete ]] || exit 0
if [[ "${CONFIRM:-}" != delete-retired-backups ]]; then
  echo "refusing to delete: set CONFIRM=delete-retired-backups after reading the list above" >&2
  exit 65
fi
backupvolumes=()
while IFS= read -r name; do backupvolumes+=("$name"); done < <(jq -r '.unenrolled[].backupVolume' <<<"$plan")
backups=()
while IFS= read -r name; do backups+=("$name"); done < <(jq -r '.superseded[] | select(.ready) | .stale[].name' <<<"$plan")
(( ${#backupvolumes[@]} )) && kubectl -n longhorn-system delete backupvolumes.longhorn.io "${backupvolumes[@]}"
(( ${#backups[@]} )) && kubectl -n longhorn-system delete backups.longhorn.io "${backups[@]}"
echo "deleted ${#backupvolumes[@]} BackupVolume(s) and ${#backups[@]} superseded backup(s); Garage frees the space after its 24 h tombstone GC"
