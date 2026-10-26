#!/usr/bin/env bash
set -euo pipefail
shopt -s inherit_errexit

readonly usage="usage: test-audit-reader.sh [--mutation-test] [repo-root]

Proves that Grafana's VictoriaLogs Audit datasource reads only the homelab's
own Kubernetes audit trail. It starts a throwaway VictoriaLogs and the
victorialogs-audit-reader vmauth with its committed config, ingests one
homelab and one Unfold audit record, and queries through the reader the ways
the Grafana plugin and a hand-written request can: a plain query, a stream
filter naming the Unfold cluster, a client-supplied extra_stream_filters,
the field and stream value endpoints, and the insert and delete paths.

  --mutation-test  also strip the reader's extra_stream_filters and require
                   the Unfold record to become visible, so a reader that
                   lets everything through cannot pass.

Needs curl, jq, sha256sum and tar."

mutation_test=false
ROOT_DIR=""
for argument in "$@"; do
  case "${argument}" in
    --mutation-test) mutation_test=true ;;
    -h | --help) echo "${usage}"; exit 0 ;;
    *) ROOT_DIR="${argument}" ;;
  esac
done
ROOT_DIR="${ROOT_DIR:-$(git rev-parse --show-toplevel)}"
readonly ROOT_DIR
readonly READER_CONFIG="${ROOT_DIR}/kubernetes/apps/observability/grafana/app/audit-reader/vmauth.yaml"

readonly VICTORIALOGS_VERSION="v1.51.0"
readonly VICTORIALOGS_TARBALL="victoria-logs-linux-amd64-${VICTORIALOGS_VERSION}.tar.gz"
readonly VICTORIALOGS_TARBALL_SHA256="4c501ea21663d7d934f8d0e026cef751bb0907bf794c7e716cb21252bdea1fac"
readonly VMUTILS_VERSION="v1.147.0"
readonly VMUTILS_TARBALL="vmutils-linux-amd64-${VMUTILS_VERSION}.tar.gz"
readonly VMUTILS_TARBALL_SHA256="1e5da38c3d8d7af9c4fc0daa8a2103f2578c40ed81752d21f20a3bd6d0506b3f"
readonly CACHE_DIR="${VLOGS_RULE_TEST_CACHE:-${XDG_CACHE_HOME:-${HOME}/.cache}/vlogs-rule-tests}"
readonly VICTORIALOGS_PORT="${AUDIT_READER_TEST_VL_PORT:-19438}"
readonly READER_PORT="${AUDIT_READER_TEST_PORT:-18437}"
readonly UPSTREAM="http://vlsingle-victorialogs-audit.observability.svc.cluster.local:9428"

fetch_binary() {
  local url="$1" tarball="$2" sha256="$3" member="$4" target="$5"
  [[ -x "$target" ]] && return
  local download
  download="$(mktemp -d)"
  curl -fsSL --retry 3 -o "${download}/${tarball}" "$url"
  echo "${sha256}  ${download}/${tarball}" | sha256sum --check --quiet >&2
  tar -xzf "${download}/${tarball}" -C "$download" "$member"
  mkdir -p "$(dirname "$target")"
  install -m 0755 "${download}/${member}" "$target"
  rm -rf "$download"
}

victorialogs_bin="${CACHE_DIR}/${VICTORIALOGS_VERSION}/victoria-logs-prod"
vmauth_bin="${CACHE_DIR}/${VMUTILS_VERSION}/vmauth-prod"
fetch_binary "https://github.com/VictoriaMetrics/VictoriaLogs/releases/download/${VICTORIALOGS_VERSION}/${VICTORIALOGS_TARBALL}" \
  "$VICTORIALOGS_TARBALL" "$VICTORIALOGS_TARBALL_SHA256" victoria-logs-prod "$victorialogs_bin"
fetch_binary "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VMUTILS_VERSION}/${VMUTILS_TARBALL}" \
  "$VMUTILS_TARBALL" "$VMUTILS_TARBALL_SHA256" vmauth-prod "$vmauth_bin"

workspace="$(mktemp -d)"
server_pids=()
stop_servers() {
  local pid
  for pid in "${server_pids[@]}"; do
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
  server_pids=()
}
trap 'stop_servers; rm -rf "$workspace"' EXIT

wait_for() {
  local url="$1" attempts=0
  until curl -fsS -o /dev/null "$url" 2>/dev/null; do
    attempts=$((attempts + 1))
    if ((attempts > 100)); then
      echo "timed out waiting for ${url}" >&2
      return 1
    fi
    sleep 0.1
  done
}

