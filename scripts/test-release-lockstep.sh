#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
CHECK="${ROOT_DIR}/scripts/check_release_lockstep.py"
STANDALONE_PLOEG=kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml
PINS=(
  kubernetes/apps/ploeg/unfold/app/ocirepository.yaml
  kubernetes/apps/ploeg/unfold/app/helmrelease.yaml
)
failures=0

fresh_copy() {
  local dir
  dir="$(mktemp -d)"
  for pin in "${PINS[@]}"; do
    mkdir -p "${dir}/$(dirname "$pin")"
    cp "${ROOT_DIR}/${pin}" "${dir}/${pin}"
  done
  echo "$dir"
}

record() {
  local want="$1" name="$2" got="$3"
  if [[ "$got" == "$want" ]]; then
    echo "ok   ${name}: ${got}"
  else
    echo "FAIL ${name}: expected ${want}, got ${got}"
    failures=$((failures + 1))
  fi
}

run_check() {
  if python3 "$CHECK" "$1" >/dev/null 2>&1; then echo pass; else echo fail; fi
}

expect() {
  local want="$1" name="$2" file="$3" sed_expr="$4" dir
  dir="$(fresh_copy)"
  if [[ -n "$file" ]]; then
    sed -E -i "$sed_expr" "${dir}/${file}"
    if cmp -s "${ROOT_DIR}/${file}" "${dir}/${file}"; then
      echo "BROKEN TEST ${name}: the mutation changed nothing in ${file}"
      failures=$((failures + 1))
      rm -rf "$dir"
      return
    fi
  fi
  record "$want" "$name" "$(run_check "$dir")"
  rm -rf "$dir"
}

expect_with_standalone_ploeg() {
  local dir
  dir="$(fresh_copy)"
  mkdir -p "${dir}/$(dirname "$STANDALONE_PLOEG")"
  printf 'apiVersion: helm.toolkit.fluxcd.io/v2\nkind: HelmRelease\nmetadata:\n  name: ploeg\nspec:\n  suspend: true\n' >"${dir}/${STANDALONE_PLOEG}"
  record fail "a standalone Ploeg HelmRelease comes back" "$(run_check "$dir")"
  rm -rf "$dir"
}

expect pass "pins as committed" "" ""
expect fail "Unfold chart ahead of its images" \
  kubernetes/apps/ploeg/unfold/app/ocirepository.yaml 's/(tag: )[0-9][^[:space:]]*/\19.9.9-rc.1/'
expect fail "Unfold image ahead of its chart" \
  kubernetes/apps/ploeg/unfold/app/helmrelease.yaml '/repository: harbor\.webgrip\.dev\/webgrip\/unfold$/{n;s/(tag: )[0-9][^[:space:]]*/\19.9.9-rc.1/}'
expect fail "Unfold workspace image ahead of its chart" \
  kubernetes/apps/ploeg/unfold/app/helmrelease.yaml 's/(unfold-agent:)[^@]+@/\19.9.9-rc.1@/'
expect fail "Unfold image without a digest" \
  kubernetes/apps/ploeg/unfold/app/helmrelease.yaml '/repository: harbor\.webgrip\.dev\/webgrip\/unfold$/{n;n;/digest:/d}'
expect_with_standalone_ploeg

if (( failures > 0 )); then
  echo "${failures} lockstep case(s) failed"
  exit 1
fi
