#!/bin/sh
set -eu
. /etc/omnigraph-embed-step/omnigraph_write.sh
OMNIGRAPH_BEARER_TOKEN=$(cat /run/secrets/omnigraph/token)
export OMNIGRAPH_BEARER_TOKEN
plan=/work/plan
pruned=0
for file in "$plan"/prune-*.gq; do
  [ -e "$file" ] || continue
  if ! omnigraph_write omnigraph mutate --server "$OMNIGRAPH_URL" --graph brain --branch main --query "$file" vault_prune --quiet; then
    echo "vault import failed: delete batch $((pruned + 1)) was refused on brain/main ($omnigraph_write_failure); nothing later was written" >&2
    exit 1
  fi
  pruned=$((pruned + 1))
done
loaded=0
for file in "$plan"/load-*.ndjson; do
  [ -e "$file" ] || continue
  if ! omnigraph_write omnigraph load --server "$OMNIGRAPH_URL" --graph brain --branch main --mode merge --data "$file" --quiet; then
    echo "vault import failed: load batch $((loaded + 1)) was refused on brain/main ($omnigraph_write_failure); the next run replans from the graph" >&2
    exit 1
  fi
  loaded=$((loaded + 1))
done
healed=0
for file in "$plan"/heal-*.ndjson; do
  [ -e "$file" ] || continue
  if ! omnigraph_write omnigraph load --server "$OMNIGRAPH_URL" --graph brain --branch main --mode merge --data "$file" --quiet; then
    echo "vault import failed: heal batch $((healed + 1)) was refused on brain/main ($omnigraph_write_failure); the next run replans from the graph" >&2
    exit 1
  fi
  healed=$((healed + 1))
done
echo "vault import applied: delete_batches=$pruned load_batches=$loaded heal_batches=$healed conflict_retries=$omnigraph_write_retries"
