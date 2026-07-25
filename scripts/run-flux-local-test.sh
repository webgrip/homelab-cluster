#!/usr/bin/env bash

set -Eeuo pipefail

# `--full` anywhere in the args forces a full render (same as FLUX_LOCAL_FULL=1); everything
# else stays positional so `run-flux-local-test.sh <root>` keeps working. The `+`-guard on the
# array expansion is the bash 3.2 idiom for "empty array under set -u" (macOS ships 3.2).
args=()
for a in "$@"; do
    case "${a}" in
        --full) FLUX_LOCAL_FULL=1 ;;
        *) args+=("${a}") ;;
    esac
done
set -- ${args[@]+"${args[@]}"}

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

# Change-detection scope. Precedence:
#   FLUX_LOCAL_FULL=1          -> render EVERYTHING (the nightly full-validation workflow, and
#                                `--full` / `task flux-local-full`). Use after touching the flux
#                                root, or for a belt-and-suspenders pass.
#   FLUX_LOCAL_BASE_REF=<ref>  -> scope to the diff against <ref> (CI e2e passes the push's
#                                `before` SHA / a PR merge base -- see .forgejo/workflows/e2e.yml).
#   neither (a bare local run) -> auto-scope to what you're about to push: HEAD's merge-base with
#                                the upstream branch, plus uncommitted and untracked files. This
#                                is the DEFAULT a human hits by just running the script -- it turns
#                                the ~20min all-90-kustomization render into rendering only the few
#                                your working changes can actually affect.
#
# The full render is ~20min and cannot be parallelised (builds are disk-iowait-bound, see
# run_flux_local_batch), so scoping is the single biggest lever on wall-clock. Blast-radius rules
# (edits to kubernetes/flux/**, components/**, or the validator itself still force FULL) live in
# select_affected_kustomizations.
if [[ "${FLUX_LOCAL_FULL:-0}" == 1 ]]; then
    log info "FLUX_LOCAL_FULL set -- rendering every kustomization"
    BASE_REF=""
elif [[ -z "${FLUX_LOCAL_BASE_REF+set}" ]]; then
    # UNSET (not merely empty) => a bare local run. Auto-scope to what you're about to push.
    # CI always SETS the var (to a ref, or to "" as its own explicit full-render signal), so this
    # branch never fires there -- it must not silently narrow CI's deliberate full-render fallback.
    BASE_REF="$(resolve_local_base_ref "${ROOT_DIR}")"
    if [[ -n "${BASE_REF}" ]]; then
        log info "Auto-scoping to local changes (FLUX_LOCAL_FULL=1 or --full forces a full render)" "base=${BASE_REF}"
    else
        log warn "No upstream to diff against -- rendering everything"
    fi
else
    # Explicitly set (CI). A real ref scopes; an empty value means "render everything" -- see
    # the "Determine diff base" step in .forgejo/workflows/e2e.yml.
    BASE_REF="${FLUX_LOCAL_BASE_REF}"
fi
if [[ -n "${BASE_REF}" ]]; then
    changed_files="${workspace}/changed.txt"
    if collect_changed_files "${ROOT_DIR}" "${BASE_REF}" "${changed_files}"; then
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
