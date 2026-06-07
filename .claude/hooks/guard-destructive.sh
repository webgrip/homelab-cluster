#!/usr/bin/env bash
# PreToolUse (Bash): hard-block direct cluster mutation. GitOps-first — change
# manifests and let Flux reconcile. Read-only ops, --dry-run, recoverable
# pod/job deletes, and the sanctioned 'task talos:apply-node-safe' are allowed.
set -euo pipefail
input="$(cat)"

jqx() {
  if command -v jq >/dev/null 2>&1; then jq "$@"
  elif command -v mise >/dev/null 2>&1; then mise exec -- jq "$@"
  else return 1; fi
}

cmd="$(printf '%s' "$input" | jqx -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -n "$cmd" ] || exit 0
c="$(printf '%s' "$cmd" | tr '\n' ' ' | tr -s ' ')"

deny() { echo "BLOCKED (GitOps policy): $1 Make the change in Git and let Flux reconcile, or run it yourself outside Claude." >&2; exit 2; }

# Previews are always fine.
case "$c" in *--dry-run*) exit 0;; esac

has() { printf '%s' "$c" | grep -qE "$1"; }

# kubectl: block mutations; allow get/describe/logs and delete of recoverable pod/job.
if has '(^|[;&|[:space:]])kubectl[[:space:]]'; then
  has 'kubectl[[:space:]]+(apply|replace|patch|edit|scale|cordon|drain|uncordon|taint|annotate|label|set[[:space:]]|create[[:space:]]+(-f|namespace|secret)|rollout[[:space:]]+(restart|undo))' \
    && deny "direct kubectl mutation."
  has 'kubectl[[:space:]]+delete[[:space:]]+(namespace|ns|pvc|persistentvolumeclaim|pv|persistentvolume|node|deployment|deploy|statefulset|sts|daemonset|ds|secret|helmrelease|hr|kustomization|crd|customresourcedefinition|clusterrole|clusterrolebinding|gateway|httproute|-f)' \
    && deny "kubectl delete of a protected resource type."
fi

has 'helm[[:space:]]+(install|upgrade|uninstall|delete|rollback)[[:space:]]' && deny "direct helm release mutation."
has 'flux[[:space:]]+(delete|uninstall)[[:space:]]' && deny "flux delete/uninstall."
has 'talosctl[[:space:]].*(reset|apply-config|bootstrap|wipe|upgrade(-k8s)?([[:space:]]|$)|edit[[:space:]]+machineconfig)' \
  && deny "destructive talosctl op — use 'task talos:apply-node-safe IP=<ip> HOSTNAME=<name>'."
# Recursive remove of catastrophic targets only (root, home, parent, glob) — not arbitrary abs paths.
has 'rm[[:space:]]+-[a-zA-Z]*[rf][a-zA-Z]*[[:space:]]+(-[a-zA-Z-]+[[:space:]]+)*(/|~|\$HOME|\.\.|\*)([[:space:]]|$)' \
  && deny "recursive remove of a catastrophic path (/, ~, .., \$HOME, or *)."

exit 0
