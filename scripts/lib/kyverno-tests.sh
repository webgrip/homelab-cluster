#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# Tool images pulled through the in-cluster Harbor pull-through proxy
# (harbor.webgrip.dev/ghcr -> ghcr.io, ADR-0025), NOT ghcr.io directly: the CI runner's DinD
# uses an emptyDir image store so every pull is cold — Harbor makes it a LAN-speed, rate-limit-
# free pull that stays warm across runs. Same manifests, so the digest pins are unchanged.
KYVERNO_CLI_IMAGE="${KYVERNO_CLI_IMAGE:-harbor.webgrip.dev/ghcr/kyverno/kyverno-cli:v1.18.1@sha256:b7e272572d244ddec0b83469f7200ba883555bf69de4b294cee52a197c8c6590}"
CHAINSAW_IMAGE="${CHAINSAW_IMAGE:-harbor.webgrip.dev/ghcr/kyverno/chainsaw:v0.2.15@sha256:527f3be2b9ec0580cb0bc84540a0fee99406b011c24ae3a30953e525af60809d}"
KYVERNO_INSTALL_URL="${KYVERNO_INSTALL_URL:-https://github.com/kyverno/kyverno/releases/download/v1.18.1/install.yaml}"
# Prefix for the ghcr.io/kyverno/* images referenced INSIDE install.yaml + the KinD node image,
# so the KinD node pulls them through Harbor too (same emptyDir cold-pull problem). Set empty to
# pull direct from upstream.
KYVERNO_IMAGE_PROXY="${KYVERNO_IMAGE_PROXY:-harbor.webgrip.dev/ghcr/}"
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-harbor.webgrip.dev/dockerhub/kindest/node:v1.32.2@sha256:f226345927d7e348497136874b6d207e0b32cc52154ad8323129352923a3142f}"
KYVERNO_TEST_SECRET_DOMAIN="${KYVERNO_TEST_SECRET_DOMAIN:-example.com}"

prepare_kyverno_test_workspace() {
    local root_dir="${1:?root dir is required}"
    local workspace="${2:?workspace dir is required}"
    # BOTH dirs. PolicyExceptions moved to their own Flux Kustomization on
    # 2026-08-02 (see kubernetes/apps/kyverno/exceptions/ks.yaml) — scanning only
    # policies/app would silently drop every exception from the test workspace,
    # so tests would report violations the cluster actually excepts. That is the
    # same silent-omission hole the kind-based discovery below was written to close.
    local policy_dirs=(
        "${root_dir}/kubernetes/apps/kyverno/policies/app"
        "${root_dir}/kubernetes/apps/kyverno/exceptions/app"
    )
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
    # disk. See ADR-0032 + scripts/check-kyverno-test-coverage.sh.
    local policy
    while IFS= read -r -d '' policy; do
        sed "s|\${SECRET_DOMAIN}|${KYVERNO_TEST_SECRET_DOMAIN}|g; s|__SECRET_DOMAIN__|${KYVERNO_TEST_SECRET_DOMAIN}|g" \
            "${policy}" >"${workspace}/policies/$(basename "${policy}")"
    done < <(grep -rlZ -E '^kind: (ClusterPolicy|Policy|PolicyException|ClusterCleanupPolicy)$' \
        "${policy_dirs[0]}"/*.yaml "${policy_dirs[1]}"/*.yaml)

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

# Talk to a KinD cluster from INSIDE its own control-plane container, never through the
# kubeconfig KinD writes on the client.
#
# KinD publishes the API server on 127.0.0.1:<random> in the DOCKER DAEMON's network namespace.
# That kubeconfig is only usable by a client that shares that namespace. On the CI runner it no
# longer does: DOCKER_HOST points at the shared per-node dind DaemonSet (forgejo-runner/app/
# dind-daemonset.yaml), a separate pod, so the runner's own 127.0.0.1 has nothing on that port
# — every client-side kubectl died with "dial tcp 127.0.0.1:<port>: connect: connection refused"
# (bit CI run 584, 2026-07-29). KinD's own `--wait` never notices: it polls readiness with
# `docker exec` on the node, not through the kubeconfig, so cluster creation reports healthy.
# `docker exec` runs on the daemon, so this works identically for a local docker and a remote
# one. Containerized steps (chainsaw) keep using the kubeconfig with `--network host`, which
# puts them in the daemon's namespace where 127.0.0.1 IS the API server.
#
# Pass manifests on stdin (`-f -`); the client's filesystem is not the node's.
kind_kubectl() {
    local cluster="${1:?cluster name is required}"
    shift
    docker exec -i "${cluster}-control-plane" \
        kubectl --kubeconfig /etc/kubernetes/admin.conf "$@"
}
