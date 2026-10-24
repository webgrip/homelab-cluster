#!/bin/sh
set -eu
rm -rf "$OMNIGRAPH_STATE_DIR"/*.omni
mkdir -p "$OMNIGRAPH_STATE_DIR/graphs"
for graph in $OMNIGRAPH_GRAPHS; do
  rm -rf "$OMNIGRAPH_STATE_DIR/graphs/$graph.omni"
  cp -a "/source/graphs/$graph.omni" "$OMNIGRAPH_STATE_DIR/graphs/$graph.omni"
  omnigraph snapshot --store "file://$OMNIGRAPH_STATE_DIR/graphs/$graph.omni" > /dev/null
  echo "copied $graph to the path it was written at and settled it with 0.11"
done
