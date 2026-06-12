#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit): validate edited Kubernetes manifests.
# yamllint + kubeconform (with the datreeio CRDs-catalog for Flux/CRDs).
# Both are optional — if not installed the check is skipped. Exit 2 feeds
# failures back to Claude to fix. Add kubeconform/yamllint to .mise.toml to enable.
set -euo pipefail
input="$(cat)"

jqx() {
  if command -v jq >/dev/null 2>&1; then jq "$@"
  elif command -v mise >/dev/null 2>&1; then mise exec -- jq "$@"
  else return 1; fi
}
resolve() {
  if command -v "$1" >/dev/null 2>&1; then echo "$1"
  elif command -v mise >/dev/null 2>&1 && mise which "$1" >/dev/null 2>&1; then echo "mise exec -- $1"; fi
}

file="$(printf '%s' "$input" | jqx -r '.tool_input.file_path // empty' 2>/dev/null || true)"
[ -n "$file" ] || exit 0
case "$file" in *kubernetes/*.yaml|*kubernetes/*.yml) ;; *) exit 0;; esac
# Authentik blueprints are configMapGenerator *data* (no kind:), not standalone
# k8s manifests, so kubeconform's strict parse always fails on them — skip.
case "$file" in */authentik/app/blueprints/*) exit 0;; esac
[ -f "$file" ] || exit 0

problems=""
yl="$(resolve yamllint || true)"
if [ -n "$yl" ]; then
  out="$($yl -d relaxed "$file" 2>&1)" || problems+="[yamllint]
$out
"
fi
kc="$(resolve kubeconform || true)"
if [ -n "$kc" ]; then
  out="$($kc -strict -ignore-missing-schemas \
    -schema-location default \
    -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
    "$file" 2>&1)" || problems+="[kubeconform]
$out
"
fi

if [ -n "$problems" ]; then
  printf 'Manifest validation failed for %s:\n%s\nPlease fix before continuing.\n' "$file" "$problems" >&2
  exit 2
fi
exit 0
