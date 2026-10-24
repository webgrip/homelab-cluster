#!/bin/sh
set -eu
source_dir=/etc/omnigraph/bundle
approved_deletions=$source_dir/approved-deletions
target="file://$OMNIGRAPH_STATE_DIR"
export OMNIGRAPH_HOME="${OMNIGRAPH_HOME:-$OMNIGRAPH_BUNDLE_DIR/.operator}"
mkdir -p "$OMNIGRAPH_HOME"
cp -L "$source_dir"/cluster.yaml "$source_dir"/*.pg "$source_dir"/*.gq "$source_dir"/*.policy.yaml "$OMNIGRAPH_BUNDLE_DIR"/

retained_lock() {
  omnigraph cluster status --target "$target" --json </dev/null 2>/dev/null \
    | tr -d ' \n' \
    | sed -n 's/.*"lock_id":"\([^"]*\)".*/\1/p'
}

release_retained_lock() {
  lock=$(retained_lock)
  if [ -n "$lock" ]; then
    omnigraph cluster force-unlock "$lock" --target "$target" </dev/null > /dev/null
    echo "released retained cluster lock $lock"
  fi
}

owned_write() {
  written=0
  "$@" || written=$?
  release_retained_lock
  return "$written"
}

unapproved_deletions() {
  printf '%s' "$1" \
    | grep -o '"resource":"[^"]*","operation":"delete"' \
    | sed 's/^"resource":"\([^"]*\)".*/\1/' \
    | while read -r resource; do
        grep -qx "$resource" "$approved_deletions" 2>/dev/null || echo "$resource"
      done
}

apply_bundle() {
  owned_write omnigraph cluster apply --target "$target" --config "$OMNIGRAPH_BUNDLE_DIR" --as "$OMNIGRAPH_OPERATOR_ACTOR" --json </dev/null > /dev/null
  echo "omnigraph bundle applied"
}

release_retained_lock
if [ ! -f "$OMNIGRAPH_STATE_DIR/__cluster/state.json" ]; then
  omnigraph cluster validate --config "$OMNIGRAPH_BUNDLE_DIR" </dev/null
  apply_bundle
elif ! validation=$(omnigraph cluster validate --config "$OMNIGRAPH_BUNDLE_DIR" </dev/null 2>&1); then
  echo "omnigraph bundle not applied: it does not validate ($(printf '%s' "$validation" | tail -n 3 | tr '\n' ' ')); serving the last applied state" >&2
else
  plan_report=$(omnigraph cluster plan --target "$target" --config "$OMNIGRAPH_BUNDLE_DIR" --as "$OMNIGRAPH_OPERATOR_ACTOR" --json </dev/null 2>/dev/null | tr -d '\n' || true)
  plan=$(printf '%s' "$plan_report" | tr -d ' ')
  refused=$(unapproved_deletions "$plan" | tr '\n' ' ')
  if [ -n "$refused" ]; then
    echo "omnigraph bundle not applied: it deletes $refused without an entry in approved-deletions; serving the last applied state" >&2
  elif ! printf '%s' "$plan" | grep -q '"ok":true'; then
    reasons=$(printf '%s' "$plan_report" | grep -o '"message": *"[^"]*"' | sed 's/^"message": *"//; s/"$//' | sort -u | tr '\n' ';')
    echo "omnigraph bundle not applied: the plan is refused (${reasons:-no plan}); serving the last applied state" >&2
  elif ! apply_bundle; then
    echo "omnigraph bundle not applied: cluster apply failed after a clean plan; serving the last applied state" >&2
  fi
fi

