#!/bin/sh
set -eu

readonly releases_url="https://api.github.com/repos/${RELEASE_REPOSITORY}/releases?per_page=30"
readonly tag_pattern='^unfold-v0\.[0-9]+\.[0-9]+-rc\.[0-9]+$'
readonly chart_registry="ghcr.io"
readonly operator_schedule_url="${OPERATOR_URL}/webhook/v1/schedule"
readonly retrigger_after_seconds=120
readonly give_up_after_seconds=3600
readonly staging_behind_after_seconds=2700
readonly run_start_slack_seconds=60

now="$(date -u +%s)"
readonly now
work="$(mktemp -d)"
readonly work
trap 'rm -rf "${work}"' EXIT

log() {
  event="$1"
  shift
  jq -cn --arg event "${event}" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$@" \
    '{ts: $ts, component: "unfold-release-watch", event: $event, msg: $event} + ($ARGS.named | del(.ts, .event))'
}

fail() {
  log tick_failed --arg reason "$1" >&2
  exit 1
}

iso_to_epoch() {
  jq -rn --arg t "$1" '$t | fromdateiso8601'
}

state_get() {
  jq -r --arg k "$1" '.data[$k] // ""' "${work}/state.json"
}

state_patch() {
  jq -cn '{data: $ARGS.named}' "$@" >"${work}/state-patch.json"
  kubectl -n "${NAMESPACE}" patch configmap "${STATE_CONFIGMAP}" --type merge --patch-file "${work}/state-patch.json" >/dev/null
}

newest_release() {
  set -- -fsS --max-time 20 -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28"
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    set -- "$@" -H "Authorization: Bearer ${GITHUB_TOKEN}"
  fi
  curl "$@" "${releases_url}" >"${work}/releases.json" || fail "github releases unreadable"
  jq -c --arg pattern "${tag_pattern}" '
    [.[] | select(.draft == false and (.tag_name | test($pattern)))]
    | sort_by(.published_at) | last // empty
    | {tag: .tag_name, version: (.tag_name | ltrimstr("unfold-v")), published_at: .published_at}
  ' "${work}/releases.json"
}

chart_published() {
  version="$1"
  registry_token="$(curl -fsS --max-time 20 "https://${chart_registry}/token?scope=repository:${CHART_REPOSITORY}:pull" | jq -r '.token // empty')" \
    || fail "ghcr token unavailable"
  status="$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' -I \
    -H "Authorization: Bearer ${registry_token}" \
    -H "Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json" \
    "https://${chart_registry}/v2/${CHART_REPOSITORY}/manifests/${version}")" || fail "ghcr manifest unreadable"
  case "${status}" in
    200) return 0 ;;
    404) return 1 ;;
    *) fail "ghcr manifest answered ${status}" ;;
  esac
}

schedule_project() {
  webhook_token="${WEBHOOK_TOKENS%%,*}"
  [ -n "${webhook_token}" ] || fail "webhook token missing"
  status="$(curl -sS --max-time 20 -o "${work}/schedule-response.json" -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${webhook_token}" \
    --get --data-urlencode "namespace=${NAMESPACE}" --data-urlencode "job=${RENOVATE_JOB}" --data-urlencode "project=${PROJECT}" \
    "${operator_schedule_url}")" || fail "renovate-operator unreachable"
  [ "${status}" = 200 ] || fail "schedule answered ${status}: $(head -c 200 "${work}/schedule-response.json")"
}

