#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
app="$repo_root/kubernetes/apps/ai/omnigraph/brain-eval/app"
suite="$repo_root/scripts/test_omnigraph_brain_eval.py"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
failures=0

run_suite() {
  BRAIN_EVAL_APP="$1" timeout 600 python3 -W ignore "$suite" > "$2" 2>&1
}

mutate() {
  local name="$1" file="$2" from="$3" to="$4"
  local copy="$work/$name"
  cp -R "$app" "$copy"
  if ! python3 - "$copy/$file" "$from" "$to" <<'PY'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path).read()
if old not in text:
    sys.exit(f"mutation target not found: {old!r}")
open(path, "w").write(text.replace(old, new, 1))
PY
  then
    echo "FAIL mutation did not apply: $name" > "$work/$name.result"
    return
  fi
  if run_suite "$copy" "$work/$name.log"; then
    echo "FAIL mutant survived: $name" > "$work/$name.result"
  elif grep -qE "^(FAIL|ERROR): test_" "$work/$name.log"; then
    echo "ok   mutant killed: $name ($(grep -cE '^(FAIL|ERROR): test_' "$work/$name.log") tests)" > "$work/$name.result"
  else
    echo "FAIL mutant broke the suite instead of failing a test: $name" > "$work/$name.result"
  fi
}

running=0
spawn() {
  mutate "$@" &
  running=$((running + 1))
  if [ "$running" -ge 8 ]; then
    wait
    running=0
  fi
}

if run_suite "$app" "$work/unmodified.log"; then
  echo "ok   unmodified harness passes"
else
  echo "FAIL the unmodified harness fails its own suite"
  tail -20 "$work/unmodified.log"
  exit 1
fi

spawn ndcg-linear-gain brain_eval.py '(2 ** grades.get(doc, 0) - 1)' 'grades.get(doc, 0)'
spawn no-shadow-rollup brain_eval.py 'return self.artifact_to_note.get(slug, "obsidian/" + slug[len("obsidian-file/"):])' 'return slug'
spawn no-adr-rollup brain_eval.py '        return artifact

    def canonical_ranking' '        return slug

    def canonical_ranking'
spawn stale-check-off brain_eval.py 'return [item["slug"] for item in case.get("expected") or [] if item["slug"] not in self.all]' 'return []'
spawn temporal-window-off brain_eval.py '            if updated and since <= updated <= now:' '            if updated:'
spawn temporal-from-stored-query brain_eval.py '        scans["notes"] = omnigraph.inline(scan_source("Note", ["slug", "updatedAt"]), snapshot=snapshot).get("rows") or []' '        omnigraph.stored("notes_recent", {}, snapshot)
        scans["notes"] = omnigraph.inline(scan_source("Note", ["slug", "updatedAt"]), snapshot=snapshot).get("rows") or []'
