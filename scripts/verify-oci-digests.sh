#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
ACCEPT_HEADER="application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json, */*"

fetch_digest() {
  local image="$1"
  local tag="$2"
  local host="${image%%/*}"
  local path="${image#*/}"

  if [[ "$host" == "ghcr.io" ]]; then
    local token
    token="$(curl -fsSL "https://ghcr.io/token?scope=repository:${path}:pull&service=ghcr.io" | jq -r .token)"
    curl -fsSI \
      -H "Authorization: Bearer ${token}" \
      -H "Accept: ${ACCEPT_HEADER}" \
      "https://${host}/v2/${path}/manifests/${tag}" |
      awk 'BEGIN { IGNORECASE=1 } /^docker-content-digest:/ { gsub("\r", "", $2); print $2; exit }'
  else
    curl -fsSI \
      -H "Accept: ${ACCEPT_HEADER}" \
      "https://${host}/v2/${path}/manifests/${tag}" |
      awk 'BEGIN { IGNORECASE=1 } /^docker-content-digest:/ { gsub("\r", "", $2); print $2; exit }'
  fi
}

status=0

while IFS= read -r -d '' file; do
  image="$(awk '/^[[:space:]]+url: oci:\/\// { sub(/^[[:space:]]+url: oci:\/\//, ""); print; exit }' "$file")"
  tag="$(awk '
    /^[[:space:]]+ref:/ { in_ref=1; next }
    in_ref && /^[[:space:]]+[a-zA-Z]/ && $1 !~ /^(tag:|digest:)$/ { in_ref=0 }
    in_ref && /^[[:space:]]+tag:/ { gsub(/"/, "", $2); print $2; exit }
  ' "$file")"
  expected="$(awk '
    /^[[:space:]]+ref:/ { in_ref=1; next }
    in_ref && /^[[:space:]]+[a-zA-Z]/ && $1 !~ /^(tag:|digest:)$/ { in_ref=0 }
    in_ref && /^[[:space:]]+digest:/ { print $2; exit }
  ' "$file")"

  if [[ -z "$image" || -z "$tag" ]]; then
    echo "SKIP ${file}: missing spec.url or spec.ref.tag"
    continue
  fi

  if [[ -z "$expected" ]]; then
    echo "FAIL ${file}: missing spec.ref.digest for ${image}:${tag}"
    status=1
    continue
  fi

  actual="$(fetch_digest "$image" "$tag" || true)"

  if [[ -z "$actual" ]]; then
    echo "FAIL ${file}: could not resolve registry digest for ${image}:${tag}"
    status=1
  elif [[ "$actual" != "$expected" ]]; then
    echo "FAIL ${file}: expected ${expected}, registry has ${actual} for ${image}:${tag}"
    status=1
  else
    echo "OK   ${file}: ${image}:${tag}@${expected}"
  fi
done < <(find "${ROOT_DIR}/kubernetes/apps" -path '*/ocirepository.yaml' -print0 | sort -z)

exit "$status"