work=$(mktemp -d)
embedding_targets() {
  omnigraph schema show --target "$target" --graph "$1" </dev/null | awk '
    /^node / { type = $2; sub(/[^A-Za-z0-9_].*/, "", type) }
    /@embed\("/ {
      field = $1; sub(/:$/, "", field)
      dim = $0; sub(/.*Vector\(/, "", dim); sub(/\).*/, "", dim)
      source = $0; sub(/.*@embed\("/, "", source); sub(/".*/, "", source)
      model = "-"
      if ($0 ~ /model="/) { model = $0; sub(/.*model="/, "", model); sub(/".*/, "", model) }
      print type, field, source, dim, model
    }'
}
backfill_max_rows=${OMNIGRAPH_BACKFILL_MAX_ROWS:-500}
backfill_part_rows=${OMNIGRAPH_BACKFILL_PART_ROWS:-100}
backfill_deadline=0
backfill_plan=$work/backfill.plan
seconds_left() {
  echo $((backfill_deadline - $(date +%s)))
}
plan_backfill() {
  graph=$1 type=$2 field=$3 source=$4 dim=$5 model=$6
  if [ "$model" != "-" ] && [ "$model" != "$OMNIGRAPH_EMBED_MODEL" ]; then
    echo "vector backfill skips $graph $type.$field: it records model $model, the provider serves $OMNIGRAPH_EMBED_MODEL" >&2
    return 0
  fi
  dir=$work/$graph.$type.$field
  mkdir -p "$dir" || return 1
  omnigraph export --target "$target" --graph "$graph" --type "$type" </dev/null > "$dir/rows.jsonl" || return 1
  awk -v vector="\"$field\":[" -v text="\"$source\":\"[^\"]" 'index($0, vector) == 0 && $0 ~ text' "$dir/rows.jsonl" > "$dir/missing.jsonl" || return 1
  rm -f "$dir/rows.jsonl"
  missing=$(wc -l < "$dir/missing.jsonl")
  if [ "$missing" -gt 0 ]; then
    printf '{"dimension":%s,"types":{"%s":{"target":"%s","fields":["%s"]}}}\n' "$dim" "$type" "$field" "$source" > "$dir/spec.json"
    echo "$missing $graph $type $field" >> "$backfill_plan"
  fi
}
fill_vectors() {
  missing=$1 graph=$2 type=$3 field=$4
  dir=$work/$graph.$type.$field
  if [ "$(seconds_left)" -le 0 ]; then
    echo "vector backfill capped: $missing $graph $type rows left for writers"
    return 0
  fi
  offset=$(($(date +%s) / 86400 * backfill_part_rows % missing))
  { tail -n +"$((offset + 1))" "$dir/missing.jsonl"; head -n "$offset" "$dir/missing.jsonl"; } | head -n "$backfill_max_rows" > "$dir/selected.jsonl"
  split -l "$backfill_part_rows" "$dir/selected.jsonl" "$dir/part." || return 1
  embedded=0
  for part in "$dir"/part.*; do
    [ -e "$part" ] || continue
    left=$(seconds_left)
    if [ "$left" -le 0 ]; then
      break
    fi
    rows=$(wc -l < "$part")
    if timeout "$left" omnigraph embed --input "$part" --output "$part.embedded" --spec "$dir/spec.json" </dev/null > /dev/null \
      && owned_write omnigraph load --target "$target" --graph "$graph" --branch main --mode merge --data "$part.embedded" --as "$OMNIGRAPH_OPERATOR_ACTOR" </dev/null > /dev/null 2>&1; then
      embedded=$((embedded + rows))
    else
      echo "vector backfill skipped a part of $rows $graph $type rows: embedding or loading it failed or ran past the deadline" >&2
    fi
  done
  echo "vector backfill embedded $embedded $graph $type rows into $field"
  if [ "$embedded" -lt "$missing" ]; then
    echo "vector backfill capped: $((missing - embedded)) $graph $type rows left for writers"
  fi
}
export OPENAI_API_KEY="$OMNIGRAPH_EMBED_API_KEY"
backfill_deadline=$(($(date +%s) + ${OMNIGRAPH_BACKFILL_DEADLINE_SECONDS:-150}))
: > "$backfill_plan"
if curl --fail --silent --show-error --max-time 10 --output /dev/null --header "Authorization: Bearer $OPENAI_API_KEY" "$OMNIGRAPH_EMBED_BASE_URL/models"; then
  for graph_dir in "$OMNIGRAPH_STATE_DIR"/graphs/*.omni; do
    graph=$(basename "$graph_dir" .omni)
    if ! embedding_targets "$graph" > "$work/$graph.targets"; then
      echo "vector backfill skips $graph: its schema could not be read" >&2
      continue
    fi
    while read -r type field source dim model; do
      plan_backfill "$graph" "$type" "$field" "$source" "$dim" "$model" \
        || echo "vector backfill for $graph $type failed; rows without a vector keep ranking on keywords only until the next start" >&2
    done < "$work/$graph.targets"
  done
  sort -n "$backfill_plan" | while read -r missing graph type field; do
    fill_vectors "$missing" "$graph" "$type" "$field" \
      || echo "vector backfill for $graph $type failed; rows without a vector keep ranking on keywords only until the next start" >&2
  done
else
  echo "vector backfill skipped: $OMNIGRAPH_EMBED_BASE_URL is not answering; rows without a vector keep ranking on keywords only until the next start" >&2
fi
rm -rf "$work"
for graph_dir in "$OMNIGRAPH_STATE_DIR"/graphs/*.omni; do
  graph=$(basename "$graph_dir" .omni)
  report=$(owned_write omnigraph optimize --target "$target" --graph "$graph" </dev/null)
  echo "$report"
  if echo "$report" | grep -q rebuild-full-text-indexes; then
    owned_write omnigraph rebuild-full-text-indexes --target "$target" --graph "$graph" --branch main --as "$OMNIGRAPH_OPERATOR_ACTOR" </dev/null
  fi
  if ! owned_write omnigraph cleanup --target "$target" --graph "$graph" --older-than "${OMNIGRAPH_CLEANUP_OLDER_THAN:-7d}" --confirm </dev/null; then
    echo "cleanup of $graph failed; its old table versions stay on the volume until the next start" >&2
  fi
done
release_retained_lock
