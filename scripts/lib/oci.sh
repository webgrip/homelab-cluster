#!/usr/bin/env bash

ACCEPT_HEADER="application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json, */*"

fetch_digest() {
  local image="$1"
  local tag="$2"
  local host="${image%%/*}"
  local path="${image#*/}"
  local registry_url="https://${host}"
  local auth_header=()

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
  esac

  curl -fsSI \
    "${auth_header[@]}" \
    -H "Accept: ${ACCEPT_HEADER}" \
    "${registry_url}/v2/${path}/manifests/${tag}" |
    awk 'BEGIN { IGNORECASE=1 } /^docker-content-digest:/ { gsub("\r", "", $2); print $2; exit }'
}
