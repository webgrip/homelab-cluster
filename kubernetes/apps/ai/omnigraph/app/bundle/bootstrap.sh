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
for graph_dir in "$OMNIGRAPH_STATE_DIR"/graphs/*.omni; do
  graph=$(basename "$graph_dir" .omni)
  report=$(omnigraph optimize --cluster "file://$OMNIGRAPH_STATE_DIR" --graph "$graph")
  echo "$report"
  if echo "$report" | grep -q rebuild-full-text-indexes; then
    omnigraph rebuild-full-text-indexes --cluster "file://$OMNIGRAPH_STATE_DIR" --graph "$graph" --branch main --as "$OMNIGRAPH_OPERATOR_ACTOR"
  fi
done
