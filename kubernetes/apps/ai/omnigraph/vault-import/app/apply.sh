#!/bin/sh
set -eu
OMNIGRAPH_BEARER_TOKEN=$(cat /run/secrets/omnigraph/token)
export OMNIGRAPH_BEARER_TOKEN
plan=/work/plan
if [ -f "$plan/prune.gq" ]; then
  if ! omnigraph mutate --server "$OMNIGRAPH_URL" --graph brain --branch main --query "$plan/prune.gq" vault_prune --quiet > /dev/null 2>&1; then
    echo "vault import failed: deleting withdrawn notes and stale links on brain/main was refused; nothing was loaded" >&2
    exit 1
  fi
fi
loaded=0
for file in "$plan"/load-*.ndjson; do
  [ -e "$file" ] || continue
  if ! omnigraph load --server "$OMNIGRAPH_URL" --graph brain --branch main --mode merge --data "$file" --quiet > /dev/null 2>&1; then
    echo "vault import failed: load batch $((loaded + 1)) was refused on brain/main; the next run replans from the graph" >&2
    exit 1
  fi
  loaded=$((loaded + 1))
done
echo "vault import applied: load_batches=$loaded"
