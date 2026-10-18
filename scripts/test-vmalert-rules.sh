#!/usr/bin/env bash
set -euo pipefail
shopt -s inherit_errexit

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
TESTS_DIR="${ROOT_DIR}/scripts/vmalert-tests"
RULES_DIR="${ROOT_DIR}/kubernetes/apps/observability/victoria-metrics/app/rules"
VMUTILS_VERSION="v1.147.0"
VMUTILS_TARBALL="vmutils-linux-amd64-${VMUTILS_VERSION}.tar.gz"
VMUTILS_TARBALL_SHA256="1e5da38c3d8d7af9c4fc0daa8a2103f2578c40ed81752d21f20a3bd6d0506b3f"
VMUTILS_URL="https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VMUTILS_VERSION}/${VMUTILS_TARBALL}"
VMALERT_TOOL_CACHE="${VMALERT_TOOL_CACHE:-${XDG_CACHE_HOME:-${HOME}/.cache}/vmalert-tool/${VMUTILS_VERSION}}"

yq_cmd() {
  if command -v yq >/dev/null 2>&1; then
    yq "$@"
  else
    mise -C "$ROOT_DIR" exec -- yq "$@"
  fi
}

pinned_vmalert_tool() {
  mkdir -p "$VMALERT_TOOL_CACHE"
  local binary
  binary="$(cd "$VMALERT_TOOL_CACHE" && pwd)/vmalert-tool-prod"
  if [[ -x "$binary" ]]; then
    echo "$binary"
    return
  fi
  local download
  download="$(mktemp -d)"
  curl -fsSL --retry 3 -o "${download}/${VMUTILS_TARBALL}" "$VMUTILS_URL"
  echo "${VMUTILS_TARBALL_SHA256}  ${download}/${VMUTILS_TARBALL}" | sha256sum --check --quiet >&2
  tar -xzf "${download}/${VMUTILS_TARBALL}" -C "$download" vmalert-tool-prod
  install -m 0755 "${download}/vmalert-tool-prod" "$binary"
  rm -rf "$download"
  echo "$binary"
}

vmalert_tool="${VMALERT_TOOL:-$(pinned_vmalert_tool)}"

workspace="$(mktemp -d)"
trap 'rm -rf "$workspace"' EXIT
mkdir -p "${workspace}/rules"

shopt -s nullglob
test_files=("${TESTS_DIR}"/*.test.yaml)
if ((${#test_files[@]} == 0)); then
  echo "no vmalert rule tests under ${TESTS_DIR}" >&2
  exit 1
fi

for test_file in "${test_files[@]}"; do
  name="$(basename "$test_file" .test.yaml)"
  rule_source="${RULES_DIR}/prometheusrule-${name}.yaml"
  if [[ ! -f "$rule_source" ]]; then
    echo "${test_file}: expected rule source ${rule_source}" >&2
    exit 1
  fi
  yq_cmd '.spec | del(.groups[].rules[].annotations.description) | del(.groups[].rules[].annotations.runbook_url) | del(.groups[].rules[].annotations.dashboard_url)' "$rule_source" | sed 's/\$\$/$/g' >"${workspace}/rules/${name}.yaml"
  cp "$test_file" "${workspace}/${name}.test.yaml"
done

cd "$workspace"
args=()
for test_file in "${test_files[@]}"; do
  args+=("--files=$(basename "$test_file")")
done
"$vmalert_tool" unittest "${args[@]}"