project_status() {
  kubectl -n "${NAMESPACE}" get renovatejob "${RENOVATE_JOB}" -o json | jq -c --arg project "${PROJECT}" '
    def seconds: [splits(" ") | select(length > 0) | (.[:-1] | tonumber) * ({"h": 3600, "m": 60, "s": 1}[.[-1:]])] | add // 0;
    [.status.projects[]? | select(.name == $project)][0] // {}
    | {
        status: (.status // "unknown"),
        transitioned: ((.lastTransition // "1970-01-01T00:00:00Z") | fromdateiso8601),
        duration: ((.duration // "") | seconds)
      }
  '
}

run_started_after() {
  since="$1"
  echo "$2" | jq -e --argjson since "${since}" --argjson slack "${run_start_slack_seconds}" '
    if .status == "running" then .transitioned >= $since
    elif (.status == "completed" or .status == "failed" or .status == "cancelled") then (.transitioned - .duration - $slack) >= $since
    else false end
  ' >/dev/null
}

staging_revision() {
  query='flux_resource_info{cluster="unfold",kind="HelmRelease",exported_namespace="unfold-staging",name="unfold"}'
  curl -fsS --max-time 20 --get --data-urlencode "query=${query}" "${METRICS_URL}/api/v1/query" \
    | jq -r '[.data.result[].metric | select(.ready == "True") | .revision | split("+")[0]] | first // ""' \
    || echo ""
}

kubectl -n "${NAMESPACE}" get configmap "${STATE_CONFIGMAP}" -o json >"${work}/state.json" || fail "state configmap unreadable"

release="$(newest_release)"
[ -n "${release}" ] || { log no_release; exit 0; }
tag="$(echo "${release}" | jq -r .tag)"
version="$(echo "${release}" | jq -r .version)"
published_at="$(echo "${release}" | jq -r .published_at)"
published_epoch="$(iso_to_epoch "${published_at}")"

if [ "$(state_get version)" != "${version}" ]; then
  state_patch --arg version "${version}" --arg tag "${tag}" --arg publishedAt "${published_at}" \
    --arg seenAt "${now}" --arg chartSeenAt "" --arg firstTriggeredAt "" --arg lastTriggeredAt "" \
    --arg runStartedAt "" --arg deployedAt "" --arg outcome "waiting-for-chart"
  log release_seen --arg tag "${tag}" --arg version "${version}" --arg published_at "${published_at}" \
    --argjson seen_after_publish_seconds "$((now - published_epoch))"
  kubectl -n "${NAMESPACE}" get configmap "${STATE_CONFIGMAP}" -o json >"${work}/state.json"
fi

outcome="$(state_get outcome)"

if [ "${outcome}" = "waiting-for-chart" ]; then
  if ! chart_published "${version}"; then
    log chart_pending --arg version "${version}" --argjson since_publish_seconds "$((now - published_epoch))"
    exit 0
  fi
  state_patch --arg chartSeenAt "${now}" --arg outcome "triggering"
  log chart_seen --arg version "${version}" --argjson chart_after_publish_seconds "$((now - published_epoch))"
  schedule_project
  state_patch --arg firstTriggeredAt "${now}" --arg lastTriggeredAt "${now}"
  log renovate_triggered --arg version "${version}" --arg project "${PROJECT}" --argjson attempt 1
  exit 0
fi

if [ "${outcome}" = "triggering" ]; then
  first_triggered="$(state_get firstTriggeredAt)"
  last_triggered="$(state_get lastTriggeredAt)"
  if [ -z "${first_triggered}" ]; then
    schedule_project
    state_patch --arg firstTriggeredAt "${now}" --arg lastTriggeredAt "${now}"
    log renovate_triggered --arg version "${version}" --arg project "${PROJECT}" --argjson attempt 1
    exit 0
  fi
  status="$(project_status)"
  if run_started_after "${first_triggered}" "${status}"; then
    started="$(echo "${status}" | jq -r 'if .status == "running" then .transitioned else (.transitioned - .duration) end')"
    state_patch --arg runStartedAt "${started}" --arg outcome "handled"
    log renovate_run_started --arg version "${version}" --arg project "${PROJECT}" \
      --arg run_status "$(echo "${status}" | jq -r .status)" \
      --argjson run_after_publish_seconds "$((started - published_epoch))" \
      --argjson run_after_trigger_seconds "$((started - first_triggered))"
  elif [ "$((now - first_triggered))" -ge "${give_up_after_seconds}" ]; then
    state_patch --arg outcome "gave-up"
    log renovate_trigger_gave_up --arg version "${version}" --arg project "${PROJECT}" \
      --arg run_status "$(echo "${status}" | jq -r .status)" >&2
  elif [ "$(echo "${status}" | jq -r .status)" = "running" ] || [ "$(echo "${status}" | jq -r .status)" = "scheduled" ]; then
    log renovate_waiting --arg version "${version}" --arg run_status "$(echo "${status}" | jq -r .status)"
  elif [ "$((now - last_triggered))" -ge "${retrigger_after_seconds}" ]; then
    schedule_project
    state_patch --arg lastTriggeredAt "${now}"
    log renovate_triggered --arg version "${version}" --arg project "${PROJECT}" --arg reason "no run started since the first trigger"
  fi
  exit 0
fi

if [ -n "$(state_get deployedAt)" ]; then
  exit 0
fi

chart_seen="$(state_get chartSeenAt)"
deployed="$(staging_revision)"
if [ "${deployed}" = "${version}" ]; then
  state_patch --arg deployedAt "${now}"
  log staging_deployed --arg version "${version}" \
    --argjson deployed_after_publish_seconds "$((now - published_epoch))" \
    --argjson deployed_after_chart_seconds "$((now - chart_seen))"
elif [ -n "${chart_seen}" ] && [ "$((now - chart_seen))" -ge "${staging_behind_after_seconds}" ]; then
  log staging_behind --arg version "${version}" --arg deployed "${deployed:-unknown}" \
    --argjson behind_seconds "$((now - chart_seen))" --arg outcome "${outcome}"
fi
