#!/usr/bin/env bash
# Asserts that every active source repo in the org carries the `renovate` topic.
#
# Discovery is topic-driven (webgrip-forgejo.yaml: discoveryFilters scopes to the org,
# discoverTopics selects inside it). That is preventive — a new repo opts in once and a deleted
# one drops out by itself — but it moves the failure mode rather than removing it: an untagged
# repo is now silently unmanaged exactly the way a missing list entry used to be. This guards it.
#
# It replaced a check against a hand-maintained list, which by 2026-09-18 had rotted both ways:
# three entries pointed at repos that no longer existed, and six that did were missing —
# including frontend-toolkit, whose packages the estate's frontend toolchain is built on, and
# semantic-release-config, which the ci-runner image bakes in.
#
# EXPECTED_UNTAGGED is for repos deliberately left out. An entry there is a decision; an entry
# in the drift output is a bug.
set -euo pipefail

FORGEJO="${FORGEJO_URL:-https://forgejo.webgrip.dev}"
ORG="${FORGEJO_ORG:-webgrip}"
TOPIC="${RENOVATE_TOPIC:-renovate}"

EXPECTED_UNTAGGED=()

command -v jq >/dev/null || { echo "FATAL: jq missing"; exit 1; }

auth=()
if [ -n "${TOKEN:-}" ]; then auth=(-H "Authorization: token ${TOKEN}"); fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
: > "${tmp}/actual"

for page in 1 2 3 4 5; do
  before=$(wc -l < "${tmp}/actual")
  curl -sf -m 30 ${auth[@]+"${auth[@]}"} "${FORGEJO}/api/v1/orgs/${ORG}/repos?limit=50&page=${page}" \
    | jq -r '.[] | select(.mirror == false and .archived == false and .empty == false) | .name' \
    >> "${tmp}/actual" || break
  [ "$(wc -l < "${tmp}/actual")" -gt "${before}" ] || break
done
sort -u "${tmp}/actual" -o "${tmp}/actual"

[ -s "${tmp}/actual" ] || { echo "FATAL: no repos returned — check the token and ${FORGEJO}"; exit 1; }

: > "${tmp}/untagged"
: > "${tmp}/tagged"
while read -r repo; do
  topics=$(curl -sf -m 20 ${auth[@]+"${auth[@]}"} "${FORGEJO}/api/v1/repos/${ORG}/${repo}/topics" | jq -r '.topics // [] | .[]')
  if grep -qxF "${TOPIC}" <<<"${topics}"; then
    echo "${repo}" >> "${tmp}/tagged"
  else
    echo "${repo}" >> "${tmp}/untagged"
  fi
done < "${tmp}/actual"

printf '%s\n' ${EXPECTED_UNTAGGED[@]+"${EXPECTED_UNTAGGED[@]}"} | sort -u > "${tmp}/expected"
sort -u "${tmp}/untagged" -o "${tmp}/untagged"
comm -23 "${tmp}/untagged" "${tmp}/expected" > "${tmp}/drift"

if [ -s "${tmp}/drift" ]; then
  echo "DRIFT: active source repos without the '${TOPIC}' topic — Renovate does not see them"
  while read -r r; do echo "  + ${ORG}/${r}"; done < "${tmp}/drift"
  echo
  echo "  Fix by tagging, which is the whole point of the topic:"
  while read -r r; do
    echo "    curl -X PUT -H \"Authorization: token \$TOKEN\" -H 'Content-Type: application/json' \\"
    echo "      -d '{\"topics\":[\"${TOPIC}\"]}' ${FORGEJO}/api/v1/repos/${ORG}/${r}/topics"
  done < "${tmp}/drift"
  echo
  echo "  Deliberately excluded? Add it to EXPECTED_UNTAGGED in this script, with a reason."
  exit 1
fi

echo "ok: $(wc -l < "${tmp}/tagged" | tr -d ' ')/$(wc -l < "${tmp}/actual" | tr -d ' ') active source repos carry '${TOPIC}', no drift"
