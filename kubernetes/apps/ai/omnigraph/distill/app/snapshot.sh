#!/bin/sh
set -eu
OMNIGRAPH_BEARER_TOKEN=$(cat /run/secrets/omnigraph/token)
export OMNIGRAPH_BEARER_TOKEN
mkdir -p /work/snapshot
queries=$(sed -n 's/^query \([a-zA-Z0-9_]*\)().*/\1/p' /etc/distill/snapshot.gq)
for query in $queries; do
  if ! omnigraph query --server "$OMNIGRAPH_URL" --graph brain --branch main --query /etc/distill/snapshot.gq "$query" --json > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-distill refused while reading $query on brain/main" >&2
    exit 1
  fi
done
echo "brain snapshot read: queries=$(echo "$queries" | wc -w)"
