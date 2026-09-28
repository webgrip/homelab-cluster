#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
app=kubernetes/apps/ai/omnigraph/distill/app
bundle=kubernetes/apps/ai/omnigraph/app/bundle
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
wrong=0

fresh() {
  rm -rf "${work:?}/tree"
  mkdir -p "$work/tree/scripts" "$work/tree/$app" "$work/tree/$bundle"
  cp "$root/scripts/test_omnigraph_distill.py" "$work/tree/scripts/"
  cp -r "$root/$app/." "$work/tree/$app/"
  cp "$root/$bundle/brain.pg" "$work/tree/$bundle/"
}

mutate() {
  python3 - "$work/tree/$app/distill.py" "$1" "$2" <<'PY'
import sys
from pathlib import Path
path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
if old not in text:
    sys.exit(f"mutation anchor not found: {old}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
PY
}

expect() {
  local want=$1 label=$2 rc
  python3 "$work/tree/scripts/test_omnigraph_distill.py" > "$work/out" 2>&1
  rc=$?
  if { [ "$want" = pass ] && [ $rc -eq 0 ]; } || { [ "$want" = fail ] && [ $rc -ne 0 ]; }; then
    echo "ok   $label ($want)"
  else
    echo "WRONG $label: wanted $want, exit $rc"
    tail -20 "$work/out"
    wrong=1
  fi
}

fresh
expect pass "unmodified distiller"

fresh
mutate 'self.by_key.get((entity_type, name_key(name)), [])' 'self.by_key.get((entity_type, name), [])'
expect fail "exact name and alias resolution disabled"

fresh
mutate 'if similarity >= self.settings.candidate_similarity:' 'if similarity > 1.5:'
expect fail "embedding candidates disabled"

fresh
mutate 'if similarity >= self.settings.same_similarity or (slug, other) in confirmed:' 'if True:'
expect fail "every embedding candidate merged without adjudication"

fresh
mutate 'if similarity >= self.settings.same_similarity or (slug, other) in confirmed:' 'if (slug, other) in confirmed:'
expect fail "near-identical names always sent to adjudication"

fresh
mutate 'if self.alias_verdicts.get((name_key(name), slug)):' 'if True:'
expect fail "alias hits accepted without confirmation"

fresh
mutate 'if same is False:' 'if False:'
expect fail "refused aliases kept"

fresh
mutate 'kept = [alias for alias in aliases if verdicts[(entity.slug, alias)]]' 'kept = aliases'
expect fail "alias audit ignores rejections"

fresh
mutate 'if any(verdicts.get((entity.slug, alias)) is None for alias in aliases):' 'if False:'
expect fail "unanswered alias audit treated as an answer"

fresh
mutate 'if not entity.derived or entity.type not in ENTITY_TYPES or referenced.get(entity.slug):' 'if True:'
expect fail "orphaned entities never deleted"

fresh
mutate 'if not entity.derived or entity.type not in ENTITY_TYPES or referenced.get(entity.slug):' 'if not entity.derived or entity.type not in ENTITY_TYPES:'
expect fail "referenced entities deleted"

fresh
mutate 'return bool(self.id) and self.id.startswith(OWNED_EDGE_PREFIX)' 'return True'
expect fail "foreign edges treated as owned"

fresh
mutate 'if state is None or state.get("content_sha256") != document.digest' 'if True or state.get("content_sha256") != document.digest'
expect fail "unchanged documents reprocessed"

fresh
mutate 'if edge_type is None or importer_owns(edge_type, document.slug) or entity.slug == document.slug:' 'if edge_type is None or entity.slug == document.slug:'
expect fail "importer-managed edges written"

fresh
mutate 'ROWS_PER_LOAD_FILE = 2000' 'ROWS_PER_LOAD_FILE = 9000'
expect fail "load batches above the write limit"

exit $wrong
