#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/kyverno-tests.sh"

check_cli curl docker find mktemp rsync sed

workspace="$(mktemp -d)"
cluster_name="kyverno-chainsaw-$(date +%s)"
kubeconfig="${workspace}/kubeconfig"
kind_bin="$(ensure_kind "${workspace}")"

cleanup() {
    if [[ "${KEEP_KIND_CLUSTER:-false}" != "true" ]]; then
        "${kind_bin}" delete cluster --name "${cluster_name}" >/dev/null 2>&1 || true
    fi
    rm -rf "${workspace}"
}
trap cleanup EXIT

prepare_kyverno_test_workspace "${ROOT_DIR}" "${workspace}"
mkdir -p "${workspace}/chainsaw/reports"
chmod -R a+rwX "${workspace}/chainsaw"

log info "Creating KinD cluster for Chainsaw" "cluster=${cluster_name}"
"${kind_bin}" create cluster --name "${cluster_name}" --kubeconfig "${kubeconfig}" --wait 2m
chmod a+r "${kubeconfig}"

log info "Installing Kyverno into KinD" "url=${KYVERNO_INSTALL_URL}"
curl -fsSL "${KYVERNO_INSTALL_URL}" -o "${workspace}/kyverno-install.yaml"
kubectl_cmd --kubeconfig "${kubeconfig}" create -f "${workspace}/kyverno-install.yaml"
kubectl_cmd --kubeconfig "${kubeconfig}" wait --for=condition=Established crd/clusterpolicies.kyverno.io --timeout=120s
kubectl_cmd --kubeconfig "${kubeconfig}" -n kyverno rollout status deploy/kyverno-admission-controller --timeout=180s
kubectl_cmd --kubeconfig "${kubeconfig}" -n kyverno rollout status deploy/kyverno-background-controller --timeout=180s
kubectl_cmd --kubeconfig "${kubeconfig}" -n kyverno rollout status deploy/kyverno-cleanup-controller --timeout=180s
kubectl_cmd --kubeconfig "${kubeconfig}" -n kyverno rollout status deploy/kyverno-reports-controller --timeout=180s

log info "Applying Kyverno policies under test"
apply_with_webhook_retry() {
    local file="${1:?policy file is required}"
    local attempts="${2:-6}"
    local delay_seconds="${3:-5}"
    local attempt=1

    while true; do
        local output
        if output="$(kubectl_cmd --kubeconfig "${kubeconfig}" apply -f "${file}" 2>&1)"; then
            printf '%s\n' "${output}"
            return 0
        fi

        printf '%s\n' "${output}" >&2
        if ! grep -q 'failed calling webhook "mutate-policy.kyverno.svc".*connect: connection refused' <<<"${output}"; then
            return 1
        fi

        if ((attempt >= attempts)); then
            return 1
        fi

        log warn "Retrying policy apply after webhook connection issue" "file=${file}" "attempt=${attempt}/${attempts}"
        sleep "${delay_seconds}"
        ((attempt++))
    done
}

apply_with_webhook_retry "${workspace}/policies/namespace-defaults-generate.yaml"
apply_with_webhook_retry "${workspace}/policies/namespace-tenancy-audit.yaml"
apply_with_webhook_retry "${workspace}/policies/network-exposure-enforce.yaml"

log info "Running Chainsaw suite" "image=${CHAINSAW_IMAGE}"
docker run --rm \
    --network host \
    -w /work/chainsaw \
    -e KUBECONFIG=/kubeconfig \
    -v "${kubeconfig}:/kubeconfig:ro" \
    -v "${workspace}:/work" \
    "${CHAINSAW_IMAGE}" \
    test . --config /work/chainsaw/chainsaw-config.yaml
