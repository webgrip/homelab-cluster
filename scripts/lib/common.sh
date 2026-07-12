#!/usr/bin/env bash
set -Eeuo pipefail

# Map a log level to its priority. Case statements instead of associative
# arrays: macOS ships bash 3.2, where `local -A` is a runtime error — these
# libs must run on stock mac AND Linux CI (2026-07-12).
function log_priority() {
    case "$1" in
        (debug) echo 1 ;;
        (warn) echo 3 ;;
        (error) echo 4 ;;
        (*) echo 2 ;; # info + unknown levels
    esac
}

# Log messages with different levels
function log() {
    local level="${1:-info}"
    shift

    # Get the current log level's priority
    local current_priority
    current_priority="$(log_priority "${level}")"

    # Get the configured log level from the environment, default to "info"
    local configured_priority
    configured_priority="$(log_priority "${LOG_LEVEL:-info}")"

    # Skip log messages below the configured log level
    if ((current_priority < configured_priority)); then
        return
    fi

    # Pick the log color, falling back to "info" cyan for unknown levels
    local color
    case "${level}" in
        (debug) color="\033[1m\033[38;5;63m" ;;  # Blue
        (warn) color="\033[1m\033[38;5;192m" ;;  # Yellow
        (error) color="\033[1m\033[38;5;198m" ;; # Red
        (*) color="\033[1m\033[38;5;87m" ;;      # Cyan (info)
    esac
    local msg="$1"
    shift

    # Prepare additional data
    local data=
    if [[ $# -gt 0 ]]; then
        for item in "$@"; do
            if [[ "${item}" == *=* ]]; then
                data+="\033[1m\033[38;5;236m${item%%=*}=\033[0m\"${item#*=}\" "
            else
                data+="${item} "
            fi
        done
    fi

    # Determine output stream based on log level
    local output_stream="/dev/stdout"
    if [[ "$level" == "error" ]]; then
        output_stream="/dev/stderr"
    fi

    # Print the log message (tr, not ${level^^} — that's bash 4+)
    local level_upper
    level_upper="$(printf '%s' "${level}" | tr '[:lower:]' '[:upper:]')"
    printf "%s %b%s%b %s %b\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        "${color}" "${level_upper}" "\033[0m" "${msg}" "${data}" >"${output_stream}"

    # Exit if the log level is error
    if [[ "$level" == "error" ]]; then
        exit 1
    fi
}

# Check if required environment variables are set
function check_env() {
    local envs=("${@}")
    local missing=()
    local values=()

    for env in "${envs[@]}"; do
        if [[ -z "${!env-}" ]]; then
            missing+=("${env}")
        else
            values+=("${env}=${!env}")
        fi
    done

    if [ ${#missing[@]} -ne 0 ]; then
        log error "Missing required env variables" "envs=${missing[*]}"
    fi

    log debug "Env variables are set" "envs=${values[*]}"
}

# Check if required CLI tools are installed
function check_cli() {
    local deps=("${@}")
    local missing=()

    for dep in "${deps[@]}"; do
        if ! command -v "${dep}" &>/dev/null; then
            missing+=("${dep}")
        fi
    done

    if [ ${#missing[@]} -ne 0 ]; then
        log error "Missing required deps" "deps=${missing[*]}"
    fi

    log debug "Deps are installed" "deps=${deps[*]}"
}
