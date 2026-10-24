#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
original="$root/kubernetes/apps/ai/omnigraph/app/next/bootstrap.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
wrong=0

expect() {
  verdict=$1 label=$2 reason=$3 script=$4
  output=$(python3 "$root/scripts/test_omnigraph_next_bootstrap.py" --bootstrap "$script" 2>&1)
  rc=$?
  if [ "$verdict" = pass ] && [ "$rc" -eq 0 ]; then
    echo "ok    expect=pass rc=0  $label"
  elif [ "$verdict" = fail ] && [ "$rc" -ne 0 ] && printf '%s' "$output" | grep -qF -- "$reason"; then
    echo "ok    expect=fail rc=$rc  $label"
  else
    echo "WRONG expect=$verdict rc=$rc  $label"
    printf '%s\n' "$output" | grep -E "^(FAIL|PASS)" | head -3 | sed 's/^/        /'
    wrong=$((wrong + 1))
  fi
}

mutant() {
  cp "$original" "$work/$1.sh"
  sed -i "$2" "$work/$1.sh"
  if cmp -s "$original" "$work/$1.sh"; then
    echo "WRONG mutation $1 changed nothing"
    wrong=$((wrong + 1))
  fi
  echo "$work/$1.sh"
}

expect pass "unchanged bootstrap" "" "$original"
expect fail "deletions applied without approval" "removing a graph without approved-deletions must be skipped" "$(mutant no-deletion-gate 's/^  if \[ -n "\$refused" \]; then$/  if false; then/')"
expect fail "a refused plan stops the pod" "bootstrap.sh exited" "$(mutant fatal-plan 's/^  elif ! printf .%s. "\$plan" | grep -q .*$/  elif ! printf "%s" "$plan" | grep -q "\\"ok\\":true" \&\& exit 1; then/')"
expect fail "direct writes keep the cluster lock, so the next write is refused" "bootstrap.sh exited" "$(mutant keeps-lock 's/^  release_retained_lock$/  :/')"
expect fail "backfill ignores its cap" "the backfill cap is" "$(mutant uncapped 's/| head -n "\$backfill_max_rows" >/| cat >/')"
expect fail "no cleanup" "cleanup ran on" "$(mutant no-cleanup '/owned_write omnigraph cleanup --target/,+2d')"

echo "wrong verdicts: $wrong"
[ "$wrong" -eq 0 ]
