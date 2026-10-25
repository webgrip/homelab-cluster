#!/usr/bin/env bash
set -euo pipefail
shopt -s inherit_errexit

readonly usage="usage: test-vlogs-rules.sh [--mutation-test] [repo-root]

Unit-tests the LogsQL (type: vlogs) alerting rules the way they run in the
cluster: every test case under scripts/vlogs-rule-tests/<vmrule>.test.yaml
starts a throwaway VictoriaLogs at the pinned version, ingests the case's log
lines (timestamps given as seconds before now), and lets a real vmalert
evaluate the VMRule's groups once. The set of alerts that fire must be exactly
the case's firing list; every other rule must stay quiet, and no rule may
report an evaluation error.

  --mutation-test  also, for every alert a case expects to fire, replace that
                   rule's expression with one that returns nothing and require
                   the alert to stop firing; and apply each case's own
                   mutations (a textual edit of one rule) and require the
                   case's result to change. A case that survives its mutation
                   was never testing that rule.

Needs curl, jq, sha256sum, tar and yq (or mise)."

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
readonly TESTS_DIR="${ROOT_DIR}/scripts/vlogs-rule-tests"

readonly VICTORIALOGS_VERSION="v1.51.0"
readonly VICTORIALOGS_TARBALL="victoria-logs-linux-amd64-${VICTORIALOGS_VERSION}.tar.gz"
readonly VICTORIALOGS_TARBALL_SHA256="4c501ea21663d7d934f8d0e026cef751bb0907bf794c7e716cb21252bdea1fac"
readonly VMUTILS_VERSION="v1.147.0"
readonly VMUTILS_TARBALL="vmutils-linux-amd64-${VMUTILS_VERSION}.tar.gz"
readonly VMUTILS_TARBALL_SHA256="1e5da38c3d8d7af9c4fc0daa8a2103f2578c40ed81752d21f20a3bd6d0506b3f"
readonly CACHE_DIR="${VLOGS_RULE_TEST_CACHE:-${XDG_CACHE_HOME:-${HOME}/.cache}/vlogs-rule-tests}"
readonly VICTORIALOGS_PORT="${VLOGS_RULE_TEST_VL_PORT:-19428}"
readonly VMALERT_PORT="${VLOGS_RULE_TEST_VMALERT_PORT:-18880}"

yq_cmd() {
  if command -v yq >/dev/null 2>&1; then
    yq "$@"
  else
    mise -C "$ROOT_DIR" exec -- yq "$@"
  fi
}

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
vmalert_bin="${CACHE_DIR}/${VMUTILS_VERSION}/vmalert-prod"
fetch_binary "https://github.com/VictoriaMetrics/VictoriaLogs/releases/download/${VICTORIALOGS_VERSION}/${VICTORIALOGS_TARBALL}" \
  "$VICTORIALOGS_TARBALL" "$VICTORIALOGS_TARBALL_SHA256" victoria-logs-prod "$victorialogs_bin"
fetch_binary "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VMUTILS_VERSION}/${VMUTILS_TARBALL}" \
  "$VMUTILS_TARBALL" "$VMUTILS_TARBALL_SHA256" vmalert-prod "$vmalert_bin"

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

resolve_rule_source() {
  find "${ROOT_DIR}/kubernetes/apps" -path '*/rules/vmrule-'"$1"'.yaml' -print -quit
}

render_rules() {
  local source="$1" target="$2"
  yq_cmd -o=json '.spec | del(.groups[].rules[].annotations)' "$source" | sed 's/\$\$/$/g' >"$target"
}

ingest() {
  local test_json="$1" stream_fields="$2" extra_fields="$3" now
  now="$(date -u +%s)"
  jq -c --argjson now "$now" '.logs[] | . + {timestamp: (($now - (.age // 150)) | todate)} | del(.age)' <<<"$test_json" \
    | curl -fsS -X POST --data-binary @- \
      -H "Content-Type: application/x-ndjson" \
      -H "VL-Stream-Fields: ${stream_fields}" \
      -H "VL-Extra-Fields: ${extra_fields}" \
      -H "VL-Msg-Field: message" \
      -H "VL-Time-Field: timestamp" \
      "http://127.0.0.1:${VICTORIALOGS_PORT}/insert/jsonline" >/dev/null
  curl -fsS "http://127.0.0.1:${VICTORIALOGS_PORT}/internal/force_flush" >/dev/null
}

