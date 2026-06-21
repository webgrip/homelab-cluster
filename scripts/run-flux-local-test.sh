#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/flux-local.sh"

check_cli docker mktemp rsync awk grep sort wc python3

# Shift-left guard: every Grafana alert-rule SSE node must carry an `expression:`
# pointer. Missing it silently broke all 16 SLO rules for ~3 weeks (kubeconform and
# the operator CRD can't see model internals). See scripts/validate_grafana_alert_expr.py
# and ADR-0030.
log info "Validating Grafana alert-rule expressions"
python3 "${SCRIPT_DIR}/validate_grafana_alert_expr.py" "${ROOT_DIR}"

workspace="$(mktemp -d)"
trap 'rm -rf "${workspace}"' EXIT

repo_workspace="${workspace}/repo"
ks_list="${workspace}/kustomizations.tsv"
stderr_file="${workspace}/flux-local.stderr"

prepare_flux_local_workspace "${ROOT_DIR}" "${repo_workspace}"
list_flux_kustomizations "${repo_workspace}" "${ks_list}" "${stderr_file}"
print_relevant_flux_local_stderr "${stderr_file}"

total="$(wc -l < "${ks_list}")"
count=0

log info "Running per-kustomization flux-local builds" "workspace=${repo_workspace}" "kustomizations=${total}"

while IFS=$'\t' read -r namespace name; do
    [[ -n "${namespace}" && -n "${name}" ]] || continue

    count=$((count + 1))
    log info "Building kustomization" "index=${count}/${total}" "namespace=${namespace}" "name=${name}"

    if ! run_flux_local "${repo_workspace}" \
        "flux-local build ks ${name} -n ${namespace} --path ${FLUX_CLUSTER_PATH} >/dev/null" \
        2>"${stderr_file}"; then
        cat "${stderr_file}" >&2
        exit 1
    fi

    print_relevant_flux_local_stderr "${stderr_file}"
done < "${ks_list}"

log info "Flux-local validation completed" "kustomizations=${total}"
