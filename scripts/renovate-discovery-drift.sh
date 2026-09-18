#!/usr/bin/env bash
# Compares the Forgejo org's real repo set against webgrip-forgejo.yaml's discoveryFilters.
#
# The list is explicit on purpose (most webgrip repos are read-only pull-mirrors, and a
# `webgrip/*` glob would spawn a serial executor Job per mirror every run). That reasoning
# still holds; what does not hold is leaving the list to rot. On 2026-09-18 it carried three
# repos that no longer exist and was missing six that do — including frontend-toolkit, whose
# packages the estate's whole frontend toolchain is built on, and semantic-release-config,
# which the CI runner image bakes in. Nothing failed. Renovate simply never ran on them.
#
# EXPECTED_MISSING is for repos deliberately left out. An entry there is a decision; an
# entry anywhere else in the drift output is a bug.
set -euo pipefail

FORGEJO="${FORGEJO_URL:-https://forgejo.webgrip.dev}"
ORG="${FORGEJO_ORG:-webgrip}"
JOB_FILE="${JOB_FILE:-kubernetes/apps/renovate/renovate-operator/jobs/webgrip-forgejo.yaml}"

EXPECTED_MISSING=()

command -v jq >/dev/null || { echo "FATAL: jq missing"; exit 1; }
[ -f "$JOB_FILE" ] || { echo "FATAL: $JOB_FILE not found (run from the repo root)"; exit 1; }

auth=()
if [ -n "${TOKEN:-}" ]; then auth=(-H "Authorization: token ${TOKEN}"); fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
: > "${tmp}/actual"

for page in 1 2 3 4 5; do
  curl -sf -m 30 ${auth[@]+"${auth[@]}"} "${FORGEJO}/api/v1/orgs/${ORG}/repos?limit=50&page=${page}" \
    | jq -r '.[] | select(.mirror == false and .archived == false and .empty == false) | .name' \
    >> "${tmp}/actual" || break
  [ -s "${tmp}/actual" ] || break
done
sort -u "${tmp}/actual" -o "${tmp}/actual"

sed -n '/discoveryFilters:/,/^  provider:/p' "$JOB_FILE" \
  | grep -E "^\s+- ${ORG}/" \
  | sed "s|.*${ORG}/||" \
  | sort -u > "${tmp}/configured"

printf '%s\n' ${EXPECTED_MISSING[@]+"${EXPECTED_MISSING[@]}"} | sort -u > "${tmp}/expected_missing"

comm -23 "${tmp}/actual" "${tmp}/configured" | comm -23 - "${tmp}/expected_missing" > "${tmp}/unmanaged"
comm -13 "${tmp}/actual" "${tmp}/configured" > "${tmp}/ghosts"

status=0

if [ -s "${tmp}/unmanaged" ]; then
  status=1
  echo "DRIFT: active source repos Renovate does not discover"
  while read -r r; do echo "  + ${ORG}/${r}"; done < "${tmp}/unmanaged"
  echo "  -> add to discoveryFilters in ${JOB_FILE}, or to EXPECTED_MISSING here with a reason"
  echo
fi

if [ -s "${tmp}/ghosts" ]; then
  status=1
  echo "DRIFT: discoveryFilters entries that are not an active source repo"
  while read -r r; do echo "  - ${ORG}/${r}"; done < "${tmp}/ghosts"
  echo "  -> renamed, archived, deleted, or now a mirror; each costs an executor Job every run"
  echo
fi

if [ "$status" -eq 0 ]; then
  echo "ok: $(wc -l < "${tmp}/configured" | tr -d ' ') discovered, $(wc -l < "${tmp}/actual" | tr -d ' ') active source repos, no drift"
fi

exit "$status"
