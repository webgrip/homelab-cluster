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
# etcd on the node's tmpfs, not its disk. The CI node's disk saturates at ~12MB/s and the shared
# per-node dind runs several jobs at once (two KinD clusters overlapped in run 587), which
# starved etcd hard enough to fail the install with "etcdserver: request timed out" and to time
# out the admission-controller rollout at 0/1 replicas. KinD already mounts a tmpfs at /tmp in
# every node container (verified: `docker inspect` -> HostConfig.Tmpfs {"/run":"","/tmp":""}), so
# pointing kubeadm's etcd dataDir there costs no extra mount and works the same on any daemon,
# local or remote. The data is throwaway — the cluster is deleted at the end of the run — and a
# single-node test cluster's etcd is well under 100MB of the dind container's memory budget.
#
# Node image is pinned through the Harbor proxy so the ~1 GiB kindest/node pull is LAN-speed and
# rate-limit-free instead of a cold docker.io pull.
cat >"${workspace}/kind-config.yaml" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: ${KIND_NODE_IMAGE}
kubeadmConfigPatches:
  - |
    kind: ClusterConfiguration
    etcd:
      local:
        dataDir: /tmp/etcd
EOF
"${kind_bin}" create cluster --name "${cluster_name}" --config "${workspace}/kind-config.yaml" \
    --kubeconfig "${kubeconfig}" --wait 2m
chmod a+r "${kubeconfig}"

log info "Installing Kyverno into KinD" "url=${KYVERNO_INSTALL_URL}"
curl -fsSL "${KYVERNO_INSTALL_URL}" -o "${workspace}/kyverno-install.yaml"
# Route the ghcr.io/kyverno/* controller images inside install.yaml through the Harbor proxy too
# (same cold-pull tax as the node image). No-op when KYVERNO_IMAGE_PROXY is empty.
if [[ -n "${KYVERNO_IMAGE_PROXY}" ]]; then
    sed -i "s#ghcr.io/kyverno/#${KYVERNO_IMAGE_PROXY}kyverno/#g" "${workspace}/kyverno-install.yaml"
fi
# Applied from inside the node (kind_kubectl) — see scripts/lib/kyverno-tests.sh for why the
# client-side kubeconfig is unusable on the CI runner.
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
        if output="$(kind_kubectl "${cluster_name}" apply --server-side --force-conflicts -f - <"${file}" 2>&1)"; then
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
kind_kubectl "${cluster_name}" wait --for=condition=Established crd/clusterpolicies.kyverno.io --timeout=120s
# Only the admission + background controllers are exercised by the suites (validate/enforce +
# generate). The reports and cleanup controllers aren't asserted on by any chainsaw test
# (grep-verified), so we don't block on their rollout — they still install, we just don't wait.
#
# 180s was not enough on a contended CI node (run 587 died at "0 of 1 updated replicas are
# available"). A rollout that needs >7min is a real failure, not slowness, so the ceiling stays
# finite — and when it IS hit, dump why instead of leaving "timed out waiting for the condition"
# as the only evidence.
wait_for_rollout() {
    local deployment="${1:?deployment is required}"

    if kind_kubectl "${cluster_name}" -n kyverno rollout status "deploy/${deployment}" --timeout=420s; then
        return 0
    fi

    log warn "Rollout failed — dumping cluster state" "deployment=${deployment}"
    kind_kubectl "${cluster_name}" -n kyverno get pods -o wide || true
    kind_kubectl "${cluster_name}" -n kyverno describe "deploy/${deployment}" || true
    kind_kubectl "${cluster_name}" -n kyverno get events --sort-by=.lastTimestamp | tail -40 || true
    return 1
}

wait_for_rollout kyverno-admission-controller
wait_for_rollout kyverno-background-controller

log info "Applying Kyverno policies under test"
apply_with_webhook_retry() {
    local file="${1:?policy file is required}"
    local attempts="${2:-6}"
    local delay_seconds="${3:-5}"
    local attempt=1

    while true; do
        local output
        if output="$(kind_kubectl "${cluster_name}" apply -f - <"${file}" 2>&1)"; then
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
