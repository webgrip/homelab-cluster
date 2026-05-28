#!/usr/bin/env bash

set -Eeuo pipefail

PULL_DIR="${1:?usage: run-flux-local-diff.sh <pull-dir> <default-dir> <output-file>}"
DEFAULT_DIR="${2:?usage: run-flux-local-diff.sh <pull-dir> <default-dir> <output-file>}"
OUTPUT_FILE="${3:?usage: run-flux-local-diff.sh <pull-dir> <default-dir> <output-file>}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/flux-local.sh"

check_cli docker mktemp rsync awk grep sort diff

workspace="$(mktemp -d)"
trap 'rm -rf "${workspace}"' EXIT

pull_workspace="${workspace}/pull"
default_workspace="${workspace}/default"
pull_list="${workspace}/pull.tsv"
default_list="${workspace}/default.tsv"
combined_list="${workspace}/combined.tsv"
stderr_file="${workspace}/flux-local.stderr"
chunk_file="${workspace}/chunk.patch"

prepare_flux_local_workspace "${PULL_DIR}" "${pull_workspace}"
prepare_flux_local_workspace "${DEFAULT_DIR}" "${default_workspace}"

list_flux_kustomizations "${pull_workspace}" "${pull_list}" "${stderr_file}"
print_relevant_flux_local_stderr "${stderr_file}"
list_flux_kustomizations "${default_workspace}" "${default_list}" "${stderr_file}"
print_relevant_flux_local_stderr "${stderr_file}"

cat "${pull_list}" "${default_list}" | sort -u > "${combined_list}"
: > "${OUTPUT_FILE}"

declare -A in_pull=()
declare -A in_default=()

while IFS=$'\t' read -r namespace name; do
    [[ -n "${namespace}" && -n "${name}" ]] || continue
    in_pull["${namespace}/${name}"]=1
done < "${pull_list}"

while IFS=$'\t' read -r namespace name; do
    [[ -n "${namespace}" && -n "${name}" ]] || continue
    in_default["${namespace}/${name}"]=1
done < "${default_list}"

log info "Generating per-kustomization flux-local diff" "output=${OUTPUT_FILE}" "kustomizations=$(wc -l < "${combined_list}")"

while IFS=$'\t' read -r namespace name; do
    [[ -n "${namespace}" && -n "${name}" ]] || continue

    key="${namespace}/${name}"
    in_pull_repo="${in_pull[${key}]:-0}"
    in_default_repo="${in_default[${key}]:-0}"

    if [[ "${in_pull_repo}" == "1" && "${in_default_repo}" == "1" ]]; then
        if ! run_flux_local_diff "${pull_workspace}" "${default_workspace}" \
            "flux-local diff ks ${name} -n ${namespace} --unified 6 --path ${FLUX_CLUSTER_PULL_PATH} --path-orig ${FLUX_CLUSTER_DEFAULT_PATH} --strip-attrs \"helm.sh/chart,checksum/config,app.kubernetes.io/version,chart\"" \
            > "${chunk_file}" 2>"${stderr_file}"; then
            cat "${stderr_file}" >&2
            exit 1
        fi

        print_relevant_flux_local_stderr "${stderr_file}"
        cat "${chunk_file}" >> "${OUTPUT_FILE}"
        continue
    fi

    old_render="${workspace}/old.yaml"
    new_render="${workspace}/new.yaml"
    : > "${old_render}"
    : > "${new_render}"

    if [[ "${in_default_repo}" == "1" ]]; then
        if ! run_flux_local "${default_workspace}" \
            "flux-local build ks ${name} -n ${namespace} --path ${FLUX_CLUSTER_PATH}" \
            > "${old_render}" 2>"${stderr_file}"; then
            cat "${stderr_file}" >&2
            exit 1
        fi

        print_relevant_flux_local_stderr "${stderr_file}"
    fi

    if [[ "${in_pull_repo}" == "1" ]]; then
        if ! run_flux_local "${pull_workspace}" \
            "flux-local build ks ${name} -n ${namespace} --path ${FLUX_CLUSTER_PATH}" \
            > "${new_render}" 2>"${stderr_file}"; then
            cat "${stderr_file}" >&2
            exit 1
        fi

        print_relevant_flux_local_stderr "${stderr_file}"
    fi

    if ! diff -u \
        --label "default/${key}" \
        --label "pull/${key}" \
        "${old_render}" \
        "${new_render}" \
        >> "${OUTPUT_FILE}"; then
        status=$?
        if [[ "${status}" -ne 1 ]]; then
            exit "${status}"
        fi
    fi
done < "${combined_list}"
