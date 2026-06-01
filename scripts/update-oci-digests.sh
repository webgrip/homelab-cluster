#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/oci.sh"

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

  digest=""
  tmp_output="$(mktemp)"
  if ! fetch_digest "$image" "$tag" >"$tmp_output"; then
    rm -f "$tmp_output"
    if [[ "${OCI_FETCH_DIGEST_ERROR_KIND:-}" == "transient" ]]; then
      echo "FAIL ${file}: registry returned a transient error while resolving ${image}:${tag}" >&2
    else
      echo "FAIL ${file}: could not resolve registry digest for ${image}:${tag}" >&2
    fi
    exit 1
  fi
  digest="$(<"$tmp_output")"
  rm -f "$tmp_output"

  if [[ -z "$digest" ]]; then
    echo "FAIL ${file}: could not resolve registry digest for ${image}:${tag}" >&2
    exit 1
  fi

  update_ref_digest "$file" "$digest"
  echo "PIN  ${file}: ${image}:${tag}@${digest}"
done < <(find "${ROOT_DIR}/kubernetes/apps" -path '*/ocirepository.yaml' -print0 | sort -z)
