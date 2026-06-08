#!/usr/bin/env bash
# Nightly cluster-health digest, run LOCALLY (the cluster MCP is LAN-only, so this can't
# be a remote routine). Runs a headless read-only audit via `claude -p` and posts the
# result to a Discord webhook. Designed for a systemd user timer — see this dir's README.
#
# Safety: runs with --dangerously-skip-permissions so cron doesn't hang on a prompt, BUT
# the PreToolUse guard-destructive.sh hook still fires and blocks any cluster mutation.
# The prompt is read-only; the hook is the backstop.
set -uo pipefail

REPO="${REPO:-/home/ryan/projects/webgrip/homelab-cluster}"
cd "$REPO" || { echo "repo not found: $REPO" >&2; exit 1; }

# Pull machine-local env (DISCORD_WEBHOOK_URL etc) from .mise.local.toml.
eval "$(mise env -s bash 2>/dev/null)" || true
: "${DISCORD_WEBHOOK_URL:?set DISCORD_WEBHOOK_URL in .mise.local.toml}"

PROMPT='Produce a concise READ-ONLY homelab cluster health digest. Check: Flux Kustomizations/HelmReleases that are not Ready or are suspended; node readiness/pressure; non-running pods (CrashLoopBackOff/Pending/ImagePullBackOff); recent Warning events; and Longhorn/Garage capacity if relevant. Output short markdown: an overall verdict line (🟢 healthy / 🟡 degraded / 🔴 broken) then bullets for anything needing attention with the resource/file to look at. Do NOT mutate anything. Keep it under 1500 characters.'

OUT="$(timeout 600 mise exec -- claude -p "$PROMPT" --dangerously-skip-permissions 2>&1)" \
  || OUT="⚠️ cluster-health run failed (exit $?):
$(printf '%s' "$OUT" | tail -c 600)"

HEADER="**🏠 Nightly homelab health** — $(date '+%Y-%m-%d %H:%M %Z')"
BODY="$(printf '%s\n\n%s' "$HEADER" "$OUT" | head -c 1900)"

payload="$(mise exec -- jq -nc --arg c "$BODY" '{content:$c, flags:4096}')"
code="$(curl -sS -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "$payload" "$DISCORD_WEBHOOK_URL")"
echo "discord POST -> $code"
[ "$code" = "204" ] || [ "$code" = "200" ]
