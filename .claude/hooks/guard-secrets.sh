#!/usr/bin/env bash
# PreToolUse (Edit|Write|MultiEdit): hard-block plaintext-secret leaks.
# The *.sops.yaml edit block lives in permissions.deny (no tooling needed);
# this catches decrypted artifacts, plaintext written into sops files, and
# (best-effort) plaintext secrets via gitleaks. Exit 2 = block + tell Claude why.
set -euo pipefail
input="$(cat)"

jqx() {
  if command -v jq >/dev/null 2>&1; then jq "$@"
  elif command -v mise >/dev/null 2>&1; then mise exec -- jq "$@"
  else return 1; fi
}

file="$(printf '%s' "$input" | jqx -r '.tool_input.file_path // empty' 2>/dev/null || true)"
content="$(printf '%s' "$input" | jqx -r '.tool_input.content // .tool_input.new_string // empty' 2>/dev/null || true)"
[ -n "$file" ] || exit 0
base="$(basename "$file")"

# 1) Never create decrypted secret artifacts.
case "$base" in
  *.decrypted*|*decrypted~*)
    echo "BLOCKED: refusing to write a decrypted secret artifact ($base). Secrets live only in *.sops.yaml." >&2
    exit 2 ;;
esac

# 2) A *.sops.yaml file must contain SOPS ciphertext, never plaintext.
case "$base" in
  *.sops.yaml|*.sops.yml)
    if [ -n "$content" ] && ! printf '%s' "$content" | grep -q 'ENC\['; then
      echo "BLOCKED: $base is a SOPS file but the content isn't encrypted. Edit plaintext elsewhere, then 'sops --encrypt'." >&2
      exit 2
    fi ;;
esac

# 3) Best-effort plaintext-secret scan (skipped silently if gitleaks isn't installed).
if [ -n "$content" ]; then
  gl=""
  if command -v gitleaks >/dev/null 2>&1; then gl="gitleaks"
  elif command -v mise >/dev/null 2>&1 && mise which gitleaks >/dev/null 2>&1; then gl="mise exec -- gitleaks"; fi
  if [ -n "$gl" ]; then
    tmp="$(mktemp)"; printf '%s' "$content" > "$tmp"
    set +e; $gl detect --no-banner --no-git --redact -s "$tmp" >/dev/null 2>&1; rc=$?; set -e
    rm -f "$tmp"
    if [ "$rc" -eq 1 ]; then
      echo "BLOCKED: gitleaks flagged a likely plaintext secret in $base. Use a SOPS secret + Helm value wiring (existingSecret/envFromSecret)." >&2
      exit 2
    fi
  fi
fi
exit 0
