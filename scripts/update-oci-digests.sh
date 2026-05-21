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

update_ref_digest() {
  local file="$1"
  local digest="$2"
  local tmp
  tmp="$(mktemp)"

  awk -v new_digest="$digest" '
    function leaving_ref() {
      return in_ref && $0 ~ /^  [A-Za-z]/ && $1 != "ref:"
    }
    {
      if (leaving_ref() && seen_tag && !seen_digest) {
        print "    digest: " new_digest
        seen_digest = 1
      }

      if ($0 ~ /^  ref:/) {
        in_ref = 1
        seen_tag = 0
        seen_digest = 0
      } else if (leaving_ref()) {
        in_ref = 0
      }

      if (in_ref && $0 ~ /^    tag:/) {
        seen_tag = 1
      }

      if (in_ref && $0 ~ /^    digest:/) {
        print "    digest: " new_digest
        seen_digest = 1
        next
      }

      print
    }
    END {
      if (in_ref && seen_tag && !seen_digest) {
        print "    digest: " new_digest
      }
    }
  ' "$file" > "$tmp"

  if ! cmp -s "$file" "$tmp"; then
    mv "$tmp" "$file"
  else
    rm "$tmp"
  fi
}

while IFS= read -r -d '' file; do
  image="$(awk '/^[[:space:]]+url: oci:\/\// { sub(/^[[:space:]]+url: oci:\/\//, ""); print; exit }' "$file")"
  tag="$(awk '
    /^[[:space:]]+ref:/ { in_ref=1; next }
    in_ref && /^[[:space:]]+[a-zA-Z]/ && $1 != "tag:" && $1 != "digest:" { in_ref=0 }
    in_ref && /^[[:space:]]+tag:/ { gsub(/"/, "", $2); print $2; exit }
  ' "$file")"

  if [[ -z "$image" || -z "$tag" ]]; then
    echo "SKIP ${file}: missing spec.url or spec.ref.tag"
    continue
  fi

  digest="$(fetch_digest "$image" "$tag")"
  if [[ -z "$digest" ]]; then
    echo "FAIL ${file}: could not resolve registry digest for ${image}:${tag}" >&2
    exit 1
  fi

  update_ref_digest "$file" "$digest"
  echo "PIN  ${file}: ${image}:${tag}@${digest}"
done < <(find "${ROOT_DIR}/kubernetes/apps" -path '*/ocirepository.yaml' -print0 | sort -z)
