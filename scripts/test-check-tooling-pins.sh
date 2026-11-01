#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
CHECK="${ROOT_DIR}/scripts/check-tooling-pins.sh"
SHA=abf3c951d8243ef030421ab2acff0af9edce3215
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
failures=0

pinned_workflow() {
  cat <<YAML
jobs:
  release:
    uses: webgrip/workflows/.forgejo/workflows/semantic-release.yml@${SHA} # v4.0.0
  docs:
    uses: webgrip/workflows/.forgejo/workflows/techdocs-generate.yml@v3.2.1
  build:
    runs-on: docker
    steps:
      - uses: actions/checkout@v4
      - uses: ./.forgejo/actions/local
      - uses: webgrip/some-other-repo/action@main
      - uses: https://forgejo.webgrip.dev/webgrip/infrastructure/.forgejo/actions/x@${SHA} # v1.0.0
      - uses: "webgrip/semantic-release-config/action@v2.5.0"
YAML
}

consumer() {
  local name="$1" dir
  dir="$work/case-$RANDOM-$RANDOM/$name"
  mkdir -p "$dir/.forgejo/workflows"
  pinned_workflow > "$dir/.forgejo/workflows/ci.yml"
  echo "$dir"
}

record() {
  local name="$1" want="$2" got="$3"
  if [[ "$got" == "$want" ]]; then
    echo "ok   ${name}"
  else
    echo "FAIL ${name}: expected ${want}, got ${got}"
    failures=$((failures + 1))
  fi
}

outcome() {
  local status=0
  bash "$CHECK" "$@" > "$work/out" 2>&1 || status=$?
  case "$status" in
    0) echo pass ;;
    1) echo fail ;;
    *) echo "error($status)" ;;
  esac
}

expect_fail_with() {
  local name="$1" line="$2" dir
  dir="$(consumer app)"
  mkdir -p "$dir/.forgejo/actions/nested"
  printf 'runs:\n  steps:\n    - uses: %s\n' "$line" > "$dir/.forgejo/actions/nested/action.yaml"
  last_failing_dir="$dir"
  record "$name" fail "$(outcome "$dir")"
  grep -q 'action.yaml:3:' "$work/out" || { echo "FAIL ${name}: the report does not name file and line"; failures=$((failures + 1)); }
}

record "every allowed pin form passes" pass "$(outcome "$(consumer app)")"
[[ ! -s "$work/out" ]] || { echo "FAIL a passing run printed: $(cat "$work/out")"; failures=$((failures + 1)); }

no_forgejo="$work/plain"
mkdir -p "$no_forgejo"
record "a repository without .forgejo passes" pass "$(outcome "$no_forgejo")"

self="$(consumer workflows)"
printf '      - uses: webgrip/workflows/.forgejo/composite-actions/x@main\n' >> "$self/.forgejo/workflows/ci.yml"
record "a repository may reference itself at @main" pass "$(outcome "$self")"

expect_fail_with "a tooling repository at @main fails" "webgrip/workflows/.forgejo/workflows/semantic-release.yml@main"
expect_fail_with "a SHA without a version label fails" "webgrip/infrastructure/.forgejo/actions/x@${SHA}"
expect_fail_with "a SHA labelled with a branch fails" "webgrip/workflows/.forgejo/workflows/techdocs-generate.yml@${SHA} # main"
expect_fail_with "a full-URL reference at @main fails" "https://forgejo.webgrip.dev/webgrip/workflows/.forgejo/composite-actions/semantic-release-monorepo@main"
expect_fail_with "a floating major tag fails" "webgrip/semantic-release-config/action@v2"
expect_fail_with "a short SHA with a label fails" "webgrip/workflows/.forgejo/workflows/x.yml@abf3c95 # v1.0.0"

record "one failing repository among passing ones fails the run" fail "$(outcome "$(consumer app)" "$self" "$last_failing_dir")"
record "no arguments is a usage error" "error(2)" "$(outcome)"
record "a missing directory is a usage error" "error(2)" "$(outcome "$work/does-not-exist")"

if [[ "$failures" -gt 0 ]]; then
  echo "${failures} case(s) failed"
  exit 1
fi
echo "ok: tooling pins pass at vX.Y.Z or <sha> # vX.Y.Z and fail at a branch, a bare SHA, a branch label, a floating tag or a short SHA"
