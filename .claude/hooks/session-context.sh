#!/usr/bin/env bash
# SessionStart hook: inject a live snapshot of cluster + repo state so every session
# opens cluster-aware instead of having to ask. stdout (exit 0) becomes additionalContext.
# Strictly read-only and time-boxed — degrades to a short note if the LAN/API is unreachable.
set -uo pipefail
# timeout(1) is a GNU-ism absent on stock macOS — wrapping made every probe exit 127, so the
# hook always claimed the API was unreachable. kubectl's --request-timeout bounds the calls
# instead; timeout stays as an outer guard where it exists.
TMO="$(command -v timeout || command -v gtimeout || true)"
K() { ${TMO:+$TMO 8} mise exec -- kubectl --request-timeout=7s "$@" 2>/dev/null; }

echo "## Live homelab snapshot (SessionStart hook, $(date -u '+%Y-%m-%dT%H:%MZ'))"
echo

# ── repo state ─────────────────────────────────────────────────────────────────
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "**Git:** branch \`$(git branch --show-current 2>/dev/null)\`, $(git status --porcelain 2>/dev/null | wc -l | tr -d ' ') uncommitted file(s); last: $(git log -1 --format='%h %s' 2>/dev/null)"
fi

# ── reachability probe ─────────────────────────────────────────────────────────
if ! K version >/dev/null 2>&1 && ! K get --raw='/readyz' >/dev/null 2>&1; then
  echo
  echo "**Cluster:** API not reachable from here (off-LAN, or VIP 10.0.0.25 down). Skipping live state — use the read-only \`kubernetes\`/\`grafana\` MCP if needed."
  exit 0
fi

# ── flux: not-ready + suspended ────────────────────────────────────────────────
notready="$(K get kustomizations,helmreleases -A -o json | mise exec -- jq -r '
  .items[] | select(any(.status.conditions[]?; .type=="Ready" and .status!="True"))
  | "  - \(.kind)/\(.metadata.namespace)/\(.metadata.name): \((.status.conditions[]?|select(.type=="Ready")|.message) // "not ready")"' 2>/dev/null)"
suspended="$(K get kustomizations,helmreleases -A -o json | mise exec -- jq -r '
  .items[] | select(.spec.suspend==true) | "  - \(.kind)/\(.metadata.namespace)/\(.metadata.name)"' 2>/dev/null)"

echo
if [ -n "$notready" ]; then echo "**Flux — NOT READY:**"; echo "$notready"; else echo "**Flux:** all Kustomizations/HelmReleases Ready ✓"; fi
[ -n "$suspended" ] && { echo "**Flux — SUSPENDED (won't reconcile):**"; echo "$suspended"; }

# ── nodes ──────────────────────────────────────────────────────────────────────
nodes="$(K get nodes --no-headers -o custom-columns=N:.metadata.name,S:.status.conditions[-1].type 2>/dev/null | awk '$2!="Ready"{print "  - "$1" "$2}')"
[ -n "$nodes" ] && { echo "**Nodes NOT Ready:**"; echo "$nodes"; }

exit 0
