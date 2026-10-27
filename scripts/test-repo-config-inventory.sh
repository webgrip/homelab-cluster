#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
inventory="$repo_root/kubernetes/apps/repo-config/repo-config/inventory/repo_config_inventory.py"
suite="$repo_root/scripts/test_repo_config_inventory.py"
python="${PYTHON:-python3}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> unmutated inventory must pass"
INVENTORY_SCRIPT="$inventory" "$python" "$suite"

mutate() {
  name="$1"
  test_name="$2"
  shift 2
  copy="$work/$name.py"
  "$python" - "$inventory" "$copy" "$@" <<'PY'
import sys
source, target, *pairs = sys.argv[1:]
text = open(source).read()
for find, replace in zip(pairs[0::2], pairs[1::2]):
    if find not in text:
        sys.exit(f"mutation anchor not found: {find!r}")
    text = text.replace(find, replace, 1)
open(target, "w").write(text)
PY
  if INVENTORY_SCRIPT="$copy" "$python" "$suite" "InventoryTest.$test_name" >"$work/$name.log" 2>&1; then
    echo "MUTATION SURVIVED: $name ($test_name passed against the mutant)" >&2
    exit 1
  fi
  echo "killed: $name by $test_name"
}

mutate unmodelled-never-flagged test_unmodelled_private_repository_is_reported \
  '1 if name in missing else 0' \
  '0'
mutate everything-flagged test_fully_modelled_org_passes_and_reports_zero \
  '1 if name in missing else 0' \
  '1'
mutate archived-counted test_archived_and_mirrored_repositories_are_not_counted \
  'if not repository.get("archived") and not repository.get("mirror"))' \
  'if not repository.get("mirror"))'
mutate mirrors-counted test_archived_and_mirrored_repositories_are_not_counted \
  'if not repository.get("archived") and not repository.get("mirror"))' \
  'if not repository.get("archived"))'
mutate first-page-only test_pages_are_read_until_an_empty_page \
  '        repositories.extend(batch)
    raise' \
  '        repositories.extend(batch)
        return repositories
    raise'
mutate anonymous-read test_unmodelled_private_repository_is_reported \
  ', "Authorization": f"token {token}"}' \
  '}'
mutate absent-token-tolerated test_absent_token_fails_without_reading_anonymously \
  '    if not token:
        raise' \
  '    if False:
        raise'
mutate private-blindness-tolerated test_token_blind_to_private_repositories_fails \
  'if expected_private and not visible_private:' \
  'if False:'
mutate forgejo-error-swallowed test_forgejo_error_fails_without_a_success_timestamp \
  'raise InventoryFailure(f"Forgejo GET {path} page {page} returned {error.code}") from None' \
  'return repositories'
mutate empty-model-tolerated test_empty_model_fails \
  '    if not entries:
        raise' \
  '    if False:
        raise'
mutate push-rejection-ignored test_rejected_metrics_push_fails_the_run \
  'if status >= 300:' \
  'if False:'
mutate archived-model-entry-dropped test_model_parser_matches_yaml_on_the_real_model \
  'return {key: entry for key, entry in entries.items() if entry["forge"] == "forgejo"}' \
  'return {key: entry for key, entry in entries.items() if entry["forge"] == "forgejo" and not entry["archived"]}'
mutate private-setting-unparsed test_model_parser_matches_yaml_on_the_real_model \
  'in ("archived", "private"):' \
  'in ("archived",):'

echo "all mutations killed"
