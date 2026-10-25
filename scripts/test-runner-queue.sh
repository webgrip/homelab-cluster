#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
script="$repo_root/kubernetes/apps/forgejo/runner-queue/app/runner_queue.py"
suite="$repo_root/scripts/test_runner_queue.py"
python="${PYTHON:-python3}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> unmutated runner queue must pass"
EXPORTER_SCRIPT="$script" "$python" -I "$suite" 2>"$work/clean.log" || { cat "$work/clean.log" >&2; exit 1; }

mutate() {
  name="$1"
  find="$2"
  replace="$3"
  test_name="$4"
  copy="$work/$name.py"
  "$python" -I - "$script" "$copy" "$find" "$replace" <<'PY'
import sys
source, target, find, replace = sys.argv[1:]
text = open(source).read()
if find not in text:
    sys.exit(f"mutation anchor not found: {find!r}")
open(target, "w").write(text.replace(find, replace, 1))
PY
  if EXPORTER_SCRIPT="$copy" "$python" -I "$suite" "$test_name" >"$work/$name.log" 2>&1; then
    echo "MUTATION SURVIVED: $name ($test_name passed against the mutant)" >&2
    exit 1
  fi
  echo "killed: $name by $test_name"
}

mutate running-jobs-count-as-waiting \
  'job["status"] == "waiting" and ' \
  '' \
  RunnerQueueTest.test_counts_only_waiting_jobs_of_the_owner
mutate other-owners-count \
  ' and job["owner_id"] == owner' \
  '' \
  RunnerQueueTest.test_counts_only_waiting_jobs_of_the_owner
mutate any-label-is-published \
  'if label not in PUBLISHED_LABELS:' \
  'if label is None:' \
  RunnerQueueTest.test_a_label_that_is_not_published_is_not_found_and_never_reaches_forgejo
mutate unreadable-queue-reads-as-zero \
  '            self.respond(502, {"error": "forgejo job queue unreadable"})
            return' \
  '            count = 0' \
  RunnerQueueTest.test_an_unreadable_queue_is_an_error_not_zero
mutate null-queue-crashes \
  '{"labels": label}) or []' \
  '{"labels": label})' \
  RunnerQueueTest.test_an_empty_queue_is_zero
mutate token-read-once \
  'def read_token():' \
  '@__import__("functools").cache
def read_token():' \
  RunnerQueueTest.test_a_rotated_token_is_used_without_a_restart
mutate label-not-forwarded \
  '{"labels": label}' \
  '{"labels": ""}' \
  RunnerQueueTest.test_asks_forgejo_for_the_label_with_the_scaler_token

echo "all mutations killed"