evaluate() {
  local rules_json="$1" test_json="$2" stream_fields="$3" extra_fields="$4" case_dir
  case_dir="$(mktemp -d "${workspace}/case.XXXXXX")"
  yq_cmd -P '.' "$rules_json" >"${case_dir}/rules.yaml"

  "$victorialogs_bin" -storageDataPath "${case_dir}/vl" -httpListenAddr "127.0.0.1:${VICTORIALOGS_PORT}" \
    -retentionPeriod 100y -loggerLevel ERROR >"${case_dir}/vl.log" 2>&1 &
  server_pids+=("$!")
  wait_for "http://127.0.0.1:${VICTORIALOGS_PORT}/health"
  ingest "$test_json" "$stream_fields" "$extra_fields"

  "$vmalert_bin" -rule "${case_dir}/rules.yaml" -rule.defaultRuleType vlogs \
    -datasource.url "http://127.0.0.1:${VICTORIALOGS_PORT}" -notifier.blackhole \
    -group.maxStartDelay 10ms -rule.evalDelay 0s -httpListenAddr "127.0.0.1:${VMALERT_PORT}" -loggerLevel ERROR \
    >"${case_dir}/vmalert.log" 2>&1 &
  local vmalert_pid="$!"
  server_pids+=("$vmalert_pid")
  until curl -fsS -o /dev/null "http://127.0.0.1:${VMALERT_PORT}/health" 2>/dev/null; do
    if ! kill -0 "$vmalert_pid" 2>/dev/null; then
      stop_servers
      jq -cn --arg log "$(grep -m 3 -iE 'error|fatal|cannot' "${case_dir}/vmalert.log")" '{firing: [], errors: [{name: "vmalert refused the rules", lastError: $log}]}'
      return
    fi
    sleep 0.1
  done

  local rules attempts=0
  until rules="$(curl -fsS "http://127.0.0.1:${VMALERT_PORT}/api/v1/rules")" \
    && jq -e '[.data.groups[].rules[] | .lastEvaluation | startswith("0001")] | any | not' <<<"$rules" >/dev/null; do
    attempts=$((attempts + 1))
    if ((attempts > 200)); then
      echo "vmalert never evaluated every rule; its log:" >&2
      tail -n 20 "${case_dir}/vmalert.log" >&2
      stop_servers
      return 1
    fi
    sleep 0.1
  done
  stop_servers
  jq -c '{
    firing: ([.data.groups[].rules[] | select(.type == "alerting" and (.alerts | length) > 0) | .name] | unique),
    errors: [.data.groups[].rules[] | select(.lastError != "") | {name, lastError}]
  }' <<<"$rules"
}

failures=0
fail() {
  failures=$((failures + 1))
  echo "FAIL  $1" >&2
}

neutralise_rule() {
  jq --arg alert "$2" '(.groups[].rules[] | select(.alert == $alert) | .expr) |= (. + " | limit 0")' "$1"
}

mutate_rule() {
  jq --arg alert "$2" --arg from "$3" --arg to "$4" \
    '(.groups[].rules[] | select(.alert == $alert) | .expr) |= (if contains($from) then (split($from) | join($to)) else error("mutation text not found in \($alert)") end)' "$1"
}

