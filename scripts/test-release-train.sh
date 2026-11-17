#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
CHECK="${ROOT_DIR}/scripts/check_release_train.py"
CHANNEL=kubernetes/apps/ploeg/unfold/release/ocirepository.yaml
RELEASE=kubernetes/apps/ploeg/unfold/app/helmrelease.yaml
STANDALONE_PLOEG=kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml
RETIRED_PINNED_CHANNEL=kubernetes/apps/ploeg/unfold/app/ocirepository.yaml
FILES=("$CHANNEL" "$RELEASE")
failures=0

fresh_copy() {
  local dir
  dir="$(mktemp -d)"
  for file in "${FILES[@]}"; do
    mkdir -p "${dir}/$(dirname "$file")"
    cp "${ROOT_DIR}/${file}" "${dir}/${file}"
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

expect_with_extra_file() {
  local name="$1" file="$2" dir
  dir="$(fresh_copy)"
  mkdir -p "${dir}/$(dirname "$file")"
  printf 'apiVersion: v1\nkind: Placeholder\nmetadata:\n  name: extra\n' >"${dir}/${file}"
  record fail "$name" "$(run_check "$dir")"
  rm -rf "$dir"
}

expect pass "the channel and release as committed" "" ""
expect pass "a hold that skips one bad candidate" \
  "$CHANNEL" 's/(semver: ">=0\.0\.0-0 <1\.0\.0-0)"/\1, !=0.4.0-rc.137"/'
expect fail "the chart pinned to one tag" \
  "$CHANNEL" 's/^(    )semver: .*/\1tag: 0.4.0-rc.136/'
expect fail "a digest pin next to the channel" \
  "$CHANNEL" 's/^(    semverFilter: .*)$/\1\n    digest: sha256:1c79c27e1153416612733cb40950c153b194ba793c5ce315303dd791fef7cbec/'
expect fail "a filter that lets per-architecture tags through" \
  "$CHANNEL" "s/^(    semverFilter: ).*/\1'^0\\\\.\\\\d+\\\\.\\\\d+-rc\\\\.\\\\d+'/"
expect fail "the chart read through Harbor's proxy cache" \
  "$CHANNEL" 's#url: oci://ghcr\.io/#url: oci://harbor.webgrip.dev/ghcr/#'
expect fail "signature verification switched off" \
  "$CHANNEL" '/^  verify:/,$d'
expect fail "a subject any workflow of the repository satisfies" \
  "$CHANNEL" 's#^(        subject: ).*#\1'"'"'^https://github\\.com/unfold-hq/unfold/'"'"'#'
expect fail "an issuer that is not anchored" \
  "$CHANNEL" 's#^(      - issuer: ).*#\1'"'"'token\\.actions\\.githubusercontent\\.com'"'"'#'
expect fail "the Unfold image pinned in the HelmRelease again" \
  "$RELEASE" 's#^(      repository: harbor\.webgrip\.dev/ghcr/unfold-hq/unfold)$#\1\n      tag: 0.4.0-rc.134#'
expect fail "the workspace image pinned in the HelmRelease again" \
  "$RELEASE" 's#^(    workspaceAgentImage:)$#    workspaceImage: harbor.webgrip.dev/ghcr/unfold-hq/unfold-agent:0.4.0-rc.134\n\1#'
expect fail "the HelmRelease reads a chart source other than the channel" \
  "$RELEASE" '/^  chartRef:/,/^  interval:/{/namespace: flux-system/d}'
expect_with_extra_file "a standalone Ploeg HelmRelease comes back" "$STANDALONE_PLOEG"
expect_with_extra_file "the pinned chart source comes back next to the channel" "$RETIRED_PINNED_CHANNEL"

if (( failures > 0 )); then
  echo "${failures} release train case(s) failed"
  exit 1
fi
