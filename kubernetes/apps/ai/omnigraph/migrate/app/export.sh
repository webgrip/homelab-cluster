#!/bin/sh
set -eu
export OMNIGRAPH_HOME=/tmp/omnigraph-home
mkdir -p "$OMNIGRAPH_HOME"
for graph in $OMNIGRAPH_GRAPHS; do
  omnigraph upgrade --target "/work/$graph.omni" --json > "/work/$graph.upgrade.json" || true
  if ! grep -q '"outcome": *"\(completed\|already_current\)"' "/work/$graph.upgrade.json"; then
    echo "upgrade of $graph did not complete:" >&2
    cat "/work/$graph.upgrade.json" >&2
    exit 1
  fi
  omnigraph export --target "file:///work/$graph.omni" > "/work/$graph.jsonl"
  echo "exported $graph: $(wc -l < "/work/$graph.jsonl") rows"
  rm -rf "/work/$graph.omni"
done
