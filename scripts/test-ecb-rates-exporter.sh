#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
script="$repo_root/kubernetes/apps/observability/ecb-rates-exporter/app/ecb_rates_exporter.py"
suite="$repo_root/scripts/test_ecb_rates_exporter.py"
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

mutate inverted-rate \
  'float(child.get("rate"))' \
  '1 / float(child.get("rate"))' \
  ExporterTest.test_metrics_carry_units_per_euro
mutate empty-cube-accepted \
  '            if not rates:
                break' \
  '            pass' \
  ParseTest.test_document_without_rates_is_an_error
mutate failure-drops-rates \
  'snapshot.refresh_failures += 1' \
  'snapshot.refresh_failures += 1; snapshot.rates = {}' \
  ExporterTest.test_failed_fetch_keeps_the_last_good_rates_and_counts_a_failure
mutate local-day \
  '.replace(tzinfo=timezone.utc)' \
  '' \
  ParseTest.test_reads_the_publication_day_as_utc_midnight

echo "all mutations killed"
