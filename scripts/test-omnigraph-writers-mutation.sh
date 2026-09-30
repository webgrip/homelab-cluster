#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
omnigraph=kubernetes/apps/ai/omnigraph
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
wrong=0

fresh() {
  rm -rf "${work:?}/tree"
  mkdir -p "$work/tree/scripts" "$work/tree/$omnigraph/app/bundle"
  cp "$root"/scripts/test_omnigraph_{embed_step,forge_import,vault_import}.py "$work/tree/scripts/"
  for part in embed-step forge-import vault-import; do
    mkdir -p "$work/tree/$omnigraph/$part"
    cp -r "$root/$omnigraph/$part/app" "$work/tree/$omnigraph/$part/"
  done
  cp "$root/$omnigraph/app/bundle/brain.pg" "$work/tree/$omnigraph/app/bundle/"
}

mutate() {
  python3 - "$work/tree/$omnigraph/$1" "$2" "$3" <<'PY'
import sys
from pathlib import Path
path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
if old not in text:
    sys.exit(f"mutation anchor not found in {path.name}: {old}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
PY
}

expect() {
  local want=$1 suite=$2 label=$3 rc
  python3 "$work/tree/scripts/test_omnigraph_$suite.py" > "$work/out" 2>&1
  rc=$?
  if { [ "$want" = pass ] && [ $rc -eq 0 ]; } || { [ "$want" = fail ] && [ $rc -ne 0 ] && grep -qE "^(FAIL|ERROR):" "$work/out"; }; then
    echo "ok   $label ($want)"
  else
    echo "WRONG $label: wanted $want, exit $rc"
    tail -20 "$work/out"
    wrong=1
  fi
}

step=embed-step/app/embed_step.py
write=embed-step/app/omnigraph_write.sh
forge=forge-import/app/forge_import.py
vault=vault-import/app/vault_import.py

fresh
expect pass embed_step "unmodified embed step"
expect pass forge_import "unmodified forge importer"
expect pass vault_import "unmodified vault importer"

fresh; mutate $step 'trimmed = (value or "").strip(self.trim)' 'trimmed = (value or "").strip()'
expect fail embed_step "embed text trimmed with Python's white space set"

fresh; mutate $step '    if normalise:' '    if False:'
expect fail embed_step "vectors stored without L2 normalisation"

fresh; mutate $step 'SIGNIFICANT_DIGITS = 8' 'SIGNIFICANT_DIGITS = 17'
expect fail embed_step "vectors written at full precision"

fresh; mutate $step 'BATCH_SIZE = 4' 'BATCH_SIZE = 16'
expect fail embed_step "batches larger than 4"

fresh; mutate $step 'kept = [row for index, row in enumerate(rows) if index in filled]' 'kept = rows'
expect fail embed_step "heal rows loaded without a vector"

fresh; mutate $step 'for line in text.split("\n") if line.strip()' 'for line in text.splitlines() if line.strip()'
expect fail embed_step "JSONL split on Unicode line breaks"

fresh; mutate $step '        if owed > 0:' '        if False:'
expect fail embed_step "embedding not paced"

fresh; mutate $step '        if self.clock() >= self.deadline:' '        if False:'
expect fail embed_step "deadline ignored"

fresh; mutate $step '                self.outcome.reason = str(error)
                break' '                raise'
expect fail embed_step "a LiteLLM failure fails the import"

fresh; mutate $write '[ "$omnigraph_write_failure" != read_set_conflict ]' '[ "$omnigraph_write_failure" = recovery_required ]'
expect fail embed_step "key_conflict retried"

fresh; mutate $write '[ "$omnigraph_write_failure" != read_set_conflict ]' '[ "$omnigraph_write_failure" != never ]'
expect fail embed_step "read_set_conflict not retried"

fresh; mutate $forge 'if current is not None and current["text"] == text and current["chunk_index"] == index:' 'if False:'
expect fail forge_import "forge rewrites unchanged chunks"

fresh; mutate $forge 'chosen = candidates[:HEAL_ROWS_PER_RUN]' 'chosen = []'
expect fail forge_import "forge heal disabled"

fresh; mutate $forge 'chosen = candidates[:HEAL_ROWS_PER_RUN]' 'chosen = candidates'
expect fail forge_import "forge heal cap ignored"

fresh; mutate $forge 'if pid not in graph.passage_vectors and pid not in touched_passages:' 'if pid not in graph.passage_vectors:'
expect fail forge_import "forge heals rows it deletes or rewrites"

fresh; mutate $forge 'VECTOR_ALLOWANCE_BYTES = 384 * 16' 'VECTOR_ALLOWANCE_BYTES = 0'
expect fail forge_import "forge load files ignore the vector size"

fresh; mutate $vault "group = [f'delete Passage where @id = \"{pid}\"' for pid in sorted(graph.passages.get(shadow, {}))]" "group = [f'delete Passage where @id = \"{pid}\"' for pid in sorted(graph.passages.get(shadow, {}))[1:]]"
expect fail vault_import "vault prune misses a chunk"

fresh; mutate $vault '    if note is not None:
        group.append' '    if False:
        group.append'
expect fail vault_import "vault rename keeps the old note"

fresh; mutate $vault '        if note not in scan.notes and note not in graph.notes:' '        if False:'
expect fail vault_import "orphaned shadow artifacts kept"

fresh; mutate $vault 'if counts.chunked_notes >= NOTES_CHUNKED_PER_RUN or' 'if False and'
expect fail vault_import "vault chunk cap ignored"

fresh; mutate $vault '        budget = CHUNK_CHARS - len(header) - 1' '        budget = CHUNK_CHARS'
expect fail vault_import "vault chunks over the limit"

fresh; mutate $vault '            if linked:' '            if False:'
expect fail vault_import "vault links a note that already comes from another artifact"

fresh; mutate $vault 'if (stored.get(pid) or {}).get("text") != text or' 'if True or'
expect fail vault_import "vault rewrites unchanged chunks"

fresh; mutate $vault 'chosen, rest = candidates[:HEAL_ROWS_PER_RUN], candidates[HEAL_ROWS_PER_RUN:]' 'chosen, rest = [], candidates'
expect fail vault_import "vault heal disabled"

fresh; mutate $vault 'match = None if fenced else MARKDOWN_HEADING.match(line)' 'match = MARKDOWN_HEADING.match(line)'
expect fail vault_import "headings inside code fences split chunks"

exit $wrong
