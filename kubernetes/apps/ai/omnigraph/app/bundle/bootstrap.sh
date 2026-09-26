#!/bin/sh
set -eu
source_dir=/etc/omnigraph/bundle
approved_deletions=$source_dir/approved-deletions
cp -L "$source_dir"/cluster.yaml "$source_dir"/*.pg "$source_dir"/*.gq "$source_dir"/*.policy.yaml "$OMNIGRAPH_BUNDLE_DIR"/
if [ ! -f "$OMNIGRAPH_STATE_DIR/__cluster/state.json" ]; then
  omnigraph cluster import --config "$OMNIGRAPH_BUNDLE_DIR"
fi
unsatisfied_gates() {
  omnigraph cluster plan --config "$OMNIGRAPH_BUNDLE_DIR" --json \
    | tr -d ' \n' \
    | grep -o '{"resource":"[^"]*","reason":"[^"]*","satisfied":false}' \
    | sed 's/^{"resource":"\([^"]*\)".*/\1/' || true
}
for resource in $(unsatisfied_gates); do
  if grep -qx "$resource" "$approved_deletions"; then
    omnigraph cluster approve "$resource" --config "$OMNIGRAPH_BUNDLE_DIR" --as "$OMNIGRAPH_OPERATOR_ACTOR"
  else
    echo "refusing to apply: $resource needs approval; applying now would drop its policy and keep serving the graph to every token" >&2
    exit 1
  fi
done
if [ -n "$(unsatisfied_gates)" ]; then
  echo "refusing to apply: gated changes remain unapproved" >&2
  exit 1
fi
omnigraph cluster apply --config "$OMNIGRAPH_BUNDLE_DIR" --as "$OMNIGRAPH_OPERATOR_ACTOR"
work=$(mktemp -d)
embedding_targets() {
  omnigraph schema show --store "$1" </dev/null | awk '
    /^node / { type = $2; sub(/[^A-Za-z0-9_].*/, "", type) }
    /@embed\("/ {
      target = $1; sub(/:$/, "", target)
      dim = $0; sub(/.*Vector\(/, "", dim); sub(/\).*/, "", dim)
      source = $0; sub(/.*@embed\("/, "", source); sub(/".*/, "", source)
      model = "-"
      if ($0 ~ /model="/) { model = $0; sub(/.*model="/, "", model); sub(/".*/, "", model) }
      print type, target, source, dim, model
    }'
}
backfill_vectors() {
  store=$1 graph=$2 type=$3 target=$4 source=$5 dim=$6 model=$7
  if [ "$model" != "-" ] && [ "$model" != "$OMNIGRAPH_EMBED_MODEL" ]; then
    echo "vector backfill skips $graph $type.$target: it records model $model, the provider serves $OMNIGRAPH_EMBED_MODEL" >&2
    return 0
  fi
  dir=$work/$graph.$type.$target
  mkdir -p "$dir" || return 1
  omnigraph export --store "$store" --type "$type" </dev/null > "$dir/rows.jsonl" || return 1
  awk -v vector="\"$target\":[" -v text="\"$source\":\"[^\"]" 'index($0, vector) == 0 && $0 ~ text' "$dir/rows.jsonl" > "$dir/missing.jsonl" || return 1
  missing=$(wc -l < "$dir/missing.jsonl")
  if [ "$missing" -eq 0 ]; then
    return 0
  fi
  printf '{"dimension":%s,"types":{"%s":{"target":"%s","fields":["%s"]}}}\n' "$dim" "$type" "$target" "$source" > "$dir/spec.json"
  split -l "$OMNIGRAPH_BACKFILL_ROWS_PER_COMMIT" "$dir/missing.jsonl" "$dir/part." || return 1
  for part in "$dir"/part.*; do
    omnigraph embed --input "$part" --output "$part.embedded" --spec "$dir/spec.json" </dev/null > /dev/null || return 1
    omnigraph load --store "$store" --branch main --mode merge --data "$part.embedded" --as "$OMNIGRAPH_OPERATOR_ACTOR" --quiet </dev/null > /dev/null || return 1
  done
  echo "vector backfill embedded $missing $graph $type rows into $target"
}
export OPENAI_API_KEY="$OMNIGRAPH_EMBED_API_KEY"
if curl --fail --silent --show-error --max-time 10 --output /dev/null --header "Authorization: Bearer $OPENAI_API_KEY" "$OMNIGRAPH_EMBED_BASE_URL/models"; then
  for graph_dir in "$OMNIGRAPH_STATE_DIR"/graphs/*.omni; do
    graph=$(basename "$graph_dir" .omni)
    if ! embedding_targets "file://$graph_dir" > "$work/$graph.targets"; then
      echo "vector backfill skips $graph: its schema could not be read" >&2
      continue
    fi
    while read -r type target source dim model; do
      backfill_vectors "file://$graph_dir" "$graph" "$type" "$target" "$source" "$dim" "$model" \
        || echo "vector backfill for $graph $type failed; rows without a vector keep ranking on keywords only until the next start" >&2
    done < "$work/$graph.targets"
  done
else
  echo "vector backfill skipped: $OMNIGRAPH_EMBED_BASE_URL is not answering; rows without a vector keep ranking on keywords only until the next start" >&2
fi
rm -rf "$work"
for graph_dir in "$OMNIGRAPH_STATE_DIR"/graphs/*.omni; do
  graph=$(basename "$graph_dir" .omni)
  report=$(omnigraph optimize --cluster "file://$OMNIGRAPH_STATE_DIR" --graph "$graph")
  echo "$report"
  if echo "$report" | grep -q rebuild-full-text-indexes; then
    omnigraph rebuild-full-text-indexes --cluster "file://$OMNIGRAPH_STATE_DIR" --graph "$graph" --branch main --as "$OMNIGRAPH_OPERATOR_ACTOR"
  fi
done
