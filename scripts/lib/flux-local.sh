#!/usr/bin/env bash

set -Eeuo pipefail

FLUX_LOCAL_IMAGE="${FLUX_LOCAL_IMAGE:-ghcr.io/allenporter/flux-local:v8.2.0@sha256:9c77739d8d7c71b808311693ea52d603d1ddb5190d3d4f23e47f6f33d5254602}"
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
