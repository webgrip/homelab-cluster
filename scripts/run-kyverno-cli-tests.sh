#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/kyverno-tests.sh"

check_cli docker find mktemp rsync sed

workspace="$(mktemp -d)"
trap 'rm -rf "${workspace}"' EXIT

prepare_kyverno_test_workspace "${ROOT_DIR}" "${workspace}"

log info "Running Kyverno CLI tests" "workspace=${workspace}" "image=${KYVERNO_CLI_IMAGE}"
docker run --rm \
    -v "${workspace}:/work" \
    "${KYVERNO_CLI_IMAGE}" \
    test /work/cli
