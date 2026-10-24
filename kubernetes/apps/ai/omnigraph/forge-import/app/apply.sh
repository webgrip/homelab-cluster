#!/bin/sh
set -eu
. /etc/omnigraph-embed-step/omnigraph_write.sh
OMNIGRAPH_TOKEN_FILE=/run/secrets/omnigraph/token
export OMNIGRAPH_TOKEN_FILE
og() { python3 -I /etc/omnigraph-embed-step/omnigraph_http.py "$@"; }
plan=/work/plan
pruned=0
for file in "$plan"/prune-*.gq; do
  [ -e "$file" ] || continue
  if ! omnigraph_write og mutate --graph brain --query "$file" forge_prune; then
    echo "forge import failed: delete batch $((pruned + 1)) was refused on brain/main ($omnigraph_write_failure); the next run replans from the graph" >&2
    exit 1
  fi
  pruned=$((pruned + 1))
done
loaded=0
for file in "$plan"/load-*.ndjson; do
  [ -e "$file" ] || continue
  if ! omnigraph_write og load --graph brain --mode merge --data "$file"; then
    echo "forge import failed: load batch $((loaded + 1)) was refused on brain/main ($omnigraph_write_failure); the next run replans from the graph" >&2
    exit 1
  fi
  loaded=$((loaded + 1))
done
healed=0
for file in "$plan"/heal-*.ndjson; do
  [ -e "$file" ] || continue
  if ! omnigraph_write og load --graph brain --mode merge --data "$file"; then
    echo "forge import failed: heal batch $((healed + 1)) was refused on brain/main ($omnigraph_write_failure); the next run replans from the graph" >&2
    exit 1
  fi
  healed=$((healed + 1))
done
echo "forge import applied: delete_batches=$pruned load_batches=$loaded heal_batches=$healed conflict_retries=$omnigraph_write_retries"
