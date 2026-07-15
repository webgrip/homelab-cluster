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
# and ADR-0035.
log info "Validating Grafana alert-rule expressions"
python3 "${SCRIPT_DIR}/validate_grafana_alert_expr.py" "${ROOT_DIR}"

workspace="$(mktemp -d)"
trap 'rm -rf "${workspace}"' EXIT

repo_workspace="${workspace}/repo"
ks_list="${workspace}/kustomizations.tsv"
stderr_file="${workspace}/flux-local.stderr"

prepare_flux_local_workspace "${ROOT_DIR}" "${repo_workspace}"

# list_flux_kustomizations's underlying `flux build` mutates (renames-to-.original then
# restores) every kustomization.yaml it resolves while walking the tree, and restores them
# owned by the flux-local container's UID with mode 644 -- not the a+rwX prepare_flux_local_workspace
# set. rsync (run as the host user, unprivileged) can't preserve that foreign UID on copy, so
# any later worker fan-out copied FROM a workspace list_flux_kustomizations touched inherits
# 644-owned-by-host-user files that the (different-UID) build containers can no longer write to
# -- "open .../kustomization.yaml: permission denied" on the very first build. Give this step
# its own disposable copy so its mutation never reaches repo_workspace, which run_flux_local_batch
# fans out from for every parallel worker.
list_workspace="${workspace}/list"
rsync -a "${repo_workspace}/" "${list_workspace}/"
list_flux_kustomizations "${list_workspace}" "${ks_list}" "${stderr_file}"
rm -rf "${list_workspace}"
print_relevant_flux_local_stderr "${stderr_file}"

total="$(wc -l < "${ks_list}")"

# Render all kustomizations across PARALLELISM isolated workspace copies (see
# run_flux_local_batch — flux-local mutates its tree, so workers can't share one). Tune
# down if the DinD sidecar's memory ceiling (scaledjob.yaml) is hit; each concurrent
# `flux-local build` runs an in-process helm template (~a few hundred MiB).
PARALLELISM="${FLUX_LOCAL_PARALLELISM:-4}"
stderr_dir="${workspace}/worker-stderr"
mkdir -p "${stderr_dir}"

log info "Running flux-local builds (sharded)" "workspace=${repo_workspace}" "kustomizations=${total}" "parallelism=${PARALLELISM}"

if ! run_flux_local_batch "${repo_workspace}" "${PARALLELISM}" "${ks_list}" "${stderr_dir}"; then
    exit 1
fi

log info "Flux-local validation completed" "kustomizations=${total}"
