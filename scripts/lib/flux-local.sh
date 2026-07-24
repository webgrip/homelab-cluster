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

# Registry blips (e.g. Harbor mid-rollback, 2026-07-24 run 434) must not fail
# validation: pre-pull with retries instead of letting `docker run` fail on
# its single implicit pull attempt.
function ensure_flux_local_image() {
    if docker image inspect "${FLUX_LOCAL_IMAGE}" >/dev/null 2>&1; then
        return 0
    fi
    local attempt
    for attempt in 1 2 3; do
        if docker pull "${FLUX_LOCAL_IMAGE}"; then
            return 0
        fi
        echo "flux-local image pull failed (attempt ${attempt}/3), retrying in $((attempt * 15))s..." >&2
        sleep $((attempt * 15))
    done
    docker pull "${FLUX_LOCAL_IMAGE}"
}

function run_flux_local() {
    local workspace="$1"
    shift

    ensure_flux_local_image
    docker run --rm \
        -e HOME=/tmp \
        -v "${workspace}:/github/workspace" \
        --entrypoint sh \
        "${FLUX_LOCAL_IMAGE}" \
        -lc "git config --global --add safe.directory /github/workspace >/dev/null && $*"
}

# Build EVERY kustomization across P workers, instead of one `docker run` per
# kustomization (the original spun up 97 containers, one per ks).
#
# `flux-local build` MUTATES its workspace in place (it renames kustomization.yaml ->
# .original and back), so parallel builds against ONE shared tree race and corrupt each
# other. Each worker therefore gets its OWN copy of the workspace and the ks list is
# sharded round-robin; within a worker the builds stay serial.
#
# IMPORTANT: parallelism (P>1) is a PESSIMISATION on the shared CI runner — these builds
# are disk-iowait-bound (rename churn), not CPU-bound, so N parallel workers just thrash
# the one node disk (measured: P=4 -> 27min, disk 57-91% busy, CPU <0.36 cores). The
# caller defaults P=1 for that reason; only raise it on fast/uncontended storage. See
# scripts/run-flux-local-test.sh.
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
while IFS='	' read -r ns name kspath; do
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

    ensure_flux_local_image
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

    # Column 3 of `-o wide` is the kustomization's PATH (e.g. kubernetes/apps/ai/litellm/app).
    # It is carried through so select_affected_kustomizations can map changed files back to the
    # kustomizations that actually read them; run_flux_local_batch ignores it.
    awk 'NR > 1 && NF >= 3 { print $1 "\t" $2 "\t" $3 }' "${raw_output}" | sort -u >"${output_file}"
    rm -f "${raw_output}"
}

# Retry wrapper around list_flux_kustomizations.
#
# WHY RETRY: flux-local's per-command timeout is hardcoded upstream at 60s
# (flux_local/command.py::_TIMEOUT — still hardcoded as of 8.4.0, no flag/env override),
# and the listing walks + kustomize-builds the WHOLE tree on every run, before any change
# scoping. On a disk-saturated runner one slow kustomize build aborts the entire listing
# with a TimeoutError (2026-07-24, run 458 + PR #436: fringe-workstation disk >90% busy
# for an hour under 7 concurrent runner pods + a Renovate wave — both runs died here).
# Those contention bursts drain in minutes, so a spaced retry turns them from a hard gate
# failure into latency.
#
# WHY A FRESH COPY PER ATTEMPT: the underlying `flux build` MUTATES the tree it walks —
# it renames every kustomization.yaml it resolves to .original and restores it owned by
# the flux-local container's UID with mode 644, not the a+rwX the workspace was prepared
# with. rsync (run as the host user, unprivileged) can't preserve that foreign UID on
# copy, so any tree the listing touched poisons every later worker fan-out copied from it
# ("open .../kustomization.yaml: permission denied" on the first build). Worse, a
# timed-out attempt aborts MID-mutation with .original files never restored — retrying in
# the same tree would fail on missing kustomization.yamls. So each attempt fans its own
# disposable copy out of SOURCE_WORKSPACE, which itself is never touched and stays safe
# for run_flux_local_batch to fan out from.
#
# Args: SOURCE_WORKSPACE SCRATCH_DIR OUTPUT_FILE STDERR_FILE
# Env: FLUX_LOCAL_LIST_ATTEMPTS (default 3), FLUX_LOCAL_LIST_BACKOFF seconds (default 75).
function list_flux_kustomizations_with_retry() {
    local source_workspace="$1"
    local scratch_dir="$2"
    local output_file="$3"
    local stderr_file="$4"

    local attempts="${FLUX_LOCAL_LIST_ATTEMPTS:-3}"
    local backoff="${FLUX_LOCAL_LIST_BACKOFF:-75}"

    local attempt list_workspace rc=1
    for (( attempt = 1; attempt <= attempts; attempt++ )); do
        list_workspace="${scratch_dir}/list-attempt-${attempt}"
        rsync -a "${source_workspace}/" "${list_workspace}/"
        rc=0
        list_flux_kustomizations "${list_workspace}" "${output_file}" "${stderr_file}" || rc=$?
        rm -rf "${list_workspace}"
        if (( rc == 0 )); then
            return 0
        fi
        if (( attempt < attempts )); then
            log warn "Kustomization listing failed -- retrying" \
                "attempt=${attempt}/${attempts}" "backoff=${backoff}s"
            sleep "${backoff}"
        fi
    done
    return "${rc}"
}

