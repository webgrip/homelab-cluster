#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
script="$repo_root/kubernetes/apps/observability/grafana-panel-health/app/panel_health_exporter.py"
suite="$repo_root/scripts/test_grafana_panel_health_exporter.py"
python="${PYTHON:-python3}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> unmutated exporter must pass"
EXPORTER_SCRIPT="$script" "$python" "$suite" 2>"$work/clean.log" || { cat "$work/clean.log" >&2; exit 1; }

mutate() {
  name="$1"
  find="$2"
  replace="$3"
  test_name="$4"
  copy="$work/$name.py"
  "$python" - "$script" "$copy" "$find" "$replace" <<'PY'
import sys
source, target, find, replace = sys.argv[1:]
text = open(source).read()
if find not in text:
    sys.exit(f"mutation anchor not found: {find!r}")
open(target, "w").write(text.replace(find, replace, 1))
PY
  if EXPORTER_SCRIPT="$copy" "$python" "$suite" "$test_name" >"$work/$name.log" 2>&1; then
    echo "MUTATION SURVIVED: $name ($test_name passed against the mutant)" >&2
    exit 1
  fi
  echo "killed: $name by $test_name"
}

mutate skip-collapsed-rows \
  'yield from walk_panels(panel.get("panels"))' \
  'pass' \
  ClassificationTest.test_panel_inside_a_collapsed_row_is_checked_and_reads_empty
mutate errors-read-as-empty \
  'return "error", "; ".join(errors)[:300]' \
  'return "empty", ""' \
  ClassificationTest.test_query_error_reads_as_error_with_its_message
mutate empty-frames-read-as-data \
  'return any(column for column in values if column)' \
  'return True' \
  ClassificationTest.test_panel_inside_a_collapsed_row_is_checked_and_reads_empty
mutate every-no-value-is-expected \
  'return isinstance(no_value, str) and no_value.strip().lower() not in GENERIC_NO_VALUE' \
  'return isinstance(no_value, str)' \
  ClassificationTest.test_specific_no_value_text_marks_empty_as_expected_and_generic_does_not
mutate no-variable-substitution \
  'query = substitute(copy.deepcopy(target), variables)' \
  'query = copy.deepcopy(target)' \
  QueryShapeTest.test_variables_are_substituted_before_querying
mutate all-ignores-allvalue \
  'current = variable.get("allValue") or ".*"
            else:' \
  'current = ".*"
            else:' \
  QueryShapeTest.test_variables_are_substituted_before_querying
mutate panel-time-override-ignored \
  'start = f"now-{panel['"'"'timeFrom'"'"']}"' \
  'pass' \
  QueryShapeTest.test_dashboard_time_range_is_used_and_panel_time_override_wins
mutate rejected-token-reads-as-no-panels \
  'raise Unauthorized(f"{path} returned {error.code}") from error' \
  'return []' \
  ExporterTest.test_rejected_token_counts_a_failure_instead_of_reporting_no_panels

echo "all mutations killed"
