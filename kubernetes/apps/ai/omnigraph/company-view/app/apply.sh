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
  if ! omnigraph_write og mutate --graph company --query "$file" company_prune; then
    echo "company view apply failed: delete batch $((pruned + 1)) was refused on company/main ($omnigraph_write_failure); the next run replans from the graph" >&2
    exit 1
  fi
  pruned=$((pruned + 1))
done
loaded=0
for file in "$plan"/load-*.ndjson; do
  [ -e "$file" ] || continue
  if ! omnigraph_write og load --graph company --mode merge --data "$file"; then
    echo "company view apply failed: load batch $((loaded + 1)) was refused on company/main ($omnigraph_write_failure); the next run replans from the graph" >&2
    exit 1
  fi
  loaded=$((loaded + 1))
done
echo "company view applied: delete_batches=$pruned load_batches=$loaded conflict_retries=$omnigraph_write_retries"
