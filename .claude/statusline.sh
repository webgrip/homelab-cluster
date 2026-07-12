#!/usr/bin/env bash
# Claude Code statusline for the homelab cluster.
# Design: render INSTANTLY. Local bits (model / git / context%) are computed inline;
# cluster health is read from a short-lived cache that a detached background job
# refreshes, so we never block the prompt on a (LAN-only, sometimes-unreachable) API.
set -uo pipefail
input="$(cat)"
JQ() { command -v jq >/dev/null 2>&1 && jq "$@" || mise exec -- jq "$@"; }
# GNU timeout is absent on stock macOS; kubectl's --request-timeout is the real bound
TMO="$(command -v timeout || command -v gtimeout || true)"
j() { printf '%s' "$input" | JQ -r "$1" 2>/dev/null; }

# ── ANSI ──────────────────────────────────────────────────────────────────────
d=$'\033[2m'; b=$'\033[1m'; r=$'\033[0m'
red=$'\033[31m'; grn=$'\033[32m'; ylw=$'\033[33m'; cyn=$'\033[36m'; mag=$'\033[35m'

model="$(j '.model.display_name')"
cwd="$(j '.workspace.current_dir // .cwd')"
[ -n "$cwd" ] && cd "$cwd" 2>/dev/null || true
ctx="$(j '.context_window.used_percentage // empty')"

# ── git ───────────────────────────────────────────────────────────────────────
gitseg=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  br="$(git branch --show-current 2>/dev/null)"
  if git diff --quiet --ignore-submodules 2>/dev/null && git diff --cached --quiet --ignore-submodules 2>/dev/null; then
    gitseg="${grn}${br}${r}"
  else
    gitseg="${ylw}${br}*${r}"
  fi
fi

# ── kube context (cheap: parse kubeconfig, no API call) ────────────────────────
kctx=""
kcfg="${KUBECONFIG:-$cwd/kubeconfig}"
[ -f "$kcfg" ] && kctx="$(sed -n 's/^current-context:[[:space:]]*//p' "$kcfg" | head -1 | tr -d '"')"

# ── flux health (from cache; background-refresh if stale) ──────────────────────
cache="${TMPDIR:-/tmp}/claude-flux-$(printf '%s' "$cwd" | cksum | cut -d' ' -f1)"
lock="${cache}.lock"
now="$(date +%s)"
age=99999
[ -f "$cache" ] && age=$(( now - $(stat -c %Y "$cache" 2>/dev/null || stat -f %m "$cache" 2>/dev/null || echo 0) ))
if [ "$age" -gt 30 ] && mkdir "$lock" 2>/dev/null; then
  ( trap 'rmdir "$lock" 2>/dev/null' EXIT
    n="$(${TMO:+$TMO 12} mise exec -- kubectl get kustomizations,helmreleases -A -o json --request-timeout=10s 2>/dev/null \
         | JQ '[.items[]|select(any(.status.conditions[]?; .type=="Ready" and .status!="True"))]|length' 2>/dev/null)"
    [ -n "$n" ] && printf '%s' "$n" > "$cache" || printf '?' > "$cache"
  ) >/dev/null 2>&1 &
fi
flux=""
if [ -f "$cache" ]; then
  n="$(cat "$cache" 2>/dev/null)"
  case "$n" in
    0)     flux="${grn}flux✓${r}" ;;
    \?|"") flux="${d}flux?${r}" ;;
    *)     flux="${red}flux⚠${n}${r}" ;;
  esac
fi

# ── context% ───────────────────────────────────────────────────────────────────
ctxseg=""
if [ -n "$ctx" ]; then
  p="${ctx%.*}"
  col="$grn"; [ "$p" -ge 60 ] 2>/dev/null && col="$ylw"; [ "$p" -ge 85 ] 2>/dev/null && col="$red"
  ctxseg="${col}${p}%${r}"
fi

# ── assemble ───────────────────────────────────────────────────────────────────
out="${mag}${b}${model}${r}"
[ -n "$gitseg" ] && out="$out ${d}|${r} $gitseg"
[ -n "$kctx" ]   && out="$out ${d}|${r} ${cyn}⎈${kctx}${r}"
[ -n "$flux" ]   && out="$out ${d}|${r} $flux"
[ -n "$ctxseg" ] && out="$out ${d}|${r} ${ctxseg}${d}ctx${r}"
printf '%s' "$out"
