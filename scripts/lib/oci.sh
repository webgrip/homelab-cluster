#!/usr/bin/env bash

ACCEPT_HEADER="application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json, */*"
OCI_FETCH_DIGEST_ERROR_KIND=""

fetch_digest() {
  local image="$1"
  local tag="$2"
  local host="${image%%/*}"
  local path="${image#*/}"
  local registry_url="https://${host}"
  local auth_header=()
  local headers_file
  local status

  OCI_FETCH_DIGEST_ERROR_KIND=""

  case "$host" in
    ghcr.io)
      local token
      token="$(curl -fsSL "https://ghcr.io/token?scope=repository:${path}:pull&service=ghcr.io" | jq -r .token)"
      auth_header=(-H "Authorization: Bearer ${token}")
      ;;
    docker.io|registry-1.docker.io)
      host="registry-1.docker.io"
      registry_url="https://${host}"
      if [[ "$path" != */* ]]; then
        path="library/${path}"
      fi

      local token
      token="$(curl -fsSL "https://auth.docker.io/token?service=registry.docker.io&scope=repository:${path}:pull" | jq -r .token)"
      auth_header=(-H "Authorization: Bearer ${token}")
      ;;
    code.forgejo.org)
      local token
      token="$(curl -fsSL "https://code.forgejo.org/v2/token?service=container_registry&scope=repository:${path}:pull" | jq -r .token)"
      auth_header=(-H "Authorization: Bearer ${token}")
      ;;
    harbor.webgrip.dev)
      # Proxy projects are public, but the registry protocol still requires an
      # (anonymous) bearer token; without it every manifest HEAD returns 401,
      # which failed the whole script — and with it every Renovate
      # postUpgradeTask — for all harbor-proxied charts.
      local token
      token="$(curl -fsSL "https://harbor.webgrip.dev/service/token?service=harbor-registry&scope=repository:${path}:pull" | jq -r .token)"
      auth_header=(-H "Authorization: Bearer ${token}")
      ;;
  esac

  headers_file="$(mktemp)"
  status="$(
    curl -sSIL \
      --retry 4 \
      --retry-delay 2 \
      --retry-all-errors \
      -o /dev/null \
      -D "$headers_file" \
      -w '%{http_code}' \
      "${auth_header[@]}" \
      -H "Accept: ${ACCEPT_HEADER}" \
      "${registry_url}/v2/${path}/manifests/${tag}" || true
  )"

  if [[ "$status" == "200" ]]; then
    awk 'BEGIN { IGNORECASE=1 } /^docker-content-digest:/ { gsub("\r", "", $2); print $2; exit }' "$headers_file"
    rm -f "$headers_file"
    return 0
  fi

  rm -f "$headers_file"

  if [[ "$status" == "000" || "$status" =~ ^5[0-9][0-9]$ ]]; then
    OCI_FETCH_DIGEST_ERROR_KIND="transient"
    return 2
  fi

  OCI_FETCH_DIGEST_ERROR_KIND="permanent"
  return 1
}