shopt -s nullglob
test_files=("${TESTS_DIR}"/*.test.yaml)
if ((${#test_files[@]} == 0)); then
  echo "no vlogs rule tests under ${TESTS_DIR}" >&2
  exit 1
fi

for test_file in "${test_files[@]}"; do
  rule_name="$(basename "$test_file" .test.yaml)"
  rule_source="$(resolve_rule_source "$rule_name")"
  if [[ -z "$rule_source" ]]; then
    fail "${test_file}: no kubernetes/apps/*/*/app/rules/vmrule-${rule_name}.yaml"
    continue
  fi
  rules_json="${workspace}/${rule_name}.json"
  render_rules "$rule_source" "$rules_json"
  suite="$(yq_cmd -o=json '.' "$test_file")"
  stream_fields="$(jq -r '.stream_fields' <<<"$suite")"
  extra_fields="$(jq -r '.extra_fields' <<<"$suite")"

  tested_alerts="$(jq -r '[.tests[].firing[]] | unique | .[]' <<<"$suite")"
  while IFS= read -r alert; do
    jq -e --arg alert "$alert" '[.groups[].rules[].alert] | index($alert)' "$rules_json" >/dev/null \
      || fail "${rule_name}: a case expects ${alert}, which the VMRule does not define"
  done <<<"$tested_alerts"
  while IFS= read -r alert; do
    grep -qx "$alert" <<<"$tested_alerts" || fail "${rule_name}: no case makes ${alert} fire"
  done < <(jq -r '.groups[].rules[] | select(.alert) | .alert' "$rules_json")

  case_count="$(jq '.tests | length' <<<"$suite")"
  for ((index = 0; index < case_count; index++)); do
    case_json="$(jq -c ".tests[${index}]" <<<"$suite")"
    name="$(jq -r '.name' <<<"$case_json")"
    expected="$(jq -c '.firing | unique' <<<"$case_json")"
    result="$(evaluate "$rules_json" "$case_json" "$stream_fields" "$extra_fields")"
    if [[ "$(jq -c '.errors' <<<"$result")" != "[]" ]]; then
      fail "${rule_name} / ${name}: rules failed to evaluate: $(jq -c '.errors' <<<"$result")"
      continue
    fi
    got="$(jq -c '.firing' <<<"$result")"
    if [[ "$got" == "$expected" ]]; then
      echo "ok    ${rule_name} / ${name}: firing ${got}"
    else
      fail "${rule_name} / ${name}: expected ${expected}, got ${got}"
      continue
    fi

    [[ "$mutation_test" == true ]] || continue

    while IFS= read -r alert; do
      [[ -n "$alert" ]] || continue
      neutralise_rule "$rules_json" "$alert" >"${workspace}/mutant.json"
      mutant_got="$(evaluate "${workspace}/mutant.json" "$case_json" "$stream_fields" "$extra_fields" | jq -c '.firing')"
      if jq -e --arg alert "$alert" 'index($alert)' <<<"$mutant_got" >/dev/null; then
        fail "${rule_name} / ${name}: ${alert} still fires with its expression neutralised"
      else
        echo "ok    ${rule_name} / ${name}: neutralising ${alert} silences it"
      fi
    done < <(jq -r '.[]' <<<"$expected")

    mutation_count="$(jq '.mutations // [] | length' <<<"$case_json")"
    for ((m = 0; m < mutation_count; m++)); do
      mutation="$(jq -c ".mutations[${m}]" <<<"$case_json")"
      alert="$(jq -r '.alert' <<<"$mutation")"
      if ! mutate_rule "$rules_json" "$alert" "$(jq -r '.replace' <<<"$mutation")" "$(jq -r '.with' <<<"$mutation")" >"${workspace}/mutant.json" 2>"${workspace}/mutant.err"; then
        fail "${rule_name} / ${name}: mutation of ${alert} did not apply: $(cat "${workspace}/mutant.err")"
        continue
      fi
      mutant_got="$(evaluate "${workspace}/mutant.json" "$case_json" "$stream_fields" "$extra_fields" | jq -c '.firing')"
      if [[ "$mutant_got" == "$expected" ]]; then
        fail "${rule_name} / ${name}: mutating ${alert} ($(jq -r '.replace' <<<"$mutation")) changed nothing"
      else
        echo "ok    ${rule_name} / ${name}: mutating ${alert} flips the result to ${mutant_got}"
      fi
    done
  done
done

if ((failures > 0)); then
  echo "${failures} vlogs rule check(s) failed" >&2
  exit 1
fi
echo "all vlogs rule tests passed"
