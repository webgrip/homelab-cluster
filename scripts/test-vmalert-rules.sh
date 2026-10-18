#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
TESTS_DIR="${ROOT_DIR}/scripts/vmalert-tests"
RULES_DIR="${ROOT_DIR}/kubernetes/apps/observability/victoria-metrics/app/rules"
VMALERT_TOOL_IMAGE="harbor.webgrip.dev/dockerhub/victoriametrics/vmalert-tool:v1.147.0@sha256:b89411be0487fbf0d966047dd76657c18f23522c4e547ae1ac757d644c52335a"

yq_cmd() {
  if command -v yq >/dev/null 2>&1; then
    yq "$@"
  else
    mise exec -- yq "$@"
  fi
}

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
docker run --rm --user "$(id -u):$(id -g)" -v "${workspace}:/data" -w /data "$VMALERT_TOOL_IMAGE" unittest "${args[@]}"
