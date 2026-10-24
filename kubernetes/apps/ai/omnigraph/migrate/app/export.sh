#!/bin/sh
set -eu
export OMNIGRAPH_HOME=/tmp/omnigraph-home
mkdir -p "$OMNIGRAPH_HOME"
for graph in $OMNIGRAPH_GRAPHS; do
  copy="$OMNIGRAPH_STATE_DIR/graphs/$graph.omni"
  omnigraph upgrade --target "$copy" --json > "$OMNIGRAPH_STATE_DIR/$graph.upgrade.json" || true
  if ! grep -q '"outcome": *"\(completed\|already_current\)"' "$OMNIGRAPH_STATE_DIR/$graph.upgrade.json"; then
    echo "upgrade of $graph did not complete:" >&2
    cat "$OMNIGRAPH_STATE_DIR/$graph.upgrade.json" >&2
    exit 1
  fi
  omnigraph export --target "file://$copy" > "$OMNIGRAPH_STATE_DIR/$graph.jsonl"
  echo "exported $graph: $(wc -l < "$OMNIGRAPH_STATE_DIR/$graph.jsonl") rows"
  rm -rf "$copy"
done
