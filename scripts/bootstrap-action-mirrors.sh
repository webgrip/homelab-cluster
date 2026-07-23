#!/usr/bin/env bash
#
# bootstrap-action-mirrors.sh — mirror every Actions repo the .forgejo workflows use onto the
# local Forgejo, so `uses: actions/checkout@v4` resolves LAN-locally instead of cloning from
# data.forgejo.org over WAN on every job (~2min/job measured, 2026-07-23).
#
# Pairs with [actions].DEFAULT_ACTIONS_URL in kubernetes/apps/forgejo/forgejo/app/helmrelease.yaml:
#   RUN THIS SCRIPT (and verify) BEFORE merging the DEFAULT_ACTIONS_URL change — once the config
#   flips, a missing mirror means the action 404s and every job using it fails.
#
# Needs: FORGEJO_TOKEN env var with an ADMIN token (orgs + repo migration). Mint one:
#   kubectl -n forgejo exec deploy/forgejo -c forgejo -- \
#     forgejo admin user generate-access-token --username gitea_admin \
#     --token-name mirror-bootstrap --scopes write:organization,write:repository,write:admin --raw
# and delete it afterwards (UI: gitea_admin -> settings -> applications, or the API).
#
# Idempotent: existing orgs/repos are left alone (409s are reported as "exists").
set -euo pipefail

FORGE="${FORGE:-https://forgejo.webgrip.dev}"
API="${FORGE}/api/v1"
: "${FORGEJO_TOKEN:?set FORGEJO_TOKEN to an admin token}"
AUTH=(-H "Authorization: token ${FORGEJO_TOKEN}")
# Daily sync keeps upstream tags (v4, v5...) fresh without hammering upstreams.
INTERVAL="24h0m0s"

# owner  repo  upstream-clone-url
MIRRORS=(
  "actions    checkout                        https://github.com/actions/checkout.git"
  "actions    cache                           https://github.com/actions/cache.git"
  "actions    setup-node                      https://github.com/actions/setup-node.git"
  "actions    setup-python                    https://github.com/actions/setup-python.git"
  "actions    setup-java                      https://github.com/actions/setup-java.git"
  "actions    setup-go                        https://github.com/actions/setup-go.git"
  "actions    github-script                   https://github.com/actions/github-script.git"
  "docker     login-action                    https://github.com/docker/login-action.git"
  "docker     setup-qemu-action               https://github.com/docker/setup-qemu-action.git"
  "docker     setup-buildx-action             https://github.com/docker/setup-buildx-action.git"
  "docker     build-push-action               https://github.com/docker/build-push-action.git"
  "azure      setup-helm                      https://github.com/Azure/setup-helm.git"
  "tj-actions changed-files                   https://github.com/tj-actions/changed-files.git"
  "golangci   golangci-lint-action            https://github.com/golangci/golangci-lint-action.git"
  "cargo-bins cargo-binstall                  https://github.com/cargo-bins/cargo-binstall.git"
  "actions-rs toolchain                       https://github.com/actions-rs/toolchain.git"
  "10up       action-wordpress-plugin-deploy  https://github.com/10up/action-wordpress-plugin-deploy.git"
  # forgejo/* artifact forks come from code.forgejo.org. NB: "forgejo" may be a reserved
  # username on some instances — if org creation fails below, keep these two referenced by
  # absolute URL in workflows (they are the only forgejo/* actions in use).
  "forgejo    upload-artifact                 https://code.forgejo.org/forgejo/upload-artifact.git"
  "forgejo    download-artifact               https://code.forgejo.org/forgejo/download-artifact.git"
)

echo "== creating orgs =="
for org in $(printf '%s\n' "${MIRRORS[@]}" | awk '{print $1}' | sort -u); do
  code=$(curl -sS -o /tmp/mirror-resp.json -w '%{http_code}' "${AUTH[@]}" \
    -X POST -H 'Content-Type: application/json' \
    -d "{\"username\":\"${org}\",\"visibility\":\"public\"}" "${API}/orgs")
  case "$code" in
    201) echo "  created org ${org}" ;;
    409|422) echo "  org ${org} exists" ;;
    *) echo "  WARN org ${org}: HTTP ${code} $(head -c200 /tmp/mirror-resp.json)" ;;
  esac
done

echo "== migrating mirrors =="
while read -r org repo url; do
  [ -n "$org" ] || continue
  code=$(curl -sS -o /tmp/mirror-resp.json -w '%{http_code}' "${AUTH[@]}" \
    -X POST -H 'Content-Type: application/json' \
    -d "$(printf '{"clone_addr":"%s","repo_owner":"%s","repo_name":"%s","mirror":true,"mirror_interval":"%s","private":false}' "$url" "$org" "$repo" "$INTERVAL")" \
    "${API}/repos/migrate")
  case "$code" in
    201) echo "  mirrored ${org}/${repo}" ;;
    409) echo "  ${org}/${repo} exists" ;;
    *) echo "  WARN ${org}/${repo}: HTTP ${code} $(head -c200 /tmp/mirror-resp.json)" ;;
  esac
done < <(printf '%s\n' "${MIRRORS[@]}")

echo "== verifying anonymous clone access (what the runner does) =="
fail=0
while read -r org repo _; do
  [ -n "$org" ] || continue
  if git ls-remote --heads "${FORGE}/${org}/${repo}.git" >/dev/null 2>&1; then
    echo "  OK ${org}/${repo}"
  else
    echo "  FAIL ${org}/${repo} — anonymous ls-remote failed (repo missing or private)"
    fail=1
  fi
done < <(printf '%s\n' "${MIRRORS[@]}")

if [ "$fail" -eq 0 ]; then
  echo "ALL MIRRORS VERIFIED — safe to merge the DEFAULT_ACTIONS_URL change."
else
  echo "SOME MIRRORS FAILED — do NOT flip DEFAULT_ACTIONS_URL yet."
  exit 1
fi
