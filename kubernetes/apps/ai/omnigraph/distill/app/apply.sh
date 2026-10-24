#!/bin/sh
set -eu
OMNIGRAPH_TOKEN_FILE=/run/secrets/omnigraph/token
export OMNIGRAPH_TOKEN_FILE
og() { python3 -I /etc/omnigraph-embed-step/omnigraph_http.py "$@"; }
plan=/work/plan
pruned=0
for file in "$plan"/prune-*.gq; do
  [ -e "$file" ] || continue
  if ! og mutate --graph brain --query "$file" distill_prune > /dev/null 2>&1; then
    echo "distill failed: delete batch $((pruned + 1)) was refused on brain/main; the next run replans from the graph" >&2
    exit 1
  fi
  pruned=$((pruned + 1))
done
loaded=0
for file in "$plan"/load-*.ndjson; do
  [ -e "$file" ] || continue
  if ! og load --graph brain --mode merge --data "$file" > /dev/null 2>&1; then
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