spawn unpinned-legs brain_eval.py '        if snapshot:
            payload["snapshot"] = snapshot
        result = self.post(f"queries/' '        result = self.post(f"queries/'
spawn control-pair-loose brain_eval.py 'ok = results["supported"] >= 0.8 and results["unsupported"] <= 0.2' 'ok = results["supported"] >= 0.8'
spawn spend-cap-ignored brain_eval.py 'if self.cap is not None and self.total > self.cap:' 'if False:'
spawn question-logged brain_eval.py 'log("answer judged", arm=arm, case=case["id"],' 'log("answer judged", arm=arm, case=case["question"],'
spawn slugs-logged brain_eval.py 'log("retrieval scored", profile=profile,' 'log("retrieval scored", ranked=[result["ranked"] for result in results], profile=profile,'
spawn label-allowlist-off brain_eval.py '            if label_value not in allowed[label]:' '            if False:'
spawn redaction-gate-off brain_eval.py 'if not args.synthetic and os.environ.get("BRAIN_EVAL_MCP_ARGUMENTS_REDACTED") != "true":
        raise EvalError("answer mode on real cases waits' 'if False:
        raise EvalError("answer mode on real cases waits'
spawn unanswerable-scored brain_eval.py 'return case["category"] != "unanswerable" and case.get("answerable", True)' 'return True'
spawn cases-overwritten candidates.py 'if cases_dir.is_dir() and any(cases_dir.glob("*.yaml")):' 'if False:'
spawn leak-check-blind brain_eval.py '                if owner:
                    leaked |= owner' '                if False:
                    leaked |= owner'
spawn metric-precision-lost brain_eval.py 'number = format(float(value), ".15g")' 'number = format(float(value), ".6g")'
spawn e1-log-collision brain_eval.py 'log("experiment e1", **{key' 'log("experiment e1", cases=0, **{key'
spawn e1-arms-swapped brain_eval.py '        for arm, ordered in (("e1-prefixed", prefixed), ("e1-raw", raw)):' '        for arm, ordered in (("e1-prefixed", raw), ("e1-raw", raw)):'
spawn no-holdout candidates.py 'chosen.append((candidate, "holdout" if index == holdout else "dev"))' 'chosen.append((candidate, "dev"))'
spawn privacy-check-off brain_eval.py '    if status == HIDDEN_FROM_ANONYMOUS_STATUS:' '    if True:'
spawn public-repo-counted-private brain_eval.py '    if status == HIDDEN_FROM_ANONYMOUS_STATUS:' '    if status in (HIDDEN_FROM_ANONYMOUS_STATUS, READABLE_BY_ANONYMOUS_STATUS):'
spawn store-privacy-gate-off store.sh 'if [ "$(cat "$PRIVACY_VERDICT" 2> /dev/null || true)" != private ]; then' 'if false; then'
spawn publish-privacy-gate-off publish.sh 'if [ "$(cat "$WORK/privacy-publish" 2> /dev/null || true)" != private ]; then' 'if false; then'
spawn key-facts-unscanned brain_eval.py '        phrases += list(case.get("key_facts") or [])' '        pass'
spawn public-source-facts-scanned brain_eval.py '    if not sourced_from_the_public_repo(case):' '    if True:'
spawn gate-control-unpublished brain_eval.py '        push_now(args, failure)' '        pass'
spawn gate-skips-control brain_eval.py '        control = require_passing_judge(args, llm, judge_prompt, "gate", sink)' '        control = {}'
spawn unreadable-verdict-passes brain_eval.py 'UNREADABLE_VERDICT_SCORE = {"supported": 0.0, "unsupported": 1.0}' 'UNREADABLE_VERDICT_SCORE = {"supported": 1.0, "unsupported": 0.0}'
spawn gate-no-calibration-templates brain_eval.py 'run["calibration_templates_written"] = write_calibration_templates(workspace, records)' 'run["calibration_templates_written"] = 0'
spawn slugs-unscanned brain_eval.py '            for match in slugs.finditer(text):' '            for match in []:'
spawn shadow-slug-unscanned brain_eval.py '            slugs.append(OBSIDIAN_SHADOW_PREFIX + slug[len(OBSIDIAN_NOTE_PREFIX):])' '            pass'
spawn generic-slugs-scanned brain_eval.py '        if not slug.startswith(PRIVATE_SLUG_PREFIXES):' '        if not slug:'
spawn slug-boundary-off brain_eval.py 'return re.compile(rf"(?<![\w-])(?:{alternatives})(?![\w-])")' 'return re.compile(rf"(?:{alternatives})")'
spawn temporal-slugs-scanned brain_eval.py '    if is_public_case(case):
        return []
    slugs = []' '    slugs = []'
spawn guides-not-refreshed brain_eval.py '        refresh_repo_guides(workspace, args.prompts_dir)' '        pass'
spawn guides-written-once brain_eval.py 'if not path.exists() or path.read_text(encoding="utf-8") != text:' 'if not path.exists():'
spawn judge-anthropic brain_eval.py 'JUDGE_MODEL = "fireworks-deepseek-v4p1-flash"' 'JUDGE_MODEL = "claude-haiku-4-5"'
spawn judge-answer-family brain_eval.py 'JUDGE_MODEL = "fireworks-deepseek-v4p1-flash"' 'JUDGE_MODEL = "chat-default"'
spawn pool-falls-back-to-drafter brain_eval.py 'POOL_FALLBACK_MODEL = "deepseek-chat"' 'POOL_FALLBACK_MODEL = "fireworks-gpt-oss-120b"'
spawn answer-in-backup-window cronjobs.yaml '  schedule: "10 5 * * 0"
  timeZone: Etc/UTC' '  schedule: "10 5 * * 0"
  timeZone: Europe/Amsterdam'
spawn retrieval-runs-into-backup-window cronjobs.yaml 'activeDeadlineSeconds: 1200' 'activeDeadlineSeconds: 1800'
wait
for result in "$work"/*.result; do
  cat "$result"
  if grep -q '^FAIL' "$result"; then
    failures=$((failures + 1))
  fi
done

if [ "$failures" -gt 0 ]; then
  echo "$failures mutants survived"
  exit 1
fi
echo "PASS: every mutant is caught and the unmodified harness passes"
