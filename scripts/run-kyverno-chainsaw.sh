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

log info "Creating KinD cluster for Chainsaw" "cluster=${cluster_name}" "node=${KIND_NODE_IMAGE}"
# Pin the node image through the Harbor proxy so the ~1 GiB kindest/node pull is LAN-speed and
# rate-limit-free instead of a cold docker.io pull on the runner's emptyDir daemon.
"${kind_bin}" create cluster --name "${cluster_name}" --image "${KIND_NODE_IMAGE}" \
    --kubeconfig "${kubeconfig}" --wait 2m
chmod a+r "${kubeconfig}"

log info "Installing Kyverno into KinD" "url=${KYVERNO_INSTALL_URL}"
curl -fsSL "${KYVERNO_INSTALL_URL}" -o "${workspace}/kyverno-install.yaml"
# Route the ghcr.io/kyverno/* controller images inside install.yaml through the Harbor proxy too
# (same cold-pull tax as the node image). No-op when KYVERNO_IMAGE_PROXY is empty.
if [[ -n "${KYVERNO_IMAGE_PROXY}" ]]; then
    sed -i "s#ghcr.io/kyverno/#${KYVERNO_IMAGE_PROXY}kyverno/#g" "${workspace}/kyverno-install.yaml"
fi
# Server-side apply (not `create`): the freshly-created KinD node's etcd can time out partway
# through applying install.yaml's ~40 CRDs+resources under CI disk load ("etcdserver: request
# timed out" — bit CI 2026-07-18). `create` is not idempotent, so a retry after a partial
# timeout dies with "already exists"; server-side apply reconciles instead, and it also dodges
# the client-side last-applied-annotation size limit that Kyverno's large CRDs blow. Retry only
# on known-transient control-plane errors so real failures still fail fast.
install_kyverno_with_retry() {
    local file="${1:?install file is required}"
    local attempts="${2:-5}"
    local delay_seconds="${3:-10}"
    local attempt=1

    while true; do
        local output
        if output="$(kubectl_cmd --kubeconfig "${kubeconfig}" apply --server-side --force-conflicts -f "${file}" 2>&1)"; then
            printf '%s\n' "${output}"
            return 0
        fi

        printf '%s\n' "${output}" >&2
        if ! grep -qE 'etcdserver: request timed out|etcdserver: leader changed|the server was unable to return a response|Timeout: request did not complete|connection refused|unexpected EOF|EOF$' <<<"${output}"; then
            return 1
        fi

        if ((attempt >= attempts)); then
            return 1
        fi

        log warn "Retrying Kyverno install after transient control-plane error" "attempt=${attempt}/${attempts}"
        sleep "${delay_seconds}"
        ((attempt++))
    done
}

install_kyverno_with_retry "${workspace}/kyverno-install.yaml"
kubectl_cmd --kubeconfig "${kubeconfig}" wait --for=condition=Established crd/clusterpolicies.kyverno.io --timeout=120s
# Only the admission + background controllers are exercised by the suites (validate/enforce +
# generate). The reports and cleanup controllers aren't asserted on by any chainsaw test
# (grep-verified), so we don't block on their rollout — they still install, we just don't wait.
kubectl_cmd --kubeconfig "${kubeconfig}" -n kyverno rollout status deploy/kyverno-admission-controller --timeout=180s
kubectl_cmd --kubeconfig "${kubeconfig}" -n kyverno rollout status deploy/kyverno-background-controller --timeout=180s

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