# Narrow a ks list down to the kustomizations a change set can actually affect.
#
# WHY: rendering all ~90 kustomizations takes ~20min on the shared runner (the builds are
# disk-iowait-bound -- see run_flux_local_batch -- so it cannot be parallelised away). A
# one-file change to a single app cannot alter any other app's render, so rendering all of
# them is pure wall-clock waste on every push.
#
# Blast-radius rules, deliberately conservative (when in doubt, render MORE):
#   kubernetes/flux/**, kubernetes/components/**  -> FULL render. The flux root wires every
#       Kustomization and components/ are mixed into many of them, so a single edit there can
#       change any render in the tree.
#   scripts/lib/flux-local.sh, scripts/run-flux-local-test.sh -> FULL render. Never let a
#       change to the validator itself be validated by only a slice of the tree.
#   kubernetes/apps/<ns>/<app>/**  -> select every ks whose PATH is under that app dir. Also
#       matches the sibling wiring file (ks.yaml lives at <app>/ks.yaml, one level ABOVE the
#       ks PATH <app>/app), which is why the prefix is the app dir and not the ks PATH.
#   kubernetes/apps/<ns>/<file>    -> namespace-level resource (namespace.yaml,
#       networkpolicy.yaml): select every ks in that namespace.
#   anything else (docs/, talos/, .forgejo/, other scripts/) -> selects NOTHING. These have no
#       Flux render surface; an empty selection means the render step is skipped entirely.
#
# Args: KS_LIST_FILE CHANGED_FILES_FILE OUTPUT_FILE
# Returns: 0 with OUTPUT_FILE written (possibly empty), or 1 meaning "full render required".
function select_affected_kustomizations() {
    local ks_list="$1"
    local changed_files="$2"
    local output_file="$3"

    local prefixes
    prefixes="$(mktemp)"

    local path
    while IFS= read -r path; do
        [[ -n "${path}" ]] || continue
        case "${path}" in
            kubernetes/flux/* | kubernetes/components/*)
                rm -f "${prefixes}"
                return 1
                ;;
            scripts/lib/flux-local.sh | scripts/run-flux-local-test.sh)
                rm -f "${prefixes}"
                return 1
                ;;
            kubernetes/apps/*)
                # kubernetes/apps/<ns>/<app>/... -> 4 segments; kubernetes/apps/<ns>/<file> -> 3.
                awk -F/ 'NF >= 5 { print $1"/"$2"/"$3"/"$4"/"; next }
                         NF == 4 { print $1"/"$2"/"$3"/" }' <<<"${path}" >>"${prefixes}"
                ;;
        esac
    done <"${changed_files}"

    sort -u -o "${prefixes}" "${prefixes}"

    # A ks is affected when its PATH (field 3) starts with one of the changed prefixes.
    awk -F'\t' 'NR == FNR { pfx[FNR] = $0; n = FNR; next }
                { for (i = 1; i <= n; i++) if (index($3 "/", pfx[i]) == 1) { print; break } }' \
        "${prefixes}" "${ks_list}" >"${output_file}"

    rm -f "${prefixes}"
}
