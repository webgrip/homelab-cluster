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
kubectl_cmd --kubeconfig "${kubeconfig}" apply -f "${workspace}/policies/namespace-defaults-generate.yaml"
kubectl_cmd --kubeconfig "${kubeconfig}" apply -f "${workspace}/policies/namespace-tenancy-audit.yaml"
kubectl_cmd --kubeconfig "${kubeconfig}" apply -f "${workspace}/policies/network-exposure-enforce.yaml"

log info "Running Chainsaw suite" "image=${CHAINSAW_IMAGE}"
docker run --rm \
    --network host \
    -w /work/chainsaw \
    -e KUBECONFIG=/kubeconfig \
    -v "${kubeconfig}:/kubeconfig:ro" \
    -v "${workspace}:/work" \
    "${CHAINSAW_IMAGE}" \
    test . --config /work/chainsaw/chainsaw-config.yaml
