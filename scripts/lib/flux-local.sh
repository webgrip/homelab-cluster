#!/usr/bin/env bash

set -Eeuo pipefail

# Pulled through the in-cluster Harbor pull-through proxy (harbor.webgrip.dev/ghcr → ghcr.io,
# ADR-0025), NOT ghcr.io directly. The CI runner's DinD daemon uses an emptyDir image store
# (scaledjob.yaml), so every pull is cold on every run — routing through Harbor makes it a
# LAN-speed, rate-limit-free pull that stays warm in Harbor's cache across runs. Same manifest,
# so the digest pin is identical to the upstream ghcr.io/allenporter/flux-local:v8.2.0.
FLUX_LOCAL_IMAGE="${FLUX_LOCAL_IMAGE:-harbor.webgrip.dev/ghcr/allenporter/flux-local:v8.2.0@sha256:9c77739d8d7c71b808311693ea52d603d1ddb5190d3d4f23e47f6f33d5254602}"
FLUX_CLUSTER_PATH="${FLUX_CLUSTER_PATH:-/github/workspace/kubernetes/flux/cluster}"
FLUX_CLUSTER_PULL_PATH="${FLUX_CLUSTER_PULL_PATH:-/github/workspace/pull/kubernetes/flux/cluster}"
FLUX_CLUSTER_DEFAULT_PATH="${FLUX_CLUSTER_DEFAULT_PATH:-/github/workspace/default/kubernetes/flux/cluster}"

function prepare_flux_local_workspace() {
    local source_dir="$1"
    local dest_dir="$2"

    mkdir -p "${dest_dir}"
    rsync -a --exclude '.git/' "${source_dir}/" "${dest_dir}/"
    if [[ -d "${source_dir}/.git" ]]; then
        cp -a "${source_dir}/.git" "${dest_dir}/.git"
    fi
    # a+rwX, not u+rwX: the flux-local container runs as a non-host UID and
    # must write *.original files into the mounted workspace.
    chmod -R a+rwX "${dest_dir}"
}

function run_flux_local() {
    local workspace="$1"
    shift

    docker run --rm \
        -e HOME=/tmp \
        -v "${workspace}:/github/workspace" \
        --entrypoint sh \
        "${FLUX_LOCAL_IMAGE}" \
        -lc "git config --global --add safe.directory /github/workspace >/dev/null && $*"
}

# Build EVERY kustomization across P parallel workers, instead of one serial
# `docker run` per kustomization (97 container starts, fully serial — the dominant cost
# of the e2e gate).
#
# `flux-local build` MUTATES its workspace in place (it renames kustomization.yaml ->
# .original and back), so parallel builds against ONE shared tree race and corrupt each
# other. We therefore give each worker its OWN copy of the workspace and shard the
# kustomization list across them round-robin. Within a worker the builds stay serial
# (the proven-safe original behaviour); parallelism is across the isolated trees. The
# repo is tiny (~16 MiB incl. .git), so N copies are cheap next to 97 serial renders.
#
# Args: BASE_WORKSPACE PARALLELISM KS_LIST STDERR_DIR
function run_flux_local_batch() {
    local base_workspace="$1"
    local parallelism="${2:-4}"
    local ks_list="$3"
    local stderr_dir="$4"

    local total actual_p
    total="$(grep -c . "${ks_list}" || true)"
    actual_p="${parallelism}"
    (( actual_p > total )) && actual_p="${total}"
    (( actual_p < 1 )) && actual_p=1

    local codes_dir="${stderr_dir}/codes"
    mkdir -p "${codes_dir}"

    local pids=()
    local i
    for (( i = 0; i < actual_p; i++ )); do
        local wdir="${base_workspace}-w${i}"
        rsync -a "${base_workspace}/" "${wdir}/"
        # Round-robin shard: worker i takes lines i, i+P, i+2P, ...
        awk -v P="${actual_p}" -v I="${i}" '(NR - 1) % P == I' "${ks_list}" > "${wdir}/.flux-ks.tsv"
        # Fixed worker script (path interpolated now; container has no host env). Serial loop
        # over this worker's shard; a build failure exits 255 and fails the worker.
        cat > "${wdir}/.build-chunk.sh" <<EOF
#!/bin/sh
set -u
while IFS='	' read -r ns name; do
    [ -n "\$ns" ] && [ -n "\$name" ] || continue
    flux-local build ks "\$name" -n "\$ns" --path ${FLUX_CLUSTER_PATH} >/dev/null \\
        || { echo "FAILED to build ks \$ns/\$name" >&2; exit 255; }
done < /github/workspace/.flux-ks.tsv
EOF
        (
            if run_flux_local "${wdir}" "sh /github/workspace/.build-chunk.sh" \
                2>"${stderr_dir}/w${i}.stderr"; then
                echo 0 > "${codes_dir}/w${i}"
            else
                echo 1 > "${codes_dir}/w${i}"
            fi
        ) &
        pids+=("$!")
    done

    wait "${pids[@]}" 2>/dev/null || true

    local rc=0
    for (( i = 0; i < actual_p; i++ )); do
        [[ -f "${stderr_dir}/w${i}.stderr" ]] && print_relevant_flux_local_stderr "${stderr_dir}/w${i}.stderr"
        [[ "$(cat "${codes_dir}/w${i}" 2>/dev/null || echo 1)" == "0" ]] || rc=1
    done
    return "${rc}"
}

function run_flux_local_diff() {
    local pull_workspace="$1"
    local default_workspace="$2"
    shift 2

    docker run --rm \
        -e HOME=/tmp \
        -v "${pull_workspace}:/github/workspace/pull" \
        -v "${default_workspace}:/github/workspace/default" \
        --entrypoint sh \
        "${FLUX_LOCAL_IMAGE}" \
        -lc "git config --global --add safe.directory /github/workspace/pull >/dev/null && git config --global --add safe.directory /github/workspace/default >/dev/null && $*"
}

function print_relevant_flux_local_stderr() {
    local stderr_file="$1"

    [[ -s "${stderr_file}" ]] || return 0

    if ! grep -Ev '^(Unable to find Secret .+ referenced|Kustomization .+ has dependsOn with invalid names: .+)$' "${stderr_file}" >&2; then
        return 0
    fi
}

function list_flux_kustomizations() {
    local workspace="$1"
    local output_file="$2"
    local stderr_file="$3"
    local raw_output

    raw_output="$(mktemp)"

    if ! run_flux_local "${workspace}" \
        "flux-local get ks --all-namespaces --path ${FLUX_CLUSTER_PATH} -o wide" \
        >"${raw_output}" 2>"${stderr_file}"; then
        # set -e would otherwise abort with the error trapped in stderr_file,
        # making the script fail with no output at all.
        cat "${stderr_file}" >&2
        return 1
    fi

    awk 'NR > 1 && NF >= 2 { print $1 "\t" $2 }' "${raw_output}" | sort -u >"${output_file}"
    rm -f "${raw_output}"
}