start_victorialogs() {
  "$victorialogs_bin" -storageDataPath "${workspace}/vl" -httpListenAddr "127.0.0.1:${VICTORIALOGS_PORT}" \
    -retentionPeriod 100y -loggerLevel ERROR >"${workspace}/vl.log" 2>&1 &
  server_pids+=("$!")
  wait_for "http://127.0.0.1:${VICTORIALOGS_PORT}/health"
  local now cluster
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for cluster in homelab-cluster unfold; do
    jq -cn --arg now "$now" --arg cluster "$cluster" \
      '{requestReceivedTimestamp: $now, requestURI: "/api/v1/namespaces/default/secrets", verb: "get", user: {username: "admin"}, marker: ("record-of-" + $cluster)}' \
      | curl -fsS -X POST --data-binary @- -H "Content-Type: application/x-ndjson" \
        -H "VL-Extra-Fields: cluster=${cluster},job=kube-audit,node=cp-1" \
        -H "VL-Stream-Fields: cluster,job,node" \
        -H "VL-Msg-Field: requestURI" \
        -H "VL-Time-Field: requestReceivedTimestamp" \
        "http://127.0.0.1:${VICTORIALOGS_PORT}/insert/jsonline" >/dev/null
  done
  curl -fsS "http://127.0.0.1:${VICTORIALOGS_PORT}/internal/force_flush" >/dev/null
}

start_reader() {
  local config="$1"
  sed "s|${UPSTREAM}|http://127.0.0.1:${VICTORIALOGS_PORT}|" "$config" >"${workspace}/reader.yaml"
  "$vmauth_bin" -httpListenAddr "127.0.0.1:${READER_PORT}" -auth.config "${workspace}/reader.yaml" \
    -loggerLevel ERROR >"${workspace}/reader.log" 2>&1 &
  server_pids+=("$!")
  wait_for "http://127.0.0.1:${READER_PORT}/health"
}

reader_get() {
  curl -sS -G "http://127.0.0.1:${READER_PORT}$1" "${@:2}"
}

markers_seen() {
  { reader_get /select/logsql/query --data-urlencode "query=$1" "${@:2}" || true; } \
    | jq -r 'select(type == "object") | .marker // empty' 2>/dev/null | sort -u | paste -sd, -
}

unfold_visible_anywhere() {
  [[ "$(markers_seen '*')" == *record-of-unfold* ]] && return 0
  [[ "$(markers_seen '{cluster="unfold"}')" == *record-of-unfold* ]] && return 0
  [[ "$(markers_seen '*' --data-urlencode 'extra_stream_filters={cluster="unfold"}')" == *record-of-unfold* ]] && return 0
  reader_get /select/logsql/stream_field_values --data-urlencode 'query=*' --data-urlencode 'field=cluster' | grep -q '"unfold"' && return 0
  reader_get /select/logsql/field_values --data-urlencode 'query=*' --data-urlencode 'field=marker' | grep -q 'record-of-unfold' && return 0
  return 1
}

failures=0
check() {
  local name="$1"
  shift
  if "$@"; then
    echo "ok    ${name}"
  else
    echo "FAIL  ${name}" >&2
    failures=$((failures + 1))
  fi
}

homelab_visible() { [[ "$(markers_seen '*')" == "record-of-homelab-cluster" ]]; }
unfold_hidden() { ! unfold_visible_anywhere; }
path_refused() { [[ "$(curl -sS -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:${READER_PORT}$1")" != 2* ]]; }

start_victorialogs
start_reader "$READER_CONFIG"
check "the homelab audit record is readable through the reader" homelab_visible
check "no query shape reaches the Unfold audit record" unfold_hidden
check "the reader refuses inserts" path_refused /insert/jsonline
check "the reader refuses deletes" path_refused /delete/run_task
check "the reader refuses internal endpoints" path_refused /internal/force_flush
stop_servers

if [[ "$mutation_test" == true ]]; then
  sed 's|?extra_stream_filters=[^[:space:]]*||' "$READER_CONFIG" >"${workspace}/mutant.yaml"
  if cmp -s "$READER_CONFIG" "${workspace}/mutant.yaml"; then
    echo "FAIL  mutation: the reader config carries no extra_stream_filters to strip" >&2
    failures=$((failures + 1))
  else
    rm -rf "${workspace}/vl"
    start_victorialogs
    start_reader "${workspace}/mutant.yaml"
    check "mutation: without extra_stream_filters the Unfold record shows, so the filter is what hides it" unfold_visible_anywhere
    stop_servers
  fi
fi

if ((failures > 0)); then
  echo "${failures} audit reader check(s) failed" >&2
  exit 1
fi
echo "the audit reader shows the homelab trail and nothing of Unfold's"
