#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
bridge="$repo_root/kubernetes/apps/github-config/secrets-bridge/app/github_secrets_bridge.py"
suite="$repo_root/scripts/test_github_secrets_bridge.py"
python="${PYTHON:-python3}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> unmutated bridge must pass"
BRIDGE_SCRIPT="$bridge" "$python" "$suite"

mutate() {
  name="$1"
  find="$2"
  replace="$3"
  test_name="$4"
  copy="$work/$name.py"
  "$python" - "$bridge" "$copy" "$find" "$replace" <<'PY'
import sys
source, target, find, replace = sys.argv[1:]
text = open(source).read()
if find not in text:
    sys.exit(f"mutation anchor not found: {find!r}")
open(target, "w").write(text.replace(find, replace, 1))
PY
  if BRIDGE_SCRIPT="$copy" "$python" "$suite" "BridgeTest.$test_name" >"$work/$name.log" 2>&1; then
    echo "MUTATION SURVIVED: $name ($test_name passed against the mutant)" >&2
    exit 1
  fi
  echo "killed: $name by $test_name"
}

mutate always-write \
  "if sync_is_current(state, fingerprint, metadata):" \
  "if False:" \
  test_unchanged_source_is_not_rewritten
mutate ignore-source-change \
  'state.get("source_fingerprint") == fingerprint
            and ' \
  '' \
  test_changed_source_is_rewritten
mutate ignore-github-drift \
  '
            and state.get("github_updated_at") == metadata.get("updated_at"))' \
  ')' \
  test_secret_overwritten_outside_the_bridge_is_restored
mutate value-in-state \
  '{"source_fingerprint": fingerprint,' \
  '{"source_fingerprint": source,' \
  test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint
mutate log-without-redaction \
  '    forbid_in_output(value)
    if not value:' \
  '    log(f"source is {value}")
    if not value:' \
  test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint
mutate log-installation-token-unredacted \
  '        self.token = body["token"]
        forbid_in_output(self.token)' \
  '        self.token = body["token"]
        log(f"token {self.token}")' \
  test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint
mutate absent-exits-nonzero \
  '        return 0

    state_store' \
  '        return 1

    state_store' \
  test_absent_app_credentials_exit_zero_and_touch_nothing_on_github
mutate denial-read-as-absent \
  'raise BridgeFailure(f"OpenBao denied reading secret/{path} (403)")' \
  'raise AppCredentialsAbsent("denied")' \
  test_openbao_denial_fails_instead_of_reading_as_absent
mutate token-not-scoped \
  'body={"repositories": [self.repository], "permissions": {"secrets": "write"}})' \
  'body={})' \
  test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint
mutate broken-sealed-box-nonce \
  'digest_size=24).digest()' \
  'digest_size=24).digest()[::-1]' \
  test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint

echo "==> redaction holds when a log line names the source (must still pass)"
redacted="$work/redacted.py"
"$python" - "$bridge" "$redacted" <<'PY'
import sys
source, target = sys.argv[1:]
text = open(source).read()
anchor = "    forbid_in_output(value)\n    if not value:"
assert anchor in text
open(target, "w").write(text.replace(anchor, "    forbid_in_output(value)\n    log(f\"source is {value}\")\n    if not value:", 1))
PY
BRIDGE_SCRIPT="$redacted" "$python" "$suite" BridgeTest.test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint
echo "all mutations killed; redaction verified"
