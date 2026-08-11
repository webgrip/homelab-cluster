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
# EXIT alone is correct and sufficient for every signal that CAN be trapped: bash runs an
# EXIT trap when the shell exits, including on SIGTERM/SIGINT/SIGHUP (verified 2026-08-04
# — adding explicit INT/TERM/HUP traps merely ran cleanup twice).
#
# The KinD leaks that starved fringe-workstation on 2026-08-04 were therefore NOT a
# missing trap. Talos's PSI OOM controller kills with SIGKILL, which cannot be trapped by
# anything, so no trap here could ever have prevented them. The backstop is the prune
# sidecar's 15-minute orphan reaper in dind-daemonset.yaml — reaping, not trapping, is the
# only mechanism that works against SIGKILL.
trap cleanup EXIT

# Any failure dumps the cluster before the EXIT trap deletes it. Without this the only evidence a
# failed run leaves behind is whatever chainsaw itself printed — which is how nightly 724/769 got
# as far as "context deadline exceeded" with no way to tell whether Kyverno was slow, evicted or
# gone. ERR runs before EXIT, so the cluster is still alive here.
dump_cluster_state() {
    local exit_code=$?
    trap - ERR

    if ! docker inspect "${cluster_name}-control-plane" >/dev/null 2>&1; then
        return "${exit_code}"
    fi

    log warn "Run failed — dumping KinD cluster state" "exit=${exit_code}"
    kind_kubectl "${cluster_name}" get pods -A -o wide || true
    kind_kubectl "${cluster_name}" -n kyverno get deploy || true
    kind_kubectl "${cluster_name}" get events -A --sort-by=.lastTimestamp 2>/dev/null | tail -50 || true
    kind_kubectl "${cluster_name}" -n kyverno logs deploy/kyverno-admission-controller --tail=60 || true
    return "${exit_code}"
}
trap dump_cluster_state ERR

# One KinD cluster at a time per docker daemon. The shared per-node dind runs every CI job on the
# node, so two chainsaw jobs stand up two KinD clusters on one disk — that overlap (runs 587/588)
# is what starved etcd, and it is what makes teardown flaky: Kyverno's validate.kyverno.svc-fail
# webhook is failurePolicy=Fail with a 10s timeout and covers DELETE on namespaces, so a
# contended admission controller turns the suites' namespace teardown into a hard error (nightly
# 724 and 769). Removing the contention beats padding timeouts around it.
#
# The lock lives in TMPDIR, which in CI is /mnt/ci-shared — the node-wide hostPath every runner
# pod on that node mounts — so this really is one lock per daemon, not per pod. FD 9 rather than
# {fd} so the script still parses under macOS's bash 3.2; flock itself is Linux-only, and a dev
# box runs one suite at a time anyway.
#
# `timeout <n> flock -x 9`, NOT `flock -w <n> 9`: busybox's flock has no -w and exits 1 on the
# unrecognized option, so the -w form silently degraded to no lock at all on any busybox-based
# runner (caught by running two suites concurrently — both announced "not acquired" instantly).
# The blocking form plus timeout is the same bounded wait on util-linux and busybox alike, and
# the lock is held by THIS shell through FD 9 for as long as the script runs.
# KIND_LOCK_FILE exists because advisory locks need a real filesystem: on a macOS bind mount
# flock returns success for every caller and serializes nothing, so a dev-box harness must point
# this at a Linux fs to exercise the lock at all. In CI the default is correct — /mnt/ci-shared is
# a tmpfs hostPath.
lock_file="${KIND_LOCK_FILE:-${TMPDIR:-/tmp}/kyverno-chainsaw.lock}"
lock_wait="${KIND_LOCK_WAIT_SECONDS:-1800}"
if command -v flock >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
    exec 9>"${lock_file}"
    log info "Waiting for the per-daemon KinD lock" "file=${lock_file}" "timeout=${lock_wait}s"
    if timeout "${lock_wait}" flock -x 9; then
        log info "Acquired the KinD lock"
    else
        # Never fail the run on the lock: a stuck holder should degrade to the old concurrent
        # behaviour, not take the gate down with it.
        log warn "KinD lock not acquired before the deadline — running concurrently" \
            "waited=${lock_wait}s"
    fi
else
    log info "flock/timeout unavailable — skipping the per-daemon KinD lock"
fi

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
    # NOT `sed -i` — GNU takes the suffix as an optional attached argument, BSD/macOS sed
    # requires it as a separate one, so `sed -i "s#...#"` there consumes the EXPRESSION as
    # the backup suffix and then reads the file as the script ("invalid command code f").
    # Substituting into a temp file and moving it back behaves identically on both.
    #
    # The same trap is documented at scripts/lib/kyverno-tests.sh:65 and was fixed there;
    # this call site was missed, which meant the whole chainsaw suite could not run on a
    # Mac at all — it died immediately after "Installing Kyverno into KinD" and the error
    # surfaced as `namespaces "kyverno" not found`, which reads like a broken install
    # rather than a portability bug two steps earlier. Found 2026-08-11 trying to run the
    # suite locally to verify a chainsaw change.
    sed "s#ghcr.io/kyverno/#${KYVERNO_IMAGE_PROXY}kyverno/#g" \
        "${workspace}/kyverno-install.yaml" >"${workspace}/kyverno-install.yaml.tmp" &&
        mv -- "${workspace}/kyverno-install.yaml.tmp" "${workspace}/kyverno-install.yaml"
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
# finite; the ERR trap dumps the cluster when it IS hit.
kind_kubectl "${cluster_name}" -n kyverno rollout status deploy/kyverno-admission-controller --timeout=420s
kind_kubectl "${cluster_name}" -n kyverno rollout status deploy/kyverno-background-controller --timeout=420s

# The reports and cleanup controllers install but no suite exercises them (grep-verified), and the
# reports controller writes a PolicyReport for every resource the suites touch — pure etcd and CPU
# load on a node that has already proven it can spare neither. Scale them away so the admission
# controller, which every teardown DELETE must round-trip through inside a 10s webhook timeout,
# gets the headroom.
kind_kubectl "${cluster_name}" -n kyverno scale --replicas=0 \
    deploy/kyverno-reports-controller deploy/kyverno-cleanup-controller

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
# Renamed 2026-08-11 with the CEL migration. This list is matched by FILENAME, so a
# policy rename breaks the KinD run at apply time rather than as a failed assertion.
apply_with_webhook_retry "${workspace}/policies/network-exposure-cel.yaml"

log info "Running Chainsaw suite" "image=${CHAINSAW_IMAGE}"
docker run --rm \
    --network host \
    -w /work/chainsaw \
    -e KUBECONFIG=/kubeconfig \
    -v "${kubeconfig}:/kubeconfig:ro" \
    -v "${workspace}:/work" \
    "${CHAINSAW_IMAGE}" \
    test . --config /work/chainsaw/chainsaw-config.yaml
