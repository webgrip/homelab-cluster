#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/oci.sh"

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

  actual=""
  tmp_output="$(mktemp)"
  if ! fetch_digest "$image" "$tag" >"$tmp_output"; then
    rm -f "$tmp_output"
    if [[ "${OCI_FETCH_DIGEST_ERROR_KIND:-}" == "transient" ]]; then
      echo "WARN ${file}: skipped digest verification for ${image}:${tag} because the registry returned a transient error"
      continue
    fi

    echo "FAIL ${file}: could not resolve registry digest for ${image}:${tag}"
    status=1
    continue
  fi
  actual="$(<"$tmp_output")"
  rm -f "$tmp_output"

  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL ${file}: expected ${expected}, registry has ${actual} for ${image}:${tag}"
    status=1
  else
    echo "OK   ${file}: ${image}:${tag}@${expected}"
  fi
done < <(find "${ROOT_DIR}/kubernetes/apps" -path '*/ocirepository.yaml' -print0 | sort -z)

exit "$status"
