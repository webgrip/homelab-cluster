#!/bin/sh
set -eu
OMNIGRAPH_BEARER_TOKEN=$(cat /run/secrets/omnigraph/token)
export OMNIGRAPH_BEARER_TOKEN
plan=/work/plan
pruned=0
for file in "$plan"/prune-*.gq; do
  [ -e "$file" ] || continue
  if ! omnigraph mutate --server "$OMNIGRAPH_URL" --graph brain --branch main --query "$file" distill_prune --quiet > /dev/null 2>&1; then
    echo "distill failed: delete batch $((pruned + 1)) was refused on brain/main; the next run replans from the graph" >&2
    exit 1
  fi
  pruned=$((pruned + 1))
done
loaded=0
for file in "$plan"/load-*.ndjson; do
  [ -e "$file" ] || continue
  if ! omnigraph load --server "$OMNIGRAPH_URL" --graph brain --branch main --mode merge --data "$file" --quiet > /dev/null 2>&1; then
    echo "distill failed: load batch $((loaded + 1)) was refused on brain/main; the next run replans from the graph" >&2
    exit 1
  fi
  loaded=$((loaded + 1))
done
echo "distill applied: delete_batches=$pruned load_batches=$loaded"
if [ -e "$plan/failed" ]; then
  echo "distill incomplete: $(cat "$plan/failed"); the documents are retried on the next run" >&2
  exit 1
fi
