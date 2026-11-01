#!/usr/bin/env bash
set -euo pipefail

TOOLING_REPOS=(semantic-release-config workflows infrastructure)
SEMVER='v[0-9]+\.[0-9]+\.[0-9]+'
SHA='[0-9a-f]{40}'

usage() {
  echo "usage: $0 <repository-dir>..." >&2
  echo "Fails when a .forgejo workflow or action references a webgrip tooling repository" >&2
  echo "(${TOOLING_REPOS[*]}) at anything but @vX.Y.Z or @<sha> # vX.Y.Z (ADR-0089)." >&2
  exit 2
}

repository_name() {
  local dir="$1" url
  if url="$(git -C "$dir" remote get-url origin 2>/dev/null < /dev/null)"; then
    url="${url%.git}"
    echo "${url##*/}"
  else
    basename "$(cd "$dir" && pwd)"
  fi
}

pinned() {
  local ref="$1" rest="$2"
  [[ "$ref" =~ ^${SEMVER}$ ]] && return 0
  [[ "$ref" =~ ^${SHA}$ && "$rest" =~ ^[[:space:]]+#[[:space:]]*${SEMVER}([[:space:]]|$) ]] && return 0
  return 1
}

scan_repository() {
  local dir="$1" self tooling file lineno line ref rest found=0
  self="$(repository_name "$dir")"
  [[ -d "$dir/.forgejo" ]] || return 0
  while IFS= read -r -d '' file; do
    lineno=0
    while IFS= read -r line || [[ -n "$line" ]]; do
      lineno=$((lineno + 1))
      [[ "$line" =~ uses:[[:space:]]*[\"\']?([^[:space:]\"\']*/)?webgrip/([a-z0-9-]+)/[^@[:space:]]*@([^[:space:]\"\']+)[\"\']?(.*)$ ]] || continue
      tooling="${BASH_REMATCH[2]}"
      ref="${BASH_REMATCH[3]}"
      rest="${BASH_REMATCH[4]}"
      [[ " ${TOOLING_REPOS[*]} " == *" ${tooling} "* ]] || continue
      [[ "$tooling" == "$self" ]] && continue
      pinned "$ref" "$rest" && continue
      echo "${file}:${lineno}: webgrip/${tooling}@${ref}${rest} is not pinned to vX.Y.Z or <sha> # vX.Y.Z"
      found=1
    done < "$file"
  done < <(find "$dir/.forgejo" -type f \( -name '*.yml' -o -name '*.yaml' \) -print0 | sort -z)
  return "$found"
}

[[ "$#" -ge 1 ]] || usage
violations=0
for dir in "$@"; do
  [[ -d "$dir" ]] || { echo "not a directory: $dir" >&2; exit 2; }
  scan_repository "$dir" || violations=1
done
exit "$violations"
