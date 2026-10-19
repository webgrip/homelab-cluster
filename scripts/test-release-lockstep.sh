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
  kubernetes/apps/ploeg/ploeg/app/claude-runner/deployment.yaml
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
expect fail "claude-runner harness behind ploegd" \
  kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml 's/(claude-runner:)[0-9][^@]*@/\10.0.1-rc.1@/'
expect fail "claude-runner behind ploegd" \
  kubernetes/apps/ploeg/ploeg/app/claude-runner/deployment.yaml 's/(claude-runner:)[0-9][^@]*@/\10.0.1-rc.1@/'

committed_version() {
  python3 "$CHECK" "$ROOT_DIR" | sed -n "s/^OK $1 //p"
}

UNFOLD_VERSION="$(committed_version Unfold)"
PLOEG_VERSION="$(committed_version Ploeg)"

unfold_release_source() {
  local certified_ploeg="$1" layout="${2:-bundle}" source release
  source="$(mktemp -d)"
  release="${source}/unfold-v${UNFOLD_VERSION}"
  if [[ -n "$certified_ploeg" ]]; then
    mkdir -p "$release"
    if [[ "$layout" == "submodule" ]]; then
      printf '[submodule "apps/ploeg"]\n\tpath = apps/ploeg\n\turl = https://github.com/ploeg-hq/ploeg.git\n\tbranch = v%s\n' \
        "$certified_ploeg" >"${release}/.gitmodules"
    else
      mkdir -p "${release}/apps/unfold"
      printf '{\n  "contract": "ghcr.io/ploeg-hq/ploeg-contract:%s@sha256:%s"\n}\n' \
        "$certified_ploeg" "$(printf '0%.0s' {1..64})" >"${release}/apps/unfold/ploeg-release.json"
    fi
  fi
  echo "$source"
}

committed_repository() {
  local dir
  dir="$(fresh_copy)"
  git -C "$dir" init -q
  git -C "$dir" add .
  git -C "$dir" -c user.name=test -c user.email=test@example.invalid -c commit.gpgsign=false commit -qm base
  echo "$dir"
}

move_ploeg_pins_to() {
  local dir="$1" version="$2"
  sed -E -i "s/(tag: )[0-9][^[:space:]]*/\1${version}/" "${dir}/kubernetes/apps/ploeg/ploeg/app/ocirepository.yaml"
  sed -E -i -e "s/(tag: \")[0-9][^@]*@/\1${version}@/" -e "s/(claude-runner:)[0-9][^@]*@/\1${version}@/" \
    "${dir}/kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml"
  sed -E -i "s/(ploegd:)[0-9][^@]*@/\1${version}@/" "${dir}/kubernetes/apps/ploeg/ploeg/app/mcp/deployment.yaml"
  sed -E -i "s/(claude-runner:)[0-9][^@]*@/\1${version}@/" "${dir}/kubernetes/apps/ploeg/ploeg/app/claude-runner/deployment.yaml"
}

expect_pair() {
  local want="$1" name="$2" certified_ploeg="$3" ploeg_pin="$4" base="$5" layout="${6:-bundle}" dir source got
  dir="$(committed_repository)"
  source="$(unfold_release_source "$certified_ploeg" "$layout")"
  [[ "$ploeg_pin" == "$PLOEG_VERSION" ]] || move_ploeg_pins_to "$dir" "$ploeg_pin"
  local arguments=(--certified-pair --source "file://${source}")
  [[ -z "$base" ]] || arguments+=(--base "$base")
  if python3 "$CHECK" "${arguments[@]}" "$dir" >/dev/null 2>&1; then got=pass; else got=fail; fi
  if [[ "$got" == "$want" ]]; then
    echo "ok   ${name}: ${got}"
  else
    echo "FAIL ${name}: expected ${want}, got ${got}"
    failures=$((failures + 1))
  fi
  rm -rf "$dir" "$source"
}

expect_pair pass "Ploeg is the release Unfold pins" "$PLOEG_VERSION" "$PLOEG_VERSION" ""
expect_pair fail "Ploeg is not the release Unfold pins" "0.0.1-rc.1" "$PLOEG_VERSION" ""
expect_pair fail "Unfold release names no Ploeg release" "" "$PLOEG_VERSION" ""
expect_pair pass "Ploeg is the release an older Unfold names in .gitmodules" "$PLOEG_VERSION" "$PLOEG_VERSION" "" submodule
expect_pair fail "Ploeg is not the release an older Unfold names in .gitmodules" "0.0.1-rc.1" "$PLOEG_VERSION" "" submodule
expect_pair pass "uncertified pair unchanged from the base" "0.0.1-rc.1" "$PLOEG_VERSION" HEAD
expect_pair fail "Ploeg moved ahead of the release Unfold pins" "$PLOEG_VERSION" "9.9.9-rc.1" HEAD
expect_pair pass "Ploeg moved to the release Unfold pins" "9.9.9-rc.1" "9.9.9-rc.1" HEAD

expect_pair_over_http() {
  local want="$1" name="$2" dir source server port got
  dir="$(committed_repository)"
  source="$(unfold_release_source "$PLOEG_VERSION")"
  python3 -c '
import functools, http.server, sys
class RefusePythonUserAgent(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        if self.headers.get("User-Agent", "").startswith("Python-urllib"):
            self.send_error(403, "error code: 1010")
            return
        super().do_GET()
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RefusePythonUserAgent, directory=sys.argv[1]))
print(server.server_address[1], flush=True)
server.serve_forever()
' "$source" >"${source}.port" &
  server=$!
  for _ in $(seq 50); do [[ -s "${source}.port" ]] && break; sleep 0.1; done
  port="$(head -n 1 "${source}.port")"
  if python3 "$CHECK" --certified-pair --source "http://127.0.0.1:${port}" "$dir" >/dev/null 2>&1; then got=pass; else got=fail; fi
  kill "$server" 2>/dev/null || true
  wait "$server" 2>/dev/null || true
  if [[ "$got" == "$want" ]]; then
    echo "ok   ${name}: ${got}"
  else
    echo "FAIL ${name}: expected ${want}, got ${got}"
    failures=$((failures + 1))
  fi
  rm -rf "$dir" "$source" "${source}.port"
}

expect_pair_over_http pass "a forge that refuses Python's default User-Agent still serves the Unfold release"

if (( failures > 0 )); then
  echo "${failures} lockstep case(s) failed"
  exit 1
fi
