#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

KYVERNO_CLI_IMAGE="${KYVERNO_CLI_IMAGE:-ghcr.io/kyverno/kyverno-cli:v1.18.1@sha256:b7e272572d244ddec0b83469f7200ba883555bf69de4b294cee52a197c8c6590}"
CHAINSAW_IMAGE="${CHAINSAW_IMAGE:-ghcr.io/kyverno/chainsaw:v0.2.15@sha256:527f3be2b9ec0580cb0bc84540a0fee99406b011c24ae3a30953e525af60809d}"
KYVERNO_INSTALL_URL="${KYVERNO_INSTALL_URL:-https://github.com/kyverno/kyverno/releases/download/v1.18.1/install.yaml}"
KYVERNO_TEST_SECRET_DOMAIN="${KYVERNO_TEST_SECRET_DOMAIN:-example.com}"

prepare_kyverno_test_workspace() {
    local root_dir="${1:?root dir is required}"
    local workspace="${2:?workspace dir is required}"
    local policy_dir="${root_dir}/kubernetes/apps/kyverno/policies/app"
    local tests_dir="${root_dir}/kubernetes/apps/kyverno/tests"

    mkdir -p "${workspace}/cli" "${workspace}/chainsaw" "${workspace}/policies"

    rsync -a "${tests_dir}/cli/" "${workspace}/cli/"
    rsync -a "${tests_dir}/chainsaw/" "${workspace}/chainsaw/"

    # Load EVERY Kyverno policy + exception into the test workspace, discovered by
    # kind. This was previously a hardcoded allowlist that silently omitted policies
    # (workload-hardening, workload-advanced-hardening, secrets-observability-ops,
    # image-hygiene, image-verify-harbor, storage-cnpg) — so one could promote those
    # to Enforce with ZERO CLI test coverage and CI would stay green. Discovering by
    # kind closes that hole and keeps the test set in lock-step with the policies on
    # disk. See ADR-0033 + scripts/check-kyverno-test-coverage.sh.
    local policy
    while IFS= read -r -d '' policy; do
        sed "s|\${SECRET_DOMAIN}|${KYVERNO_TEST_SECRET_DOMAIN}|g; s|__SECRET_DOMAIN__|${KYVERNO_TEST_SECRET_DOMAIN}|g" \
            "${policy}" >"${workspace}/policies/$(basename "${policy}")"
    done < <(grep -rlZ -E '^kind: (ClusterPolicy|Policy|PolicyException|ClusterCleanupPolicy)$' "${policy_dir}"/*.yaml)

    while IFS= read -r -d '' file; do
        sed -i "s|\${SECRET_DOMAIN}|${KYVERNO_TEST_SECRET_DOMAIN}|g; s|__SECRET_DOMAIN__|${KYVERNO_TEST_SECRET_DOMAIN}|g" "${file}"
    done < <(find "${workspace}/cli" "${workspace}/chainsaw" -type f \( -name '*.yaml' -o -name '*.yml' \) -print0)

    chmod -R a+rwX "${workspace}"
}

ensure_kind() {
    local install_dir="${1:?install dir is required}"

    if command -v kind >/dev/null 2>&1; then
        command -v kind
        return 0
    fi

    check_cli go

    local bin_dir="${install_dir}/bin"
    mkdir -p "${bin_dir}"
    GOBIN="${bin_dir}" go install sigs.k8s.io/kind@v0.27.0
    printf '%s\n' "${bin_dir}/kind"
}

kubectl_cmd() {
    if command -v kubectl >/dev/null 2>&1; then
        kubectl "$@"
        return
    fi

    if command -v mise >/dev/null 2>&1; then
        mise exec -- kubectl "$@"
        return
    fi

    log error "kubectl is required to run Chainsaw tests"
}
