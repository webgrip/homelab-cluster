#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
bridge="$repo_root/kubernetes/apps/github-secrets-bridge/github-secrets-bridge/app/github_secrets_bridge.py"
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
    if not value:
        raise BridgeFailure(f"source value at' \
  '    log(f"source is {value}")
    if not value:
        raise BridgeFailure(f"source value at' \
  test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint
mutate log-openbao-source-without-redaction \
  '    forbid_in_output(value)
    if not value:
        raise BridgeFailure(f"source secret/' \
  '    log(f"source is {value}")
    if not value:
        raise BridgeFailure(f"source secret/' \
  test_every_target_is_written_through_its_own_owner_app_token_and_state
mutate log-installation-token-unredacted \
  '        self.token = body["token"]
        forbid_in_output(self.token)' \
  '        self.token = body["token"]
        log(f"token {self.token}")' \
  test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint
mutate absent-exits-nonzero \
  '"run_success_timestamp_seconds": int(time.time())})
        return

    try:' \
  '"run_success_timestamp_seconds": int(time.time())})
        raise BridgeFailure("absent")

    try:' \
  test_absent_app_credentials_exit_zero_and_touch_nothing_on_github
mutate absent-source-exits-nonzero \
  'raise SourceAbsent(str(absent)) from None' \
  'raise BridgeFailure(str(absent)) from None' \
  test_absent_openbao_source_exits_zero_and_writes_nothing
mutate source-denial-read-as-absent \
  '    except OpenBaoSecretAbsent as absent:
        raise SourceAbsent' \
  '    except (OpenBaoSecretAbsent, BridgeFailure) as absent:
        raise SourceAbsent' \
  test_openbao_denial_on_a_source_fails_instead_of_reading_as_absent
mutate wrong-source-property \
  'value = str(data.get(field) or "").strip()' \
  'value = str(data.get("CLOUDFLARE_API_TOKEN") or "").strip()' \
  test_every_target_is_written_through_its_own_owner_app_token_and_state
mutate missing-property-skipped \
  '        raise BridgeFailure(f"source secret/{path} has no value under {field}")' \
  '        raise SourceAbsent(f"source secret/{path} has no value under {field}")' \
  test_openbao_source_without_its_property_fails
mutate one-shared-state \
  'spec["state_configmap"],' \
  '"github-secrets-bridge-state",' \
  test_every_target_is_written_through_its_own_owner_app_token_and_state
mutate first-failure-stops-the-run \
  '            log(f"bridge failed for {target}: {failure}")
            failed.append(target)' \
  '            log(f"bridge failed for {target}: {failure}")
            return 1' \
  test_one_failing_target_does_not_stop_the_others
mutate failure-exits-zero \
  '        return 1
    return 0' \
  '        return 0
    return 0' \
  test_one_failing_target_does_not_stop_the_others
mutate denial-read-as-absent \
  'raise BridgeFailure(f"OpenBao denied reading secret/{path} (403)")' \
  'raise OpenBaoSecretAbsent("denied")' \
  test_openbao_denial_fails_instead_of_reading_as_absent
mutate token-not-scoped \
  'body={"repositories": [self.repository], "permissions": {"secrets": "write"}})' \
  'body={})' \
  test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint
mutate broken-sealed-box-nonce \
  'digest_size=24).digest()' \
  'digest_size=24).digest()[::-1]' \
  test_first_run_writes_the_sealed_source_and_records_only_a_fingerprint

manifest_mutate() {
  name="$1"
  file="$2"
  find="$3"
  test_name="$4"
  copy="$work/manifest-$name"
  mkdir -p "$copy"
  cp "$app_dir"/* "$copy/"
  cp "$policy" "$copy/policy.hcl"
  "$python" - "$copy/$file" "$find" <<'PY'
import sys
path, find = sys.argv[1:]
text = open(path).read()
if find not in text:
    sys.exit(f"mutation anchor not found: {find!r}")
open(path, "w").write(text.replace(find, "", 1))
PY
  if BRIDGE_APP_DIR="$copy" BRIDGE_POLICY="$copy/policy.hcl" "$python" "$suite" "ManifestTest.$test_name" >"$work/manifest-$name.log" 2>&1; then
    echo "MUTATION SURVIVED: manifest $name ($test_name passed against the mutant)" >&2
    exit 1
  fi
  echo "killed: manifest $name by $test_name"
}

app_dir="$repo_root/kubernetes/apps/github-secrets-bridge/github-secrets-bridge/app"
policy="$repo_root/kubernetes/apps/security/openbao/bootstrap/github-secrets-bridge.hcl"
manifest_mutate state-not-in-rbac rbac.yaml '      - "github-secrets-bridge-state-unfold-cloudflare-dns-read-token"
' test_every_state_configmap_is_writable_by_the_bridge
manifest_mutate source-not-in-policy policy.hcl 'path "secret/data/cloudflare/deploy" {
  capabilities = ["read"]
}
' test_every_openbao_path_the_targets_read_is_granted
manifest_mutate targets-not-shipped kustomization.yaml '      - targets.json=./targets.json
' test_the_cronjob_reads_the_targets_file_the_kustomization_ships

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
