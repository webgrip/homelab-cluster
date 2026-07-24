#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/oci.sh"

# Verify one OCIRepository's pinned digest against the registry. Echoes a status line and
# returns non-zero ONLY on a hard failure (missing digest / unresolvable / mismatch); SKIP
# and transient-WARN return 0. Runs in its own subshell per file so the checks parallelize.
check_file() {
  local file="$1"
  local image tag expected actual tmp_output

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
    return 0
  fi

  if [[ -z "$expected" ]]; then
    echo "FAIL ${file}: missing spec.ref.digest for ${image}:${tag}"
    return 1
  fi

  tmp_output="$(mktemp)"
  if ! fetch_digest "$image" "$tag" >"$tmp_output"; then
    rm -f "$tmp_output"
    if [[ "${OCI_FETCH_DIGEST_ERROR_KIND:-}" == "transient" ]]; then
      echo "WARN ${file}: skipped digest verification for ${image}:${tag} because the registry returned a transient error"
      return 0
    fi
    if [[ "${OCI_FETCH_DIGEST_ERROR_KIND:-}" == "anonymous-private" ]]; then
      echo "SKIP ${file}: ${image}:${tag} is in a private Harbor project and this run has no registry credentials (digest presence still enforced; the push/main run verifies the match)"
      return 0
    fi
    echo "FAIL ${file}: could not resolve registry digest for ${image}:${tag}"
    return 1
  fi
  actual="$(<"$tmp_output")"
  rm -f "$tmp_output"

  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL ${file}: expected ${expected}, registry has ${actual} for ${image}:${tag}"
    return 1
  fi
  echo "OK   ${file}: ${image}:${tag}@${expected}"
  return 0
}
export -f check_file fetch_digest
export ACCEPT_HEADER

# Fan the 43-odd independent registry lookups out across workers instead of walking them
# serially (each is a token fetch + one manifest HEAD). xargs exits non-zero if ANY worker
# returned non-zero, which is exactly our aggregate FAIL signal.
status=0
find "${ROOT_DIR}/kubernetes/apps" -path '*/ocirepository.yaml' -print0 | sort -z \
  | xargs -0 -P "${OCI_VERIFY_PARALLELISM:-8}" -I{} bash -c 'check_file "$@"' _ {} \
  || status=1

exit "$status"
