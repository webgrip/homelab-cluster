#!/bin/sh
set -eu
cp -L /etc/omnigraph/bundle/cluster.yaml /etc/omnigraph/bundle/*.pg /etc/omnigraph/bundle/*.gq /etc/omnigraph/bundle/*.policy.yaml "$OMNIGRAPH_BUNDLE_DIR"/
if [ ! -f "$OMNIGRAPH_STATE_DIR/__cluster/state.json" ]; then
  omnigraph cluster import --config "$OMNIGRAPH_BUNDLE_DIR"
fi
omnigraph cluster apply --config "$OMNIGRAPH_BUNDLE_DIR" --as "$OMNIGRAPH_OPERATOR_ACTOR"
for graph in $OMNIGRAPH_GRAPHS; do
  omnigraph optimize --cluster "file://$OMNIGRAPH_STATE_DIR" --graph "$graph"
done
