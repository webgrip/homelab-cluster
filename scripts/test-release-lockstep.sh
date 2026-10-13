#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
CHECK="${ROOT_DIR}/scripts/check_release_lockstep.py"
PINS=(
  kubernetes/apps/ploeg/unfold/app/ocirepository.yaml
  kubernetes/apps/ploeg/unfold/app/helmrelease.yaml
  kubernetes/apps/ploeg/ploeg/app/ocirepository.yaml
  kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml
  kubernetes/apps/ploeg/ploeg/app/mcp/deployment.yaml
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

expect() {
  local want="$1" name="$2" file="$3" sed_expr="$4" dir got
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
  if python3 "$CHECK" "$dir" >/dev/null 2>&1; then got=pass; else got=fail; fi
  if [[ "$got" == "$want" ]]; then
    echo "ok   ${name}: ${got}"
  else
    echo "FAIL ${name}: expected ${want}, got ${got}"
    failures=$((failures + 1))
  fi
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
expect fail "Ploeg chart ahead of ploegd" \
  kubernetes/apps/ploeg/ploeg/app/ocirepository.yaml 's/(tag: )[0-9][^[:space:]]*/\19.9.9-rc.1/'
expect fail "ploegd ahead of its chart" \
  kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml 's/(tag: ")[0-9][^@]*@/\19.9.9-rc.1@/'
expect fail "ploegd without a digest" \
  kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml 's/(tag: "[0-9][^@]*)@sha256:[a-f0-9]{64}/\1/'
expect fail "ploeg-mcp ahead of ploegd" \
  kubernetes/apps/ploeg/ploeg/app/mcp/deployment.yaml 's/(ploegd:)[0-9][^@]*@/\19.9.9-rc.1@/'

if (( failures > 0 )); then
  echo "${failures} lockstep case(s) failed"
  exit 1
fi
