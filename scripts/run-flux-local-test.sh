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

# The retry wrapper fans a fresh disposable workspace copy out of repo_workspace per
# attempt: the listing mutates the tree it walks (and a timeout aborts it mid-mutation),
# so neither repo_workspace — which run_flux_local_batch later fans its workers out from —
# nor a previous attempt's tree may ever be reused. Full rationale, including why one
# attempt can time out at all, lives on list_flux_kustomizations_with_retry.
if ! list_flux_kustomizations_with_retry "${repo_workspace}" "${workspace}" "${ks_list}" "${stderr_file}"; then
    log error "Kustomization listing failed after all attempts" "attempts=${FLUX_LOCAL_LIST_ATTEMPTS:-3}"
fi
print_relevant_flux_local_stderr "${stderr_file}"

total="$(wc -l < "${ks_list}")"

# Change-detection scope. FLUX_LOCAL_BASE_REF (a git ref, e.g. the push's `before` SHA or a
# PR's merge base) narrows the render to the kustomizations the diff can actually affect --
# see select_affected_kustomizations for the blast-radius rules. Unset => render everything,
# which is what a local run and the nightly full-validation workflow both want.
#
# This exists because the full render is ~20min and cannot be parallelised (the builds are
# disk-iowait-bound, see run_flux_local_batch), so validating all ~90 kustomizations on a
# one-file push was the dominant cost of the CI gate.
BASE_REF="${FLUX_LOCAL_BASE_REF:-}"
if [[ -n "${BASE_REF}" ]]; then
    changed_files="${workspace}/changed.txt"
    if git -C "${ROOT_DIR}" diff --name-only "${BASE_REF}" -- >"${changed_files}" 2>/dev/null; then
        scoped_list="${workspace}/kustomizations.scoped.tsv"
        if select_affected_kustomizations "${ks_list}" "${changed_files}" "${scoped_list}"; then
            ks_list="${scoped_list}"
            scoped_total="$(wc -l < "${ks_list}")"
            log info "Scoped to changed paths" \
                "base=${BASE_REF}" "changed_files=$(wc -l < "${changed_files}")" \
                "kustomizations=${scoped_total}/${total}"
            total="${scoped_total}"
            if (( total == 0 )); then
                log info "No kustomization is affected by this change set -- nothing to render"
                exit 0
            fi
        else
            log info "Change set has cluster-wide blast radius -- rendering everything" "base=${BASE_REF}"
        fi
    else
        # A shallow clone or an unknown base ref must never silently downgrade the gate.
        log warn "Cannot diff against base ref -- rendering everything" "base=${BASE_REF}"
    fi
fi

# Render all kustomizations serially in ONE container (see run_flux_local_batch).
#
# PARALLELISM defaults to 1 on purpose. flux-local builds are NOT CPU-bound on the CI
# runner — they're disk-iowait-bound: each `flux-local build` renames every
# kustomization.yaml in its tree to .original and back (metadata-heavy, ~zero bytes). On
# the shared worker node's disk this is the bottleneck. Fanning out to N workers on N
# isolated tree copies just multiplies concurrent IOPS on the ONE disk -> seek-thrash. A
# P=4 run measured 27min (node disk 57-91% busy the whole time, pod CPU <0.36 cores);
# serial removes the thrash. Raise FLUX_LOCAL_PARALLELISM only on a runner with fast,
# uncontended storage (e.g. a tmpfs workspace) where builds become CPU-bound.
PARALLELISM="${FLUX_LOCAL_PARALLELISM:-1}"
stderr_dir="${workspace}/worker-stderr"
mkdir -p "${stderr_dir}"

log info "Running flux-local builds (sharded)" "workspace=${repo_workspace}" "kustomizations=${total}" "parallelism=${PARALLELISM}"

if ! run_flux_local_batch "${repo_workspace}" "${PARALLELISM}" "${ks_list}" "${stderr_dir}"; then
    exit 1
fi

log info "Flux-local validation completed" "kustomizations=${total}"
