#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
configmap="$repo_root/kubernetes/apps/ai/litellm/app/litellm-runtime-patches.configmap.yaml"
suite="$repo_root/scripts/test_litellm_runtime_patches.py"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
failures=0

if [ "${1:-}" = "--pinned-image" ]; then
  LITELLM_PINNED_IMAGE="${2:-$(python3 "$suite" --print-pinned-image)}"
  export LITELLM_PINNED_IMAGE
  docker image inspect "$LITELLM_PINNED_IMAGE" > /dev/null 2>&1 || docker pull -q "$LITELLM_PINNED_IMAGE" > /dev/null
  echo "probing the pinned image $LITELLM_PINNED_IMAGE"
fi

run_suite() {
  LITELLM_RUNTIME_PATCHES="$1" python3 -W ignore "$suite" > "$2" 2>&1
}

mutate() {
  local name="$1" from="$2" to="$3"
  local copy="$work/$name.yaml"
  if ! python3 - "$configmap" "$copy" "$from" "$to" <<'PY'
import sys
source, target, old, new = sys.argv[1:5]
text = open(source).read()
if old not in text:
    sys.exit(f"mutation target not found: {old!r}")
open(target, "w").write(text.replace(old, new, 1))
PY
  then
    echo "FAIL mutation did not apply: $name"
    failures=$((failures + 1))
    return
  fi
  if run_suite "$copy" "$work/$name.log"; then
    echo "FAIL mutant survived: $name"
    failures=$((failures + 1))
  elif grep -qE "^(FAIL|ERROR): test_" "$work/$name.log"; then
    echo "ok   mutant killed: $name ($(grep -cE '^(FAIL|ERROR): test_' "$work/$name.log") tests)"
  else
    echo "FAIL mutant broke the suite instead of failing a test: $name"
    tail -5 "$work/$name.log"
    failures=$((failures + 1))
  fi
}

if run_suite "$configmap" "$work/unmodified.log"; then
  echo "ok   the deployed patches pass ($(grep -oE 'Ran [0-9]+ tests' "$work/unmodified.log"), $(grep -oE 'skipped=[0-9]+' "$work/unmodified.log" || echo 'none skipped'))"
else
  echo "FAIL the deployed patches fail their own suite"
  tail -30 "$work/unmodified.log"
  exit 1
fi

mutate registration-off '    sys.meta_path.insert(0, RedactMcpArgumentsOnImport())' '    RedactMcpArgumentsOnImport()'
mutate standard-logging-unpatched '        STANDARD_LOGGING_MODULE: _redact_standard_logging_metadata,
' ''
mutate spend-logs-unpatched '        SPEND_TRACKING_MODULE: _redact_spend_logs_metadata,
' ''
mutate arguments-kept '        redacted["arguments"] = dict(MCP_TOOL_CALL_REDACTED)
' ''
mutate result-kept '            redacted["result"] = dict(MCP_TOOL_CALL_REDACTED)' '            pass'
mutate live-call-rewritten '        redacted = dict(tool_call)' '        redacted = tool_call'

if [ "$failures" -gt 0 ]; then
  echo "$failures mutation check(s) failed"
  exit 1
fi
echo "every mutant was killed"
